import asyncio

import pytest

from app.config import Settings
from app.models.schemas import CURRENT_QUALITY_REVISION, Paper, PaperJudgment
from app.models.schemas import Decomposition
from app.db.cache import FieldCache
from app.services.field_explorer import FieldExplorer
from app.services.field_decomposer import FieldDecomposer
from app.services.evidence_verifier import TITLE_ONLY_CORE_SCORE_CAP
from app.providers.base import ProviderError
from app.services.literature_retriever import (
    LiteratureRetriever,
    merge_lanes,
    expand_formula_tokens,
    diversify_foundations,
    diversify_evidence_lanes,
    _build_validation_need_query,
)
from app.services.paper_ranker import PaperRanker


def _source_scope_response(kwargs):
    if 'source-scope classifier' not in kwargs.get('system', ''):
        return None
    return {'papers': [
        {'paper_id': paper['id'], 'scope_relation': 'direct',
         'reason': 'The paper matches the requested study object.'}
        for paper in kwargs['payload']['papers']
    ]}


def judgment(paper_id, relevance=.9, importance=.8, role='primary'):
    return PaperJudgment(paper_id=paper_id, relevance=relevance, importance=importance,
                         reason='Contribution within the research scope.', role=role)


def test_famous_adjacent_paper_cannot_displace_scope_evidence():
    papers = [Paper(id='direct', title='Prime editing efficiency', citation_count=12),
              Paper(id='adjacent', title='Genome editing background', citation_count=90000)]
    assessments = [judgment('direct', .9, .8), judgment('adjacent', .4, 1)]
    ranked = PaperRanker(Settings(_env_file=None).rank_weights).rank('prime editing efficiency', papers, assessments)
    assert [core.paper.id for core in ranked] == ['direct']


def test_title_only_relevance_cannot_displace_abstract_backed_core_candidate():
    title_papers = [
        Paper(id=f'title-{index}', title=f'Quantum transport title {index}')
        for index in range(8)
    ]
    title_judgments = [
        PaperJudgment(
            paper_id=paper.id,
            relevance=1.0,
            importance=.55,  # The production validator already caps this.
            reason='标题线索，尚未核验摘要。',
            role='unknown',
            evidence_basis='title',
            evidence_quote=paper.title,
        )
        for paper in title_papers
    ]
    abstract_paper = Paper(
        id='abstract-backed',
        title='Quantum transport direct measurement',
        abstract='This study directly measures quantum transport in a controlled device.',
    )
    abstract_judgment = PaperJudgment(
        paper_id=abstract_paper.id,
        relevance=.8,
        importance=.9,
        reason='摘要支持直接测量贡献。',
        role='primary',
        evidence_basis='abstract',
        evidence_quote=abstract_paper.abstract,
    )

    ranked = PaperRanker(Settings(_env_file=None).rank_weights).rank(
        'Quantum transport',
        [*title_papers, abstract_paper],
        [*title_judgments, abstract_judgment],
        limit=8,
        analysis_source='llm',
    )

    ranked_ids = [core.paper.id for core in ranked]
    assert len(ranked) == 8
    assert ranked_ids[0] == 'abstract-backed'
    assert 'abstract-backed' in ranked_ids
    title_ranked = [core for core in ranked if core.evidence_basis == 'title']
    assert title_ranked
    assert all(core.signals['relevance'] == 1.0 for core in title_ranked)
    assert all(core.score <= TITLE_ONLY_CORE_SCORE_CAP for core in title_ranked)


def test_title_only_relevance_cap_does_not_change_mock_sorting():
    title_paper = Paper(id='title-only', title='Quantum transport title')
    abstract_paper = Paper(
        id='abstract-backed',
        title='Quantum transport experiment',
        abstract='This study directly measures quantum transport.',
    )
    judgments = [
        PaperJudgment(
            paper_id='title-only', relevance=1.0, importance=.9,
            reason='演示标题线索', role='unknown', evidence_basis='title',
            evidence_quote=title_paper.title,
        ),
        PaperJudgment(
            paper_id='abstract-backed', relevance=.8, importance=.9,
            reason='演示摘要线索', role='primary', evidence_basis='abstract',
            evidence_quote=abstract_paper.abstract,
        ),
    ]

    ranked = PaperRanker(Settings(_env_file=None).rank_weights).rank(
        'Quantum transport', [title_paper, abstract_paper], judgments,
        limit=2, analysis_source='mock',
    )

    assert ranked[0].paper.id == 'title-only'
    assert ranked[0].signals['relevance'] == 1.0
    assert ranked[0].score > ranked[1].score


def test_title_only_score_cap_keeps_uncapped_score_as_tie_break():
    papers = [
        Paper(id='z-high', title='Quantum transport high-priority title'),
        Paper(id='a-low', title='Quantum transport lower-priority title'),
    ]
    judgments = [
        PaperJudgment(
            paper_id='z-high', relevance=1.0, importance=1.0,
            reason='标题主题高度相关。', role='primary', evidence_basis='title',
            evidence_quote=papers[0].title,
        ),
        PaperJudgment(
            paper_id='a-low', relevance=1.0, importance=.8,
            reason='标题主题相关。', role='primary', evidence_basis='title',
            evidence_quote=papers[1].title,
        ),
    ]

    ranked = PaperRanker(Settings(_env_file=None).rank_weights).rank(
        'Quantum transport', papers, judgments, limit=2, analysis_source='llm',
    )

    assert [core.paper.id for core in ranked] == ['z-high', 'a-low']
    assert [core.score for core in ranked] == [TITLE_ONLY_CORE_SCORE_CAP] * 2
    assert all(core.signals['relevance'] == 1.0 for core in ranked)


def test_unverified_excerpt_cannot_keep_a_fabricated_semantic_relevance_boost():
    papers = [Paper(id='W1', title='Unrelated molecular crystal', abstract='Reports optical absorption.', citation_count=100000)]
    assessment = [judgment('W1', .99, .55)]  # Exact excerpt validation has failed.
    assert PaperRanker(Settings(_env_file=None).rank_weights).rank('prime editing efficiency', papers, assessment) == []


def test_formula_spacing_expansion_is_generic_and_respects_exact_quotes():
    for formula in ('KTaO3', 'MoS2', 'LaAlO3', 'CO2'):
        expanded = expand_formula_tokens(formula + ' transport')
        assert formula in expanded and ' OR ' in expanded
    assert expand_formula_tokens('GPT4 DNA2 RAG 2024') == 'GPT4 DNA2 RAG 2024'
    assert expand_formula_tokens('"MoS2" optical transport') == '"MoS2" optical transport'


def test_mechanism_lane_keeps_a_separate_bounded_search():
    class LLM:
        async def generate_structured(self, **kwargs):
            return {'anchor': 'Research object', 'alternative': 'Research object outcome',
                    'facets': ['mechanism A', 'method variant B']}
    class Papers:
        def __init__(self):
            self.calls = []
        async def search_papers(self, query, limit=40, **kwargs):
            self.calls.append(query)
            return [Paper(id=f'W{len(self.calls)}', title=query)]
    papers = Papers()
    result = asyncio.run(LiteratureRetriever(Settings(_env_file=None), papers, LLM()).retrieve('Research object outcome', 40))
    assert len(papers.calls) == 3  # The synonym query duplicates the untouched original.
    assert any('mechanism A OR method variant B' in query for query in result.queries)
    assert all('"mechanism A"' not in query for query in result.queries)


def test_legacy_chinese_branch_can_retrieve_english_metadata():
    class LLM:
        async def generate_structured(self, **kwargs):
            return {'anchor': 'non Bloch band theory', 'alternative': 'generalized Brillouin zone',
                    'facets': ['generalized Brillouin zone']}
    class Papers:
        async def search_papers(self, query, limit=40, **kwargs):
            return [] if query == '非布洛赫能带理论' else [Paper(id='W1', title='Non Bloch band theory')]
    result = asyncio.run(LiteratureRetriever(Settings(_env_file=None), Papers(), LLM()).retrieve('非布洛赫能带理论', 40))
    assert [paper.id for paper in result.papers] == ['W1']
    assert result.queries[0] == '非布洛赫能带理论'


def test_mechanism_recall_does_not_require_umbrella_outcome_or_discard_synonyms():
    class LLM:
        async def generate_structured(self, **kwargs):
            return {'anchor': 'Research material device stability',
                    'object_query': 'Research material',
                    'alternative': 'Research material (degradation OR phase segregation)',
                    'facets': ['ion migration', 'thermal stress']}
    class Papers:
        def __init__(self):
            self.calls = []
        async def search_papers(self, query, limit=40, **kwargs):
            self.calls.append(query)
            return [Paper(id=f'W{len(self.calls)}', title=query)]
    papers = Papers()
    asyncio.run(LiteratureRetriever(Settings(_env_file=None), papers, LLM()).retrieve(
        'Research material device stability', 40))
    assert len(papers.calls) == 4
    assert 'degradation OR phase segregation' in papers.calls[2]
    assert '(Research material) AND (ion migration OR thermal stress)' in papers.calls[3]
    assert all('device stability' not in query for query in papers.calls[2:])


def test_evidence_needs_use_separate_plain_queries_and_paper_keyed_provenance():
    class LLM:
        async def generate_structured(self, **kwargs):
            return {
                'anchor': 'Research object',
                'alternative': 'Research object complementary terminology',
                'evidence_needs': [
                    {'label': 'systematic error source', 'focused_query': 'Research object confound source'},
                    {'label': 'reference platform difference', 'focused_query': 'Research object platform mismatch'},
                    {'label': 'posterior validation check', 'focused_query': 'Research object posterior coverage'},
                ],
                # Legacy facets must not create a seventh lane when needs exist.
                'facets': ['legacy method', 'legacy comparison'],
            }

    class Papers:
        def __init__(self):
            self.calls = []

        async def search_papers(self, query, limit=40, **kwargs):
            self.calls.append((query, kwargs.get('search_scope')))
            return [Paper(id=f'W{len(self.calls)}', title=query)]

    papers = Papers()
    result = asyncio.run(LiteratureRetriever(Settings(_env_file=None), papers, LLM()).retrieve(
        'Research object outcome', 40))
    assert len(papers.calls) == 6
    assert [need['id'] for need in result.evidence_needs] == ['need-1', 'need-2', 'need-3']
    focused = [need['focused_query'] for need in result.evidence_needs]
    assert all(3 <= len(query.split()) <= 8 for query in focused)
    assert all('"' not in query and not any(op in query.split() for op in ('AND', 'OR', 'NOT'))
               for query in focused)
    assert all(need_id in set(sum(result.candidate_focus_ids.values(), []))
               for need_id in ('need-1', 'need-2', 'need-3'))


def test_oversized_optional_alternative_does_not_discard_valid_evidence_needs():
    class LLM:
        async def generate_structured(self, **kwargs):
            return {
                'anchor': 'Research object',
                'alternative': 'Research object ' + ('long optional term ' * 20),
                'evidence_needs': [
                    {'label': 'systematic error source', 'focused_query': 'Research object confound source'},
                    {'label': 'reference platform difference', 'focused_query': 'Research object platform mismatch'},
                    {'label': 'posterior validation check', 'focused_query': 'Research object posterior coverage'},
                ],
            }

    class Papers:
        def __init__(self):
            self.calls = []

        async def search_papers(self, query, limit=40, **kwargs):
            self.calls.append((query, kwargs.get('search_scope')))
            return [Paper(id=f'W{len(self.calls)}', title=query)]

    papers = Papers()
    result = asyncio.run(LiteratureRetriever(Settings(_env_file=None), papers, LLM()).retrieve(
        'Research object outcome', 40))
    assert len(papers.calls) == 5  # original + foundation + three focused needs
    assert len(result.queries) == 5
    assert [need['id'] for need in result.evidence_needs] == ['need-1', 'need-2', 'need-3']
    assert all(len(query) <= 180 for query, _ in papers.calls)


def test_unknown_search_plan_fields_still_trigger_safe_foundation_fallback():
    class LLM:
        async def generate_structured(self, **kwargs):
            return {'anchor': 'Research object', 'alternative': '', 'unexpected': 'reject me'}

    class Papers:
        def __init__(self):
            self.calls = []

        async def search_papers(self, query, limit=40, **kwargs):
            self.calls.append((query, kwargs.get('sort'), kwargs.get('search_scope')))
            return [Paper(id=f'W{len(self.calls)}', title=query)]

    papers = Papers()
    result = asyncio.run(LiteratureRetriever(Settings(_env_file=None), papers, LLM()).retrieve(
        'Research object outcome', 40))
    assert len(papers.calls) == 2
    assert papers.calls[1] == ('Research object outcome', 'cited_by_count:desc', 'title_abstract')
    assert result.evidence_needs == []


def test_validation_axis_reserves_an_independent_need_and_keeps_direct_lane():
    class LLM:
        async def generate_structured(self, **kwargs):
            return {
                'anchor': 'inverse inference',
                'object_query': 'inverse',
                'alternative': 'inverse reconstruction',
                'validation_axes': ['calibration'],
                'evidence_needs': [
                    {'label': 'systematic error source', 'focused_query': 'inverse inference confound source'},
                    {'label': 'platform comparison', 'focused_query': 'inverse inference platform mismatch'},
                    {'label': 'generic method', 'focused_query': 'inverse inference method variant'},
                ],
            }

    class Papers:
        def __init__(self):
            self.calls = []

        async def search_papers(self, query, limit=40, **kwargs):
            self.calls.append((query, kwargs.get('search_scope')))
            if query == 'inverse calibration inference':
                return [Paper(id='calibration-paper', title='Inverse inference calibration study',
                              abstract='Validates posterior calibration on held-out observations.')]
            return [Paper(id=f'W{len(self.calls)}', title=query)]

    papers = Papers()
    result = asyncio.run(LiteratureRetriever(Settings(_env_file=None), papers, LLM()).retrieve(
        'inverse inference outcome', 40))
    assert len(papers.calls) == 6  # original + foundation + validation + two needs + alternative
    assert 'inverse calibration inference' in [query for query, _ in papers.calls]
    assert result.evidence_needs[0] == {
        'id': 'need-1', 'label': 'calibration validation',
        'focused_query': 'inverse calibration inference',
    }
    assert len(result.evidence_needs) == 3
    assert 'generic method' not in [need['label'] for need in result.evidence_needs]
    assert result.candidate_focus_ids['calibration-paper'] == ['need-1']


def test_valid_planner_validation_query_is_used_for_the_independent_lane():
    class LLM:
        async def generate_structured(self, **kwargs):
            return {
                'anchor': 'diffusion models inverse problems',
                'object_query': 'diffusion models inverse problems',
                'alternative': '',
                'validation_axes': ['calibration'],
                'validation_query': 'diffusion imaging calibration',
            }

    class Papers:
        def __init__(self):
            self.calls = []

        async def search_papers(self, query, limit=40, **kwargs):
            self.calls.append(query)
            if query == 'diffusion imaging calibration':
                return [Paper(id='application-calibration', title='Diffusion imaging calibration',
                              abstract='Calibrates uncertainty for noisy image reconstruction.')]
            return [Paper(id=f'W{len(self.calls)}', title=query)]

    papers = Papers()
    result = asyncio.run(LiteratureRetriever(Settings(_env_file=None), papers, LLM()).retrieve(
        'diffusion models inverse problems outcome', 40))
    assert papers.calls == [
        'diffusion models inverse problems outcome',
        'diffusion models inverse problems',
        'diffusion imaging calibration',
    ]
    assert result.evidence_needs[0]['focused_query'] == 'diffusion imaging calibration'
    assert result.candidate_focus_ids['application-calibration'] == ['need-1']


def test_invalid_planner_validation_query_uses_bounded_generic_fallback():
    class LLM:
        async def generate_structured(self, **kwargs):
            return {
                'anchor': 'diffusion models inverse problems',
                'object_query': 'diffusion models inverse problems',
                'alternative': '',
                'validation_axes': ['calibration'],
                'validation_query': 'diffusion imaging OR calibration',
            }

    class Papers:
        def __init__(self):
            self.calls = []

        async def search_papers(self, query, limit=40, **kwargs):
            self.calls.append(query)
            return [Paper(id=f'W{len(self.calls)}', title=query)]

    papers = Papers()
    result = asyncio.run(LiteratureRetriever(Settings(_env_file=None), papers, LLM()).retrieve(
        'diffusion models inverse problems outcome', 40))
    assert 'diffusion imaging OR calibration' not in papers.calls
    assert 'diffusion models inverse problems calibration' in papers.calls
    assert result.evidence_needs[0]['focused_query'] == 'diffusion models inverse problems calibration'


def test_posterior_request_protects_reference_comparison_and_calibration_when_axes_are_omitted():
    class LLM:
        async def generate_structured(self, **kwargs):
            return {
                'anchor': 'posterior inference',
                'object_query': 'posterior inference',
                'alternative': '',
                'evidence_needs': [
                    {'label': 'posterior method', 'focused_query': 'posterior inference sampling method'},
                    {'label': 'consistency check', 'focused_query': 'posterior inference consistency check'},
                ],
            }

    class Papers:
        def __init__(self):
            self.calls = []

        async def search_papers(self, query, limit=40, **kwargs):
            self.calls.append(query)
            if query == 'posterior inference calibration':
                return [Paper(id='posterior-calibration', title='Posterior inference calibration',
                              abstract='Reports calibration of posterior uncertainty.')]
            if query == 'posterior inference evaluation':
                return [Paper(id='posterior-evaluation', title='Posterior inference evaluation',
                              abstract='Compares approximate samples with a known reference posterior.')]
            return [Paper(id=f'W{len(self.calls)}', title=query)]

    papers = Papers()
    result = asyncio.run(LiteratureRetriever(Settings(_env_file=None), papers, LLM()).retrieve(
        'posterior inference problem', 40))
    assert 'posterior inference calibration' in papers.calls
    assert [need['label'] for need in result.evidence_needs[:2]] == [
        'reference posterior validation', 'calibration validation',
    ]
    assert result.candidate_focus_ids['posterior-evaluation'] == ['need-1']
    assert result.candidate_focus_ids['posterior-calibration'] == ['need-2']
    assert len(result.evidence_needs) <= 3 and len(papers.calls) <= 6
    assert len(result.papers) <= 40


def test_validation_query_keeps_late_strong_object_qualifier():
    query = _build_validation_need_query(
        'calibration',
        anchor_query='diffusion models inverse problems',
        object_query='diffusion models inverse problems',
        context_queries=(
            'diffusion models noisy linear inverse problems posterior approximation '
            'data consistency hallucination trade-off',
            'noisy linear inverse problem posterior sampling diffusion',
        ),
    )
    assert query == 'diffusion models inverse problems calibration posterior'
    assert len(query.split()) <= 8


def test_validation_query_keeps_a_short_multiword_object_intact():
    query = _build_validation_need_query(
        'calibration',
        anchor_query='tidal deformability neutron star',
        object_query='tidal deformability neutron star',
    )
    assert query == 'tidal deformability neutron star calibration'


def test_focused_lane_gets_a_slot_after_early_duplicates_are_squeezed_out():
    shared = [Paper(id=f'shared-{index}', title=f'Research object shared paper {index}')
              for index in range(10)]
    original = shared + [Paper(id=f'original-{index}', title=f'Research object original paper {index}')
                         for index in range(30)]
    other = [Paper(id=f'other-{index}', title=f'Research object other paper {index}')
             for index in range(40)]
    focused = shared + [Paper(id='focused-unique', title='Research object focused limitation')]
    selected = merge_lanes([original, other, focused], 8, protected_lane_indices={2})
    assert 'focused-unique' in {paper.id for paper in selected}


def test_late_distinctive_evidence_hits_enter_small_fair_budget_without_new_requests():
    needs = [
        {'id': 'need-1', 'label': 'measurement limitation',
         'focused_query': 'diffusion measurement noise limitation'},
        {'id': 'need-2', 'label': 'posterior calibration',
         'focused_query': 'diffusion posterior calibration coverage'},
    ]
    original = [Paper(id=f'original-{index}', title=f'Diffusion models study {index}',
                      abstract='A generic method result.') for index in range(40)]
    original[13] = Paper(id='measurement-late', title='Diffusion models measurement study',
                         abstract='Measures noise and limitation effects in reconstruction.')
    foundation = [Paper(id=f'foundation-{index}', title=f'Diffusion models foundation {index}',
                        abstract='A foundational method result.') for index in range(40)]
    alternative = [Paper(id=f'alternative-{index}', title=f'Diffusion models alternative {index}',
                         abstract='A generic reconstruction result.') for index in range(40)]
    alternative[28] = Paper(id='posterior-late', title='Diffusion models posterior study',
                            abstract='Evaluates posterior calibration and coverage.')
    specs = [
        ('diffusion inverse problem', None, 'all'),
        ('diffusion models', 'cited_by_count:desc', 'title_abstract'),
        ('diffusion reconstruction', None, 'title_abstract'),
    ]
    reordered, promoted = diversify_evidence_lanes(
        [original, foundation, alternative], specs, needs,
        anchor_query='diffusion models', object_query='diffusion',
    )
    assert [paper.id for paper in reordered[0][:2]] == ['original-0', 'original-1']
    assert reordered[0][2].id == 'measurement-late'
    assert [paper.id for paper in reordered[1][:8]] == [f'foundation-{i}' for i in range(8)]
    assert reordered[2][2].id == 'posterior-late'
    assert promoted['need-1'][0].id == 'measurement-late'
    assert promoted['need-2'][0].id == 'posterior-late'

    selected = merge_lanes(reordered, 9)
    assert {'measurement-late', 'posterior-late'} <= {paper.id for paper in selected}
    unchanged, no_focus = diversify_evidence_lanes(
        [original], [specs[0]], [], anchor_query='diffusion models', object_query='diffusion'
    )
    assert [paper.id for paper in unchanged[0]] == [paper.id for paper in original]
    assert no_focus == {}


def test_zero_hit_evidence_lane_gets_at_most_two_short_fallback_requests():
    class LLM:
        async def generate_structured(self, **kwargs):
            return {
                'anchor': 'diffusion models',
                'alternative': 'diffusion reconstruction',
                'object_query': 'diffusion',
                'evidence_needs': [{
                    'label': 'posterior calibration validation',
                    'focused_query': 'diffusion inverse problem posterior calibration measurement noise',
                }],
            }

    class Papers:
        def __init__(self):
            self.calls = []

        async def search_papers(self, query, limit=40, **kwargs):
            self.calls.append(query)
            if ('calibration' in query and query !=
                    'diffusion inverse problem posterior calibration measurement noise'):
                return [Paper(id='fallback-uq', title='Diffusion posterior calibration',
                              abstract='Posterior calibration and validation under measurement noise.')]
            if query == 'diffusion inverse problem posterior calibration measurement noise':
                return []
            return [Paper(id=f'generic-{len(self.calls)}', title=f'Diffusion generic study {len(self.calls)}',
                          abstract='A generic diffusion method result.')]

    papers = Papers()
    result = asyncio.run(LiteratureRetriever(Settings(_env_file=None), papers, LLM()).retrieve(
        'diffusion inverse problem', 40))
    assert len(papers.calls) == 5
    assert len(result.queries) == 5
    fallback_query = result.queries[-1]
    assert fallback_query.split()[:1] == ['diffusion']
    assert 2 <= len(fallback_query.split()) <= 5
    assert 'measurement' not in fallback_query
    assert 'fallback-uq' in {paper.id for paper in result.papers}
    assert result.candidate_focus_ids['fallback-uq'] == ['need-1']


def test_provider_error_in_evidence_lane_is_not_retried_by_zero_hit_fallback():
    class LLM:
        async def generate_structured(self, **kwargs):
            return {
                'anchor': 'diffusion models',
                'alternative': 'diffusion reconstruction',
                'object_query': 'diffusion',
                'evidence_needs': [{
                    'label': 'posterior calibration validation',
                    'focused_query': 'diffusion inverse problem posterior calibration measurement noise',
                }],
            }

    class Papers:
        def __init__(self):
            self.calls = []

        async def search_papers(self, query, limit=40, **kwargs):
            self.calls.append(query)
            if query == 'diffusion inverse problem posterior calibration measurement noise':
                raise ProviderError('focused provider unavailable', 503)
            return [Paper(id=f'generic-{len(self.calls)}', title=f'Diffusion generic study {len(self.calls)}',
                          abstract='A generic diffusion method result.')]

    papers = Papers()
    result = asyncio.run(LiteratureRetriever(Settings(_env_file=None), papers, LLM()).retrieve(
        'diffusion inverse problem', 40))
    assert len(papers.calls) == 4
    assert len(result.queries) == 4
    assert all('calibration' not in query for query in result.queries[4:])


def test_scientific_subscript_versions_share_identity_with_author_and_year_evidence():
    from app.services.paper_quality import quality_filter_and_dedupe
    papers = [Paper(id='pub', title='Superconductivity at KTaO 3 (111) interfaces', year=2021,
                    authors=['Research Author'], work_version='publishedVersion'),
              Paper(id='pre', title='Superconductivity at KTaO$_3$ (111) interfaces', year=2020,
                    authors=['Research Author'], work_version='submittedVersion')]
    merged = quality_filter_and_dedupe(papers)
    assert len(merged) == 1 and merged[0].id == 'pub'
    assert 'pre' in merged[0].source_record_ids


def test_extra_valid_citation_is_cleaned_without_losing_the_whole_map():
    class LLM:
        async def generate_structured(self, **kwargs):
            scoped = _source_scope_response(kwargs)
            if scoped is not None:
                return scoped
            if set(kwargs['schema']['properties']) == {'summary'}:
                assert kwargs['payload']['audited_relations'][0]['status'] == 'supported'
                return {'summary': '摘要支持这个具体方向。'}
            if 'audits' in kwargs['schema']['properties']:
                ids = kwargs['payload']['relations'][0]['evidence_paper_ids']
                assert len(ids) == 3 and 'W4' in ids and 'not-a-candidate' not in ids
                return {'audits': [{'relation_id': 'r1', 'verdict': 'supported',
                                    'reason': '摘要支持这个具体方向。',
                                    'corrected_name': 'Specific mechanism',
                                    'supported_quote_ids': ['r1:q1', 'r1:q2', 'r1:q3'],
                                    'scope_relation': 'direct'}]}
            return {'summary': 'A useful map', 'prerequisites': [], 'subfields': [{
                'name': 'Specific mechanism', 'reason': 'A supported research direction.', 'confidence': .8,
                'evidence_paper_ids': ['p1', 'p2', 'p3', 'p4', 'not-a-candidate'],
                'evidence_quotes': [
                    {'paper_id': alias, 'source': 'abstract',
                     'quote': 'measures the specific mechanism directly'}
                    for alias in ['p2', 'p3', 'p4']
                ],
            }]}
    papers = [Paper(id=f'W{i}', title=f'Mechanism paper {i}',
                    abstract='This study measures the specific mechanism directly.') for i in range(1, 5)]
    result = asyncio.run(FieldDecomposer(LLM()).decompose_map('A topic', papers))
    assert result.evidence_audit_complete
    assert len(result.subfields) == 1
    assert len(result.subfields[0].evidence_paper_ids) == 3
    assert result.subfields[0].evidence_status == 'supported'


def test_paper_phase_discards_known_map_superset_without_contaminating_judgments():
    paper = Paper(
        id='W1', title='A direct measurement',
        abstract='This study directly measures the requested mechanism.',
    )

    class SupersetLLM:
        async def generate_structured(self, **kwargs):
            assert set(kwargs['schema']['properties']) == {'paper_judgments'}
            return {
                'paper_judgments': [{
                    'paper_id': 'p1', 'importance': .8, 'relevance': .9,
                    'reason': 'Directly evaluates the supplied candidate.',
                    'role': 'primary', 'evidence_basis': 'abstract',
                    'evidence_quote': 'This study directly measures the requested mechanism.',
                }],
                # Known fields from the map phase are a provider superset and
                # must never enter the papers result or later cache.
                'summary': 'Injected map summary',
                'prerequisites': [{
                    'name': 'Injected prerequisite', 'reason': 'Injected',
                    'confidence': 1, 'evidence_paper_ids': ['p1'],
                }],
                'subfields': [{
                    'name': 'Injected subfield', 'reason': 'Injected',
                    'confidence': 1, 'evidence_paper_ids': ['p1'],
                }],
                'warnings': ['Injected warning'],
                'evidence_audit_complete': True,
            }

    judgments = asyncio.run(FieldDecomposer(SupersetLLM()).judge_papers(
        'A topic', [paper]))
    assert [judgment.paper_id for judgment in judgments] == ['W1']
    assert judgments[0].reason == 'Directly evaluates the supplied candidate.'


@pytest.mark.parametrize('raw', [
    {'summary': 'Missing paper judgments', 'prerequisites': [], 'subfields': []},
    {'paper_judgments': [], 'unexpected': 'must fail closed'},
])
def test_paper_phase_rejects_missing_requested_field_or_unknown_extra(raw):
    class InvalidPhaseLLM:
        async def generate_structured(self, **kwargs):
            return raw

    with pytest.raises(ProviderError, match='schema'):
        asyncio.run(FieldDecomposer(InvalidPhaseLLM()).judge_papers(
            'A topic', [Paper(id='W1', title='Candidate')]))


def test_small_map_list_overflow_is_trimmed_before_bounded_audit():
    papers = [
        Paper(
            id=f'W{i + 1}',
            title=f'Relation paper {i + 1}',
            abstract=f'This study metadata supports relation {i + 1} clearly.',
        )
        for i in range(17)
    ]

    def raw_relation(*, alias, name, confidence, number):
        return {
            'name': name,
            'reason': 'The supplied metadata supports this direction.',
            'confidence': confidence,
            'evidence_paper_ids': [alias],
            'evidence_quotes': [{
                'paper_id': alias,
                'source': 'abstract',
                'quote': f'metadata supports relation {number} clearly',
            }],
        }

    prerequisites = [
        raw_relation(
            alias=f'p{i + 1}',
            name='Shared foundation' if i == 0 else f'Prerequisite {i}',
            confidence=.55 + i * .05,
            number=i + 1,
        )
        for i in range(6)
    ]
    subfields = [
        raw_relation(
            alias='p7' if i == 0 else f'p{i + 7}',
            name='Shared foundation' if i == 0 else f'Subfield {i + 1}',
            confidence=.95 if i == 0 else .50 + i * .01,
            number=7 if i == 0 else i + 7,
        )
        for i in range(11)
    ]

    class OverflowMapLLM:
        def __init__(self):
            self.calls = []

        async def generate_structured(self, **kwargs):
            self.calls.append(kwargs)
            scoped = _source_scope_response(kwargs)
            if scoped is not None:
                return scoped
            if set(kwargs['schema']['properties']) == {'summary'}:
                assert len(kwargs['payload']['audited_relations']) == 12
                return {'summary': 'A bounded map of the displayed research directions.'}
            if 'independent evidence auditor' in kwargs['system']:
                relations = kwargs['payload']['relations']
                assert len(relations) == 12
                assert all(item['evidence_paper_ids'] for item in relations)
                return {'audits': [
                    {
                        'relation_id': item['relation_id'],
                        'verdict': 'supported',
                        'reason': '摘要支持该具体方向。',
                        'corrected_name': (
                            'Shared foundation'
                            if item['evidence_paper_ids'][0] in {'W1', 'W7'}
                            else (
                                f"Prerequisite {int(item['evidence_paper_ids'][0][1:]) - 1}"
                                if int(item['evidence_paper_ids'][0][1:]) <= 6
                                else f"Subfield {int(item['evidence_paper_ids'][0][1:]) - 6}"
                            )
                        ),
                        'supported_quote_ids': [
                            quote['quote_id'] for quote in item['evidence_quotes']
                        ],
                        'scope_relation': 'direct',
                    }
                    for item in relations
                ]}
            return {
                'summary': 'A bounded map',
                'prerequisites': prerequisites,
                'subfields': subfields,
            }

    llm = OverflowMapLLM()
    result = asyncio.run(FieldDecomposer(llm).decompose_map('Prime research', papers))

    assert result.evidence_audit_complete
    assert len(result.prerequisites) == 5
    assert len(result.subfields) == 7
    assert len([*result.prerequisites, *result.subfields]) == 12
    names = [relation.name for relation in [*result.prerequisites, *result.subfields]]
    assert len(names) == len(set(names))
    assert 'Shared foundation' not in {relation.name for relation in result.prerequisites}
    assert 'Shared foundation' in {relation.name for relation in result.subfields}
    by_name = {relation.name: relation for relation in [*result.prerequisites, *result.subfields]}
    assert by_name['Prerequisite 5'].confidence == .8
    assert by_name['Prerequisite 5'].evidence_paper_ids == ['W6']
    assert by_name['Shared foundation'].confidence == .95
    assert by_name['Shared foundation'].evidence_paper_ids == ['W7']
    assert by_name['Shared foundation'].evidence_quotes[0].paper_id == 'W7'
    assert all(relation.evidence_paper_ids[0].startswith('W') for relation in [
        *result.prerequisites, *result.subfields,
    ])
    assert all(relation.evidence_status == 'supported' for relation in [
        *result.prerequisites, *result.subfields,
    ])
    assert len(llm.calls) == 4


def test_small_quote_overflow_keeps_only_valid_bounded_citations_before_audit():
    class LLM:
        async def generate_structured(self, **kwargs):
            scoped = _source_scope_response(kwargs)
            if scoped is not None:
                return scoped
            if set(kwargs['schema']['properties']) == {'summary'}:
                return {'summary': '摘要支持该研究方向。'}
            if 'audits' in kwargs['schema']['properties']:
                relation = kwargs['payload']['relations'][0]
                assert relation['evidence_paper_ids'] == ['W2', 'W3', 'W4']
                return {'audits': [{'relation_id': 'r1', 'verdict': 'supported',
                                    'reason': '摘要支持该研究方向。',
                                    'corrected_name': 'Specific mechanism',
                                    'supported_quote_ids': ['r1:q1', 'r1:q2', 'r1:q3'],
                                    'scope_relation': 'direct'}]}
            return {'summary': 'A useful map', 'prerequisites': [], 'subfields': [{
                'name': 'Specific mechanism', 'reason': 'A supported direction.', 'confidence': .8,
                'evidence_paper_ids': ['p1', 'p2', 'p3', 'p4'],
                'evidence_quotes': [
                    {'paper_id': alias, 'source': 'abstract',
                     'quote': 'measures the specific mechanism directly'}
                    for alias in ['not-a-candidate', 'p2', 'p3', 'p4', 'p1']
                ],
            }]}
    papers = [Paper(id=f'W{i}', title=f'Mechanism paper {i}',
                    abstract='This study measures the specific mechanism directly.') for i in range(1, 5)]
    result = asyncio.run(FieldDecomposer(LLM()).decompose_map('A topic', papers))
    relation = result.subfields[0]
    assert result.evidence_audit_complete
    assert relation.evidence_status == 'supported'
    assert [quote.paper_id for quote in relation.evidence_quotes] == ['W2', 'W3', 'W4']
    assert len(relation.evidence_paper_ids) == len(relation.evidence_quotes) == 3


def test_long_relation_excerpt_is_a_bounded_exact_prefix_before_audit():
    excerpt = 'This study measures the specific mechanism directly. ' * 8

    class LLM:
        async def generate_structured(self, **kwargs):
            scoped = _source_scope_response(kwargs)
            if scoped is not None:
                return scoped
            if set(kwargs['schema']['properties']) == {'summary'}:
                return {'summary': '摘要支持该研究方向。'}
            if 'audits' in kwargs['schema']['properties']:
                return {'audits': [{'relation_id': 'r1', 'verdict': 'supported',
                                    'reason': '摘要支持该研究方向。',
                                    'corrected_name': 'Specific mechanism',
                                    'supported_quote_ids': ['r1:q1'],
                                    'scope_relation': 'direct'}]}
            return {'summary': 'A useful map', 'prerequisites': [], 'subfields': [{
                'name': 'Specific mechanism', 'reason': 'A supported direction.', 'confidence': .8,
                'evidence_paper_ids': ['p1'],
                'evidence_quotes': [{'paper_id': 'p1', 'source': 'abstract', 'quote': excerpt}],
            }]}

    result = asyncio.run(FieldDecomposer(LLM()).decompose_map('A topic', [
        Paper(id='W1', title='Mechanism paper', abstract=excerpt)
    ]))
    relation = result.subfields[0]
    assert result.evidence_audit_complete and relation.evidence_status == 'supported'
    assert relation.evidence_quotes[0].quote == excerpt.strip()[:300]
    assert relation.evidence_quotes[0].quote in excerpt


def test_decomposer_preserves_independent_abstract_provenance_without_changing_citation_id():
    class LLM:
        async def generate_structured(self, **kwargs):
            if set(kwargs['schema']['properties']) == {'summary'}:
                assert kwargs['payload']['audited_relations'] == []
                return {'summary': 'No branch evidence has been displayed in this map.'}
            paper = kwargs['payload']['papers'][0]
            assert paper['id'] == 'p1'
            assert paper['source'] == 'datacite'
            assert paper['abstract_source_record_id'] == 'https://api.datacite.org/dois/10.48550/arxiv.2401.12345'
            return {'summary': 'A useful map', 'prerequisites': [], 'subfields': []}
    result = asyncio.run(FieldDecomposer(LLM()).decompose_map('A topic', [
        Paper(id='W1', title='Mechanism paper', abstract='This study measures a mechanism.',
              source='datacite', abstract_source_record_id='https://api.datacite.org/dois/10.48550/arxiv.2401.12345')
    ]))
    assert result.evidence_audit_complete


def test_incomplete_semantic_audit_remains_retryable():
    from app.models.schemas import FieldRelation, EvidenceQuote
    from app.services.evidence_verifier import EvidenceVerifier, SentPaper
    class LLM:
        async def generate_structured(self, **kwargs):
            scoped = _source_scope_response(kwargs)
            if scoped is not None:
                return scoped
            return {'audits': [{'relation_id': 'r1', 'verdict': 'supported',
                                'reason': 'Supports the first relation.',
                                'corrected_name': 'First relation',
                                'supported_quote_ids': ['r1:q1'],
                                'scope_relation': 'direct'}]}
    relations = [FieldRelation(name=f'Direction {i}', reason='A specific direction.', confidence=.8,
                    evidence_paper_ids=['W1'], evidence_quotes=[EvidenceQuote(paper_id='W1', source='abstract',
                    quote='measures two distinct research mechanisms')]) for i in range(2)]
    _, _, warnings, complete = asyncio.run(EvidenceVerifier(LLM()).verify_map(
        'A topic', [], relations, {'W1': SentPaper('W1', 'Mechanisms', 'This paper measures two distinct research mechanisms.')}))
    assert not complete and any('全部' in warning for warning in warnings)


def test_overlong_core_display_fields_are_bounded_and_excerpt_still_verified():
    from app.models.schemas import CorePaper
    from app.services.evidence_verifier import EvidenceVerifier, SentPaper
    excerpt = 'We directly measure quantum transport and observe a specific response. ' * 6
    class LLM:
        async def generate_structured(self, **kwargs):
            if kwargs['schema'].get('title') == 'CoreReasonAuditBatch':
                return {'audits': [{'paper_id': 'W1', 'reason': '摘要支持这一具体研究贡献。' * 30}]}
            return {'audits': [{'paper_id': 'W1', 'verdict': 'direct', 'role': 'primary',
                'reason': '摘要支持这一具体研究贡献。' * 30, 'evidence_quote': excerpt}]}
    paper = Paper(id='W1', title='Quantum transport measurement', abstract=excerpt)
    cores = [CorePaper(paper=paper, score=.8, reason='Initial contribution', role='primary',
                       evidence_quote=excerpt[:300], evidence_basis='abstract')]
    audited, _ = asyncio.run(EvidenceVerifier(LLM()).verify_core('Quantum transport', cores,
                                                   {'W1': SentPaper.from_paper(paper)}))
    assert len(audited) == 1 and audited[0].evidence_basis == 'abstract'
    assert len(audited[0].reason) <= 220 and len(audited[0].evidence_quote) == 300
    assert audited[0].evidence_quote in paper.abstract


def test_insufficient_core_audit_cannot_be_overridden_by_title_overlap():
    from app.models.schemas import CorePaper
    from app.services.evidence_verifier import EvidenceVerifier, SentPaper
    class LLM:
        async def generate_structured(self, **kwargs):
            return {'audits': [{'paper_id': 'W1', 'verdict': 'insufficient', 'role': 'unknown',
                               'reason': '索引缺少摘要。', 'evidence_quote': ''}]}
    paper = Paper(id='W1', title='Quantum transport in a one-dimensional chain')
    cores = [CorePaper(paper=paper, score=.9, reason='Overly specific contribution', role='primary')]
    audited, warnings = asyncio.run(EvidenceVerifier(LLM()).verify_core('Quantum transport', cores,
                                                   {'W1': SentPaper.from_paper(paper)}))
    assert audited == []
    assert any('题录元数据不足' in warning for warning in warnings)


def test_overviews_do_not_fill_the_primary_evidence_reading_list():
    papers = [Paper(id=f'W{i}', title=f'Quantum transport paper {i}', citation_count=1000-i) for i in range(6)]
    assessments = [judgment(p.id, role='review' if i < 3 else 'primary') for i, p in enumerate(papers)]
    ranked = PaperRanker(Settings(_env_file=None).rank_weights).rank('Quantum transport', papers, assessments)
    assert sum(core.role == 'review' for core in ranked) == 1
    assert {'W3', 'W4', 'W5'} <= {core.paper.id for core in ranked}


def test_missing_model_judgment_does_not_gain_from_renormalized_signals():
    papers = [Paper(id='judged', title='Relevant topic', citation_count=20),
              Paper(id='missing', title='Relevant topic', citation_count=99999)]
    ranked = PaperRanker(Settings(_env_file=None).rank_weights).rank('Relevant topic', papers, [judgment('judged')])
    assert [core.paper.id for core in ranked] == ['judged']


def test_retrieval_reserves_room_for_foundations_and_complementary_facets():
    original = [Paper(id=f'o{i}', title=f'Research object facet {i}') for i in range(20)]
    classic = [Paper(id='foundation', title='Research object discovery')]
    facet = [Paper(id='distinct', title='Research object different terminology')]
    selected = merge_lanes([original, classic, facet], 8)
    assert {'foundation', 'distinct', 'o0', 'o1'} <= {p.id for p in selected}
    assert len(selected) == 8


def test_merged_model_budget_remains_forty_with_balanced_recall_lanes():
    from collections import Counter
    lanes = [[Paper(id=f'{lane}{i}', title=f'Distinct paper {lane}{i}') for i in range(40)] for lane in 'abc']
    selected = merge_lanes(lanes, 40)
    assert len(selected) == 40
    assert Counter(p.id[0] for p in selected) == {'a': 14, 'b': 13, 'c': 13}


def test_balanced_lanes_do_not_replace_fair_head_allocations_with_blind_tail_samples():
    lanes = [[Paper(id=f'{lane}-{i}', title=f'Distinct topic {lane} paper {i}') for i in range(40)]
             for lane in ('original', 'foundation', 'facet')]
    selected = merge_lanes(lanes, 40)
    selected_ids = {paper.id for paper in selected}
    assert len(selected) == 40
    assert {'original-0', 'foundation-0', 'facet-0'} <= selected_ids
    assert {f'{lane}-{i}' for lane in ('original', 'foundation', 'facet') for i in range(13)} <= selected_ids
    assert not any(paper.id.endswith(('-35', '-37')) for paper in selected)


def test_overlapping_lanes_fill_budget_with_distinct_canonical_works():
    original = [Paper(id=f'work-{i}', title=f'Overlapping study {i}',
                      source_record_ids=[f'preprint-{i}', f'accepted-{i}'],
                      year=2020, authors=['A. Research'], work_version='publishedVersion')
                for i in range(40)]
    foundation = ([Paper(id=f'preprint-{i}', title=f'Overlapping study {i}',
                         source_record_ids=[f'work-{i}'], year=2020, authors=['A. Research'],
                         work_version='submittedVersion')
                   for i in range(20)]
                  + [Paper(id=f'foundation-{i}', title=f'Foundation study {i}') for i in range(20)])
    facet = ([Paper(id=f'accepted-{i}', title=f'Overlapping study {i}',
                    source_record_ids=[f'work-{i}'], year=2020, authors=['A. Research'],
                    work_version='acceptedVersion')
              for i in range(10, 30)]
             + [Paper(id=f'facet-{i}', title=f'Facet study {i}') for i in range(20)])
    selected = merge_lanes([original, foundation, facet], 40)
    assert len(selected) == 40
    assert len({paper.id for paper in selected}) == 40
    assert selected[0].id == 'work-0'
    assert 'foundation-0' in {paper.id for paper in selected}
    assert 'facet-0' in {paper.id for paper in selected}
    assert not any(paper.id.startswith(('preprint-', 'accepted-')) for paper in selected)


def test_foundation_diversity_retains_leaders_and_deeper_distinct_mechanisms():
    papers = [Paper(id=f'W{i}', title='Research object standard technique', citation_count=1000-i)
              for i in range(40)]
    papers[21] = Paper(id='distinct', title='Research object unusual mechanism',
                       abstract='Measures an unusual mechanism.', citation_count=10)
    chosen = diversify_foundations(papers, {'unusual', 'mechanism'}, 14)
    assert len(chosen) == 14 and [paper.id for paper in chosen[:8]] == [f'W{i}' for i in range(8)]
    assert 'distinct' in [paper.id for paper in chosen]
    assert {'W35', 'W37'} <= {paper.id for paper in chosen}


def test_long_contiguous_judgment_quote_is_bounded_then_source_checked():
    excerpt = 'This study evaluates the research method using carefully controlled experiments. ' * 8
    class LLM:
        async def generate_structured(self, **kwargs):
            return {'paper_judgments': [{'paper_id': 'p1', 'importance': .8, 'relevance': .9,
                'reason': 'A long display reason. ' * 30, 'role': 'primary',
                'evidence_basis': 'abstract', 'evidence_quote': excerpt}]}
    result = asyncio.run(FieldDecomposer(LLM()).judge_papers('Research method', [
        Paper(id='W1', title='Controlled research method study', abstract=excerpt)]))
    assert len(result[0].reason) <= 120 and 1 <= len(result[0].evidence_quote) <= 300
    assert result[0].evidence_quote in excerpt
    assert result[0].evidence_basis == 'abstract' and result[0].paper_id == 'W1'


def test_legacy_server_payload_cannot_claim_current_quality_by_default(tmp_path):
    import json
    from app.models.schemas import FieldNode
    cache = FieldCache(tmp_path / 'legacy.db')
    node = FieldNode(id='test', name='A topic', summary='Legacy map', prerequisites=[], subfields=[],
                     core_papers=[], paper_source='openalex', analysis_source='llm', candidate_count=1,
                     quality_revision=CURRENT_QUALITY_REVISION)
    cache.save('legacy', node, 300)
    assert cache.get('legacy')
    with cache.connect() as db:
        raw = json.loads(db.execute("SELECT payload FROM fields WHERE cache_key='legacy'").fetchone()[0])
        raw.pop('quality_revision')
        db.execute("UPDATE fields SET payload=? WHERE cache_key='legacy'", (json.dumps(raw),))
    assert FieldNode.model_validate(raw).quality_revision == 0
    assert cache.get('legacy') is None


def test_retrieval_plan_is_bounded_and_original_question_is_preserved():
    class LLM:
        calls = 0
        async def generate_structured(self, **kwargs):
            self.calls += 1
            return {'anchor': 'Research object', 'alternative': 'Research object (facet OR mechanism)'}

    class Papers:
        def __init__(self):
            self.calls = []
        async def search_papers(self, query, limit=40, **kwargs):
            self.calls.append((query, kwargs.get('sort')))
            return [Paper(id=f'W{len(self.calls)}', title=query)]

    async def run():
        llm, papers = LLM(), Papers()
        result = await LiteratureRetriever(Settings(_env_file=None), papers, llm).retrieve('Research object specific facet', 40)
        assert llm.calls == 1 and len(papers.calls) == 3
        assert papers.calls[0] == ('Research object specific facet', None)
        assert ('Research object', 'cited_by_count:desc') in papers.calls
        assert result.queries[0] == 'Research object specific facet'
    asyncio.run(run())


def test_retrieval_caps_four_raw_lanes_and_final_candidate_budget():
    class LLM:
        async def generate_structured(self, **kwargs):
            return {'anchor': 'Research object', 'alternative': 'Research object mechanism',
                    'facets': ['distinct method']}

    class Papers:
        def __init__(self):
            self.limits = []

        async def search_papers(self, query, limit=40, **kwargs):
            self.limits.append(limit)
            return [Paper(id=f'{len(self.limits)}-{i}', title=f'Research object paper {len(self.limits)} {i}')
                    for i in range(40)]

    papers = Papers()
    result = asyncio.run(LiteratureRetriever(Settings(_env_file=None), papers, LLM()).retrieve(
        'Research object', 100))
    assert papers.limits == [40, 40, 40, 40]
    assert len(result.papers) <= 40


def test_same_topic_different_research_questions_never_share_analyzed_maps(tmp_path):
    class Papers:
        calls = 0
        async def search_papers(self, query, limit=40):
            self.calls += 1
            return [Paper(id='W1', title='Relevant topic')]

    class Decomposer:
        questions = []
        async def decompose_map(self, field, papers, *, research_question=None):
            self.questions.append(research_question)
            return Decomposition(summary=research_question or field,
                                 prerequisites=[], subfields=[], paper_judgments=[])
        async def judge_papers(self, field, papers, *, research_question=None):
            return [judgment('W1')]

    async def run():
        settings = Settings(_env_file=None, llm_api_key='test', database_path=str(tmp_path / 'goals.db'))
        papers, decomposer = Papers(), Decomposer()
        explorer = FieldExplorer(settings, papers, decomposer, PaperRanker(settings.rank_weights), FieldCache(settings.db_path))
        first = await explorer.explore('Relevant topic', 'live', research_question='One-dimensional chains')
        second = await explorer.explore('Relevant topic', 'live', research_question='Two-dimensional circuits')
        cached = await explorer.explore('Relevant topic', 'live', research_question='One-dimensional chains')
        assert (first.summary, second.summary) == ('One-dimensional chains', 'Two-dimensional circuits')
        assert cached.cache_hit and cached.research_question == 'One-dimensional chains'
        assert decomposer.questions == ['One-dimensional chains', 'Two-dimensional circuits']
        assert papers.calls == 1  # Same retrieval, separately scoped analysis.
    asyncio.run(run())


def test_failed_evidence_audit_is_not_saved_as_a_complete_map(tmp_path):
    class Papers:
        async def search_papers(self, *args):
            return [Paper(id='W1', title='Relevant topic')]
    class Decomposer:
        async def decompose_map(self, *args):
            return Decomposition(summary='Unchecked map', prerequisites=[], subfields=[],
                                 paper_judgments=[], evidence_audit_complete=False)
        async def judge_papers(self, *args):
            return [judgment('W1')]
    async def run():
        settings = Settings(_env_file=None, llm_api_key='test', llm_model='test-model', database_path=str(tmp_path / 'audit.db'))
        cache = FieldCache(settings.db_path)
        explorer = FieldExplorer(settings, Papers(), Decomposer(), PaperRanker(settings.rank_weights), cache)
        result = await explorer.explore('Relevant topic', 'live', allow_partial=True)
        assert result.phase == 'papers' and result.analysis_source == 'pending'
        assert not result.subfields and cache.count() == 0
        with cache.connect() as db:
            assert db.execute("SELECT COUNT(*) FROM analysis_artifacts WHERE kind='map'").fetchone()[0] == 0
    asyncio.run(run())


def test_failed_core_contribution_check_preserves_verified_map_but_not_full_cache(tmp_path):
    class Papers:
        async def search_papers(self, *args):
            return [Paper(id='W1', title='Relevant topic')]
    class Decomposer:
        async def decompose_map(self, *args):
            return Decomposition(summary='Verified map', prerequisites=[], subfields=[],
                                 paper_judgments=[], evidence_audit_complete=True)
        async def judge_papers(self, *args):
            return [judgment('W1')]
        async def audit_core_papers(self, *args, **kwargs):
            raise ProviderError('Contribution audit unavailable')
    async def run():
        settings = Settings(_env_file=None, llm_api_key='test', llm_model='test-model', database_path=str(tmp_path / 'core-audit.db'))
        cache = FieldCache(settings.db_path)
        explorer = FieldExplorer(settings, Papers(), Decomposer(), PaperRanker(settings.rank_weights), cache)
        result = await explorer.explore('Relevant topic', 'live', allow_partial=True)
        assert result.phase == 'map' and result.summary == 'Verified map'
        assert result.analysis_source == 'pending' and cache.count() == 0
        with cache.connect() as db:
            assert db.execute("SELECT COUNT(*) FROM analysis_artifacts WHERE kind='map'").fetchone()[0] == 1
            assert db.execute("SELECT COUNT(*) FROM analysis_artifacts WHERE kind='core_audit'").fetchone()[0] == 0
    asyncio.run(run())


def test_invalid_planner_and_one_failed_lane_do_not_destroy_useful_retrieval():
    class LLM:
        async def generate_structured(self, **kwargs):
            return {'anchor': 'Completely unrelated', 'alternative': 'Research object mechanism'}

    class Papers:
        async def search_papers(self, query, limit=40, **kwargs):
            if 'mechanism' in query:
                raise ProviderError('temporarily unavailable')
            return [Paper(id='W1', title='Research object')]

    result = asyncio.run(LiteratureRetriever(Settings(_env_file=None), Papers(), LLM()).retrieve('Research object', 40))
    assert [p.id for p in result.papers] == ['W1']
    assert len(result.warnings) == 2


def test_cancelled_retrieval_cancels_all_network_lanes():
    async def run():
        entered, cancelled = set(), set()
        ready = asyncio.Event()
        class LLM:
            async def generate_structured(self, **kwargs):
                return {'anchor': 'Research object', 'alternative': 'Research object mechanism'}
        class Papers:
            async def search_papers(self, query, limit=40, **kwargs):
                entered.add((query, kwargs.get('sort')))
                if len(entered) == 3:
                    ready.set()
                try:
                    await asyncio.Event().wait()
                finally:
                    cancelled.add((query, kwargs.get('sort')))
        task = asyncio.create_task(LiteratureRetriever(Settings(_env_file=None), Papers(), LLM()).retrieve('Research object question', 40))
        await asyncio.wait_for(ready.wait(), 1)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert entered == cancelled
    asyncio.run(run())


def test_narrow_mechanism_hits_keep_a_quota_when_broad_synonym_lane_is_full():
    class Planner:
        async def generate_structured(self, **kwargs):
            return {'anchor': 'Research object', 'alternative': 'Research object synonym',
                    'object_query': 'Research object', 'facets': ['contact loss']}

    class Papers:
        async def search_papers(self, query, limit=40, **kwargs):
            if query == '(Research object) AND (contact loss)':
                return [Paper(id='mechanism', title='Research object contact loss experiment')]
            lane = 'foundation' if kwargs.get('sort') else 'synonym' if 'synonym' in query else 'original'
            return [Paper(id=f'{lane}-{i}', title=f'Research object {lane} study {i}') for i in range(40)]

    result = asyncio.run(LiteratureRetriever(Settings(_env_file=None), Papers(), Planner()).retrieve(
        'Research object outcome', 40, research_question='Separate current and contact loss.'))
    assert len(result.papers) == 40
    assert 'mechanism' in {paper.id for paper in result.papers}
    assert {'original-0', 'foundation-0', 'synonym-0'} <= {paper.id for paper in result.papers}


def test_small_foundation_quota_does_not_spend_all_diversity_slots_on_blind_tail_samples():
    papers = [Paper(id=f'W{i}', title='Research object common method', citation_count=1000-i)
              for i in range(40)]
    papers[18] = Paper(id='mechanism', title='Research object contact loss experiment', citation_count=10)
    chosen = diversify_foundations(papers, {'contact', 'loss'}, 10)
    assert len(chosen) == 10
    assert [paper.id for paper in chosen[:8]] == [f'W{i}' for i in range(8)]
    assert 'mechanism' in {paper.id for paper in chosen}
    assert any(paper.id in {'W35', 'W37'} for paper in chosen)


def test_four_full_recall_lanes_retain_high_rank_methods_at_the_candidate_budget_boundary():
    lanes = [[Paper(id=f'{lane}-{i}', title=f'Research object {lane} study {i}') for i in range(40)]
             for lane in ('original', 'foundation', 'synonym', 'mechanism')]
    selected = merge_lanes(lanes, 40)
    assert len(selected) == 40
    assert {f'{lane}-{i}' for lane in ('original', 'foundation', 'synonym', 'mechanism')
            for i in range(10)} == {paper.id for paper in selected}
