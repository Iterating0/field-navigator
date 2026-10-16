import asyncio
import hashlib
import json
import time
import logging
import inspect
import re
from collections.abc import Awaitable, Callable
from weakref import WeakValueDictionary
from app.config import Settings
from app.db.cache import FieldCache
from app.data.demo import demo_papers, lookup
from app.models.schemas import (DEFAULT_LANGUAGE, Decomposition, FieldNode, Paper,
                                PaperJudgment, CorePaper, field_id, normalize_field)
from app.models.schemas import CURRENT_QUALITY_REVISION
from app.providers.base import PaperProvider, ProviderError
from app.providers.mock import MockLLMProvider
from app.services.field_decomposer import FieldDecomposer, PROMPT_VERSION
from app.services.paper_ranker import PaperRanker
from app.services.paper_selector import select_analysis_papers
from app.services.paper_quality import quality_filter_and_dedupe
from app.services.literature_retriever import LiteratureRetriever, RETRIEVAL_VERSION
from app.services.evidence_verifier import localize_evidence_warnings

Progress = Callable[[dict], Awaitable[None]]
logger = logging.getLogger(__name__)


def _language(value: str | None) -> str:
    """Normalize direct service callers while API models enforce the enum."""
    return 'en' if value == 'en' else DEFAULT_LANGUAGE


_COPY = {
    'offline_only': (
        '离线演示仅覆盖 NHSE 及其预设分支。请切换自动或实时模式探索其他领域。',
        'Offline demo mode covers only NHSE and its bundled branches. Switch to automatic or live mode to explore another field.',
    ),
    'no_papers': (
        '未检索到论文。请尝试更具体的英文领域名称或常见别名。',
        'No papers were found. Try a more specific English field name or a common alias.',
    ),
    'no_valid_papers': (
        '未检索到论文。请尝试更具体的英文领域名称或常见别名。',
        'No valid papers were found. Try a more specific English field name or a common alias.',
    ),
    'missing_abstract': (
        '候选论文缺少摘要，分析仅基于标题和书目信息。',
        'The candidate papers have no abstracts; analysis is limited to titles and bibliographic metadata.',
    ),
    'papers_pending': (
        '已找到候选论文，但模型分析尚未完成。请稍后重试，或选择离线示例。',
        'Candidate papers were found, but model analysis is not complete. Try again later or choose the offline demo.',
    ),
    'papers_pending_summary': (
        '已找到候选论文，但模型分析尚未完成。下方论文为初步筛选。',
        'Candidate papers were found, but model analysis is not complete. The papers below are an initial shortlist.',
    ),
    'analysis_pending': (
        '已找到论文，但模型分析尚未完成。可先阅读当前初筛论文，稍后重试或选择离线示例。',
        'Papers were found, but model analysis is not complete. You can read the initial shortlist, then retry later or choose the offline demo.',
    ),
    'mock_warning': (
        '当前使用预设拆分：领域关系、置信度和阅读优先级仅用于演示；非预设领域不生成分支。',
        'This uses a bundled teaching map: relations, confidence, and reading priority are illustrative; no branches are generated for other fields.',
    ),
    'demo_warning': (
        '论文书目信息已核对；演示不含实时引用量，排序不代表学术共识。',
        'Paper bibliographic metadata has been checked; the demo has no live citation counts, and its ranking is not an academic consensus.',
    ),
    'core_fewer': (
        '通过范围与证据筛选的核心论文不足预设数量；未用低相关条目补足。',
        'Fewer core papers passed the scope and evidence checks than the configured limit; low-relevance items were not added to fill the list.',
    ),
    'audit_review': (
        '独立核对后仅保留一篇综述导读；其余综述未占用核心研究位置。',
        'After independent review, only one review was kept as an orientation paper; other reviews did not occupy core research slots.',
    ),
    'core_audit_pending': (
        '领域关系已完成；核心论文贡献说明尚未完成独立核对，请重试补齐。',
        'The field map is complete, but core-paper contribution checks are unfinished. Retry to complete the audit.',
    ),
}


def _copy(language: str, key: str) -> str:
    return _COPY[key][1 if _language(language) == 'en' else 0]


_RETRIEVAL_WARNING_EXACT_EN = {
    '检索扩展未通过范围检查；保留原始问题检索。':
        'Query expansion failed the scope check; the original query was retained.',
    '检索扩展暂不可用；保留原始检索与同主题基础路径，仍可能遗漏不同表述的论文。':
        'Query expansion is temporarily unavailable; the original and same-topic baseline paths were retained, so alternate phrasings may be missed.',
    '一条检索路径暂不可用；候选集来自其余成功路径。':
        'One retrieval path is temporarily unavailable; candidates came from the remaining successful paths.',
    'arXiv 官方元数据响应超过 2 MiB，候选未核查。':
        'The arXiv metadata response exceeded 2 MiB; the candidates were not verified.',
    'arXiv 官方元数据请求超时，候选未核查。':
        'The arXiv metadata request timed out; the candidates were not verified.',
    'arXiv 官方元数据网络请求失败，候选未核查。':
        'The arXiv metadata network request failed; the candidates were not verified.',
    'arXiv 官方元数据包含不支持的 XML 声明，候选未核查。':
        'The arXiv metadata contained an unsupported XML declaration; the candidates were not verified.',
    'arXiv 官方元数据不是有效 Atom 响应，候选未核查。':
        'The arXiv metadata was not a valid Atom response; the candidates were not verified.',
    'arXiv 官方响应包含未知或无效 ID，已忽略。':
        'The official arXiv response contained an unknown or invalid ID; it was ignored.',
    'DOI 注册元数据暂不可用，部分条目未核查。':
        'DOI registration metadata is temporarily unavailable; some records were not verified.',
    'DOI 注册元数据超过大小预算，部分条目未核查。':
        'DOI registration metadata exceeded the size budget; some records were not verified.',
    'DOI 注册元数据核查未完成，部分条目仅保留题名线索。':
        'DOI registration metadata verification did not finish; some records retain only title clues.',
    'arXiv API 路径暂不可用；已使用 arXiv 的 DOI 注册元数据核查，当前撤回状态仍未核查，仅保留题名身份。':
        'The arXiv API is unavailable; DOI registration metadata verified title identity only. Current withdrawal status remains unverified, so the abstract was not used as evidence.',
}


def _localize_retrieval_warning(text: str, language: str) -> str:
    if _language(language) != 'en' or not isinstance(text, str):
        return text
    exact = _RETRIEVAL_WARNING_EXACT_EN.get(text)
    if exact:
        return exact
    match = re.fullmatch(r'arXiv 官方元数据请求 HTTP (\d+)，候选未核查。', text)
    if match:
        return f'The arXiv metadata request returned HTTP {match.group(1)}; the candidates were not verified.'
    match = re.fullmatch(r'arXiv 官方响应包含重复 ID (.+)，该候选未核查。', text)
    if match:
        return f'The official arXiv response contained duplicate ID {match.group(1)}; that candidate was not verified.'
    match = re.fullmatch(r'arXiv 条目 (.+) 缺少题名，该候选未核查。', text)
    if match:
        return f'arXiv entry {match.group(1)} has no title; that candidate was not verified.'
    match = re.fullmatch(r'arXiv 条目 (.+) 缺失或未形成唯一记录，候选未核查。', text)
    if match:
        return f'arXiv entry {match.group(1)} is missing or did not form a unique record; the candidate was not verified.'
    match = re.fullmatch(r'arXiv 条目 (.+) 的 DOI 注册元数据未提供当前撤回状态，仅保留题名身份，摘要未作为证据使用。', text)
    if match:
        return f'DOI registration metadata for arXiv entry {match.group(1)} did not verify its current withdrawal status; only title identity was retained, and its abstract was not used as evidence.'
    match = re.fullmatch(r'arXiv 条目 (.+) 明确标记为 (withdrawn|retracted)，已排除该预印本的摘要和引用证据。', text)
    if match:
        return f'arXiv entry {match.group(1)} is explicitly marked {match.group(2)}; the preprint abstract and citation evidence were excluded.'
    match = re.fullmatch(r'arXiv 条目 (.+) 明确标记为 (withdrawn|retracted)，仅记录链接状态，未将正式发表版本标记为撤稿。', text)
    if match:
        return f'arXiv entry {match.group(1)} is explicitly marked {match.group(2)}; only the linked preprint status was recorded. The published version was not marked retracted.'
    match = re.fullmatch(r'候选 (.+) 包含多个冲突的 arXiv ID，未核查。', text)
    if match:
        return f'Candidate {match.group(1)} contains conflicting arXiv IDs; it was not verified.'
    # Conflict/qualification text contains the paper title and a provider-
    # specific scope phrase.  Preserve the title while replacing the unsafe
    # mixed-language suffix with a stable English explanation.
    match = re.fullmatch(r'“(.+?)”(?:与出版题名冲突|的索引题名存在错配).*', text)
    if match:
        return f'The metadata for “{match.group(1)}” conflicted across sources; the record was conservatively retained or excluded.'
    if re.search(r'[\u3400-\u9fff]', text):
        return 'A retrieval or metadata verification safeguard was applied; the affected record may be incomplete.'
    return text


def _localize_backend_warnings(warnings: list[str] | tuple[str, ...], language: str) -> list[str]:
    if _language(language) != 'en':
        return list(dict.fromkeys(warnings))
    retrieved = [_localize_retrieval_warning(warning, language) for warning in warnings]
    return localize_evidence_warnings(retrieved, language)


def _optional_kwargs(method, *, research_question: str | None, language: str,
                     evidence_needs: list[dict] | None = None,
                     candidate_focus_ids: dict[str, list[str]] | None = None) -> dict:
    """Keep lightweight injected test/service doubles source-compatible."""
    try:
        parameters = inspect.signature(method).parameters
    except (TypeError, ValueError):
        parameters = {}
    kwargs = {}
    if research_question and ('research_question' in parameters or
                              any(p.kind == inspect.Parameter.VAR_KEYWORD for p in parameters.values())):
        kwargs['research_question'] = research_question
    if 'language' in parameters or any(p.kind == inspect.Parameter.VAR_KEYWORD
                                       for p in parameters.values()):
        kwargs['language'] = language
    for key, value in (('evidence_needs', evidence_needs), ('candidate_focus_ids', candidate_focus_ids)):
        if value and (key in parameters or any(p.kind == inspect.Parameter.VAR_KEYWORD
                                               for p in parameters.values())):
            kwargs[key] = value
    return kwargs


def digest(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def relation_evidence_papers(decomposition: Decomposition, candidates: list[Paper]) -> list[Paper]:
    """Return only current candidates explicitly cited by field relations.

    Evidence is kept in relation order and de-duplicated so the response can
    expose supporting papers that did not make the ranked core-paper shortlist.
    """
    by_id = {paper.id: paper for paper in candidates}
    seen: set[str] = set()
    evidence: list[Paper] = []
    for relation in [*decomposition.prerequisites, *decomposition.subfields]:
        for paper_id in relation.evidence_paper_ids:
            if paper_id in seen or paper_id not in by_id:
                continue
            seen.add(paper_id)
            evidence.append(by_id[paper_id])
    return evidence


class FieldExplorer:
    def __init__(self, settings: Settings, papers: PaperProvider, decomposer: FieldDecomposer,
                 ranker: PaperRanker, cache: FieldCache, retriever: LiteratureRetriever | None = None):
        self.settings, self.papers, self.decomposer = settings, papers, decomposer
        self.ranker, self.cache = ranker, cache
        self.retriever = retriever
        self.locks: WeakValueDictionary[str, asyncio.Lock] = WeakValueDictionary()
        analysis_config = {'version': PROMPT_VERSION, 'quality': CURRENT_QUALITY_REVISION,
                  'llm': bool(settings.llm_api_key), 'model': settings.llm_model,
                  'base': settings.llm_base_url, 'format': settings.llm_response_format,
                  'thinking': settings.thinking_options, 'analysis_limit': settings.llm_analysis_limit}
        # The bundled demo graph and its supporting-paper annotations are
        # versioned separately from the LLM prompt.  Bumping this revision
        # prevents an old complete demo field from hiding a corrected demo.
        analysis_config['demo_revision'] = 2
        self.analysis_fingerprint = digest(analysis_config)
        self.search_fingerprint = digest({'version': RETRIEVAL_VERSION, 'quality': CURRENT_QUALITY_REVISION,
            'openalex_key': bool(settings.openalex_api_key), 'search_limit': settings.search_limit,
            'retriever': bool(retriever), 'planner': {
                'model': settings.llm_model, 'base': settings.llm_base_url,
                'format': settings.llm_response_format, 'thinking': settings.thinking_options,
            } if retriever else None,
            'metadata_verification': bool(getattr(retriever, 'metadata_verifier', None))})
        self.fingerprint = digest({'analysis': self.analysis_fingerprint, 'search': self.search_fingerprint,
                                   'core_limit': settings.core_paper_limit, 'weights': settings.rank_weights,
                                   'ranking_revision': 5})[:16]

    async def _stage(self, kind: str, key: str, refresh: bool, compute):
        lock = self.locks.setdefault(kind + ':' + key, asyncio.Lock())
        async with lock:
            if not refresh:
                cached = await asyncio.to_thread(self.cache.get_artifact, kind, key)
                if cached is not None:
                    logger.info('stage_complete stage=%s cache_hit=true', kind)
                    return cached
            started = time.perf_counter()
            value = await compute()
            ttl = self.settings.search_cache_ttl_hours if kind == 'search' else self.settings.cache_ttl_hours
            await asyncio.to_thread(self.cache.save_artifact, kind, key, value, ttl * 3600)
            logger.info('stage_complete stage=%s cache_hit=false seconds=%.3f', kind, time.perf_counter() - started)
            return value

    async def explore(self, query: str, mode: str = 'auto', refresh: bool = False,
                      progress: Progress | None = None, *, allow_partial: bool = False,
                      research_question: str | None = None,
                      language: str = DEFAULT_LANGUAGE) -> FieldNode:
        language = _language(language)
        research_question = ' '.join(research_question.split()) if research_question and mode != 'demo' else None
        key = self.cache_key(query, mode, research_question, language)
        lock = self.locks.setdefault(key, asyncio.Lock())
        started = time.perf_counter()
        if progress:
            await progress({'type': 'status', 'stage': 'waiting'})
        async with lock:
            if not refresh:
                cached = await asyncio.to_thread(self.cache.get, key)
                if cached:
                    logger.info('explore_complete cache_hit=true seconds=%.3f', time.perf_counter() - started)
                    return cached
            node = await self._analyze(query, mode, progress, refresh, allow_partial=allow_partial,
                                       research_question=research_question, language=language)
            ttl = self.settings.cache_ttl_hours * 3600
            if mode == 'auto' and node.paper_source == 'demo':
                ttl = min(ttl, 300)
            if node.phase == 'complete':
                await asyncio.to_thread(self.cache.save, key, node, ttl)
                logger.info('explore_complete cache_hit=false seconds=%.3f', time.perf_counter() - started)
            else:
                logger.info('explore_incomplete cache_hit=false phase=%s seconds=%.3f',
                            node.phase, time.perf_counter() - started)
            return node

    def cache_key(self, query: str, mode: str, research_question: str | None = None,
                  language: str = DEFAULT_LANGUAGE) -> str:
        key = self.fingerprint + ':' + mode + ':' + normalize_field(query)
        if research_question and mode != 'demo':
            key += ':question:' + digest(normalize_field(research_question))[:20]
        # Keep the historical Chinese key stable so old cached maps remain
        # readable; English maps get a separate key and can never overwrite a
        # Chinese result.
        return key if _language(language) == DEFAULT_LANGUAGE else key + ':language:en'

    async def _analyze(self, query: str, mode: str, progress: Progress | None = None,
                       refresh: bool = False, *, allow_partial: bool = False,
                       research_question: str | None = None,
                       language: str = DEFAULT_LANGUAGE) -> FieldNode:
        language = _language(language)
        warnings = []
        search_queries = [query]
        evidence_needs: list[dict] = []
        candidate_focus_ids: dict[str, list[str]] = {}
        source = 'openalex'
        found = lookup(query)
        name = found[0] if found else query
        ranking_scope = name + (' ' + research_question if research_question else '')
        if progress:
            await progress({'type': 'status', 'stage': 'search'})
        search_started = time.perf_counter()
        if mode == 'demo':
            candidates, source = demo_papers(query), 'demo'
            if not candidates:
                raise ProviderError(_copy(language, 'offline_only'), 422)
        else:
            try:
                async def search():
                    if self.retriever:
                        retrieval = await self.retriever.retrieve(name, self.settings.search_limit,
                                                                  research_question=research_question)
                        return {'papers': [p.model_dump() for p in retrieval.papers],
                                'queries': retrieval.queries, 'warnings': retrieval.warnings,
                                'evidence_needs': getattr(retrieval, 'evidence_needs', []),
                                'candidate_focus_ids': getattr(retrieval, 'candidate_focus_ids', {})}
                    papers = quality_filter_and_dedupe(await self.papers.search_papers(name, self.settings.search_limit))
                    if not papers:
                        raise ProviderError(_copy(language, 'no_papers'), 404)
                    return {'papers': [p.model_dump() for p in papers], 'queries': [name], 'warnings': []}
                search_key = self.search_fingerprint + ':' + normalize_field(name)
                if self.retriever and research_question:
                    search_key += ':' + digest(normalize_field(research_question))[:20]
                raw = await self._stage('search', search_key, refresh, search)
                candidates = quality_filter_and_dedupe([Paper.model_validate(p) for p in raw['papers']])
                search_queries = raw['queries']
                evidence_needs = raw.get('evidence_needs', [])
                candidate_focus_ids = raw.get('candidate_focus_ids', {})
                warnings.extend(_localize_backend_warnings(raw['warnings'], language))
            except ProviderError as exc:
                if mode != 'auto' or not found:
                    if language == 'en':
                        raise ProviderError(_copy(language, 'no_valid_papers'), exc.status_code) from exc
                    raise
                candidates, source = demo_papers(query), 'demo'
                warnings.append((f'{str(exc)} 本次使用离线演示资料。' if language != 'en'
                                 else 'Live search was unavailable; the bundled offline demo is shown instead.'))
        if not candidates:
            raise ProviderError(_copy(language, 'no_valid_papers'), 404)
        logger.info('search_complete seconds=%.3f candidates=%d', time.perf_counter() - search_started, len(candidates))
        if source == 'openalex' and not any(p.abstract for p in candidates):
            warnings.append(_copy(language, 'missing_abstract'))
        model_ready = bool(self.settings.llm_api_key and self.settings.llm_model.strip())
        if source == 'openalex' and not model_ready and allow_partial:
            logger.warning(
                'analysis_unavailable phase=papers source=openalex key_configured=%s '
                'model_configured=%s response_format=%s',
                bool(self.settings.llm_api_key), bool(self.settings.llm_model.strip()),
                self.settings.llm_response_format,
            )
            warnings.append(_copy(language, 'papers_pending'))
            return FieldNode(
                id=field_id(name), name=name,
                summary=_copy(language, 'papers_pending_summary'),
                prerequisites=[], subfields=[],
                core_papers=self.ranker.rank(
                    ranking_scope, candidates, [], self.settings.core_paper_limit, 'pending', language),
                candidate_count=len(candidates), analyzed_paper_count=0,
                paper_source='openalex', analysis_source='pending', phase='papers',
                warnings=warnings,
                search_queries=search_queries,
                research_question=research_question,
                quality_revision=CURRENT_QUALITY_REVISION,
                language=language,
            )
        if source == 'demo':
            decomposer = FieldDecomposer(MockLLMProvider(), require_evidence=False)
        else:
            # Direct service/unit callers retain their injected decomposer;
            # the public API takes the honest partial branch above instead.
            decomposer = self.decomposer
        # A configured key keeps the staged analysis path for direct service
        # callers and injected test providers. The public API has already
        # returned the honest papers-only result when the model is incomplete.
        analysis_source = 'llm' if self.settings.llm_api_key and source != 'demo' else 'mock'
        if analysis_source == 'mock':
            warnings.append(_copy(language, 'mock_warning'))
        if source == 'demo':
            warnings.append(_copy(language, 'demo_warning'))
        analyzed = candidates
        if analysis_source == 'llm':
            limit = self.settings.llm_analysis_limit
            analyzed = select_analysis_papers(
                ranking_scope, candidates, max(limit, self.settings.core_paper_limit) if limit else 0,
                **_optional_kwargs(select_analysis_papers, research_question=None, language=language,
                                   evidence_needs=evidence_needs, candidate_focus_ids=candidate_focus_ids))
            if len(analyzed) < len(candidates):
                warnings.append(
                    (f'候选筛选实验：从 {len(candidates)} 篇检索结果中选择 {len(analyzed)} 篇分析；'
                     '核心论文在该子集中排序，可能遗漏其他研究方向。')
                    if language != 'en' else
                    f'The analysis selected {len(analyzed)} of {len(candidates)} retrieved papers; '
                    'core papers were ranked within this subset and other directions may be missed.'
                )
            analysis_key = digest({'config': self.analysis_fingerprint, 'field': normalize_field(name),
                                   'research_question': research_question,
                                   'language': language,
                                   'evidence_needs': evidence_needs,
                                   'candidate_focus_ids': candidate_focus_ids,
                                   'papers': [p.model_dump() for p in analyzed]})

            async def build_map():
                kwargs = _optional_kwargs(decomposer.decompose_map,
                                          research_question=research_question, language=language,
                                          evidence_needs=evidence_needs, candidate_focus_ids=candidate_focus_ids)
                decomposition = await decomposer.decompose_map(name, analyzed, **kwargs)
                if decomposition.evidence_audit_complete is False:
                    raise ProviderError(
                        'The independent evidence audit did not finish; the initial paper shortlist was '
                        'retained. Retry to complete relation checks.'
                        if language == 'en' else
                        '独立证据审查未完成；本次保留论文初筛，请重试补齐分支核对。'
                    )
                return decomposition.model_dump()

            async def assess_papers():
                kwargs = _optional_kwargs(decomposer.judge_papers,
                                          research_question=research_question, language=language,
                                          evidence_needs=evidence_needs, candidate_focus_ids=candidate_focus_ids)
                return [j.model_dump() for j in await decomposer.judge_papers(name, analyzed, **kwargs)]

            preview = FieldNode(id=field_id(name), name=name,
                                summary=('已找到候选论文，正在分析领域关系。下方论文为初步筛选。'
                                         if language != 'en' else
                                         'Candidate papers were found; field relations are being analyzed. '
                                         'The papers below are an initial shortlist.'),
                                prerequisites=[], subfields=[],
                                core_papers=self.ranker.rank(ranking_scope, candidates, [], self.settings.core_paper_limit,
                                                             'pending', language),
                                candidate_count=len(candidates), paper_source=source, analysis_source='pending',
                                phase='papers', warnings=warnings, search_queries=search_queries,
                                research_question=research_question, quality_revision=CURRENT_QUALITY_REVISION,
                                language=language)
            if progress:
                await progress({'type': 'partial', 'stage': 'papers', 'field': preview.model_dump()})
            judgments = asyncio.create_task(self._stage('judgments', analysis_key, refresh, assess_papers))
            current = preview
            try:
                decomposition = Decomposition.model_validate(await self._stage('map', analysis_key, refresh, build_map))
                preview = preview.model_copy(update={'summary': decomposition.summary,
                    'prerequisites': decomposition.prerequisites, 'subfields': decomposition.subfields,
                    'evidence_papers': relation_evidence_papers(decomposition, candidates),
                    'analysis_source': 'llm', 'phase': 'map',
                    'warnings': _localize_backend_warnings(
                        [*warnings, *decomposition.warnings], language
                    )})
                if progress:
                    await progress({'type': 'partial', 'stage': 'map', 'field': preview.model_dump()})
                current = preview
                decomposition.paper_judgments = [PaperJudgment.model_validate(j) for j in await judgments]
            except asyncio.CancelledError:
                judgments.cancel()
                await asyncio.gather(judgments, return_exceptions=True)
                raise
            except (ProviderError, asyncio.TimeoutError) as exc:
                judgments.cancel()
                await asyncio.gather(judgments, return_exceptions=True)
                if not allow_partial:
                    raise
                detail = str(exc).strip()[:300] or '模型分析未完成'
                logger.warning('analysis_partial phase=%s source=%s reason=%s',
                               current.phase, source, detail)
                warning = _copy(language, 'analysis_pending')
                return current.model_copy(update={
                    'analysis_source': 'pending',
                    'warnings': [*current.warnings, warning],
                    'analyzed_paper_count': len(analyzed),
                })
        else:
            kwargs = _optional_kwargs(decomposer.decompose,
                                      research_question=None, language=language)
            decomposition = await decomposer.decompose(name, candidates, **kwargs)
        warnings.extend(_localize_backend_warnings(decomposition.warnings, language))
        rank_kwargs = _optional_kwargs(self.ranker.rank, research_question=None, language=language,
                                      evidence_needs=evidence_needs, candidate_focus_ids=candidate_focus_ids)
        # language is already positional for compatibility with existing rankers.
        rank_kwargs.pop('language', None)
        core_papers = self.ranker.rank(ranking_scope, analyzed, decomposition.paper_judgments,
                                      self.settings.core_paper_limit, analysis_source, language, **rank_kwargs)
        if analysis_source == 'llm' and hasattr(decomposer, 'audit_core_papers') and core_papers:
            core_key = digest({'analysis': analysis_key, 'ranking': self.fingerprint,
                               'core_papers': [core.model_dump() for core in core_papers]})

            async def audit_core():
                kwargs = _optional_kwargs(decomposer.audit_core_papers,
                                          research_question=research_question, language=language,
                                          evidence_needs=evidence_needs, candidate_focus_ids=candidate_focus_ids)
                audited, audit_warnings = await decomposer.audit_core_papers(
                    name, core_papers, analyzed, **kwargs)
                return {'core_papers': [core.model_dump() for core in audited], 'warnings': audit_warnings}

            try:
                raw_core = await self._stage('core_audit', core_key, refresh, audit_core)
                core_papers = sorted([CorePaper.model_validate(core) for core in raw_core['core_papers']],
                                     key=lambda core: (-core.score, core.paper.id))
                warnings.extend(_localize_backend_warnings(raw_core['warnings'], language))
                # The contribution audit can correct a primary label to review.
                # Apply the overview limit again after those corrections.
                overview_seen = False
                final_core = []
                for core in core_papers:
                    if core.role == 'review':
                        if overview_seen:
                            warnings.append(_copy(language, 'audit_review'))
                            continue
                        overview_seen = True
                    final_core.append(core)
                core_papers = final_core
            except (ProviderError, asyncio.TimeoutError):
                if not allow_partial:
                    raise
                # The verified map and bibliography remain useful, but a failed
                # contribution check is retryable rather than a complete cache.
                return current.model_copy(update={
                    'analysis_source': 'pending',
                    'warnings': list(dict.fromkeys([*warnings,
                        _copy(language, 'core_audit_pending')])),
                    'analyzed_paper_count': len(analyzed),
                })
        if analysis_source == 'llm' and len(core_papers) < self.settings.core_paper_limit:
            warnings.append(_copy(language, 'core_fewer'))
        return FieldNode(id=field_id(name), name=name, summary=decomposition.summary,
                         prerequisites=decomposition.prerequisites, subfields=decomposition.subfields,
                         core_papers=core_papers,
                         candidate_count=len(candidates), analyzed_paper_count=len(analyzed), paper_source=source,
                         analysis_source=analysis_source, warnings=list(dict.fromkeys(warnings)), search_queries=search_queries,
                         research_question=research_question,
                         quality_revision=CURRENT_QUALITY_REVISION,
                         language=language,
                          evidence_papers=relation_evidence_papers(decomposition, candidates))
