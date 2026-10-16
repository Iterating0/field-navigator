import asyncio
import json
import time
import httpx
import pytest
from fastapi.testclient import TestClient
from app.config import Settings
from app.data.demo import PAPERS, MAP
from app.db.cache import FieldCache
from app.main import create_app
from app.models.schemas import Decomposition, FieldNode, FieldRelation, Paper, PaperJudgment
from app.providers.base import ProviderError
from app.providers.llm import CompatibleLLMProvider
from app.providers.openalex import OpenAlexProvider, parse_work
from app.services.field_decomposer import FieldDecomposer
from app.services.field_explorer import FieldExplorer
from app.services.paper_ranker import PaperRanker, core_paper_score


@pytest.fixture
def client(tmp_path):
    settings = Settings(_env_file=None, database_path=str(tmp_path / 'cache.db'), llm_api_key='')
    with TestClient(create_app(settings)) as c:
        yield c


def post(client, query='NHSE', mode='demo', **extra):
    return client.post('/api/fields/explore', json=dict(query=query, mode=mode, **extra))


def test_end_to_end_recursive_map_and_normalized_cache(client):
    root = post(client).json()
    assert len(root['core_papers']) == 8 and len(root['subfields']) == 4
    assert root['paper_source'] == 'demo' and not root['cache_hit']
    assert all(p['reason'] and 0 <= p['score'] <= 1 for p in root['core_papers'])
    relation_ids = {paper_id for relation in [*root['prerequisites'], *root['subfields']]
                    for paper_id in relation['evidence_paper_ids']}
    assert {paper['id'] for paper in root['evidence_papers']} == relation_ids
    assert post(client, '  non-Hermitian   skin effect  ').json()['cache_hit']
    child = post(client, 'Incoherent NHSE').json()
    assert child['subfields'][0]['name'] == 'Photonic quantum walks'
    assert child['core_papers'][0]['paper']['id'] == 'arxiv:2404.04536'
    leaf = post(client, child['subfields'][0]['name']).json()
    assert leaf['subfields'] == []
    for name in MAP:
        assert post(client, name).status_code == 200


def test_cache_persists_and_stores_relations_atomically(client):
    first = post(client).json()
    cache = FieldCache(client.app.state.explorer.cache.path)
    key = client.app.state.explorer.fingerprint + ':demo:non-hermitian skin effect'
    assert cache.get(key).id == first['id']
    with cache.connect() as db:
        assert db.execute('SELECT COUNT(*) FROM field_core_papers').fetchone()[0] == 8
        assert db.execute('SELECT COUNT(*) FROM field_relations').fetchone()[0] == 6
    refreshed = post(client, refresh=True).json()
    assert not refreshed['cache_hit']
    assert post(client).json()['cache_hit']


def test_expired_cache_is_not_used(client):
    post(client)
    with client.app.state.explorer.cache.connect() as db:
        db.execute('UPDATE fields SET expires_at=?', (time.time() - 1,))
    assert not post(client).json()['cache_hit']


def test_bad_inputs_and_unknown_demo_do_not_fabricate_fields(client):
    for value in ['', ' ', 'x', 'a' * 181]:
        assert post(client, value).status_code == 422
    assert post(client, 'Protein folding').status_code == 422
    assert client.app.state.explorer.cache.count() == 0


def test_legacy_field_payload_defaults_missing_evidence_metadata(client):
    payload = post(client).json()
    payload.pop('evidence_papers')
    assert FieldNode.model_validate(payload).evidence_papers == []


class SearchStub:
    def __init__(self, papers=None, error=None):
        self.papers = papers if papers is not None else PAPERS[:5]
        self.error = error
        self.calls = 0

    async def search_papers(self, query, limit=40):
        self.calls += 1
        await asyncio.sleep(.01)
        if self.error:
            raise self.error
        return self.papers


def test_relation_evidence_survives_core_paper_shortlist(tmp_path):
    class Decomposer:
        async def decompose(self, *args):
            return Decomposition(
                summary='Map',
                prerequisites=[],
                subfields=[FieldRelation(
                    name='Supporting field',
                    reason='The second candidate provides direct support.',
                    confidence=.8,
                    evidence_paper_ids=['W2'],
                )],
                paper_judgments=[],
            )

    settings = Settings(_env_file=None, llm_api_key='', core_paper_limit=1,
                        database_path=str(tmp_path / 'evidence.db'))
    candidates = [Paper(id='W1', title='Test field'),
                  Paper(id='W2', title='Unrelated supporting paper')]
    explorer = FieldExplorer(settings, SearchStub(candidates), Decomposer(),
                             PaperRanker(settings.rank_weights), FieldCache(settings.db_path))
    result = asyncio.run(explorer.explore('Test field', 'live'))
    assert [paper.paper.id for paper in result.core_papers] == ['W1']
    assert [paper.id for paper in result.evidence_papers] == ['W2']


def test_live_mode_does_not_read_demo_cache_or_silently_fallback(client):
    post(client)
    stub = SearchStub(error=ProviderError('OpenAlex rate limited', 429))
    client.app.state.explorer.papers = stub
    response = post(client, mode='live')
    assert response.status_code == 429
    result = post(client, mode='auto').json()
    assert result['paper_source'] == 'demo' and any('429' in w or 'rate limited' in w for w in result['warnings'])
    assert post(client, 'Unlisted field', mode='auto').status_code == 429


def test_unknown_field_without_llm_has_papers_but_no_invented_taxonomy(client):
    client.app.state.explorer.papers = SearchStub()
    result = post(client, 'Protein folding', mode='live').json()
    assert result['prerequisites'] == result['subfields'] == []
    assert len(result['core_papers']) == 5
    assert result['paper_source'] == 'openalex'
    assert result['analysis_source'] == 'pending' and result['phase'] == 'papers'
    assert result['evidence_papers'] == []


def test_empty_search_not_cached(client):
    stub = SearchStub(papers=[])
    client.app.state.explorer.papers = stub
    assert post(client, mode='live').status_code == 404
    assert post(client, mode='live').status_code == 404
    assert stub.calls == 2


def test_concurrent_requests_share_work_and_failed_refresh_preserves_cache(client):
    explorer = client.app.state.explorer
    stub = SearchStub()
    explorer.papers = stub
    async def run():
        return await asyncio.gather(*(explorer.explore('NHSE', 'live') for _ in range(4)))
    results = asyncio.run(run())
    assert stub.calls == 1 and sum(r.cache_hit for r in results) == 3
    stub.error = ProviderError('test failure')
    assert post(client, mode='live', refresh=True).status_code == 502
    assert post(client, mode='live').json()['cache_hit']


def test_ranking_uses_relevance_not_only_citations():
    papers = [Paper(id='relevant', title='Non-Hermitian Skin Effect', year=2024, citation_count=100),
              Paper(id='unrelated', title='Unrelated famous topic', year=2010, citation_count=100000)]
    judgments = [PaperJudgment(paper_id='relevant', relevance=1, importance=1, reason='Directly develops the target field.'),
                 PaperJudgment(paper_id='unrelated', relevance=0, importance=0, reason='Unrelated to the field.')]
    ranked = PaperRanker(Settings(_env_file=None).rank_weights).rank('NHSE', papers, judgments)
    assert ranked[0].paper.id == 'relevant'
    assert core_paper_score({'relevance': .8}, {'relevance': .3, 'citation': .7}) == .8


def test_year_unknown_and_missing_citations_do_not_count_as_zero():
    paper = Paper(id='1', title='Non-Hermitian Skin Effect')
    result = PaperRanker(Settings(_env_file=None).rank_weights).rank('NHSE', [paper], [])[0]
    assert set(result.signals) == {'relevance'}
    assert result.score == .8


def test_candidate_reference_signal():
    papers = [Paper(id='W1', title='Non-Hermitian Skin Effect'),
              Paper(id='W2', title='Non-Hermitian Skin Effect', referenced_works=['W1', 'W1']),
              Paper(id='W3', title='Non-Hermitian Skin Effect', referenced_works=['W1'])]
    results = PaperRanker(Settings(_env_file=None).rank_weights).rank('NHSE', papers, [])
    assert results[0].paper.id == 'W1'
    assert '2' in results[0].reason and results[0].signals['shared_references'] == 1


def test_openalex_maps_metadata_and_abstract():
    paper = parse_work({'id': 'https://openalex.org/W123', 'title': 'A title', 'cited_by_count': 12,
                        'abstract_inverted_index': {'world': [1], 'Hello': [0]},
                        'primary_location': None, 'authorships': []})
    assert paper.abstract == 'Hello world' and paper.citation_count == 12


def test_openalex_request_contract_and_rate_limit():
    seen = []
    def handle(request):
        seen.append(request)
        return httpx.Response(429 if len(seen) > 1 else 200, json={'results': [{'id': 'https://openalex.org/W1', 'title': 'Paper'}]})
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as http:
            provider = OpenAlexProvider(http, 'test-key')
            assert len(await provider.search_papers('NHSE', 40)) == 1
            with pytest.raises(ProviderError, match='429'):
                await provider.get_citations('W1')
    asyncio.run(run())
    assert seen[0].headers['authorization'] == 'Bearer test-key'
    assert seen[0].url.params['search'] == 'NHSE'
    assert seen[1].url.params['filter'].startswith('cites:W1')


def test_decomposer_rejects_bad_schema_and_filters_invented_evidence():
    class FakeLLM:
        async def generate_structured(self, **kwargs):
            return {'summary': 'Summary', 'prerequisites': [], 'subfields': [
                {'name': 'NHSE', 'reason': 'self', 'confidence': .9, 'evidence_paper_ids': ['1']},
                {'name': 'Invented evidence', 'reason': 'unsupported', 'confidence': .8, 'evidence_paper_ids': ['fake']},
                {'name': 'Valid field', 'reason': 'supported', 'confidence': .8, 'evidence_paper_ids': ['1']}],
                'paper_judgments': []}
    result = asyncio.run(FieldDecomposer(FakeLLM()).decompose('Non-Hermitian Skin Effect', [Paper(id='1', title='Paper')]))
    assert [r.name for r in result.subfields] == ['Valid field']
    class Invalid:
        async def generate_structured(self, **kwargs):
            return {'summary': 'Missing required keys'}
    with pytest.raises(ProviderError, match='schema'):
        asyncio.run(FieldDecomposer(Invalid()).decompose('NHSE', []))


def test_llm_transport_uses_strict_schema_and_handles_invalid_json():
    requests = []
    def handler(request):
        requests.append(json.loads(request.content))
        content = '{}' if len(requests) == 1 else 'not json'
        return httpx.Response(200, json={'choices': [{'finish_reason': 'stop', 'message': {'content': content}}]})
    async def run():
        settings = Settings(_env_file=None, llm_api_key='test-key', llm_model='test-model',
                            llm_response_format='json_schema')
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            provider = CompatibleLLMProvider(http, settings)
            assert await provider.generate_structured(system='Return JSON', payload={}, schema=Decomposition.model_json_schema()) == {}
            with pytest.raises(ProviderError):
                await provider.generate_structured(system='Return JSON', payload={}, schema={})
    asyncio.run(run())
    assert requests[0]['response_format']['json_schema']['strict'] is True


def test_cache_configuration_changes_and_health_hides_keys(client, tmp_path):
    first = client.app.state.explorer.fingerprint
    settings = Settings(_env_file=None, database_path=str(tmp_path / 'other.db'), rank_relevance=.7)
    with TestClient(create_app(settings)) as other:
        assert other.app.state.explorer.fingerprint != first
        health = other.get('/api/health').json()
        assert set(health) == {'status', 'llm_configured', 'llm_ready', 'openalex_key_configured'}


def test_demo_never_calls_paid_model_even_with_key(tmp_path):
    settings = Settings(_env_file=None, database_path=str(tmp_path / 'demo.db'),
                        llm_api_key='test-key', llm_model='test-model')
    with TestClient(create_app(settings)) as client:
        result = post(client).json()
        assert result['analysis_source'] == 'mock' and result['paper_source'] == 'demo'
