import asyncio

from app.models.schemas import EvidenceQuote, FieldRelation
from app.services.evidence_verifier import EvidenceVerifier, SentPaper


class _AuditLLM:
    def __init__(self, audits):
        self.audits = audits
        self.calls = []

    async def generate_structured(self, **kwargs):
        self.calls.append(kwargs)
        if 'source-scope classifier' in kwargs.get('system', ''):
            return {'papers': [
                {'paper_id': paper['id'], 'scope_relation': 'direct',
                 'reason': 'The paper matches the requested study object.'}
                for paper in kwargs['payload']['papers']
            ]}
        return {'audits': self.audits}


def _relation(name='Target branch', *, paper_id='p1', quote=None):
    quote = quote or 'The study measures the target response in the stated system.'
    return FieldRelation(
        name=name,
        reason='The draft relation claims a measured contribution.',
        confidence=.9,
        evidence_paper_ids=[paper_id],
        evidence_quotes=[EvidenceQuote(
            paper_id=paper_id, source='abstract', quote=quote,
        )],
    )


def _paper(*, paper_id='p1', title='Adjacent system study', abstract=None):
    return SentPaper(
        id=paper_id,
        title=title,
        abstract=abstract or 'The study measures the target response in the stated system.',
    )


def test_supported_context_relation_cannot_remain_an_internal_subfield():
    llm = _AuditLLM([{
        'relation_id': 'r1',
        'verdict': 'supported',
        'reason': 'The excerpt supports the measured response.',
        'corrected_name': 'Measured target response',
        'supported_quote_ids': ['r1:q1'],
        'scope_relation': 'context',
    }])
    _, subfields, warnings, complete = asyncio.run(EvidenceVerifier(llm).verify_map(
        'Target system',
        [],
        [_relation()],
        {'p1': _paper()},
        research_question='Measure the target system response.',
        language='en',
    ))

    assert complete is True
    assert subfields == []
    assert any('adjacent-system background' in warning for warning in warnings)
    assert not any(any('\u4e00' <= char <= '\u9fff' for char in warning)
                   for warning in warnings)


def test_context_prerequisite_is_kept_as_weak_background():
    llm = _AuditLLM([{
        'relation_id': 'r1',
        'verdict': 'supported',
        'reason': 'The excerpt supports a related background response.',
        'corrected_name': 'Related background response',
        'supported_quote_ids': ['r1:q1'],
        'scope_relation': 'context',
    }])
    prerequisites, subfields, warnings, complete = asyncio.run(EvidenceVerifier(llm).verify_map(
        'Target system',
        [_relation(name='Background dependency')],
        [],
        {'p1': _paper()},
        research_question='Measure the target system response.',
        language='en',
    ))

    assert complete is True
    assert subfields == []
    assert len(prerequisites) == 1
    assert prerequisites[0].evidence_status == 'weak'
    assert prerequisites[0].confidence == .55
    assert 'Adjacent-system background; it is not quantitative evidence for the current question.' in prerequisites[0].reason
    assert not any(any('\u4e00' <= char <= '\u9fff' for char in warning)
                   for warning in warnings)


def test_off_topic_scope_classification_removes_a_prerequisite():
    llm = _AuditLLM([{
        'relation_id': 'r1',
        'verdict': 'supported',
        'reason': 'The excerpt supports its own measured response.',
        'corrected_name': 'Out-of-scope response',
        'supported_quote_ids': ['r1:q1'],
        'scope_relation': 'off_topic',
    }])
    prerequisites, _, warnings, complete = asyncio.run(EvidenceVerifier(llm).verify_map(
        'Target system',
        [_relation(name='Unrelated dependency')],
        [],
        {'p1': _paper()},
        research_question='Measure the target system response.',
        language='en',
    ))

    assert complete is True
    assert prerequisites == []
    assert any('outside the requested scope' in warning for warning in warnings)
    assert not any(any('\u4e00' <= char <= '\u9fff' for char in warning)
                   for warning in warnings)


def test_legacy_scope_omission_keeps_supported_relation_behavior():
    llm = _AuditLLM([{
        'relation_id': 'r1',
        'verdict': 'supported',
        'reason': 'The excerpt supports the target response.',
        'corrected_name': 'Measured target response',
        'supported_quote_ids': ['r1:q1'],
        'scope_relation': 'direct',
    }])
    _, subfields, _, complete = asyncio.run(EvidenceVerifier(llm).verify_map(
        'Target system',
        [],
        [_relation()],
        {'p1': _paper()},
    ))

    assert complete is True
    assert len(subfields) == 1
    assert subfields[0].evidence_status == 'supported'
    assert subfields[0].name == 'Measured target response'
