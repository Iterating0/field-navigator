import asyncio
import json
from types import SimpleNamespace

from fastapi.testclient import TestClient
import pytest

from app.config import Settings
from app.db.cache import FieldCache
from app.main import create_app
from app.models.schemas import Decomposition, FieldRelation, Paper, PaperJudgment
from app.models.schemas import ExploreRequest
from app.api.fields import explore_stream
from app.providers.base import ProviderError
from app.services.field_decomposer import FieldDecomposer
from app.services.field_explorer import FieldExplorer
from app.services.paper_ranker import PaperRanker


class Papers:
    async def search_papers(self, *args):
        return [Paper(id='W1', title='Test field', abstract='Evidence')]


def make_explorer(tmp_path, decomposer):
    config = Settings(_env_file=None, llm_api_key='test', llm_model='test-model',
                      database_path=str(tmp_path / 'cache.db'))
    return FieldExplorer(config, Papers(), decomposer, PaperRanker(config.rank_weights), FieldCache(config.db_path))


def test_papers_and_map_arrive_before_evaluation_and_only_final_is_cached(tmp_path):
    async def run():
        release = asyncio.Event()
        evaluation_started = asyncio.Event()

        class Decomposer:
            async def decompose_map(self, *args):
                await evaluation_started.wait()
                return Decomposition(
                    summary='Map ready',
                    prerequisites=[],
                    subfields=[FieldRelation(
                        name='Supporting field',
                        reason='Supported by the candidate paper.',
                        confidence=.8,
                        evidence_paper_ids=['W1'],
                    )],
                    paper_judgments=[],
                )

            async def judge_papers(self, *args):
                evaluation_started.set()
                await release.wait()
                return [PaperJudgment(paper_id='W1', importance=.9, relevance=.9, reason='Evidence')]

        explorer = make_explorer(tmp_path, Decomposer())
        events = []

        async def progress(event):
            events.append(event)
            assert explorer.cache.count() == 0
            if event.get('stage') == 'map':
                assert not release.is_set()
                assert [paper['id'] for paper in event['field']['evidence_papers']] == ['W1']
                release.set()

        result = await asyncio.wait_for(explorer.explore('Test field', 'live', progress=progress), 2)
        assert [e['stage'] for e in events] == ['waiting', 'search', 'papers', 'map']
        assert events[2]['field']['analysis_source'] == 'pending'
        assert events[3]['field']['phase'] == 'map'
        assert result.phase == 'complete' and result.core_papers[0].signals['llm_importance'] == .9
        assert [paper.id for paper in result.evidence_papers] == ['W1']
        assert explorer.cache.count() == 1

    asyncio.run(run())


def test_failed_map_cancels_evaluation_and_does_not_save_partial(tmp_path):
    async def run():
        started = asyncio.Event()
        cancelled = asyncio.Event()

        class Decomposer:
            async def decompose_map(self, *args):
                await started.wait()
                raise ProviderError('Invalid map')

            async def judge_papers(self, *args):
                started.set()
                try:
                    await asyncio.Event().wait()
                finally:
                    cancelled.set()

        explorer = make_explorer(tmp_path, Decomposer())
        with pytest.raises(ProviderError):
            await explorer.explore('Test field', 'live')
        assert cancelled.is_set() and explorer.cache.count() == 0

    asyncio.run(run())


def test_stream_terminal_success_cache_and_error(tmp_path):
    config = Settings(_env_file=None, llm_api_key='', database_path=str(tmp_path / 'cache.db'))
    with TestClient(create_app(config)) as client:
        def request(query):
            response = client.post('/api/fields/explore/stream', json={'query': query, 'mode': 'demo'})
            assert response.headers['x-accel-buffering'] == 'no'
            return [json.loads(line) for line in response.text.splitlines()]
        events = request('NHSE')
        assert events[-1]['type'] == 'complete' and not events[-1]['field']['cache_hit']
        cached = request('NHSE')
        assert [e['type'] for e in cached] == ['status', 'complete']
        assert cached[-1]['field']['cache_hit']
        assert request('Unknown field')[-1]['type'] == 'error'


def test_split_requests_have_independent_schemas_and_restore_ids():
    class LLM:
        async def generate_structured(self, **kwargs):
            if set(kwargs['schema']['properties']) == {'summary'}:
                assert 'current_summary' not in kwargs['payload']
                return {'summary': 'Map'}
            if 'source-scope classifier' in kwargs.get('system', ''):
                return {'papers': [
                    {'paper_id': paper['id'], 'scope_relation': 'direct',
                     'reason': 'The paper matches the requested study object.'}
                    for paper in kwargs['payload']['papers']
                ]}
            if 'audits' in kwargs['schema']['properties']:
                return {'audits': [{
                    'relation_id': 'r1',
                    'verdict': 'supported',
                    'reason': 'The quoted abstract supports this branch.',
                    'corrected_name': 'Evidence-backed branch',
                    'supported_quote_ids': ['r1:q1'],
                    'scope_relation': 'direct',
                }]}
            if set(kwargs['schema']['properties']) == {'paper_judgments'}:
                return {'paper_judgments': [{'paper_id': 'p1', 'importance': .8, 'relevance': .9, 'reason': 'Contribution'}]}
            assert set(kwargs['schema']['properties']) == {'summary', 'prerequisites', 'subfields'}
            return {'summary': 'Map', 'prerequisites': [], 'subfields': [{
                'name': 'Evidence-backed branch',
                'reason': 'The supplied metadata supports this direction.',
                'confidence': .8,
                'evidence_paper_ids': ['p1'],
                'evidence_quotes': [{
                    'paper_id': 'p1', 'source': 'abstract',
                    'quote': 'The paper provides evidence.',
                }],
            }]}

    async def run():
        decomposer = FieldDecomposer(LLM())
        papers = [Paper(id='W1', title='Paper', abstract='The paper provides evidence.')]
        assert (await decomposer.decompose_map('Test', papers)).summary == 'Map'
        assert (await decomposer.judge_papers('Test', papers))[0].paper_id == 'W1'
    asyncio.run(run())


def test_closing_stream_cancels_both_llm_stages_and_releases_locks(tmp_path):
    async def run():
        map_started, papers_started = asyncio.Event(), asyncio.Event()
        cancelled = set()

        class Decomposer:
            async def decompose_map(self, *args):
                map_started.set()
                try:
                    await asyncio.Event().wait()
                finally:
                    cancelled.add('map')

            async def judge_papers(self, *args):
                papers_started.set()
                try:
                    await asyncio.Event().wait()
                finally:
                    cancelled.add('papers')

        explorer = make_explorer(tmp_path, Decomposer())
        request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(explorer=explorer)))
        response = await explore_stream(ExploreRequest(query='Test field', mode='live'), request)
        stream = response.body_iterator
        for _ in range(3):
            await asyncio.wait_for(anext(stream), 2)
        await asyncio.wait_for(map_started.wait(), 2)
        await asyncio.wait_for(papers_started.wait(), 2)
        await asyncio.wait_for(stream.aclose(), 2)
        assert cancelled == {'map', 'papers'}
        assert explorer.cache.count() == 0
        assert all(not lock.locked() for lock in explorer.locks.values())

    asyncio.run(run())
