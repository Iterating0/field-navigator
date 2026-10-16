import asyncio

import pytest

from app.models.schemas import CorePaper, Paper
from app.services.evidence_verifier import (
    EvidenceVerifier,
    QUANTITATIVE_TOKEN,
    SentPaper,
    _qualitative_core_reason_without_unscoped_amplitude,
)


BARE_QUOTE = (
    'The estimated parameters can differ by more than a factor of two '
    'depending on the employed description.'
)


def test_spelled_number_support_does_not_parse_a_suffix_of_a_compound_number():
    assert QUANTITATIVE_TOKEN.search('十六倍') is None
    assert QUANTITATIVE_TOKEN.search('两倍').group() == '两倍'


@pytest.mark.parametrize(('reason', 'language', 'expected'), [
    (BARE_QUOTE, 'en', 'The estimated parameters can differ depending on the employed description.'),
    ('估计参数可能相差两倍以上，取决于所用描述。', 'zh-CN', '估计参数可能存在差异，取决于所用描述。'),
])
def test_unscoped_effect_size_becomes_a_readable_qualitative_contribution(reason, language, expected):
    result, limited = _qualitative_core_reason_without_unscoped_amplitude(
        reason, BARE_QUOTE, language=language, limit=220,
    )
    assert limited and result == expected


def test_explicit_simulation_setting_and_method_counts_remain_available():
    scoped = 'In a simulation with fixed noise, the estimated parameters differ by a factor of two.'
    counts = 'We compare 18 methods on 50 real-world and simulated datasets.'
    for quote in (scoped, counts):
        result, limited = _qualitative_core_reason_without_unscoped_amplitude(
            quote, quote, language='en', limit=220,
        )
        assert not limited and result == quote


def test_explicit_parameter_conditions_preserve_the_credible_level():
    quote = (
        'The bound is (0,630) when we allow for large component spins, and '
        '300 - 230 + 420 (using a 90% highest posterior density interval) '
        'when restricting the magnitude of the component spins.'
    )
    reason = '允许大分量自旋时为(0,630)，限制分量自旋幅度时为300−230+420（90%最高后验密度区间）。'
    result, limited = _qualitative_core_reason_without_unscoped_amplitude(
        reason, quote, language='zh-CN', limit=220,
    )
    assert not limited and result == reason


def test_final_reason_review_cannot_reintroduce_an_unscoped_effect_size():
    class LLM:
        def __init__(self):
            self.calls = []

        async def generate_structured(self, **kwargs):
            self.calls.append(kwargs)
            if kwargs['schema']['title'] == 'CoreReasonAuditBatch':
                return {'audits': [{'paper_id': 'p1', 'reason': BARE_QUOTE}]}
            return {'audits': [{
                'paper_id': 'p1', 'verdict': 'direct', 'role': 'primary',
                'reason': BARE_QUOTE, 'evidence_quote': BARE_QUOTE,
            }]}

    llm = LLM()
    paper = Paper(id='p1', title='Inference in a specified imaging modality', abstract=BARE_QUOTE,
                  work_type='article')
    core = CorePaper(paper=paper, score=.8, reason='An old claim must not become evidence.',
                     role='primary', evidence_basis='abstract', evidence_quote=BARE_QUOTE)
    result, warnings = asyncio.run(EvidenceVerifier(llm).verify_core(
        'Scientific inference', [core], {'p1': SentPaper.from_paper(paper)}, language='en',
    ))
    assert len(result) == 1 and 'factor of two' not in result[0].reason
    assert 'can differ depending on' in result[0].reason
    assert result[0].evidence_quote == BARE_QUOTE
    assert any('p1' in warning and 'made qualitative' in warning for warning in warnings)
    payload = llm.calls[1]['payload']['papers'][0]
    assert set(payload) == {'paper_id', 'scope_title', 'evidence_quote'}
    assert payload['scope_title'] == paper.title
    assert 'An old claim' not in str(payload)
