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
from app.models.schemas import Decomposition, FieldNode, Paper, PaperJudgment, field_id, normalize_field
from app.providers.base import PaperProvider, ProviderError
from app.providers.mock import MockLLMProvider
from app.services.field_decomposer import FieldDecomposer, PROMPT_VERSION
from app.services.paper_ranker import PaperRanker
from app.services.paper_selector import select_analysis_papers

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
                 ranker: PaperRanker, cache: FieldCache):
        self.settings, self.papers, self.decomposer = settings, papers, decomposer
        self.ranker, self.cache = ranker, cache
        self.locks: WeakValueDictionary[str, asyncio.Lock] = WeakValueDictionary()
        analysis_config = {'version': PROMPT_VERSION, 'llm': bool(settings.llm_api_key), 'model': settings.llm_model,
                  'base': settings.llm_base_url, 'format': settings.llm_response_format,
                  'thinking': settings.thinking_options, 'analysis_limit': settings.llm_analysis_limit}
        self.analysis_fingerprint = digest(analysis_config)
        self.search_fingerprint = digest({'version': 1, 'openalex_key': bool(settings.openalex_api_key),
                                          'search_limit': settings.search_limit})
        self.fingerprint = digest({'analysis': self.analysis_fingerprint, 'search': self.search_fingerprint,
                                   'core_limit': settings.core_paper_limit, 'weights': settings.rank_weights})[:16]

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
                      progress: Progress | None = None) -> FieldNode:
        key = self.fingerprint + ':' + mode + ':' + normalize_field(query)
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
            node = await self._analyze(query, mode, progress, refresh)
            ttl = self.settings.cache_ttl_hours * 3600
            if mode == 'auto' and node.paper_source == 'demo':
                ttl = min(ttl, 300)
            await asyncio.to_thread(self.cache.save, key, node, ttl)
            logger.info('explore_complete cache_hit=false seconds=%.3f', time.perf_counter() - started)
            return node

    async def _analyze(self, query: str, mode: str, progress: Progress | None = None,
                       refresh: bool = False) -> FieldNode:
        warnings = []
        source = 'openalex'
        found = lookup(query)
        name = found[0] if found else query
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
                    papers = await self.papers.search_papers(name, self.settings.search_limit)
                    if not papers:
                        raise ProviderError('未检索到论文。请尝试更具体的英文领域名称或常见别名。', 404)
                    return [p.model_dump() for p in papers]
                search_key = self.search_fingerprint + ':' + normalize_field(name)
                raw = await self._stage('search', search_key, refresh, search)
                candidates = [Paper.model_validate(p) for p in raw]
            except ProviderError as exc:
                if mode != 'auto' or not found:
                    raise
                candidates, source = demo_papers(query), 'demo'
                warnings.append(str(exc) + ' 本次使用离线演示资料。')
        if not candidates:
            raise ProviderError('未检索到论文。请尝试更具体的英文领域名称或常见别名。', 404)
        logger.info('search_complete seconds=%.3f candidates=%d', time.perf_counter() - search_started, len(candidates))
        decomposer = FieldDecomposer(MockLLMProvider(), require_evidence=False) if source == 'demo' else self.decomposer
        analysis_source = 'llm' if self.settings.llm_api_key and source != 'demo' else 'mock'
        if analysis_source == 'mock':
            warnings.append('当前使用预设拆分：领域关系、置信度和阅读优先级仅用于演示；非预设领域不生成分支。')
        if source == 'demo':
            warnings.append('论文书目信息已核对；演示不含实时引用量，排序不代表学术共识。')
        if source == 'openalex' and not any(p.abstract for p in candidates):
            warnings.append('候选论文缺少摘要，分析仅基于标题和书目信息。')
        analyzed = candidates
        if analysis_source == 'llm':
            limit = self.settings.llm_analysis_limit
            analyzed = select_analysis_papers(name, candidates, max(limit, self.settings.core_paper_limit) if limit else 0)
            if len(analyzed) < len(candidates):
                warnings.append(f'候选筛选实验：从 {len(candidates)} 篇检索结果中选择 {len(analyzed)} 篇分析；'
                                '核心论文在该子集中排序，可能遗漏其他研究方向。')
            analysis_key = digest({'config': self.analysis_fingerprint, 'field': normalize_field(name),
                                   'papers': [p.model_dump() for p in analyzed]})

            async def build_map():
                return (await decomposer.decompose_map(name, analyzed)).model_dump()

            async def assess_papers():
                return [j.model_dump() for j in await decomposer.judge_papers(name, analyzed)]

            preview = FieldNode(id=field_id(name), name=name,
                                summary='已找到候选论文，正在分析领域关系。下方论文为初步筛选。',
                                prerequisites=[], subfields=[],
                                core_papers=self.ranker.rank(name, candidates, [], self.settings.core_paper_limit),
                                candidate_count=len(candidates), paper_source=source, analysis_source='pending',
                                phase='papers', warnings=warnings)
            if progress:
                await progress({'type': 'partial', 'stage': 'papers', 'field': preview.model_dump()})
            judgments = asyncio.create_task(self._stage('judgments', analysis_key, refresh, assess_papers))
            try:
                decomposition = Decomposition.model_validate(await self._stage('map', analysis_key, refresh, build_map))
                if progress:
                    preview = preview.model_copy(update={'summary': decomposition.summary,
                        'prerequisites': decomposition.prerequisites, 'subfields': decomposition.subfields,
                        'evidence_papers': relation_evidence_papers(decomposition, candidates),
                        'analysis_source': 'llm', 'phase': 'map'})
                    await progress({'type': 'partial', 'stage': 'map', 'field': preview.model_dump()})
                decomposition.paper_judgments = [PaperJudgment.model_validate(j) for j in await judgments]
            except BaseException:
                judgments.cancel()
                await asyncio.gather(judgments, return_exceptions=True)
                raise
        else:
            decomposition = await decomposer.decompose(name, candidates)
        return FieldNode(id=field_id(name), name=name, summary=decomposition.summary,
                         prerequisites=decomposition.prerequisites, subfields=decomposition.subfields,
                         core_papers=self.ranker.rank(name, analyzed, decomposition.paper_judgments,
                                                     self.settings.core_paper_limit, analysis_source),
                         candidate_count=len(candidates), analyzed_paper_count=len(analyzed), paper_source=source,
                         analysis_source=analysis_source, warnings=warnings,
                         evidence_papers=relation_evidence_papers(decomposition, candidates))
