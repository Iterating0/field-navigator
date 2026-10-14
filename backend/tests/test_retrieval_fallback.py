import asyncio

import pytest

from app.config import Settings
from app.models.schemas import Paper
from app.providers.base import ProviderError
from app.services.literature_retriever import LiteratureRetriever


@pytest.mark.parametrize('failure', [ProviderError('planning unavailable'), asyncio.TimeoutError(), ValueError('invalid plan')])
def test_failed_planner_preserves_exact_topic_foundation_lane_without_llm_retry(failure):
    class Planner:
        calls = 0

        async def generate_structured(self, **kwargs):
            self.calls += 1
            raise failure

    class Papers:
        def __init__(self):
            self.calls = []

        async def search_papers(self, query, limit=40, **kwargs):
            self.calls.append((query, kwargs.get('sort'), kwargs.get('search_scope')))
            return [Paper(id='foundation' if kwargs else 'original', title='Research object specific scope')]

    planner, papers = Planner(), Papers()
    result = asyncio.run(LiteratureRetriever(Settings(_env_file=None), papers, planner).retrieve(
        'Research object specific scope', 40, research_question='Keep this specific object scope.'))
    assert planner.calls == 1
    assert papers.calls == [('Research object specific scope', None, None),
                           ('Research object specific scope', 'cited_by_count:desc', 'title_abstract')]
    assert {paper.id for paper in result.papers} == {'original', 'foundation'}
    assert any('仍可能遗漏' in warning for warning in result.warnings)


def test_invalid_anchor_uses_fallback_without_overwriting_valid_alternative_or_widening_scope():
    class Planner:
        async def generate_structured(self, **kwargs):
            return {'anchor': 'Unrelated subject', 'alternative': 'Research object specific scope mechanism'}

    class Papers:
        def __init__(self):
            self.calls = []

        async def search_papers(self, query, limit=40, **kwargs):
            self.calls.append((query, kwargs.get('sort')))
            return [Paper(id='p1', title='Research object specific scope')]

    papers = Papers()
    result = asyncio.run(LiteratureRetriever(Settings(_env_file=None), papers, Planner()).retrieve(
        'Research object specific scope', 40))
    assert len(papers.calls) == 3
    assert papers.calls[1] == ('Research object specific scope', 'cited_by_count:desc')
    assert 'mechanism' in papers.calls[2][0]
    assert all('Unrelated' not in query for query, _ in papers.calls)
    assert result.papers[0].id == 'p1'


def test_failed_planner_and_failed_foundation_lane_still_keep_original_results():
    class Planner:
        async def generate_structured(self, **kwargs):
            raise ProviderError('planning unavailable')

    class Papers:
        async def search_papers(self, query, limit=40, **kwargs):
            if kwargs:
                raise ProviderError('foundation temporarily unavailable')
            return [Paper(id='p1', title='Research object specific scope')]

    result = asyncio.run(LiteratureRetriever(Settings(_env_file=None), Papers(), Planner()).retrieve(
        'Research object specific scope', 40))
    assert [paper.id for paper in result.papers] == ['p1']
    assert any('成功路径' in warning for warning in result.warnings)
