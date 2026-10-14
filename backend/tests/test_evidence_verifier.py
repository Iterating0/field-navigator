import asyncio

import pytest

import app.services.evidence_verifier as evidence_verifier_module
from app.models.schemas import CorePaper, EvidenceQuote, FieldRelation, Paper, PaperJudgment
from app.providers.base import ProviderError
from app.services.evidence_verifier import (
    EvidenceVerifier,
    SentPaper,
    _benchmark_result_needs_scope_limit,
    exact_quote_source,
)
from app.services.field_decomposer import FieldDecomposer


def relation(name='A branch', *, paper_id='p1', quote=None, abstract=True, confidence=.9):
    paper_quote = []
    if quote is not None:
        paper_quote = [EvidenceQuote(paper_id=paper_id, source='abstract' if abstract else 'title', quote=quote)]
    return FieldRelation(
        name=name,
        reason='The supplied metadata describes this direction.',
        confidence=confidence,
        evidence_paper_ids=[paper_id],
        evidence_quotes=paper_quote,
    )


class AuditLLM:
    def __init__(self, result=None, error=None):
        self.result = result or {
            'audits': [{
                'relation_id': 'r1',
                'verdict': 'supported',
                'reason': '摘要直接支持该研究方向。',
            }]
        }
        self.error = error
        self.calls = []

    async def generate_structured(self, **kwargs):
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        return self.result


def test_abstract_quote_requires_one_independent_batch_and_is_supported():
    paper = SentPaper('p1', 'Quantum transport branch', 'The paper measures quantum transport in a two-dimensional interface.')
    llm = AuditLLM()
    prerequisites, subfields, warnings, audit_complete = asyncio.run(
        EvidenceVerifier(llm).verify_map(
            'Test field',
            [],
            [relation(quote='measures quantum transport in a two-dimensional interface.')],
            {'p1': paper},
        )
    )

    assert audit_complete and not prerequisites and len(subfields) == 1
    result = subfields[0]
    assert result.evidence_status == 'supported'
    assert result.evidence_quotes[0].source == 'abstract'
    assert result.confidence == .9
    assert not warnings
    assert len(llm.calls) == 1
    assert list(llm.calls[0]['payload']['papers']) == [{'id': 'p1', 'title': paper.title, 'abstract': None}]


def test_relation_without_abstract_evidence_is_always_a_title_only_clue():
    paper = SentPaper('p1', 'Guide RNA pairing strategies', 'A description that was not quoted.')
    llm = AuditLLM({'audits': [{
        'relation_id': 'r1', 'verdict': 'weak', 'reason': '目前只有题名线索。',
    }]})
    _, branches, _, complete = asyncio.run(EvidenceVerifier(llm).verify_map(
        'Prime editing', [], [relation(name='Guide RNA pairing strategies')], {'p1': paper},
    ))
    assert complete and len(branches) == 1
    assert branches[0].evidence_status == 'weak'
    assert branches[0].claim_level == 'title_only'
    assert not branches[0].evidence_quotes


def test_map_audit_narrows_branch_name_to_its_own_excerpt():
    excerpt = 'We propose a nematic d-wave pairing state in this system.'
    paper = SentPaper('p1', 'A proposed pairing theory', excerpt)
    llm = AuditLLM({'audits': [{
        'relation_id': 'r1', 'verdict': 'supported',
        'reason': '摘录提出一种向列d波配对态。',
        'corrected_name': 'Theory of nematic d-wave pairing',
    }]})
    _, branches, warnings, _ = asyncio.run(EvidenceVerifier(llm).verify_map(
        'Test field', [], [relation(name='Pairing: d+id, p+ip and s-wave', quote=excerpt)], {'p1': paper},
    ))
    assert branches[0].name == 'Theory of nematic d-wave pairing'
    assert branches[0].claim_level == 'theory_or_proposed'
    assert any('分支名称已按本条核对摘录收窄' in warning for warning in warnings)


def test_map_audit_cannot_rename_branch_into_a_scope_conflict():
    excerpt = 'We measure boundary accumulation in a one-dimensional chain.'
    paper = SentPaper('p1', 'One-dimensional boundary accumulation', excerpt)
    llm = AuditLLM({'audits': [{
        'relation_id': 'r1', 'verdict': 'supported', 'reason': '摘录支持该方向。',
        'corrected_name': 'Higher-dimensional boundary accumulation',
    }]})
    _, branches, warnings, _ = asyncio.run(EvidenceVerifier(llm).verify_map(
        'One-dimensional nonreciprocal chain', [], [relation(name='Boundary accumulation', quote=excerpt)], {'p1': paper},
    ))
    assert branches == []
    assert any('维度范围冲突' in warning for warning in warnings)


def test_audited_name_collisions_keep_one_stronger_relation_without_borrowing_quotes():
    excerpt = 'We measure carrier density and superconductivity at the interface.'
    paper = SentPaper('p1', 'Interface carrier density', excerpt)
    llm = AuditLLM({'audits': [
        {'relation_id': 'r1', 'verdict': 'weak', 'reason': '线索有限。', 'corrected_name': 'Carrier control'},
        {'relation_id': 'r2', 'verdict': 'supported', 'reason': '摘录支持调控方向。', 'corrected_name': 'carrier control'},
    ]})
    _, branches, warnings, _ = asyncio.run(EvidenceVerifier(llm).verify_map(
        'Test field', [], [relation(name='Carrier density', quote=excerpt), relation(name='Gate tuning', quote=excerpt)], {'p1': paper},
    ))
    assert len(branches) == 1
    assert branches[0].evidence_status == 'supported'
    assert len(branches[0].evidence_quotes) == 1
    assert any('重复方向' in warning for warning in warnings)


def test_map_audit_sends_only_relation_verified_quotes_and_title_context(monkeypatch):
    monkeypatch.setattr(evidence_verifier_module, 'scope_mismatch', lambda *args: None)

    quote_a1 = 'The surface defect enables ion migration.'
    quote_a2 = 'The interface shows a field-driven transition.'
    quote_b = 'The legal RAG tool reports answer faithfulness.'
    invalid = 'This sentence is absent from the supplied metadata.'
    relation_a = FieldRelation(
        name='Surface defect migration',
        reason='Current recommendation for relation A.',
        confidence=.9,
        evidence_paper_ids=['a', 'b'],
        evidence_quotes=[
            EvidenceQuote(paper_id='a', source='abstract', quote=quote_a1),
            EvidenceQuote(paper_id='a', source='abstract', quote=quote_a2),
            EvidenceQuote(paper_id='a', source='abstract', quote=invalid),
        ],
    )
    relation_b = FieldRelation(
        name='Legal RAG faithfulness',
        reason='Current recommendation for relation B.',
        confidence=.9,
        evidence_paper_ids=['b'],
        evidence_quotes=[EvidenceQuote(paper_id='b', source='abstract', quote=quote_b)],
    )
    papers = {
        'a': SentPaper(
            'a', 'Surface defect field response',
            f'Background omitted. {quote_a1} More omitted detail. {quote_a2}',
        ),
        'b': SentPaper(
            'b', 'Legal RAG evaluation',
            f'Background omitted. {quote_b} Unquoted claim about evaluator reliability.',
        ),
    }

    class LLM:
        def __init__(self):
            self.payload = None

        async def generate_structured(self, **kwargs):
            self.payload = kwargs['payload']
            return {'audits': [
                {'relation_id': 'r1', 'verdict': 'supported', 'reason': '核对摘录支持关系A。'},
                {'relation_id': 'r2', 'verdict': 'supported', 'reason': '核对摘录支持关系B。'},
            ]}

    llm = LLM()
    _, branches, warnings, complete = asyncio.run(EvidenceVerifier(llm).verify_map(
        'Research field', [], [relation_a, relation_b], papers,
    ))

    assert complete and len(branches) == 2
    assert any('无法在实际发送的标题或摘要中核对' in warning for warning in warnings)
    assert all(item['abstract'] is None for item in llm.payload['papers'])
    relation_payload = {item['relation_id']: item for item in llm.payload['relations']}
    assert [item['quote'] for item in relation_payload['r1']['evidence_quotes']] == [quote_a1, quote_a2]
    assert [item['quote'] for item in relation_payload['r2']['evidence_quotes']] == [quote_b]
    assert invalid not in str(llm.payload)
    assert quote_b not in [item['quote'] for item in relation_payload['r1']['evidence_quotes']]


def test_title_only_support_is_weak_even_when_audit_says_supported():
    paper = SentPaper('p1', 'Non-Hermitian skin effect', None)
    llm = AuditLLM()
    _, subfields, warnings, audit_complete = asyncio.run(
        EvidenceVerifier(llm).verify_map(
            'Non-Hermitian physics',
            [],
            [relation(name='Skin effect', quote=paper.title, abstract=False, confidence=.9)],
            {'p1': paper},
        )
    )

    result = subfields[0]
    assert result.evidence_status == 'weak'
    assert result.confidence == .55
    assert any('标题线索' in warning for warning in result.evidence_warnings)
    assert any('标题线索' in warning for warning in warnings)


def test_semantic_unsupported_relation_is_removed_and_invalid_quote_never_supported():
    paper = SentPaper('p1', 'A paper about unrelated optics', 'The abstract reports an unrelated optics experiment.')
    llm = AuditLLM({
        'audits': [{
            'relation_id': 'r1',
            'verdict': 'unsupported',
            'reason': '元数据没有支持该关系。',
        }]
    })
    _, subfields, warnings, audit_complete = asyncio.run(
        EvidenceVerifier(llm).verify_map(
            'Quantum transport',
            [],
            [relation(name='Quantum transport', quote='this phrase is absent')],
            {'p1': paper},
        )
    )

    assert subfields == []
    assert any('已删除' in warning for warning in warnings)


def test_scope_mismatch_blocks_relation_before_a_malicious_supported_audit(monkeypatch):
    def fake_scope(field, research_question, title, abstract=''):
        return '显式范围冲突' if 'Blocked' in title else None

    monkeypatch.setattr(evidence_verifier_module, 'scope_mismatch', fake_scope)
    llm = AuditLLM()
    paper = SentPaper(
        'p1', 'Target paper', 'The paper measures target transport in the interface.'
    )
    _, subfields, warnings, audit_complete = asyncio.run(
        EvidenceVerifier(llm).verify_map(
            'Target field', [],
            [relation(name='Blocked branch', quote='measures target transport in the interface.')],
            {'p1': paper},
        )
    )

    assert audit_complete and subfields == []
    assert llm.calls == []
    assert any('显式范围冲突' in warning for warning in warnings)


def test_scope_mismatch_filters_blocked_evidence_before_supported_audit(monkeypatch):
    def fake_scope(field, research_question, title, abstract=''):
        return '显式范围冲突' if 'Blocked' in title else None

    monkeypatch.setattr(evidence_verifier_module, 'scope_mismatch', fake_scope)

    class LLM:
        def __init__(self):
            self.calls = []

        async def generate_structured(self, **kwargs):
            self.calls.append(kwargs)
            assert kwargs['payload']['relations'][0]['evidence_paper_ids'] == ['good']
            return {'audits': [{
                'relation_id': 'r1',
                'verdict': 'supported',
                'reason': '摘要支持范围内方向。',
            }]}

    llm = LLM()
    relation_with_two_sources = FieldRelation(
        name='Target branch',
        reason='The metadata describes this direction.',
        confidence=.9,
        evidence_paper_ids=['blocked', 'good'],
        evidence_quotes=[
            EvidenceQuote(paper_id='blocked', source='abstract', quote='blocked evidence text'),
            EvidenceQuote(paper_id='good', source='abstract', quote='in-scope evidence text'),
        ],
    )
    papers = {
        'blocked': SentPaper('blocked', 'Blocked adjacent system', 'blocked evidence text'),
        'good': SentPaper('good', 'Target system result', 'in-scope evidence text'),
    }

    _, subfields, warnings, audit_complete = asyncio.run(
        EvidenceVerifier(llm).verify_map(
            'Target field', [], [relation_with_two_sources], papers,
        )
    )

    assert audit_complete and len(subfields) == 1
    assert subfields[0].evidence_status == 'supported'
    assert subfields[0].evidence_paper_ids == ['good']
    assert [quote.paper_id for quote in subfields[0].evidence_quotes] == ['good']
    assert any('范围外引文已过滤' in warning for warning in warnings)


def test_verified_benchmark_percentage_reason_is_limited_to_its_evaluation_setting(monkeypatch):
    monkeypatch.setattr(evidence_verifier_module, 'scope_mismatch', lambda *args: None)

    class LLM:
        async def generate_structured(self, **kwargs):
            return {'audits': [{
                'relation_id': 'r1',
                'verdict': 'supported',
                'reason': '该结果证明模型具有一般可靠性。',
            }]}

    paper = SentPaper(
        'p1',
        'RAG benchmark evaluation',
        'On the benchmark, GPT-4o-mini achieved 25.7% recall.',
    )
    branch = relation(
        name='RAG benchmark performance',
        paper_id='p1',
        quote='GPT-4o-mini achieved 25.7% recall',
    )
    _, subfields, warnings, audit_complete = asyncio.run(
        EvidenceVerifier(LLM()).verify_map(
            'RAG reliability', [], [branch], {'p1': paper},
        )
    )

    assert audit_complete and len(subfields) == 1
    assert subfields[0].evidence_status == 'supported'
    assert subfields[0].reason.startswith('在所引论文的具体评测设置中：')
    assert '不外推其他模型或任务' in subfields[0].reason
    assert subfields[0].evidence_quotes[0].quote == 'GPT-4o-mini achieved 25.7% recall'
    assert any('评测数值仅限' in warning for warning in warnings)


def test_benchmark_detector_keeps_decimal_and_metric_order():
    assert _benchmark_result_needs_scope_limit(['GPT achieves25.7%recall'])
    assert _benchmark_result_needs_scope_limit(['recallof25.7%'])
    assert _benchmark_result_needs_scope_limit(['The system failed on 3 of 10 cases'])


def test_evaluated_tool_reliability_does_not_establish_evaluator_reliability_in_map(monkeypatch):
    monkeypatch.setattr(evidence_verifier_module, 'scope_mismatch', lambda *args: None)

    class LLM:
        async def generate_structured(self, **kwargs):
            return {'audits': [{
                'relation_id': 'r1',
                'verdict': 'supported',
                'reason': '法律RAG工具评估涉及评价者可靠性。',
            }]}

    quote = 'We evaluate AI research tools and report hallucination rates.'
    paper = SentPaper('p1', 'Assessing reliability of AI research tools', quote)
    _, branches, warnings, complete = asyncio.run(EvidenceVerifier(LLM()).verify_map(
        'RAG evaluation', [], [relation(name='Legal RAG evaluation', quote=quote)], {'p1': paper},
    ))

    assert complete and len(branches) == 1
    assert '法律RAG工具评估' in branches[0].reason
    assert '未由所引题录确认评价者可靠性' in branches[0].reason
    assert branches[0].evidence_quotes[0].quote == quote
    assert any('评估者或 LLM judge' in warning for warning in warnings)


def test_quantitative_reason_without_verified_value_is_neutralized_and_values_are_scoped(monkeypatch):
    monkeypatch.setattr(evidence_verifier_module, 'scope_mismatch', lambda *args: None)

    class LLM:
        def __init__(self, reason):
            self.reason = reason

        async def generate_structured(self, **kwargs):
            return {'audits': [{
                'relation_id': 'r1',
                'verdict': 'supported',
                'reason': self.reason,
            }]}

    quote_without_value = 'We evaluate legal RAG tools for hallucination.'
    paper_without_value = SentPaper('p1', 'Legal RAG evaluation', quote_without_value)
    _, branches, warnings, complete = asyncio.run(EvidenceVerifier(LLM('报告17%至33%幻觉率。')).verify_map(
        'RAG evaluation', [], [relation(name='Legal RAG evaluation', quote=quote_without_value)],
        {'p1': paper_without_value},
    ))
    assert complete and len(branches) == 1
    assert '17%' not in branches[0].reason and '33%' not in branches[0].reason
    assert '具体定量值未由核对摘录确认' in branches[0].reason
    assert any('定量值未出现在核对摘录' in warning for warning in warnings)

    quote_with_value = 'The method reduces hallucination rates to 10.39%.'
    paper_with_value = SentPaper('p2', 'Hallucination mitigation', quote_with_value)
    _, scoped, warnings, complete = asyncio.run(EvidenceVerifier(LLM('该方法降低幻觉率至10.39%。')).verify_map(
        'RAG evaluation', [], [relation(name='Mitigation evaluation', paper_id='p2', quote=quote_with_value)],
        {'p2': paper_with_value},
    ))
    assert complete and len(scoped) == 1
    assert scoped[0].reason.startswith('在所引论文的具体评测设置中：')
    assert '10.39%' in scoped[0].reason
    assert any('评测数值仅限' in warning for warning in warnings)


def test_quantitative_guard_matches_translated_units_and_ranges_without_substring_false_positive():
    assert evidence_verifier_module._quantitative_token_in_excerpts(
        '17倍', ['The method improves performance by 17-fold.'],
    )
    assert evidence_verifier_module._quantitative_token_in_excerpts(
        '2–17-fold', ['The method improves performance by 2–17倍.'],
    )
    assert not evidence_verifier_module._quantitative_token_in_excerpts(
        '6%', ['The measured rate is 16%.'],
    )
    assert evidence_verifier_module._quantitative_token_in_excerpts(
        '16%', ['The measured rate is 16%.'],
    )


def test_quantitative_guard_removes_a_full_unverified_range_without_residual_connector():
    reason, changed = evidence_verifier_module._sanitize_unverified_quantitative_reason(
        '报告2–17倍的提升。', ['The abstract reports a qualitative improvement.'], limit=220,
    )
    assert changed
    assert '2–' not in reason and '17倍' not in reason
    assert '相关定量值' in reason
    assert '2–相关定量值' not in reason


def test_quantitative_guard_normalizes_spelled_multipliers_and_bounded_counts():
    assert evidence_verifier_module._quantitative_token_in_excerpts(
        'up to seven-fold', ['The benchmark reaches 7-fold improvement.'],
    )
    assert evidence_verifier_module._quantitative_token_in_excerpts(
        '41种组合', ['The benchmark evaluates 41 combinations.'],
    )
    assert evidence_verifier_module._quantitative_result_needs_scope_limit(
        ['The benchmark evaluates 41 combinations.'],
    )

    reason, changed = evidence_verifier_module._sanitize_unverified_quantitative_reason(
        '覆盖41种组合。', ['The abstract reports a qualitative evaluation.'], limit=220,
    )
    assert changed
    assert '41种组合' not in reason
    assert '相关定量值' in reason

    identifier_context = 'In 2024, GPT-4o and GPT 4 models are evaluated on a 2D model.'
    assert not evidence_verifier_module._quantitative_result_needs_scope_limit(
        [identifier_context],
    )


def test_audit_failure_keeps_only_conservative_unverified_result():
    paper = SentPaper('p1', 'Transport branch', 'The paper measures transport in interface.')
    llm = AuditLLM(error=ProviderError('audit unavailable'))
    _, subfields, warnings, audit_complete = asyncio.run(
        EvidenceVerifier(llm).verify_map(
            'Test field',
            [],
            [relation(quote='measures transport in interface.')],
            {'p1': paper},
        )
    )

    assert len(subfields) == 1
    assert subfields[0].evidence_status == 'weak'
    assert subfields[0].confidence == .55
    assert all(item.evidence_status != 'supported' for item in subfields)
    assert any('未完成' in warning for warning in warnings)


def test_judgment_quote_validation_canonicalizes_basis_and_caps_title_or_invalid():
    papers = {
        'abstract': SentPaper('abstract', 'A title', 'The abstract reports a measured contribution.'),
        'title': SentPaper('title', 'Title-only contribution', None),
    }
    judgments = [
        PaperJudgment(
            paper_id='abstract', importance=.9, relevance=.8, reason='Measured contribution.',
            evidence_quote='reports a measured contribution.',
        ),
        PaperJudgment(
            paper_id='title', importance=.9, relevance=.8, reason='Contribution.',
            evidence_quote='Title-only contribution',
        ),
        PaperJudgment(
            paper_id='abstract', importance=.9, relevance=.8, reason='Mechanism claim.',
            evidence_quote='not present in metadata',
        ),
    ]

    result = EvidenceVerifier(AuditLLM()).validate_judgments(judgments, papers)

    assert result[0].evidence_basis == 'abstract' and result[0].importance == .9
    assert result[1].evidence_basis == 'title' and result[1].importance == .55
    assert result[2].evidence_basis == 'unverified'
    assert result[2].evidence_quote == '' and result[2].importance == .55
    assert '没有可核对摘录' in result[2].reason


def test_decomposer_runs_main_map_then_independent_audit_and_restores_aliases():
    class TwoStageLLM:
        def __init__(self):
            self.calls = []

        async def generate_structured(self, **kwargs):
            self.calls.append(kwargs)
            if 'independent evidence auditor' in kwargs['system']:
                return {'audits': [{
                    'relation_id': 'r1',
                    'verdict': 'supported',
                    'reason': '摘要直接支持该具体研究方向。',
                }]}
            return {
                'summary': 'Map',
                'prerequisites': [],
                'subfields': [{
                    'name': 'Transport branch',
                    'reason': 'The metadata supports this direction.',
                    'confidence': .8,
                    'evidence_paper_ids': ['p1'],
                    'evidence_quotes': [{
                        'paper_id': 'p1',
                        'source': 'abstract',
                        'quote': 'measures transport in the interface',
                    }],
                }],
            }

    llm = TwoStageLLM()
    paper = Paper(
        id='W1',
        title='Transport paper',
        abstract='This paper measures transport in the interface and reports a transition.',
    )
    result = asyncio.run(FieldDecomposer(llm).decompose_map('Test field', [paper], research_question='Keep this to one-dimensional transport interfaces.'))

    assert len(llm.calls) == 2
    assert result.subfields[0].evidence_status == 'supported'
    assert result.subfields[0].evidence_paper_ids == ['W1']
    assert result.subfields[0].evidence_quotes[0].paper_id == 'W1'
    assert llm.calls[0]['payload']['research_question'] == 'Keep this to one-dimensional transport interfaces.'
    assert llm.calls[0]['payload']['papers'][0]['work_type'] is None
    assert llm.calls[1]['payload']['papers'][0]['id'] == 'W1'
    assert llm.calls[1]['payload']['relations'][0]['evidence_paper_ids'] == ['W1']
    assert llm.calls[1]['payload']['research_question'] == 'Keep this to one-dimensional transport interfaces.'


def test_decomposer_audit_failure_returns_warning_and_never_supported_map():
    class FailingAuditLLM:
        def __init__(self):
            self.calls = 0

        async def generate_structured(self, **kwargs):
            self.calls += 1
            if self.calls == 1:
                return {
                    'summary': 'Map',
                    'prerequisites': [],
                    'subfields': [{
                        'name': 'Transport branch',
                        'reason': 'The metadata supports this direction.',
                        'confidence': .8,
                        'evidence_paper_ids': ['p1'],
                        'evidence_quotes': [{
                            'paper_id': 'p1',
                            'source': 'abstract',
                            'quote': 'measures transport in interface',
                        }],
                    }],
                }
            raise ProviderError('audit unavailable')

    result = asyncio.run(FieldDecomposer(FailingAuditLLM()).decompose_map(
        'Test field',
        [Paper(id='W1', title='Transport', abstract='The paper measures transport in interface.')],
    ))

    assert result.subfields[0].evidence_status == 'weak'
    assert any('未完成' in warning for warning in result.warnings)


def test_judge_papers_rejects_missing_candidate_coverage():
    class PartialJudgmentLLM:
        async def generate_structured(self, **kwargs):
            return {
                'paper_judgments': [{
                    'paper_id': 'p1',
                    'importance': .8,
                    'relevance': .8,
                    'reason': 'Contribution.',
                    'evidence_quote': 'Paper one',
                }]
            }

    with pytest.raises(ProviderError, match='未覆盖全部候选'):
        asyncio.run(FieldDecomposer(PartialJudgmentLLM()).judge_papers(
            'Test field',
            [Paper(id='W1', title='Paper one'), Paper(id='W2', title='Paper two')],
        ))



def test_short_single_token_quote_is_not_treated_as_semantic_evidence():
    paper = SentPaper('p1', 'A superconductivity paper', 'The abstract reports strong superconductivity observed at low temperature.')
    assert exact_quote_source('superconductivity', paper) is None
    assert exact_quote_source('strong superconductivity observed', paper) == 'abstract'


def test_supported_theory_direction_is_not_presented_as_an_established_mechanism():
    class LLM:
        async def generate_structured(self, **kwargs):
            return {'audits': [{'relation_id': 'r1', 'verdict': 'supported',
                               'reason': '论文提出该配对候选机制，支持研究方向。'}]}
    relation = FieldRelation(name='Phonon pairing mechanisms', reason='A mechanism claim.',
                             confidence=.9, evidence_paper_ids=['W1'],
                             evidence_quotes=[EvidenceQuote(paper_id='W1', source='abstract',
                                 quote='We propose a phonon-mediated pairing mechanism')])
    paper = SentPaper('W1', 'Pairing theory', 'We propose a phonon-mediated pairing mechanism; its experimental status remains unresolved.')
    _, branches, _, complete = asyncio.run(EvidenceVerifier(LLM()).verify_map(
        'Interface superconductivity', [], [relation], {'W1': paper}))
    assert complete and branches[0].evidence_status == 'supported'
    assert branches[0].claim_level == 'theory_or_proposed'
    assert '提出' in branches[0].reason
    assert any('不代表机制已被证实' in text for text in branches[0].evidence_warnings)


def test_an_incidental_may_or_proposed_method_is_not_a_tentative_physical_mechanism():
    from app.services.evidence_verifier import theoretical_claim
    assert not theoretical_claim('Interface growth engineering', '报告外延膜生长结果。',
                                  ['These devices may support future applications.'])
    assert not theoretical_claim('pegRNA design', '论文提出并测试新的设计。',
                                  ['We propose a design and experimentally measure editing efficiency.'])
    assert theoretical_claim('Phonon pairing mechanisms', '论文讨论配对起源。',
                              ['The measured correlation could explain this pairing mechanism.'])


def test_model_prediction_is_research_direction_without_same_sentence_mechanism_context():
    from app.services.evidence_verifier import theoretical_claim

    assert not theoretical_claim(
        'Machine learning prediction of prime editing efficiency',
        '模型预测编辑效率并辅助 pegRNA 设计。',
        ['We train a predictive model for editing outcomes.'],
    )
    assert not theoretical_claim(
        'Interface mechanism engineering',
        '该方法可能提高效率。',
        ['The interface mechanism is studied separately.'],
    )
    assert theoretical_claim(
        'Pairing theory prediction',
        '模型预测该配对机制的起源。',
        [],
    )


class CoreAuditLLM:
    def __init__(self, result):
        self.result = result
        self.calls = []

    async def generate_structured(self, **kwargs):
        self.calls.append(kwargs)
        return self.result


def core_paper(paper: Paper, *, score=.9, reason='Current recommendation overclaims the result.', role='primary', quote=None):
    excerpt = quote if quote is not None else (paper.abstract or paper.title)[:300]
    return CorePaper(paper=paper, score=score, reason=reason, role=role,
                     evidence_quote=excerpt, evidence_basis='abstract' if paper.abstract else 'title')


def test_core_audit_corrects_false_gapless_inference_from_nodeless_result():
    paper = Paper(
        id='p1',
        title='Nodeless superconductivity at an oxide interface',
        abstract='We observe nodeless superconductivity at the oxide interface; this does not establish a gapless spectrum.',
    )
    llm = CoreAuditLLM({
        'audits': [{
            'paper_id': 'p1',
            'verdict': 'direct',
            'reason': '摘要支持界面无节点超导，但未证明无能隙谱。',
            'evidence_quote': 'observe nodeless superconductivity at the oxide interface',
            'role': 'primary',
        }]
    })

    result, warnings = asyncio.run(EvidenceVerifier(llm).verify_core(
        'oxide-interface superconductivity',
        [core_paper(paper)],
        {'p1': SentPaper.from_paper(paper)},
        'Restrict this question to oxide-interface superconductivity.',
    ))

    assert len(result) == 1
    assert '无能隙' in result[0].reason
    assert 'overclaims' not in result[0].reason
    assert result[0].evidence_basis == 'abstract'
    assert result[0].evidence_quote == paper.abstract
    assert not warnings


def test_core_benchmark_reason_is_limited_to_quoted_evaluation_setting(monkeypatch):
    monkeypatch.setattr(evidence_verifier_module, 'scope_mismatch', lambda *args: None)
    paper = Paper(
        id='p1',
        title='RAG benchmark evaluation',
        abstract='On the benchmark, GPT-4o-mini achieved 25.7% recall.',
    )
    llm = CoreAuditLLM({
        'audits': [{
            'paper_id': 'p1',
            'verdict': 'direct',
            'reason': '该结果证明模型具有一般可靠性。',
            'evidence_quote': 'GPT-4o-mini achieved 25.7% recall',
            'role': 'primary',
        }]
    })

    result, warnings = asyncio.run(EvidenceVerifier(llm).verify_core(
        'RAG reliability',
        [core_paper(paper)],
        {'p1': SentPaper.from_paper(paper)},
    ))

    assert len(result) == 1
    assert result[0].reason.startswith('在所引论文的具体评测设置中：')
    assert '不外推其他模型或任务。' in result[0].reason
    assert result[0].evidence_quote == paper.abstract
    assert not warnings


def test_core_evaluated_tool_reliability_does_not_establish_evaluator_reliability(monkeypatch):
    monkeypatch.setattr(evidence_verifier_module, 'scope_mismatch', lambda *args: None)
    quote = 'We evaluate AI research tools and report hallucination rates.'
    paper = Paper(id='p1', title='Assessing reliability of AI research tools', abstract=quote)
    llm = CoreAuditLLM({
        'audits': [{
            'paper_id': 'p1',
            'verdict': 'direct',
            'reason': '该研究评估法律RAG工具，并涉及评价者可靠性。',
            'evidence_quote': quote,
            'role': 'primary',
        }]
    })

    result, warnings = asyncio.run(EvidenceVerifier(llm).verify_core(
        'RAG evaluation', [core_paper(paper)], {'p1': SentPaper.from_paper(paper)},
    ))

    assert len(result) == 1
    assert '评估法律RAG工具' in result[0].reason
    assert '未由所引题录确认评价者可靠性' in result[0].reason
    assert result[0].evidence_quote == quote
    assert any('评估者或 LLM judge' in warning for warning in warnings)


def test_core_genuine_judge_validation_preserves_evaluator_claim(monkeypatch):
    monkeypatch.setattr(evidence_verifier_module, 'scope_mismatch', lambda *args: None)
    quote = 'We validate an LLM-as-a-judge against human judgments for faithfulness.'
    paper = Paper(id='p1', title='Validating an LLM judge', abstract=quote)
    llm = CoreAuditLLM({
        'audits': [{
            'paper_id': 'p1',
            'verdict': 'direct',
            'reason': '该研究支持LLM-as-judge可靠性。',
            'evidence_quote': quote,
            'role': 'primary',
        }]
    })

    result, warnings = asyncio.run(EvidenceVerifier(llm).verify_core(
        'RAG evaluation', [core_paper(paper)], {'p1': SentPaper.from_paper(paper)},
    ))

    assert len(result) == 1
    assert '支持LLM-as-judge可靠性' in result[0].reason
    assert not any('评估者或 LLM judge' in warning for warning in warnings)


def test_human_evaluation_of_tool_does_not_validate_the_evaluator(monkeypatch):
    monkeypatch.setattr(evidence_verifier_module, 'scope_mismatch', lambda *args: None)
    quote = 'Human judges evaluated answers from our AI tool; system accuracy was reported.'
    paper = Paper(id='p1', title='Evaluation of an AI tool', abstract=quote)
    llm = CoreAuditLLM({
        'audits': [{
            'paper_id': 'p1',
            'verdict': 'direct',
            'reason': '该研究涉及评价者可靠性。',
            'evidence_quote': quote,
            'role': 'primary',
        }]
    })

    result, warnings = asyncio.run(EvidenceVerifier(llm).verify_core(
        'AI tool evaluation', [core_paper(paper)], {'p1': SentPaper.from_paper(paper)},
    ))

    assert len(result) == 1
    assert '未由所引题录确认评价者可靠性' in result[0].reason
    assert any('评估者或 LLM judge' in warning for warning in warnings)


def test_core_efficiency_does_not_imply_editing_purity_without_abstract_evidence(monkeypatch):
    monkeypatch.setattr(evidence_verifier_module, 'scope_mismatch', lambda *args: None)
    quote = 'We measure prime editing efficiency in mammalian cells.'
    paper = Paper(id='p1', title='Prime editing efficiency', abstract=quote)
    llm = CoreAuditLLM({
        'audits': [{
            'paper_id': 'p1',
            'verdict': 'direct',
            'reason': '该工作提高编辑效率并增强意向编辑纯度。',
            'evidence_quote': quote,
            'role': 'primary',
        }]
    })

    result, warnings = asyncio.run(EvidenceVerifier(llm).verify_core(
        'Prime editing', [core_paper(paper)], {'p1': SentPaper.from_paper(paper)},
    ))

    assert len(result) == 1
    assert '提高编辑效率' in result[0].reason
    assert '未由核对摘要明确支持的纯度或编辑产物' in result[0].reason
    assert any('保真度、纯度或特异性主张' in warning for warning in warnings)


def test_core_abstract_quote_with_efficiency_and_fidelity_preserves_both_outcomes(monkeypatch):
    monkeypatch.setattr(evidence_verifier_module, 'scope_mismatch', lambda *args: None)
    quote = 'We improve prime editing efficiency, fidelity, and intended-edit purity in mammalian cells.'
    paper = Paper(id='p1', title='Prime editing efficiency, fidelity, and intended-edit purity', abstract=quote)
    llm = CoreAuditLLM({
        'audits': [{
            'paper_id': 'p1',
            'verdict': 'direct',
            'reason': '该工作提高编辑效率并增强意向编辑纯度。',
            'evidence_quote': quote,
            'role': 'primary',
        }]
    })

    result, warnings = asyncio.run(EvidenceVerifier(llm).verify_core(
        'Prime editing', [core_paper(paper)], {'p1': SentPaper.from_paper(paper)},
    ))

    assert len(result) == 1
    assert result[0].reason == '该工作提高编辑效率并增强意向编辑纯度。'
    assert not any('保真度、纯度或特异性主张' in warning for warning in warnings)


def test_core_cautious_or_unmeasured_outcome_claim_is_not_rewritten(monkeypatch):
    monkeypatch.setattr(evidence_verifier_module, 'scope_mismatch', lambda *args: None)
    quote = 'The study reports an efficiency result; fidelity remains to be evaluated.'
    paper = Paper(id='p1', title='Prime editing efficiency', abstract=quote)
    reasons = [
        '该工作提高编辑效率，未来需要评估保真度。',
        'The work improves efficiency; fidelity is not established.',
    ]
    for reason in reasons:
        llm = CoreAuditLLM({
            'audits': [{
                'paper_id': 'p1',
                'verdict': 'direct',
                'reason': reason,
                'evidence_quote': quote,
                'role': 'primary',
            }]
        })
        result, warnings = asyncio.run(EvidenceVerifier(llm).verify_core(
            'Prime editing', [core_paper(paper)], {'p1': SentPaper.from_paper(paper)},
        ))
        assert len(result) == 1
        assert result[0].reason == reason
        assert not any('保真度、纯度或特异性主张' in warning for warning in warnings)


def test_core_system_reliability_and_human_tasks_are_not_evaluator_claims(monkeypatch):
    monkeypatch.setattr(evidence_verifier_module, 'scope_mismatch', lambda *args: None)
    quote = 'We evaluate RAG tools on human question answering tasks.'
    paper = Paper(id='p1', title='RAG tool evaluation on human tasks', abstract=quote)
    reason = '该工作评估RAG系统可靠性与人类任务表现。'
    llm = CoreAuditLLM({
        'audits': [{
            'paper_id': 'p1',
            'verdict': 'direct',
            'reason': reason,
            'evidence_quote': quote,
            'role': 'primary',
        }]
    })

    result, warnings = asyncio.run(EvidenceVerifier(llm).verify_core(
        'RAG evaluation', [core_paper(paper)], {'p1': SentPaper.from_paper(paper)},
    ))

    assert len(result) == 1
    assert result[0].reason == reason
    assert not warnings


def test_core_audit_requires_exact_coverage_and_rejects_missing_result():
    papers = [
        Paper(id='p1', title='Direct paper', abstract='The abstract supports a direct contribution.'),
        Paper(id='p2', title='Second paper', abstract='The abstract supports another contribution.'),
    ]
    llm = CoreAuditLLM({
        'audits': [{
            'paper_id': 'p1', 'verdict': 'direct',
            'reason': '摘要支持该贡献。',
            'evidence_quote': 'supports a direct contribution', 'role': 'primary',
        }]
    })

    with pytest.raises(ProviderError, match='未覆盖全部候选'):
        asyncio.run(EvidenceVerifier(llm).verify_core(
            'Test field',
            [core_paper(papers[0]), core_paper(papers[1])],
            {paper.id: SentPaper.from_paper(paper) for paper in papers},
        ))
    assert len(llm.calls) == 1


def test_scope_mismatch_blocks_core_before_a_malicious_direct_audit(monkeypatch):
    def fake_scope(field, research_question, title, abstract=''):
        return '显式范围冲突' if 'Blocked' in title else None

    monkeypatch.setattr(evidence_verifier_module, 'scope_mismatch', fake_scope)

    class LLM:
        def __init__(self):
            self.calls = []

        async def generate_structured(self, **kwargs):
            self.calls.append(kwargs)
            return {'audits': [{
                'paper_id': 'p1',
                'verdict': 'direct',
                'reason': '摘要直接支持该贡献。',
                'evidence_quote': 'blocked system contribution',
                'role': 'primary',
            }]}

    llm = LLM()
    paper = Paper(
        id='p1',
        title='Blocked adjacent system contribution',
        abstract='The blocked system contribution is reported here.',
    )
    result, warnings = asyncio.run(EvidenceVerifier(llm).verify_core(
        'Target field',
        [core_paper(paper)],
        {'p1': SentPaper.from_paper(paper)},
        'Keep the target system scope narrow.',
    ))

    assert result == []
    assert llm.calls == []
    assert any('显式范围冲突' in warning for warning in warnings)


def test_core_audit_is_one_batch_and_sends_only_selected_metadata():
    papers = [
        Paper(id='p1', title='Direct paper one', abstract='The abstract supports the first contribution.'),
        Paper(id='p2', title='Direct paper two', abstract='The abstract supports the second contribution.'),
        Paper(id='p3', title='Unselected paper', abstract='This paper must not enter the audit payload.'),
    ]
    llm = CoreAuditLLM({
        'audits': [
            {'paper_id': 'p1', 'verdict': 'direct', 'reason': '支持第一项贡献。',
             'evidence_quote': 'supports the first contribution', 'role': 'primary'},
            {'paper_id': 'p2', 'verdict': 'context', 'reason': '仅提供邻近背景。',
             'evidence_quote': 'supports the second contribution', 'role': 'background'},
        ]
    })

    result, warnings = asyncio.run(EvidenceVerifier(llm).verify_core(
        'Test field',
        [core_paper(papers[0]), core_paper(papers[1])],
        {paper.id: SentPaper.from_paper(paper) for paper in papers},
        'Keep this scope narrow.',
    ))

    assert len(llm.calls) == 1
    assert [paper['id'] for paper in llm.calls[0]['payload']['papers']] == ['p1', 'p2']
    assert llm.calls[0]['payload']['research_question'] == 'Keep this scope narrow.'
    assert [item.paper.id for item in result] == ['p1']
    assert any('背景' in warning for warning in warnings)


def test_core_title_only_direct_is_a_capped_title_clue_not_confirmed_contribution():
    paper = Paper(id='p1', title='KTaO3 interface superconductivity', abstract=None)
    llm = CoreAuditLLM({
        'audits': [{
            'paper_id': 'p1', 'verdict': 'direct',
            'reason': '题名与当前范围相关。',
            'evidence_quote': 'KTaO3 interface superconductivity', 'role': 'primary',
        }]
    })

    result, warnings = asyncio.run(EvidenceVerifier(llm).verify_core(
        'KTaO3 interface superconductivity',
        [core_paper(paper, score=.95)],
        {'p1': SentPaper.from_paper(paper)},
    ))

    assert len(result) == 1
    assert result[0].score == .65
    assert result[0].evidence_basis == 'title'
    assert result[0].role == 'unknown'
    assert '仅题名线索' in result[0].reason
    assert '确认具体贡献' in result[0].reason
    assert any('题名线索' in warning for warning in warnings)


def test_scoped_insufficient_core_title_clue_is_removed_without_range_evidence():
    paper = Paper(id='p1', title='Mammalian prime editing efficiency', abstract=None)
    llm = CoreAuditLLM({
        'audits': [{
            'paper_id': 'p1',
            'verdict': 'insufficient',
            'reason': '只有题名线索。',
            'evidence_quote': 'Mammalian prime editing efficiency',
            'role': 'unknown',
        }]
    })

    result, warnings = asyncio.run(EvidenceVerifier(llm).verify_core(
        'prime editing efficiency',
        [core_paper(paper, score=.95)],
        {'p1': SentPaper.from_paper(paper)},
        'How do pegRNA and editor design affect precise mammalian genome edits?',
    ))

    assert result == []
    assert any('研究问题范围证据' in warning for warning in warnings)


def test_unscoped_insufficient_core_title_clue_is_removed_from_core_list():
    paper = Paper(id='p1', title='KTaO3 interface superconductivity', abstract=None)
    llm = CoreAuditLLM({
        'audits': [{
            'paper_id': 'p1',
            'verdict': 'insufficient',
            'reason': '只有题名线索。',
            'evidence_quote': 'KTaO3 interface superconductivity',
            'role': 'unknown',
        }]
    })

    result, warnings = asyncio.run(EvidenceVerifier(llm).verify_core(
        'KTaO3 interface superconductivity',
        [core_paper(paper, score=.95)],
        {'p1': SentPaper.from_paper(paper)},
    ))

    assert result == []
    assert any('题录元数据不足' in warning for warning in warnings)


def test_field_decomposer_core_wrapper_sends_only_bounded_verified_contribution_excerpt():
    paper = Paper(id='p1', title='A direct contribution', abstract='A useful abstract. ' * 400)
    llm = CoreAuditLLM({
        'audits': [{
            'paper_id': 'p1', 'verdict': 'direct',
            'reason': '摘要支持该贡献。',
            'evidence_quote': 'A useful abstract', 'role': 'primary',
        }]
    })

    result, _ = asyncio.run(FieldDecomposer(llm).audit_core_papers(
        'Test field', [core_paper(paper)], [paper],
        research_question='A narrow question.',
    ))

    assert len(result) == 1
    assert len(llm.calls) == 1
    assert llm.calls[0]['payload']['papers'][0]['abstract'] == paper.abstract[:300].strip()
    assert result[0].evidence_quote == paper.abstract[:300].strip()
    assert llm.calls[0]['payload']['research_question'] == 'A narrow question.'


def test_core_audit_cannot_borrow_unquoted_abstract_facts_or_current_reason():
    initial = 'We measure editing efficiency in mammalian cells.'
    omitted = 'The improved editor corrects pathogenic mutations in mice.'
    paper = Paper(id='p1', title='Improved editing', abstract=f'{initial} {omitted}')
    llm = CoreAuditLLM({'audits': [{
        'paper_id': 'p1', 'verdict': 'direct', 'role': 'primary',
        'reason': '在小鼠中纠正致病突变。', 'evidence_quote': omitted,
    }]})
    result, warnings = asyncio.run(EvidenceVerifier(llm).verify_core(
        'Prime editing', [core_paper(paper, quote=initial, reason='AAV corrects mouse mutations.')],
        {'p1': SentPaper.from_paper(paper)},
    ))
    payload = llm.calls[0]['payload']
    assert payload['papers'][0]['abstract'] == initial
    assert 'reason' not in payload['cores'][0]['recommendation']
    assert result == []
    assert any('超出实际审查证据' in warning for warning in warnings)


def test_core_audit_retains_full_audited_excerpt_when_provider_shortens_quote():
    excerpt = 'We measure editing efficiency in mammalian cells and show reduced byproducts.'
    paper = Paper(id='p1', title='Improved editing', abstract=excerpt)
    llm = CoreAuditLLM({'audits': [{
        'paper_id': 'p1', 'verdict': 'direct', 'role': 'primary',
        'reason': '测量哺乳动物细胞中的编辑效率并减少副产物。',
        'evidence_quote': 'We measure editing efficiency in mammalian cells',
    }]})
    result, _ = asyncio.run(EvidenceVerifier(llm).verify_core(
        'Prime editing', [core_paper(paper)], {'p1': SentPaper.from_paper(paper)},
    ))
    assert len(result) == 1
    assert result[0].evidence_quote == excerpt


def test_core_invalid_initial_excerpt_cannot_unlock_full_abstract():
    excerpt = 'We measure editing efficiency in mammalian cells.'
    paper = Paper(id='p1', title='Improved editing', abstract=excerpt)
    llm = CoreAuditLLM({'audits': [{
        'paper_id': 'p1', 'verdict': 'direct', 'role': 'primary',
        'reason': '测量哺乳动物细胞中的编辑效率。', 'evidence_quote': excerpt,
    }]})
    result, warnings = asyncio.run(EvidenceVerifier(llm).verify_core(
        'Prime editing', [core_paper(paper, quote='This nonexistent excerpt cannot enter the audit.')],
        {'p1': SentPaper.from_paper(paper)},
    ))
    assert llm.calls[0]['payload']['papers'][0]['abstract'] is None
    assert llm.calls[0]['payload']['cores'][0]['recommendation']['evidence_quote'] == ''
    assert result == []
    assert any('超出实际审查证据' in warning for warning in warnings)


def test_explicit_theory_qualification_applies_to_a_causal_direction_name():
    from app.services.evidence_verifier import theoretical_claim

    assert theoretical_claim('Pairing symmetry and gap structure',
                             '摘要覆盖该研究方向。仍属于 theoretical prediction。', [])
    assert theoretical_claim('Origin of superconductivity',
                             '需继续实验区分。该解释是一个 hypothesis。', [])
    assert not theoretical_claim('Machine learning prediction of editing efficiency',
                                 '模型预测效率。', ['A predictive design tool.'])
