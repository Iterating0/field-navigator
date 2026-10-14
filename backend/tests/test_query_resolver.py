import asyncio
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.api.fields import resolve as resolve_endpoint
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
        return self.by_query.get(query, self.papers)


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
        llm = ResolverLLM()
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
