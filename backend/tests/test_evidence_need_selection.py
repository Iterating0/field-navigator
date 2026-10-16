import asyncio

import pytest

from app.config import Settings
from app.models.schemas import CorePaper, Decomposition, Paper, PaperJudgment
from app.providers.base import ProviderError
from app.services.evidence_verifier import SentPaper
from app.services.field_decomposer import CompactDecomposition, CompactRelation, FieldDecomposer
from app.services.paper_ranker import PaperRanker


NEEDS = [
    {'id': 'need-1', 'label': 'Systematic error', 'focused_query': 'transport systematic error'},
    {'id': 'need-2', 'label': 'Platform comparison', 'focused_query': 'transport platform comparison'},
]


def _paper(index: int, *, abstract: str | None = None, citation_count: int = 0) -> Paper:
    return Paper(
        id=f'W{index}',
        title=f'Quantum transport study {index}',
        abstract=abstract,
        citation_count=citation_count,
    )


def _judgment(paper: Paper, *, need_ids=None, basis='abstract', relevance=.8,
              importance=.8, role='primary', quote=None) -> PaperJudgment:
    return PaperJudgment(
        paper_id=paper.id,
        relevance=relevance,
        importance=importance,
        reason='The supplied abstract describes a scoped contribution.',
        role=role,
        evidence_basis=basis,
        evidence_quote=quote if quote is not None else (paper.abstract or paper.title),
        evidence_need_ids=list(need_ids or []),
    )


def test_core_need_reservation_uses_verified_abstract_tag_and_avoids_duplicate_slots():
    generic = _paper(1, abstract='This abstract measures a generic transport response.', citation_count=100000)
    focused = _paper(2, abstract='This abstract measures systematic error and platform variation.', citation_count=1)
    other = _paper(3, abstract='This abstract describes another platform comparison.', citation_count=2)
    judgments = [
        _judgment(generic, relevance=.9, importance=.9),
        _judgment(focused, need_ids=['need-1', 'need-2'], relevance=.58, importance=.2),
        _judgment(other, need_ids=['need-2'], relevance=.7, importance=.6),
    ]

    ranked = PaperRanker(Settings(_env_file=None).rank_weights).rank(
        'Quantum transport', [generic, focused, other], judgments, limit=2,
        analysis_source='llm', evidence_needs=NEEDS,
        candidate_focus_ids={focused.id: ['need-1'], other.id: ['need-2']},
    )

    # One paper explicitly tags both needs, so it covers both reservation
    # opportunities; a second need-2 paper must not consume another forced slot.
    assert [core.paper.id for core in ranked] == [focused.id, generic.id]


def test_title_only_or_bad_abstract_quote_cannot_reserve_a_need_slot():
    generic = _paper(1, abstract='This abstract directly measures quantum transport.', citation_count=1000)
    title_only = _paper(2, abstract=None, citation_count=1)
    judgments = [
        _judgment(generic, relevance=.8, importance=.8),
        _judgment(title_only, need_ids=['need-1'], basis='title', relevance=1.0,
                  importance=1.0, quote=title_only.title),
    ]

    ranked = PaperRanker(Settings(_env_file=None).rank_weights).rank(
        'Quantum transport', [generic, title_only], judgments, limit=1,
        analysis_source='llm', evidence_needs=NEEDS,
        candidate_focus_ids={title_only.id: ['need-1']},
    )
    assert [core.paper.id for core in ranked] == [generic.id]

    bad_quote = title_only.model_copy(update={'abstract': 'A different abstract.'})
    bad_judgment = _judgment(
        bad_quote, need_ids=['need-1'], basis='abstract', relevance=.6,
        importance=.2, quote='This excerpt is not present.',
    )
    ranked_bad = PaperRanker(Settings(_env_file=None).rank_weights).rank(
        'Quantum transport', [generic, bad_quote],
        [judgments[0], bad_judgment], limit=1, analysis_source='llm',
        evidence_needs=NEEDS,
    )
    assert [core.paper.id for core in ranked_bad] == [generic.id]


class _NoopEvidenceVerifier:
    async def verify_map(self, field, prerequisites, subfields, papers, **kwargs):
        return prerequisites, subfields, [], True

    def validate_judgments(self, judgments, papers):
        return judgments

    async def verify_core(self, field, cores, papers, **kwargs):
        return cores, []


class _JudgmentLLM:
    async def generate_structured(self, **kwargs):
        paper = kwargs['payload']['papers'][0]
        return {
            'paper_judgments': [{
                'paper_id': paper['id'],
                'importance': .8,
                'relevance': .8,
                'reason': 'The abstract supports the requested contribution.',
                'role': 'primary',
                'evidence_basis': 'abstract',
                'evidence_quote': paper['abstract'],
                'evidence_need_ids': ['need-1', 'need-99'],
            }],
        }


class _MapLLM:
    def __init__(self):
        self.calls = []

    async def generate_structured(self, **kwargs):
        self.calls.append(kwargs)
        paper = kwargs['payload']['papers'][0]
        if 'ONLY assesses papers' in kwargs['system']:
            return {
                'paper_judgments': [{
                    'paper_id': paper['id'],
                    'importance': .8,
                    'relevance': .8,
                    'reason': 'The abstract supports the requested contribution.',
                    'role': 'primary',
                    'evidence_basis': 'abstract',
                    'evidence_quote': paper['abstract'],
                    'evidence_need_ids': ['need-1'],
                }],
            }
        return {
            'summary': 'A broad draft summary that needs evidence-boundary review.',
            'prerequisites': [],
            'subfields': [{
                'name': 'Systematic error analysis',
                'reason': 'The abstract supports this research direction.',
                'confidence': .8,
                'evidence_paper_ids': [paper['id']],
                'evidence_quotes': [{
                    'paper_id': paper['id'],
                    'source': 'abstract',
                    'quote': paper['abstract'],
                }],
                'evidence_need_ids': ['need-1'],
            }],
        }


class _SummaryVerifier(_NoopEvidenceVerifier):
    def __init__(self, *, failure: ProviderError | None = None):
        self.summary_calls = []
        self.failure = failure

    async def verify_summary(self, summary, prerequisites, subfields, **kwargs):
        self.summary_calls.append({
            'summary': summary,
            'relation_names': [relation.name for relation in [*prerequisites, *subfields]],
            # The summary audit receives displayed relation evidence only. It
            # must not receive the raw paper objects or their full abstracts.
            'has_papers_kwarg': 'papers' in kwargs,
            'relation_has_abstract': [hasattr(relation, 'abstract')
                                      for relation in [*prerequisites, *subfields]],
        })
        if self.failure is not None:
            raise self.failure
        return 'A narrower summary grounded in the audited direction.'


def test_judgment_need_ids_are_filtered_to_known_abstract_supported_needs():
    paper = _paper(1, abstract='This abstract supports systematic error analysis.')
    decomposer = FieldDecomposer(_JudgmentLLM(), evidence_verifier=_NoopEvidenceVerifier())
    judgment = PaperJudgment(
        paper_id=paper.id,
        relevance=.8,
        importance=.8,
        reason='The abstract supports the requested contribution.',
        role='primary',
        evidence_basis='abstract',
        evidence_quote=paper.abstract,
        evidence_need_ids=['need-1', 'need-99'],
    )
    canonical = decomposer._canonical_judgment(
        judgment,
        {},
        sent_papers={paper.id: SentPaper.from_paper(paper)},
        valid_need_ids={'need-1', 'need-2'},
    )
    assert canonical.evidence_need_ids == ['need-1']


def test_needs_map_uses_independent_summary_audit_without_raw_papers():
    llm = _MapLLM()
    verifier = _SummaryVerifier()
    paper = _paper(
        1,
        abstract='The abstract reports a measured transport systematic error.',
    )

    result = asyncio.run(FieldDecomposer(
        llm, evidence_verifier=verifier,
    ).decompose_map(
        'Quantum transport',
        [paper],
        evidence_needs=NEEDS,
        candidate_focus_ids={paper.id: ['need-1']},
    ))

    assert result.summary == 'A narrower summary grounded in the audited direction.'
    assert result.evidence_audit_complete is True
    assert result.subfields[0].evidence_paper_ids == [paper.id]
    assert llm.calls[0]['payload']['evidence_needs'] == NEEDS
    assert len(verifier.summary_calls) == 1
    assert verifier.summary_calls[0]['relation_names'] == ['Systematic error analysis']
    assert verifier.summary_calls[0]['has_papers_kwarg'] is False
    assert verifier.summary_calls[0]['relation_has_abstract'] == [False]


def test_summary_audit_failure_propagates_and_does_not_block_paper_phase():
    llm = _MapLLM()
    verifier = _SummaryVerifier(
        failure=ProviderError('summary audit unavailable', 503),
    )
    paper = _paper(
        1,
        abstract='The abstract reports a measured transport systematic error.',
    )
    decomposer = FieldDecomposer(llm, evidence_verifier=verifier)

    with pytest.raises(ProviderError, match='summary audit unavailable') as error:
        asyncio.run(decomposer.decompose_map(
            'Quantum transport', [paper], evidence_needs=NEEDS,
        ))
    assert error.value.status_code == 503
    assert len(verifier.summary_calls) == 1

    judgments = asyncio.run(decomposer.judge_papers(
        'Quantum transport', [paper], evidence_needs=NEEDS,
    ))
    assert len(judgments) == 1
    assert judgments[0].paper_id == paper.id
    assert judgments[0].evidence_need_ids == ['need-1']
    # The summary audit is map-only; the paper phase must remain usable.
    assert len(verifier.summary_calls) == 1


def _compact_relation(name, paper_id, quote, *, confidence=.5, need_ids=None, source='abstract'):
    return CompactRelation(
        name=name,
        reason='The supplied metadata describes this direction.',
        confidence=confidence,
        evidence_paper_ids=[paper_id],
        evidence_quotes=[{'paper_id': paper_id, 'source': source, 'quote': quote}],
        evidence_need_ids=list(need_ids or []),
    )


def test_relation_trim_reserves_each_need_only_after_exact_abstract_provenance():
    papers = {
        f'W{i}': SentPaper(
            id=f'W{i}', title=f'Quantum transport study {i}',
            abstract=f'Abstract evidence for generic direction {i}.',
        )
        for i in range(1, 9)
    }
    relations = [
        _compact_relation(
            f'Generic {i}', f'W{i}', papers[f'W{i}'].abstract,
            confidence=.95,
        )
        for i in range(1, 8)
    ]
    relations.append(_compact_relation(
        'Systematic error branch', 'W8', papers['W8'].abstract,
        confidence=.1, need_ids=['need-1'],
    ))

    decomposer = FieldDecomposer(_JudgmentLLM(), evidence_verifier=_NoopEvidenceVerifier())
    compact = CompactDecomposition(
        summary='A map', prerequisites=[], subfields=relations, paper_judgments=[]
    )
    trimmed = decomposer._clean_relation_groups(
        'Quantum transport', compact, {}, set(papers), papers, NEEDS
    )
    names = {relation.name for relation in trimmed.subfields}
    assert 'Systematic error branch' in names
    assert len(trimmed.subfields) == 7


def test_title_only_need_tag_is_removed_before_relation_reservation():
    papers = {
        f'W{i}': SentPaper(
            id=f'W{i}', title=f'Quantum transport study {i}',
            abstract=f'Abstract evidence for generic direction {i}.',
        )
        for i in range(1, 9)
    }
    relations = [
        _compact_relation(
            f'Generic {i}', f'W{i}', papers[f'W{i}'].abstract,
            confidence=.5,
        )
        for i in range(1, 8)
    ]
    title_relation = _compact_relation(
        'Title-only need branch', 'W8', papers['W8'].title,
        confidence=.99, need_ids=['need-1'], source='title',
    )
    compact = CompactDecomposition(
        summary='A map', prerequisites=[], subfields=[*relations, title_relation],
        paper_judgments=[]
    )
    decomposer = FieldDecomposer(_JudgmentLLM(), evidence_verifier=_NoopEvidenceVerifier())
    trimmed = decomposer._clean_relation_groups(
        'Quantum transport', compact, {}, set(papers), papers, NEEDS
    )
    assert 'Title-only need branch' not in {relation.name for relation in trimmed.subfields}


def test_public_decomposition_does_not_expose_internal_relation_need_ids():
    relation = _compact_relation(
        'Systematic error branch', 'W1',
        'This abstract supports systematic error.', need_ids=['need-1'],
    )
    compact = CompactDecomposition(
        summary='A map', prerequisites=[], subfields=[relation], paper_judgments=[]
    )
    public = FieldDecomposer._public_decomposition_data(compact)
    assert 'evidence_need_ids' not in public['subfields'][0]


def test_rank_without_evidence_needs_keeps_legacy_order():
    first = _paper(1, abstract='A broad transport survey.', citation_count=30)
    second = _paper(2, abstract='A focused transport measurement.', citation_count=10)
    judgments = [
        _judgment(first, relevance=.9, importance=.8),
        _judgment(second, relevance=.7, importance=.7),
    ]
    ranker = PaperRanker(Settings(_env_file=None).rank_weights)
    legacy = ranker.rank('Quantum transport', [first, second], judgments, limit=2)
    with_hints = ranker.rank(
        'Quantum transport', [first, second], judgments, limit=2,
        evidence_needs=[], candidate_focus_ids={second.id: ['need-1']},
    )
    assert [core.paper.id for core in with_hints] == [core.paper.id for core in legacy]
