import asyncio
import json

from app.config import Settings
from app.db.cache import FieldCache
from app.models.schemas import CURRENT_QUALITY_REVISION, Decomposition, Paper
from app.services.field_explorer import FieldExplorer
from app.services.paper_ranker import PaperRanker


def test_old_or_corrupt_analysis_artifacts_are_cache_misses(tmp_path):
    cache = FieldCache(tmp_path / 'quality.db')
    cache.save_artifact('map', 'key', {'summary': 'Verified stage'}, 60)
    assert cache.get_artifact('map', 'key') == {'summary': 'Verified stage'}
    for payload in ('not json', json.dumps({'summary': 'Unversioned stage'}),
                    json.dumps({'quality_revision': CURRENT_QUALITY_REVISION - 1,
                                'value': {'summary': 'Outdated stage'}})):
        with cache.connect() as db:
            db.execute('UPDATE analysis_artifacts SET payload=?', (payload,))
        assert cache.get_artifact('map', 'key') is None


def test_full_question_reaches_initial_rank_and_analysis_shortlist(tmp_path, monkeypatch):
    scopes = []
    from app.services import field_explorer as module
    original_selector = module.select_analysis_papers

    def select(scope, papers, limit):
        scopes.append(('select', scope))
        return original_selector(scope, papers, limit)

    monkeypatch.setattr(module, 'select_analysis_papers', select)

    class Ranker(PaperRanker):
        def rank(self, scope, *args):
            scopes.append(('rank', scope))
            return super().rank(scope, *args)

    class Papers:
        async def search_papers(self, *args):
            return [Paper(id='W1', title='Material one dimensional transport')]

    class Decomposer:
        async def decompose_map(self, *args, **kwargs):
            return Decomposition(summary='Map', prerequisites=[], subfields=[],
                                 paper_judgments=[], evidence_audit_complete=True)
        async def judge_papers(self, *args, **kwargs):
            return []

    settings = Settings(_env_file=None, llm_api_key='test', llm_model='test',
                        database_path=str(tmp_path / 'question.db'))
    explorer = FieldExplorer(settings, Papers(), Decomposer(), Ranker(settings.rank_weights),
                             FieldCache(settings.db_path))
    asyncio.run(explorer.explore('Material', 'live', research_question='one dimensional transport'))
    assert scopes and {scope for _, scope in scopes} == {'Material one dimensional transport'}
    assert {'select', 'rank'} <= {kind for kind, _ in scopes}
