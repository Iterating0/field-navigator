import asyncio
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.api.fields import resolve as resolve_endpoint, _watch_client_disconnect
from app.config import Settings
from app.db.cache import FieldCache
from app.main import create_app
from app.models.schemas import Decomposition, Paper, ResolveRequest
from app.providers.base import ProviderError
from app.services.access_policy import LiveRequestGate
from app.services.query_resolver import QueryResolver


class ResolverPapers:
    def __init__(self, papers=None, by_query=None):
        self.papers = papers if papers is not None else [
            Paper(id='W1', title='Quantum transport evidence', abstract='Evidence')
        ]
        self.by_query = by_query or {}
        self.queries = []

    async def search_papers(self, query, limit=40):
        self.queries.append((query, limit))
        result = self.by_query.get(query, self.papers)
        if isinstance(result, BaseException):
            raise result
        return result


def test_disconnect_watcher_honours_cancellation_consumed_by_request_probe():
    async def run():
        entered = asyncio.Event()

        class RequestProbe:
            swallowed = False

            async def is_disconnected(self):
                entered.set()
                try:
                    await asyncio.sleep(10)
                except asyncio.CancelledError:
                    if self.swallowed:
                        raise
                    self.swallowed = True
                    return False

        task = asyncio.create_task(_watch_client_disconnect(RequestProbe()))
        await entered.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, timeout=.3)

    asyncio.run(run())


class ResolverLLM:
    def __init__(self, result=None, delay=0):
        self.result = result or {'candidates': [
            {'query': 'quantum transport', 'name': 'Quantum transport',
             'summary': 'Transport phenomena in quantum systems.'},
            {'query': 'unsupported direction', 'name': 'Unsupported direction',
             'summary': 'A second possible direction.'},
        ]}
        self.delay = delay
        self.calls = 0
        self.payloads = []

    async def generate_structured(self, **kwargs):
        self.calls += 1
        self.payloads.append(kwargs['payload'])
        if self.delay:
            await asyncio.sleep(self.delay)
        return self.result


def make_client(tmp_path, **kwargs):
    settings = Settings(_env_file=None, database_path=str(tmp_path / 'resolve.db'), **kwargs)
    return TestClient(create_app(settings))


def test_alias_and_direct_resolution_do_not_call_external_providers(tmp_path):
    with make_client(tmp_path) as client:
        papers = ResolverPapers()
        client.app.state.resolver.papers = papers

        alias = client.post('/api/fields/resolve', json={'query': 'NHSE', 'mode': 'auto'})
        assert alias.status_code == 200
        assert alias.json()['status'] == 'ready'
        assert alias.json()['source'] == 'alias'
        assert alias.json()['candidates'][0]['query'] == 'Non-Hermitian Skin Effect'
        assert alias.json()['candidates'][0]['evidence_papers']

        direct = client.post('/api/fields/resolve', json={
            'query': 'quantum transport', 'mode': 'auto'})
        assert direct.status_code == 200
        assert direct.json()['source'] == 'direct'
        assert direct.json()['candidates'][0]['query'] == 'quantum transport'
        assert papers.queries == []


def test_ambiguous_chinese_input_without_model_only_clarifies(tmp_path):
    with make_client(tmp_path) as client:
        papers = ResolverPapers(by_query={'unsupported direction': []})
        client.app.state.resolver.papers = papers
        response = client.post('/api/fields/resolve', json={
            'query': '我想了解 KTO 界面超导', 'mode': 'auto'})
        result = response.json()
        assert response.status_code == 200
        assert result['status'] == 'clarify'
        assert result['candidates'] == []
        assert '语言模型' in result['message']
        assert papers.queries == []


def test_llm_candidates_are_probed_with_exact_queries_and_cached(tmp_path):
    with make_client(tmp_path, llm_api_key='test-key', llm_model='test-model') as client:
        papers = ResolverPapers(by_query={'unsupported direction': []})
        llm = ResolverLLM(result={
            'candidates': [
                {'query': 'quantum transport', 'name': 'Quantum transport',
                 'summary': 'Transport phenomena in quantum systems.'},
                {'query': 'unsupported direction', 'name': 'Unsupported direction',
                 'summary': 'A second mutually exclusive interpretation.'},
            ],
            'multiple_interpretations': True,
        })
        client.app.state.resolver.papers = papers
        client.app.state.resolver.llm = llm
        client.app.state.resolver.llm_ready = True

        body = {'query': '我想研究量子输运', 'mode': 'live'}
        first = client.post('/api/fields/resolve', json=body)
        second = client.post('/api/fields/resolve', json=body)
        assert first.status_code == second.status_code == 200
        assert first.json()['status'] == 'ready'
        assert first.json()['source'] == 'llm'
        assert [item['query'] for item in first.json()['candidates']] == ['quantum transport']
        assert papers.queries == [('quantum transport', 6), ('unsupported direction', 6)]
        assert llm.calls == 1
        assert llm.payloads[0] == {'user_query': '我想研究量子输运'}


def test_cohesive_request_does_not_promote_surviving_complementary_facet(tmp_path):
    """A failed central probe must not turn a subquestion into the scope."""
    central = 'tidal deformability GW170817 neutron star equation of state constraints'
    facet = 'electromagnetic counterparts GW170817 systematic errors'
    result = {
        'candidates': [
            {'query': central, 'name': 'Central target',
             'summary': 'The complete question in one search target.'},
            {'query': facet, 'name': 'Complementary facet',
             'summary': 'A requested error facet, not a separate interpretation.'},
        ],
        # The model must explicitly opt into mutually exclusive meanings.
        'multiple_interpretations': False,
    }
    with make_client(tmp_path, llm_api_key='test-key', llm_model='test-model') as client:
        papers = ResolverPapers(by_query={
            central: ProviderError('central probe timed out', 504),
            facet: [Paper(id='facet', title='Electromagnetic counterpart evidence')],
        })
        client.app.state.resolver.papers = papers
        client.app.state.resolver.llm = ResolverLLM(result=result)
        client.app.state.resolver.llm_ready = True

        response = client.post('/api/fields/resolve', json={
            'query': 'GW170817 双中子星并合的潮汐形变怎样约束中子星状态方程，需要区分哪些系统误差？',
            'mode': 'live', 'refresh': True,
        })

        payload = response.json()
        assert response.status_code == 200
        assert payload['status'] == 'clarify'
        assert payload['candidates'] == []
        assert papers.queries == [(central, 6)]
        assert asyncio.run(client.app.state.resolver.cached(
            payload['query'], 'live')) is None


def test_compound_center_target_keeps_hard_scope_without_keyword_stuffing_rejection(tmp_path):
    """A bounded compound target remains usable when a model slightly overruns 12 words."""
    target = (
        'inorganic solid electrolyte lithium metal battery dendrite filament '
        'formation current density mechanical defects stack pressure'
    )
    assert len(target.split()) == 15
    result = {
        'candidates': [{
            'query': target,
            'name': 'Solid electrolyte filament formation',
            'summary': 'Compare current density, mechanical defects, and stack pressure within the stated system.',
        }],
        'multiple_interpretations': False,
    }
    with make_client(tmp_path, llm_api_key='test-key', llm_model='test-model') as client:
        papers = ResolverPapers(by_query={
            target: [Paper(id='solid-center', title='Solid electrolyte filament formation')],
        })
        resolver = client.app.state.resolver
        resolver.papers = papers
        resolver.llm = ResolverLLM(result=result)
        resolver.llm_ready = True

        payload = client.post('/api/fields/resolve', json={
            'query': '无机固态电解质锂金属电池中枝晶或丝状体的形成与电流、缺陷、堆压因素',
            'mode': 'live', 'refresh': True,
        }).json()

        assert payload['status'] == 'ready'
        assert [candidate['query'] for candidate in payload['candidates']] == [target]
        assert papers.queries == [(target, 6)]


def test_true_mutual_ambiguity_keeps_each_interpretation(tmp_path):
    """Only an explicit ambiguity marker permits multiple probes/results."""
    first = 'cell type deconvolution spatial transcriptomics'
    second = 'spot deconvolution spatial transcriptomics'
    result = {
        'candidates': [
            {'query': first, 'name': 'Cell type deconvolution',
             'summary': 'Interpretation one.'},
            {'query': second, 'name': 'Spot deconvolution',
             'summary': 'Interpretation two.'},
        ],
        'multiple_interpretations': True,
    }
    with make_client(tmp_path, llm_api_key='test-key', llm_model='test-model') as client:
        papers = ResolverPapers(by_query={
            first: [Paper(id='first', title='Cell type deconvolution evidence')],
            second: [Paper(id='second', title='Spot deconvolution evidence')],
        })
        client.app.state.resolver.papers = papers
        client.app.state.resolver.llm = ResolverLLM(result=result)
        client.app.state.resolver.llm_ready = True

        payload = client.post('/api/fields/resolve', json={
            'query': '空间转录组中的 deconvolution 到底指细胞类型还是 spot 层面的反卷积？',
            'mode': 'live', 'refresh': True,
        }).json()

        assert payload['status'] == 'choose'
        assert [candidate['query'] for candidate in payload['candidates']] == [first, second]
        assert papers.queries == [(first, 6), (second, 6)]


def test_resolve_deadline_returns_clarify_without_success_cache(tmp_path):
    with make_client(tmp_path, llm_api_key='test-key', llm_model='test-model',
                     resolve_timeout_seconds=.01) as client:
        llm = ResolverLLM(delay=.1)
        client.app.state.resolver.llm = llm
        client.app.state.resolver.llm_ready = True
        result = client.post('/api/fields/resolve', json={
            'query': '我想研究量子输运', 'mode': 'live'}).json()
        assert result['status'] == 'clarify'
        assert result['candidates'] == []
        assert '未生成候选' in result['message']
        with client.app.state.resolver.cache.connect() as db:
            assert db.execute("SELECT COUNT(*) FROM analysis_artifacts WHERE kind='resolve'").fetchone()[0] == 0


def test_live_resolve_uses_public_budget(tmp_path):
    with make_client(tmp_path, llm_api_key='test-key', llm_model='test-model',
                     live_request_budget=1, live_max_concurrency=1) as client:
        client.app.state.resolver.llm = ResolverLLM()
        client.app.state.resolver.llm_ready = True
        client.app.state.resolver.papers = ResolverPapers()
        first = client.post('/api/fields/resolve', json={
            'query': '我想研究量子输运', 'mode': 'live', 'refresh': True})
        denied = client.post('/api/fields/resolve', json={
            'query': '我想研究拓扑材料', 'mode': 'live', 'refresh': True})
        assert first.status_code == 200
        assert denied.status_code == 429


@pytest.mark.parametrize('status', [429, 503, 504])
def test_transient_model_failure_does_not_ask_user_to_change_configuration(tmp_path, status):
    with make_client(tmp_path, llm_api_key='test-key', llm_model='test-model') as client:
        class UnavailableLLM:
            async def generate_structured(self, **kwargs):
                raise ProviderError('模型服务暂时不可用', status)

        resolver = client.app.state.resolver
        resolver.llm = UnavailableLLM()
        resolver.llm_ready = True
        papers = ResolverPapers()
        resolver.papers = papers
        query = '空间转录组如何反卷积'
        result = client.post('/api/fields/resolve', json={
            'query': query, 'mode': 'live', 'refresh': True,
        }).json()
        assert result['status'] == 'clarify'
        assert result['candidates'] == []
        assert '稍后重试' in result['message']
        assert '检查模型配置' not in result['message']
        assert papers.queries == []
        assert asyncio.run(resolver.cached(query, 'live')) is None


def test_llm_failure_is_not_mistaken_for_evidence(tmp_path):
    with make_client(tmp_path, llm_api_key='test-key', llm_model='test-model') as client:
        class FailingLLM:
            async def generate_structured(self, **kwargs):
                raise ProviderError('schema 不受支持', 502)

        client.app.state.resolver.llm = FailingLLM()
        client.app.state.resolver.llm_ready = True
        result = client.post('/api/fields/resolve', json={
            'query': '我想研究量子输运', 'mode': 'live'}).json()
        assert result['status'] == 'clarify'
        assert result['candidates'] == []
        assert 'schema' in result['message']


def test_missing_model_keeps_retrieved_papers_without_full_cache(tmp_path):
    with make_client(tmp_path, llm_api_key='test-key', llm_model='') as client:
        client.app.state.explorer.papers = ResolverPapers()
        response = client.post('/api/fields/explore', json={
            'query': 'quantum transport', 'mode': 'live'})
        result = response.json()
        assert response.status_code == 200
        assert result['phase'] == 'papers'
        assert result['analysis_source'] == 'pending'
        assert result['core_papers']
        assert any('模型分析尚未完成' in warning for warning in result['warnings'])
        assert all('LLM_MODEL' not in warning and '响应格式' not in warning
                   for warning in result['warnings'])
        assert client.app.state.explorer.cache.count() == 0


def test_realtime_without_llm_keeps_openalex_papers_without_demo_relations(tmp_path):
    with make_client(tmp_path, llm_api_key='') as client:
        class ForbiddenDecomposer:
            async def decompose(self, *args, **kwargs):
                raise AssertionError('realtime no-model path must not build a mock relation map')

        client.app.state.explorer.papers = ResolverPapers()
        client.app.state.explorer.decomposer = ForbiddenDecomposer()
        response = client.post('/api/fields/explore', json={
            'query': 'NHSE', 'mode': 'live'})
        result = response.json()
        assert response.status_code == 200
        assert result['paper_source'] == 'openalex'
        assert result['phase'] == 'papers'
        assert result['analysis_source'] == 'pending'
        assert result['core_papers']
        assert result['prerequisites'] == result['subfields'] == []
        assert result['evidence_papers'] == []
        assert any('模型分析尚未完成' in warning for warning in result['warnings'])
        assert client.app.state.explorer.cache.count() == 0


def test_live_resolve_cancels_on_disconnected_request_and_releases_gate(tmp_path):
    async def run():
        class BlockingLLM:
            def __init__(self):
                self.started = asyncio.Event()
                self.cancelled = False

            async def generate_structured(self, **kwargs):
                self.started.set()
                try:
                    await asyncio.Event().wait()
                except asyncio.CancelledError:
                    self.cancelled = True
                    raise

        class RequestStub:
            def __init__(self, resolver, cache, gate, llm):
                self.app = SimpleNamespace(state=SimpleNamespace(
                    resolver=resolver,
                    explorer=SimpleNamespace(fingerprint='explorer', cache=cache),
                    live_gate=gate,
                ))
                self.llm = llm

            async def is_disconnected(self):
                await self.llm.started.wait()
                return True

        settings = Settings(
            _env_file=None,
            llm_api_key='test-key',
            llm_model='test-model',
            database_path=str(tmp_path / 'disconnect.db'),
        )
        cache = FieldCache(settings.db_path)
        llm = BlockingLLM()
        resolver = QueryResolver(settings, llm, ResolverPapers(), cache)
        gate = LiveRequestGate(budget=1, max_concurrency=1)
        request = RequestStub(resolver, cache, gate, llm)

        with pytest.raises(HTTPException) as caught:
            await resolve_endpoint(
                ResolveRequest(query='我想研究量子输运', mode='live', refresh=True),
                request,
            )

        assert caught.value.status_code == 499
        assert llm.cancelled
        assert gate.active == 0
        assert gate.used == 1
        with cache.connect() as db:
            assert db.execute(
                "SELECT COUNT(*) FROM analysis_artifacts WHERE kind='resolve'"
            ).fetchone()[0] == 0

    asyncio.run(run())


def test_failed_judgment_returns_map_phase_without_full_cache(tmp_path):
    with make_client(tmp_path, llm_api_key='test-key', llm_model='test-model') as client:
        class FailingDecomposer:
            async def decompose_map(self, *args):
                return Decomposition(summary='Map from evidence', prerequisites=[], subfields=[], paper_judgments=[])

            async def judge_papers(self, *args):
                raise ProviderError('模型额度已用完', 429)

        client.app.state.explorer.papers = ResolverPapers()
        # With a configured model the app also constructs its optional live
        # retriever; this unit test supplies its own paper provider and should
        # not reach OpenAlex.
        client.app.state.explorer.retriever = None
        client.app.state.explorer.decomposer = FailingDecomposer()
        response = client.post('/api/fields/explore', json={
            'query': 'quantum transport', 'mode': 'live'})
        result = response.json()
        assert response.status_code == 200
        assert result['phase'] == 'map'
        assert result['analysis_source'] == 'pending'
        assert result['summary'] == 'Map from evidence'
        assert any('模型分析尚未完成' in warning for warning in result['warnings'])
        assert all('LLM_MODEL' not in warning and '响应格式' not in warning
                   for warning in result['warnings'])
        assert client.app.state.explorer.cache.count() == 0
