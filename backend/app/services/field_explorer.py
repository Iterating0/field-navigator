import asyncio
import hashlib
import json
import time
import logging
from collections.abc import Awaitable, Callable
from weakref import WeakValueDictionary
from app.config import Settings
from app.db.cache import FieldCache
from app.data.demo import demo_papers, lookup
from app.models.schemas import Decomposition, FieldNode, Paper, PaperJudgment, CorePaper, field_id, normalize_field
from app.models.schemas import CURRENT_QUALITY_REVISION
from app.providers.base import PaperProvider, ProviderError
from app.providers.mock import MockLLMProvider
from app.services.field_decomposer import FieldDecomposer, PROMPT_VERSION
from app.services.paper_ranker import PaperRanker
from app.services.paper_selector import select_analysis_papers
from app.services.paper_quality import quality_filter_and_dedupe
from app.services.literature_retriever import LiteratureRetriever, RETRIEVAL_VERSION

Progress = Callable[[dict], Awaitable[None]]
logger = logging.getLogger(__name__)


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
                                   'ranking_revision': 4})[:16]

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
                      research_question: str | None = None) -> FieldNode:
        research_question = ' '.join(research_question.split()) if research_question and mode != 'demo' else None
        key = self.cache_key(query, mode, research_question)
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
                                       research_question=research_question)
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

    def cache_key(self, query: str, mode: str, research_question: str | None = None) -> str:
        key = self.fingerprint + ':' + mode + ':' + normalize_field(query)
        if research_question and mode != 'demo':
            key += ':question:' + digest(normalize_field(research_question))[:20]
        return key

    async def _analyze(self, query: str, mode: str, progress: Progress | None = None,
                       refresh: bool = False, *, allow_partial: bool = False,
                       research_question: str | None = None) -> FieldNode:
        warnings = []
        search_queries = [query]
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
                raise ProviderError('离线演示仅覆盖 NHSE 及其预设分支。请切换自动或实时模式探索其他领域。', 422)
        else:
            try:
                async def search():
                    if self.retriever:
                        retrieval = await self.retriever.retrieve(name, self.settings.search_limit,
                                                                  research_question=research_question)
                        return {'papers': [p.model_dump() for p in retrieval.papers],
                                'queries': retrieval.queries, 'warnings': retrieval.warnings}
                    papers = quality_filter_and_dedupe(await self.papers.search_papers(name, self.settings.search_limit))
                    if not papers:
                        raise ProviderError('未检索到论文。请尝试更具体的英文领域名称或常见别名。', 404)
                    return {'papers': [p.model_dump() for p in papers], 'queries': [name], 'warnings': []}
                search_key = self.search_fingerprint + ':' + normalize_field(name)
                if self.retriever and research_question:
                    search_key += ':' + digest(normalize_field(research_question))[:20]
                raw = await self._stage('search', search_key, refresh, search)
                candidates = quality_filter_and_dedupe([Paper.model_validate(p) for p in raw['papers']])
                search_queries = raw['queries']
                warnings.extend(raw['warnings'])
            except ProviderError as exc:
                if mode != 'auto' or not found:
                    raise
                candidates, source = demo_papers(query), 'demo'
                warnings.append(str(exc) + ' 本次使用离线演示资料。')
        if not candidates:
            raise ProviderError('未检索到论文。请尝试更具体的英文领域名称或常见别名。', 404)
        logger.info('search_complete seconds=%.3f candidates=%d', time.perf_counter() - search_started, len(candidates))
        if source == 'openalex' and not any(p.abstract for p in candidates):
            warnings.append('候选论文缺少摘要，分析仅基于标题和书目信息。')
        model_ready = bool(self.settings.llm_api_key and self.settings.llm_model.strip())
        if source == 'openalex' and not model_ready and allow_partial:
            logger.warning(
                'analysis_unavailable phase=papers source=openalex key_configured=%s '
                'model_configured=%s response_format=%s',
                bool(self.settings.llm_api_key), bool(self.settings.llm_model.strip()),
                self.settings.llm_response_format,
            )
            warnings.append('已找到候选论文，但模型分析尚未完成。请稍后重试，或选择离线示例。')
            return FieldNode(
                id=field_id(name), name=name,
                summary='已找到候选论文，但模型分析尚未完成。下方论文为初步筛选。',
                prerequisites=[], subfields=[],
                core_papers=self.ranker.rank(
                    ranking_scope, candidates, [], self.settings.core_paper_limit, 'pending'),
                candidate_count=len(candidates), analyzed_paper_count=0,
                paper_source='openalex', analysis_source='pending', phase='papers',
                warnings=warnings,
                search_queries=search_queries,
                research_question=research_question,
                quality_revision=CURRENT_QUALITY_REVISION,
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
            warnings.append('当前使用预设拆分：领域关系、置信度和阅读优先级仅用于演示；非预设领域不生成分支。')
        if source == 'demo':
            warnings.append('论文书目信息已核对；演示不含实时引用量，排序不代表学术共识。')
        analyzed = candidates
        if analysis_source == 'llm':
            limit = self.settings.llm_analysis_limit
            analyzed = select_analysis_papers(ranking_scope, candidates, max(limit, self.settings.core_paper_limit) if limit else 0)
            if len(analyzed) < len(candidates):
                warnings.append(f'候选筛选实验：从 {len(candidates)} 篇检索结果中选择 {len(analyzed)} 篇分析；'
                                '核心论文在该子集中排序，可能遗漏其他研究方向。')
            analysis_key = digest({'config': self.analysis_fingerprint, 'field': normalize_field(name),
                                   'research_question': research_question,
                                   'papers': [p.model_dump() for p in analyzed]})

            async def build_map():
                kwargs = {'research_question': research_question} if research_question else {}
                decomposition = await decomposer.decompose_map(name, analyzed, **kwargs)
                if decomposition.evidence_audit_complete is False:
                    raise ProviderError('独立证据审查未完成；本次保留论文初筛，请重试补齐分支核对。')
                return decomposition.model_dump()

            async def assess_papers():
                kwargs = {'research_question': research_question} if research_question else {}
                return [j.model_dump() for j in await decomposer.judge_papers(name, analyzed, **kwargs)]

            preview = FieldNode(id=field_id(name), name=name,
                                summary='已找到候选论文，正在分析领域关系。下方论文为初步筛选。',
                                prerequisites=[], subfields=[],
                                core_papers=self.ranker.rank(ranking_scope, candidates, [], self.settings.core_paper_limit, 'pending'),
                                candidate_count=len(candidates), paper_source=source, analysis_source='pending',
                                phase='papers', warnings=warnings, search_queries=search_queries,
                                research_question=research_question, quality_revision=CURRENT_QUALITY_REVISION)
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
                    'warnings': list(dict.fromkeys([*warnings, *decomposition.warnings]))})
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
                warning = '已找到论文，但模型分析尚未完成。可先阅读当前初筛论文，稍后重试或选择离线示例。'
                return current.model_copy(update={
                    'analysis_source': 'pending',
                    'warnings': [*current.warnings, warning],
                    'analyzed_paper_count': len(analyzed),
                })
        else:
            decomposition = await decomposer.decompose(name, candidates)
        warnings.extend(decomposition.warnings)
        core_papers = self.ranker.rank(ranking_scope, analyzed, decomposition.paper_judgments,
                                      self.settings.core_paper_limit, analysis_source)
        if analysis_source == 'llm' and hasattr(decomposer, 'audit_core_papers') and core_papers:
            core_key = digest({'analysis': analysis_key, 'ranking': self.fingerprint,
                               'core_papers': [core.model_dump() for core in core_papers]})

            async def audit_core():
                audited, audit_warnings = await decomposer.audit_core_papers(
                    name, core_papers, analyzed, research_question=research_question)
                return {'core_papers': [core.model_dump() for core in audited], 'warnings': audit_warnings}

            try:
                raw_core = await self._stage('core_audit', core_key, refresh, audit_core)
                core_papers = sorted([CorePaper.model_validate(core) for core in raw_core['core_papers']],
                                     key=lambda core: (-core.score, core.paper.id))
                warnings.extend(raw_core['warnings'])
                # The contribution audit can correct a primary label to review.
                # Apply the overview limit again after those corrections.
                overview_seen = False
                final_core = []
                for core in core_papers:
                    if core.role == 'review':
                        if overview_seen:
                            warnings.append('独立核对后仅保留一篇综述导读；其余综述未占用核心研究位置。')
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
                        '领域关系已完成；核心论文贡献说明尚未完成独立核对，请重试补齐。'])),
                    'analyzed_paper_count': len(analyzed),
                })
        if analysis_source == 'llm' and len(core_papers) < self.settings.core_paper_limit:
            warnings.append('通过范围与证据筛选的核心论文不足预设数量；未用低相关条目补足。')
        return FieldNode(id=field_id(name), name=name, summary=decomposition.summary,
                         prerequisites=decomposition.prerequisites, subfields=decomposition.subfields,
                         core_papers=core_papers,
                         candidate_count=len(candidates), analyzed_paper_count=len(analyzed), paper_source=source,
                         analysis_source=analysis_source, warnings=list(dict.fromkeys(warnings)), search_queries=search_queries,
                         research_question=research_question,
                         quality_revision=CURRENT_QUALITY_REVISION,
                          evidence_papers=relation_evidence_papers(decomposition, candidates))
