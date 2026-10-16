import asyncio

import pytest

from app.models.schemas import EvidenceQuote, FieldRelation
from app.services.evidence_verifier import EvidenceVerifier, SentPaper


class ScopeAuditLLM:
    def __init__(self, scope, audits=None):
        self.scope = scope
        self.audits = audits or []
        self.calls = []

    async def generate_structured(self, **kwargs):
        self.calls.append(kwargs)
        if 'source-scope classifier' in kwargs.get('system', ''):
            return self.scope(kwargs['payload']) if callable(self.scope) else self.scope
        return {'audits': self.audits}


def _relation(*paper_ids_and_quotes, kind_name='Target branch'):
    return FieldRelation(
        name=kind_name,
        reason='The draft relation contains a target-system result.',
        confidence=.9,
        evidence_paper_ids=[paper_id for paper_id, _ in paper_ids_and_quotes],
        evidence_quotes=[EvidenceQuote(paper_id=paper_id, source='abstract', quote=quote)
                         for paper_id, quote in paper_ids_and_quotes],
    )


def _paper(paper_id, title, abstract):
    return SentPaper(id=paper_id, title=title, abstract=abstract)


def _audit(relation_id='r1', *, quote_id='r1:q1', verdict='supported', scope='direct'):
    return {
        'relation_id': relation_id,
        'verdict': verdict,
        'reason': 'The checked excerpt supports the bounded target result.',
        'corrected_name': 'Bounded target result',
        'supported_quote_ids': [quote_id],
        'scope_relation': scope,
    }


def _scope_for(**relations):
    def response(payload):
        return {'papers': [
            {
                'paper_id': paper['id'],
                'scope_relation': relations.get(paper['id'], 'direct'),
                'reason': f"Classified the source object for {paper['id']}.",
            }
            for paper in payload['papers']
        ]}
    return response


def test_mixed_target_and_adjacent_sources_are_filtered_before_captioning():
    target_quote = 'The experiment measures the requested target response in the target system.'
    adjacent_quote = 'The simulation measures the same response in an adjacent system.'
    llm = ScopeAuditLLM(
        _scope_for(target='direct', adjacent='context'),
        [_audit()],
    )
    _, subfields, _, complete = asyncio.run(EvidenceVerifier(llm).verify_map(
        'Target system', [],
        [_relation(('target', target_quote), ('adjacent', adjacent_quote))],
        {
            'target': _paper('target', 'Target-system experiment', target_quote),
            'adjacent': _paper('adjacent', 'Adjacent-system simulation', adjacent_quote),
        },
        research_question='Measure the target response in the target system.',
    ))

    assert complete is True
    assert len(subfields) == 1
    assert subfields[0].evidence_status == 'supported'
    assert subfields[0].evidence_paper_ids == ['target']
    audit_call = next(call for call in llm.calls
                      if 'independent evidence auditor' in call['system'])
    relation_payload = audit_call['payload']['relations'][0]
    assert relation_payload['evidence_paper_ids'] == ['target']
    assert all(quote['paper_id'] == 'target'
               for quote in relation_payload['evidence_quotes'])
    scope_call = next(call for call in llm.calls
                      if 'source-scope classifier' in call['system'])
    assert 'relations' not in scope_call['payload']
    assert all(set(paper) == {'id', 'title', 'abstract', 'relation_usage'}
               for paper in scope_call['payload']['papers'])
    assert scope_call['payload']['papers'][1]['abstract'] == adjacent_quote


def test_context_only_prerequisite_cannot_buy_a_supported_slot():
    quote = 'The adjacent system supplies a generic foundation for the target method.'
    llm = ScopeAuditLLM(
        _scope_for(background='context'),
        [_audit(scope='direct')],
    )
    prerequisites, _, _, complete = asyncio.run(EvidenceVerifier(llm).verify_map(
        'Target system',
        [_relation(('background', quote), kind_name='Background dependency')],
        [],
        {'background': _paper('background', 'Adjacent foundation', quote)},
        research_question='Measure the target response in the target system.',
        language='en',
    ))

    assert complete is True
    assert len(prerequisites) == 1
    assert prerequisites[0].evidence_status == 'weak'
    assert prerequisites[0].confidence == .55
    assert 'Adjacent-system background' in prerequisites[0].reason


@pytest.mark.parametrize('scope_response', [
    {'papers': []},
    {'papers': [
        {'paper_id': 'p1', 'scope_relation': 'direct', 'reason': 'first'},
        {'paper_id': 'p1', 'scope_relation': 'direct', 'reason': 'duplicate'},
    ]},
    {'papers': [
        {'paper_id': 'unknown', 'scope_relation': 'direct', 'reason': 'unknown'},
    ]},
])
def test_scope_coverage_failure_never_marks_map_complete(scope_response):
    quote = 'The study measures the target response in the target system.'
    llm = ScopeAuditLLM(scope_response, [_audit()])
    _, subfields, warnings, complete = asyncio.run(EvidenceVerifier(llm).verify_map(
        'Target system', [], [_relation(('p1', quote))],
        {'p1': _paper('p1', 'Target study', quote)},
        research_question='Measure the target response in the target system.',
    ))

    assert complete is False
    assert len(llm.calls) == 1
    assert subfields
    assert subfields[0].evidence_status != 'supported'
    assert any('来源范围审查' in warning for warning in warnings)


def test_no_cited_paper_skips_source_scope_call():
    relation = FieldRelation(
        name='Uncited branch', reason='No source.', confidence=.5,
        evidence_paper_ids=[], evidence_quotes=[],
    )
    llm = ScopeAuditLLM(_scope_for())
    _, subfields, _, complete = asyncio.run(EvidenceVerifier(llm).verify_map(
        'Target system', [], [relation], {},
    ))

    assert complete is True
    assert subfields == []
    assert llm.calls == []


def test_source_scope_budget_overflow_fails_before_provider_call():
    quote1 = 'The study measures the first target response in the target system.'
    quote2 = 'The study measures the second target response in the target system.'
    llm = ScopeAuditLLM(_scope_for())
    _, subfields, warnings, complete = asyncio.run(EvidenceVerifier(
        llm, max_papers=1,
    ).verify_map(
        'Target system', [], [_relation(('p1', quote1), ('p2', quote2))],
        {
            'p1': _paper('p1', 'First target study', quote1),
            'p2': _paper('p2', 'Second target study', quote2),
        },
    ))

    assert complete is False
    assert subfields
    assert llm.calls == []
    assert any('超出论文预算' in warning for warning in warnings)
