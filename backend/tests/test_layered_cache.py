import asyncio
import time

import pytest

from app.config import Settings
from app.db.cache import FieldCache
from app.models.schemas import Decomposition, Paper, PaperJudgment
from app.providers.base import ProviderError
from app.services.field_explorer import FieldExplorer
from app.services.paper_ranker import PaperRanker
from app.services.literature_retriever import RetrievalResult


class Papers:
    calls = 0
    async def search_papers(self, *args):
        self.calls += 1
        return [Paper(id='W1', title='Test field', abstract='Evidence')]


class Decomposer:
    maps = 0
    judgments = 0
    fail = False
    async def decompose_map(self, *args):
        self.maps += 1
        return Decomposition(summary='Map', prerequisites=[], subfields=[], paper_judgments=[])

    async def judge_papers(self, *args):
        self.judgments += 1
        await asyncio.sleep(.03)
        if self.fail:
            raise ProviderError('Evaluation failed')
        return [PaperJudgment(paper_id='W1', relevance=.9, importance=.8, reason='Evidence')]


def explorer(tmp_path, papers, decomposer, **kwargs):
    settings = Settings(_env_file=None, llm_api_key='test', database_path=str(tmp_path / 'cache.db'), **kwargs)
    return FieldExplorer(settings, papers, decomposer, PaperRanker(settings.rank_weights), FieldCache(settings.db_path))


def test_weight_changes_reuse_search_and_analysis_model_changes_only_reanalyze(tmp_path):
    async def run():
        papers, decomposer = Papers(), Decomposer()
        first = explorer(tmp_path, papers, decomposer)
        await first.explore('Test field', 'live')
        reweighted = explorer(tmp_path, papers, decomposer, rank_relevance=.7)
        assert reweighted.fingerprint != first.fingerprint
        assert not (await reweighted.explore('Test field', 'live')).cache_hit
        assert (papers.calls, decomposer.maps, decomposer.judgments) == (1, 1, 1)
        new_model = explorer(tmp_path, papers, decomposer, llm_model='new-model')
        await new_model.explore('Test field', 'live')
        assert (papers.calls, decomposer.maps, decomposer.judgments) == (1, 2, 2)
        await new_model.explore('Test field', 'live', refresh=True)
        assert (papers.calls, decomposer.maps, decomposer.judgments) == (2, 3, 3)
    asyncio.run(run())


def test_failed_evaluation_retries_only_missing_stage(tmp_path):
    async def run():
        papers, decomposer = Papers(), Decomposer()
        service = explorer(tmp_path, papers, decomposer)
        decomposer.fail = True
        with pytest.raises(ProviderError):
            await service.explore('Test field', 'live')
        assert service.cache.count() == 0
        decomposer.fail = False
        await service.explore('Test field', 'live')
        assert (papers.calls, decomposer.maps, decomposer.judgments) == (1, 1, 2)
    asyncio.run(run())


def test_expired_search_is_refetched_but_identical_evidence_reuses_analysis(tmp_path):
    async def run():
        papers, decomposer = Papers(), Decomposer()
        service = explorer(tmp_path, papers, decomposer)
        await service.explore('Test field', 'live')
        with service.cache.connect() as db:
            db.execute('UPDATE fields SET expires_at=?', (time.time() - 1,))
            db.execute("UPDATE analysis_artifacts SET expires_at=? WHERE kind='search'", (time.time() - 1,))
        await service.explore('Test field', 'live')
        assert (papers.calls, decomposer.maps, decomposer.judgments) == (2, 1, 1)
    asyncio.run(run())


def test_shortlist_keeps_retrieval_broad_and_ranks_only_analyzed_evidence(tmp_path):
    class ManyPapers:
        async def search_papers(self, *args):
            return [Paper(id=f'W{i}', title=f'Test field topic {i}') for i in range(40)]

    class SelectedDecomposer(Decomposer):
        async def decompose_map(self, field, papers):
            assert len(papers) == 16
            return await super().decompose_map(field, papers)

        async def judge_papers(self, field, papers):
            return [PaperJudgment(paper_id=p.id, relevance=.8, importance=.8, reason='Evidence') for p in papers]

    async def run():
        service = explorer(tmp_path, ManyPapers(), SelectedDecomposer(), llm_analysis_limit=16)
        result = await service.explore('Test field', 'live')
        assert result.candidate_count == 40 and result.analyzed_paper_count == 16
        assert len(result.core_papers) == 8 and all('llm_importance' in p.signals for p in result.core_papers)
        assert any('16' in w for w in result.warnings)
    asyncio.run(run())


def test_changed_evidence_needs_reanalyze_identical_papers_and_legacy_artifact_is_readable(tmp_path):
    class FocusedRetriever:
        needs = []
        focus = {}

        async def retrieve(self, *args, **kwargs):
            return RetrievalResult([Paper(id='W1', title='Test field', abstract='Evidence')],
                                   ['Test field'], evidence_needs=self.needs,
                                   candidate_focus_ids=self.focus)

    class FocusedDecomposer(Decomposer):
        seen = []

        async def decompose_map(self, field, papers, *, evidence_needs=None, candidate_focus_ids=None):
            self.seen.append((evidence_needs, candidate_focus_ids))
            return await super().decompose_map(field, papers)

    async def run():
        retriever, decomposer = FocusedRetriever(), FocusedDecomposer()
        settings = Settings(_env_file=None, llm_api_key='test', database_path=str(tmp_path / 'focus.db'))
        cache = FieldCache(settings.db_path)
        service = FieldExplorer(settings, Papers(), decomposer, PaperRanker(settings.rank_weights), cache, retriever)
        await service.explore('Test field', 'live')
        with cache.connect() as db:
            # Simulate a pre-extension search artifact and expire only final.
            db.execute('DELETE FROM fields')
        search_key = service.search_fingerprint + ':test field'
        cache.save_artifact('search', search_key, {'papers': [Paper(id='W1', title='Test field', abstract='Evidence').model_dump()],
                                                  'queries': ['Test field'], 'warnings': []}, 3600)
        await service.explore('Test field', 'live')
        assert decomposer.maps == 1  # Empty metadata matches legacy analysis.
        retriever.needs = [{'id': 'need-1', 'label': 'Reference sensitivity', 'focused_query': 'test field reference'}]
        retriever.focus = {'W1': ['need-1']}
        # Refresh search while allowing analysis cache reuse if its key were wrong.
        cache.save_artifact('search', search_key, {'papers': [Paper(id='W1', title='Test field', abstract='Evidence').model_dump()],
            'queries': ['Test field'], 'warnings': [], 'evidence_needs': retriever.needs,
            'candidate_focus_ids': retriever.focus}, 3600)
        with cache.connect() as db:
            db.execute('DELETE FROM fields')
        await service.explore('Test field', 'live')
        assert decomposer.maps == 2 and decomposer.judgments == 2
        assert decomposer.seen[-1] == (retriever.needs, retriever.focus)
    asyncio.run(run())
