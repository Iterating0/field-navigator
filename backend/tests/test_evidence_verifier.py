import asyncio
import json

import pytest

import app.services.evidence_verifier as evidence_verifier_module
from app.models.schemas import CorePaper, EvidenceQuote, FieldRelation, Paper, PaperJudgment
from app.providers.base import ProviderError
from app.services.evidence_verifier import (
    AuditWireBatch,
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


def source_scope_response(kwargs, relation='direct'):
    """Return a complete paper-level scope response for map-test stubs."""
    if 'source-scope classifier' not in kwargs.get('system', ''):
        return None
    return {'papers': [
        {'paper_id': paper['id'], 'scope_relation': relation,
         'reason': 'The paper matches the requested study object.'}
        for paper in kwargs['payload']['papers']
    ]}


class AuditLLM:
    def __init__(self, result=None, error=None):
        self.result = result or {
            'audits': [{
                'relation_id': 'r1',
                'verdict': 'supported',
                'reason': '摘要直接支持该研究方向。',
                'corrected_name': 'A branch',
                'supported_quote_ids': ['r1:q1'],
                'scope_relation': 'direct',
            }]
        }
        self.error = error
        self.calls = []

    async def generate_structured(self, **kwargs):
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        scoped = source_scope_response(kwargs)
        if scoped is not None:
            return scoped
        return self.result


@pytest.mark.parametrize('missing', ['corrected_name', 'supported_quote_ids', 'scope_relation'])
def test_map_audit_requires_complete_wire_contract(missing):
    quote = 'The paper measures quantum transport in the target interface.'
    response = {'audits': [{
        'relation_id': 'r1',
        'verdict': 'supported',
        'reason': 'The quoted abstract supports the direction.',
        'corrected_name': 'Measured target transport',
        'supported_quote_ids': ['r1:q1'],
        'scope_relation': 'direct',
    }]}
    response['audits'][0].pop(missing)
    _, branches, warnings, complete = asyncio.run(EvidenceVerifier(
        AuditLLM(response),
    ).verify_map(
        'Target interface transport',
        [],
        [relation(name='Target transport', quote=quote)],
        {'p1': SentPaper('p1', 'Target transport measurement', quote)},
    ))

    assert not complete
    assert branches and branches[0].evidence_status == 'weak'
    assert any('独立证据审查未完成' in warning for warning in warnings)


def test_map_audit_wire_schema_requires_downstream_fields():
    required = set(
        AuditWireBatch.model_json_schema()['$defs']['AuditWireItem']['required']
    )
    assert required == {
        'relation_id', 'verdict', 'reason', 'corrected_name',
        'supported_quote_ids', 'scope_relation',
    }


def test_abstract_quote_requires_one_independent_batch_and_is_supported():
    paper = SentPaper('p1', 'Quantum transport branch', 'The paper measures quantum transport in a two-dimensional interface.')
    llm = AuditLLM({'audits': [{
        'relation_id': 'r1', 'verdict': 'supported',
        'reason': '摘要直接支持该研究方向。',
        'corrected_name': 'A branch',
        'supported_quote_ids': ['r1:q1'], 'scope_relation': 'direct',
    }]})
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
    assert len(llm.calls) == 2
    audit_call = llm.calls[-1]
    assert list(audit_call['payload']['papers']) == [{
        'id': 'p1', 'title': paper.title, 'abstract': None, 'scope_context': paper.abstract,
    }]


def test_relation_without_abstract_evidence_is_always_a_title_only_clue():
    paper = SentPaper('p1', 'Guide RNA pairing strategies', 'A description that was not quoted.')
    llm = AuditLLM({'audits': [{
        'relation_id': 'r1', 'verdict': 'weak', 'reason': '目前只有题名线索。',
        'corrected_name': 'Guide RNA pairing strategies',
        'supported_quote_ids': [], 'scope_relation': 'direct',
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
        'supported_quote_ids': ['r1:q1'], 'scope_relation': 'direct',
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
        'supported_quote_ids': ['r1:q1'], 'scope_relation': 'direct',
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
        {'relation_id': 'r1', 'verdict': 'weak', 'reason': '线索有限。', 'corrected_name': 'Carrier control',
         'supported_quote_ids': ['r1:q1'], 'scope_relation': 'direct'},
        {'relation_id': 'r2', 'verdict': 'supported', 'reason': '摘录支持调控方向。', 'corrected_name': 'carrier control',
         'supported_quote_ids': ['r2:q1'], 'scope_relation': 'direct'},
    ]})
    _, branches, warnings, _ = asyncio.run(EvidenceVerifier(llm).verify_map(
        'Test field', [], [relation(name='Carrier density', quote=excerpt), relation(name='Gate tuning', quote=excerpt)], {'p1': paper},
    ))
    assert len(branches) == 1
    assert branches[0].evidence_status == 'supported'
    assert len(branches[0].evidence_quotes) == 1
    assert any('重复方向' in warning for warning in warnings)


def test_map_audit_separates_relation_quotes_from_scope_only_context(monkeypatch):
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
            scoped = source_scope_response(kwargs)
            if scoped is not None:
                return scoped
            return {'audits': [
                {'relation_id': 'r1', 'verdict': 'supported', 'reason': '核对摘录支持关系A。',
                 'corrected_name': 'Surface defect migration', 'supported_quote_ids': ['r1:q1'],
                 'scope_relation': 'direct'},
                {'relation_id': 'r2', 'verdict': 'supported', 'reason': '核对摘录支持关系B。',
                 'corrected_name': 'Legal RAG faithfulness', 'supported_quote_ids': ['r2:q1'],
                 'scope_relation': 'direct'},
            ]}

    llm = LLM()
    _, branches, warnings, complete = asyncio.run(EvidenceVerifier(llm).verify_map(
        'Research field', [], [relation_a, relation_b], papers,
    ))

    assert complete and len(branches) == 2
    assert any('一条候选摘录未能在所发标题或摘要中核对，已忽略' in warning for warning in warnings)
    assert all(item['abstract'] is None for item in llm.payload['papers'])
    assert [item['scope_context'] for item in llm.payload['papers']] == [
        papers['a'].abstract, papers['b'].abstract,
    ]
    relation_payload = {item['relation_id']: item for item in llm.payload['relations']}
    assert [item['quote'] for item in relation_payload['r1']['evidence_quotes']] == [quote_a1, quote_a2]
    assert [item['quote'] for item in relation_payload['r2']['evidence_quotes']] == [quote_b]
    assert invalid not in str(llm.payload)
    assert quote_b not in [item['quote'] for item in relation_payload['r1']['evidence_quotes']]


def test_map_scope_context_can_veto_an_adjacent_system_without_becoming_evidence():
    quote = 'We find large systematic errors in tidal inference.'
    context = ('We study neutron-star black-hole binaries. ' + quote)
    paper = SentPaper('p1', 'Waveform errors in neutron-star black-hole binaries', context)

    class ScopeGuardLLM(AuditLLM):
        async def generate_structured(self, **kwargs):
            self.calls.append(kwargs)
            scoped = source_scope_response(kwargs)
            if scoped is not None:
                return scoped
            assert kwargs['payload']['papers'][0]['scope_context'] == context
            assert kwargs['payload']['relations'][0]['evidence_quotes'][0]['quote'] == quote
            return {'audits': [{
                'relation_id': 'r1', 'verdict': 'weak',
                'reason': 'Adjacent binary composition, not evidence for the requested system.',
                'corrected_name': 'Adjacent-system waveform uncertainty',
                'supported_quote_ids': [], 'scope_relation': 'context',
            }]}

    llm = ScopeGuardLLM()
    _, branches, warnings, complete = asyncio.run(EvidenceVerifier(llm).verify_map(
        'Binary neutron-star tidal inference', [], [relation(quote=quote)], {'p1': paper},
        research_question='Which systematic errors affect binary neutron-star tidal inference?',
    ))
    assert complete and not branches
    assert len(llm.calls) == 2
    assert any('相邻系统背景' in warning for warning in warnings)


@pytest.mark.parametrize('selected', [[], ['r1:q2']])
def test_map_context_qualifications_cannot_be_promoted_to_display_quotes(selected):
    quote = 'Temperature changes the basic ingredients of tidal deformability.'
    hidden = 'The net tidal deformability remains almost unchanged in the adiabatic model.'
    context = quote + ' ' + hidden
    paper = SentPaper('p1', 'Model-dependent thermal response', context)
    llm = AuditLLM({'audits': [{
        'relation_id': 'r1', 'verdict': 'supported' if selected else 'weak',
        'reason': 'The excerpt alone does not establish the net observable response.',
        'corrected_name': 'Model-dependent thermal response',
        'supported_quote_ids': selected, 'scope_relation': 'direct',
    }]})
    _, branches, _, complete = asyncio.run(EvidenceVerifier(llm).verify_map(
        'Neutron-star tidal inference', [], [relation(quote=quote)], {'p1': paper},
    ))
    assert complete and branches[0].evidence_status != 'supported'
    assert not branches[0].evidence_quotes
    assert hidden not in branches[0].model_dump_json()
    audit_call = llm.calls[-1]
    assert audit_call['payload']['papers'][0]['scope_context'] == context
    assert len(audit_call['payload']['relations'][0]['evidence_quotes']) == 1


def test_map_audit_filters_relation_quotes_by_returned_quote_id(monkeypatch):
    monkeypatch.setattr(evidence_verifier_module, 'scope_mismatch', lambda *args: None)
    direct_quote = 'We model EOS parametrization for binary neutron-star tidal inference.'
    context_quote = 'NICER measures neutron-star radii with a four percent uncertainty.'
    paper = SentPaper(
        'p1', 'EOS parametrization for binary neutron-star inference',
        direct_quote,
    )
    context_paper = SentPaper(
        'p2', 'Neutron-star radius observations', context_quote,
    )
    branch = FieldRelation(
        name='EOS parametrization and priors',
        reason='The recommendation combines direct and contextual excerpts.',
        confidence=.9,
        evidence_paper_ids=['p1', 'p2'],
        evidence_quotes=[
            EvidenceQuote(paper_id='p1', source='abstract', quote=direct_quote),
            EvidenceQuote(paper_id='p2', source='abstract', quote=context_quote),
        ],
    )

    class QuoteSelectingLLM:
        def __init__(self):
            self.calls = []

        async def generate_structured(self, **kwargs):
            self.calls.append(kwargs)
            scoped = source_scope_response(kwargs)
            if scoped is not None:
                return scoped
            return {'audits': [{
                'relation_id': 'r1',
                'verdict': 'supported',
                'reason': 'The EOS parametrization excerpt supports this direction.',
                'supported_quote_ids': ['r1:q1'],
                'corrected_name': 'EOS parametrization',
                'scope_relation': 'direct',
            }]}

    llm = QuoteSelectingLLM()
    _, branches, _, complete = asyncio.run(EvidenceVerifier(llm).verify_map(
        'Gravitational-wave neutron-star inference', [], [branch], {'p1': paper, 'p2': context_paper},
    ))

    assert complete and len(branches) == 1
    assert branches[0].evidence_status == 'supported'
    assert branches[0].evidence_paper_ids == ['p1']
    assert [quote.quote for quote in branches[0].evidence_quotes] == [direct_quote]
    payload_quotes = llm.calls[-1]['payload']['relations'][0]['evidence_quotes']
    assert [item['quote_id'] for item in payload_quotes] == ['r1:q1', 'r1:q2']
    assert [item['quote'] for item in payload_quotes] == [direct_quote, context_quote]


def test_map_audit_invalid_quote_selection_is_conservative(monkeypatch):
    monkeypatch.setattr(evidence_verifier_module, 'scope_mismatch', lambda *args: None)
    quote = 'We measure tidal deformability in binary neutron-star systems.'
    paper = SentPaper('p1', 'Binary neutron-star tidal inference', quote)
    branch = relation(name='Tidal inference', quote=quote)

    class InvalidQuoteSelectionLLM:
        async def generate_structured(self, **kwargs):
            scoped = source_scope_response(kwargs)
            if scoped is not None:
                return scoped
            return {'audits': [{
                'relation_id': 'r1',
                'verdict': 'supported',
                'reason': 'The excerpt supports this direction.',
                'supported_quote_ids': ['r1:q99'],
                'corrected_name': 'Tidal inference',
                'scope_relation': 'direct',
            }]}

    _, branches, warnings, complete = asyncio.run(EvidenceVerifier(InvalidQuoteSelectionLLM()).verify_map(
        'Gravitational-wave neutron-star inference', [], [branch], {'p1': paper},
    ))

    assert complete and len(branches) == 1
    assert branches[0].evidence_status == 'weak'
    assert branches[0].evidence_paper_ids == []
    assert branches[0].evidence_quotes == []
    assert any('未知摘录 ID' in warning for warning in warnings)


def test_title_only_support_is_weak_even_when_audit_says_supported():
    paper = SentPaper('p1', 'Non-Hermitian skin effect', None)
    llm = AuditLLM()
    _, subfields, warnings, audit_complete = asyncio.run(
        EvidenceVerifier(llm).verify_map(
            'Non-Hermitian physics',
            [],
            [relation(name='Skin effect', quote=paper.title, abstract=False, confidence=.9)],
            {'p1': paper},
            evidence_needs=[{
                'id': 'need-1',
                'label': 'Posterior calibration and coverage',
                'focused_query': 'posterior calibration coverage held-out validation',
            }],
        )
    )

    result = subfields[0]
    assert llm.calls[-1]['payload']['evidence_needs'] == [{
        'id': 'need-1',
        'label': 'Posterior calibration and coverage',
        'focused_query': 'posterior calibration coverage held-out validation',
    }]
    assert result.evidence_status == 'weak'
    assert result.confidence == .55
    assert any('标题线索' in warning for warning in result.evidence_warnings)
    assert any('标题线索' in warning for warning in warnings)


def test_evidence_needs_are_bounded_context_and_do_not_become_relation_evidence():
    quote = 'We validate posterior calibration and coverage on held-out noise levels.'
    paper = SentPaper('p1', 'Posterior calibration study', quote)
    llm = AuditLLM({'audits': [{
        'relation_id': 'r1', 'verdict': 'supported',
        'reason': '摘要直接支持该研究方向。',
        'corrected_name': 'Posterior validation',
        'supported_quote_ids': ['r1:q1'], 'scope_relation': 'direct',
    }]})
    _, subfields, warnings, complete = asyncio.run(EvidenceVerifier(llm).verify_map(
        'Posterior sampling',
        [],
        [relation(name='Posterior validation', quote=quote)],
        {'p1': paper},
        evidence_needs=[
            {
                'id': 'need-1',
                'label': 'Posterior calibration and coverage',
                'focused_query': 'posterior calibration coverage held-out validation',
                'untrusted': 'must be ignored',
            },
            {
                'id': 'need-2',
                'label': 'Limitations',
                'focused_query': 'reported limitations and failure cases',
            },
            {'id': 'need-1', 'label': 'Duplicate', 'focused_query': 'duplicate'},
            {'id': 'not-a-need', 'label': 'Invalid', 'focused_query': 'invalid'},
        ],
    ))

    assert complete and not warnings
    assert subfields[0].evidence_status == 'supported'
    assert llm.calls[-1]['payload']['evidence_needs'] == [
        {
            'id': 'need-1',
            'label': 'Posterior calibration and coverage',
            'focused_query': 'posterior calibration coverage held-out validation',
        },
        {
            'id': 'need-2',
            'label': 'Limitations',
            'focused_query': 'reported limitations and failure cases',
        },
    ]
    assert llm.calls[-1]['payload']['relations'][0]['evidence_quotes'] == [{
        'quote_id': 'r1:q1', 'paper_id': 'p1', 'source': 'abstract', 'quote': quote,
    }]


def test_semantic_unsupported_relation_is_removed_and_invalid_quote_never_supported():
    paper = SentPaper('p1', 'A paper about unrelated optics', 'The abstract reports an unrelated optics experiment.')
    llm = AuditLLM({
        'audits': [{
            'relation_id': 'r1',
            'verdict': 'unsupported',
            'reason': '元数据没有支持该关系。',
            'corrected_name': 'Unrelated optics',
            'supported_quote_ids': [], 'scope_relation': 'off_topic',
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
            scoped = source_scope_response(kwargs)
            if scoped is not None:
                return scoped
            assert kwargs['payload']['relations'][0]['evidence_paper_ids'] == ['good']
            return {'audits': [{
                'relation_id': 'r1',
                'verdict': 'supported',
                'reason': '摘要支持范围内方向。',
                'corrected_name': 'Target branch',
                'supported_quote_ids': ['r1:q1'], 'scope_relation': 'direct',
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
            scoped = source_scope_response(kwargs)
            if scoped is not None:
                return scoped
            return {'audits': [{
                'relation_id': 'r1',
                'verdict': 'supported',
                'reason': '该结果证明模型具有一般可靠性。',
                'corrected_name': 'RAG benchmark performance',
                'supported_quote_ids': ['r1:q1'], 'scope_relation': 'direct',
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
            scoped = source_scope_response(kwargs)
            if scoped is not None:
                return scoped
            return {'audits': [{
                'relation_id': 'r1',
                'verdict': 'supported',
                'reason': '法律RAG工具评估涉及评价者可靠性。',
                'corrected_name': 'Legal RAG evaluation',
                'supported_quote_ids': ['r1:q1'], 'scope_relation': 'direct',
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
            scoped = source_scope_response(kwargs)
            if scoped is not None:
                return scoped
            return {'audits': [{
                'relation_id': 'r1',
                'verdict': 'supported',
                'reason': self.reason,
                'corrected_name': 'Legal RAG evaluation',
                'supported_quote_ids': ['r1:q1'], 'scope_relation': 'direct',
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


@pytest.mark.parametrize('reason,language', [
    ('通过将argyrodite Li6PS5Cl致密化至99%，可实现9 mA cm−2且无枝晶。', 'zh-CN'),
    ('Densifying argyrodite Li6PS5Cl to 99% enables 9 mA cm−2 without dendrites.', 'en'),
])
def test_quantitative_guard_preserves_a_quoted_preparation_condition(reason, language):
    quote = ('we show that plating currents of 9 mA cm −2 can be achieved without dendrite '
             'formation, by densifying argyrodite, Li 6 PS 5 Cl, to 99%.')
    result, changed = evidence_verifier_module._qualitative_core_reason_without_unscoped_amplitude(
        reason, quote, language=language, limit=220,
    )
    assert not changed and '99%' in result and '9 mA' in result


def test_map_scope_context_cannot_supply_an_unquoted_decimal_condition():
    quote = 'Neglected couplings may bias parameter estimation by future detectors.'
    context = quote + ' The analysis assumes a spin of 0.1.'
    llm = AuditLLM({'audits': [{
        'relation_id': 'r1', 'verdict': 'supported',
        'reason': '对自旋约0.1的系统，忽略耦合可能导致参数估计偏差。',
        'corrected_name': 'Coupling assumptions in parameter inference',
        'supported_quote_ids': ['r1:q1'], 'scope_relation': 'direct',
    }]})
    _, branches, _, complete = asyncio.run(EvidenceVerifier(llm).verify_map(
        'Parameter inference', [], [relation(quote=quote)],
        {'p1': SentPaper('p1', 'Parameter inference assumptions', context)},
    ))
    assert complete and branches[0].evidence_status == 'supported'
    assert '0.1' not in branches[0].reason
    assert branches[0].evidence_quotes[0].quote == quote
    assert llm.calls[-1]['payload']['papers'][0]['scope_context'] == context


def test_quoted_decimal_condition_is_not_removed():
    reason = '在自旋约0.1的设置下报告该效应。'
    result, changed = evidence_verifier_module._guard_unquoted_map_decimals(
        reason, ['We assume a spin of 0.1.'], language='zh-CN',
    )
    assert not changed and result == reason


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
            if 'final evidence-boundary editor for a research-field navigator summary' in kwargs['system']:
                return {'summary': '核对摘录支持界面中的输运研究方向。'}
            scoped = source_scope_response(kwargs)
            if scoped is not None:
                return scoped
            if 'independent evidence auditor' in kwargs['system']:
                return {'audits': [{
                    'relation_id': 'r1',
                    'verdict': 'supported',
                    'reason': '摘要直接支持该具体研究方向。',
                    'corrected_name': 'Transport branch',
                    'supported_quote_ids': ['r1:q1'], 'scope_relation': 'direct',
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

    assert len(llm.calls) == 4
    assert result.subfields[0].evidence_status == 'supported'
    assert result.subfields[0].evidence_paper_ids == ['W1']
    assert result.subfields[0].evidence_quotes[0].paper_id == 'W1'
    assert result.summary == '核对摘录支持界面中的输运研究方向。'
    assert llm.calls[0]['payload']['research_question'] == 'Keep this to one-dimensional transport interfaces.'
    assert llm.calls[0]['payload']['papers'][0]['work_type'] is None
    assert llm.calls[2]['payload']['papers'][0]['id'] == 'W1'
    assert llm.calls[2]['payload']['relations'][0]['evidence_paper_ids'] == ['W1']
    assert llm.calls[2]['payload']['research_question'] == 'Keep this to one-dimensional transport interfaces.'
    assert set(llm.calls[3]['payload']) == {'audited_relations'}
    assert llm.calls[3]['payload']['audited_relations'][0]['name'] == 'Transport branch'
    assert llm.calls[3]['payload']['audited_relations'][0]['status'] == 'supported'


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


def test_summary_review_is_quote_bounded_and_payload_isolated():
    mixed_quote = (
        'We observe mixed effects under the stated noise model; conclusions are conditional on that model.'
    )
    title_quote = 'Posterior calibration coverage'
    supported = FieldRelation(
        name='Conditional inverse reconstruction',
        reason='摘要支持混合效应，并给出受噪声模型条件约束的结论。',
        confidence=.9,
        evidence_paper_ids=['p1'],
        evidence_status='supported',
        claim_level='research_direction',
        evidence_quotes=[EvidenceQuote(paper_id='p1', source='abstract', quote=mixed_quote)],
    )
    weak = FieldRelation(
        name='Posterior calibration coverage',
        reason='题名提示相关方向，但没有摘要验证；不能据此声称校准覆盖。',
        confidence=.4,
        evidence_paper_ids=['p2'],
        evidence_status='weak',
        claim_level='title_only',
        evidence_quotes=[EvidenceQuote(paper_id='p2', source='title', quote=title_quote)],
    )
    llm = SummaryReviewLLM({
        'summary': (
            'The study reports mixed effects under a stated noise model; conclusions remain conditional on that '
            'model.'
        )
    })

    result = asyncio.run(EvidenceVerifier(llm).verify_summary(
        'NICER measurements show a roughly twofold result and unconditional performance decline.',
        [supported],
        [weak],
        language='en',
    ))

    assert result == (
        'The study reports mixed effects under a stated noise model; conclusions remain conditional on that '
        'model.'
    )
    assert len(llm.calls) == 1
    payload = llm.calls[0]['payload']
    assert set(payload) == {'audited_relations'}
    assert 'current_summary' not in payload
    assert payload['audited_relations'] == [
        {
            'name': 'Conditional inverse reconstruction',
            'status': 'supported',
            'claim_level': 'research_direction',
            'reason': '摘要支持混合效应，并给出受噪声模型条件约束的结论。',
            'evidence_quotes': [{
                'paper_id': 'p1', 'source': 'abstract', 'quote': mixed_quote,
            }],
        },
    ]
    assert 'field' not in payload
    assert 'research_question' not in payload
    assert 'evidence_needs' not in payload
    assert 'abstract' not in payload
    assert 'full_metadata' not in payload


def test_summary_review_hides_non_supported_quotes_and_quantitative_reason():
    supported_quote = 'We observe mixed effects under the stated noise model.'
    adjacent_quote = 'The adjacent system reaches 98% SNR in a different setup.'
    supported = FieldRelation(
        name='Conditional inverse reconstruction',
        reason='The audited result concerns mixed effects.',
        confidence=.9,
        evidence_paper_ids=['p1'],
        evidence_status='supported',
        claim_level='research_direction',
        evidence_quotes=[EvidenceQuote(paper_id='p1', source='abstract', quote=supported_quote)],
    )
    weak = FieldRelation(
        name='Adjacent system performance',
        reason='The adjacent system reports 98% SNR, but it is not the target system.',
        confidence=.4,
        evidence_paper_ids=['p2'],
        evidence_status='weak',
        claim_level='title_only',
        evidence_quotes=[EvidenceQuote(paper_id='p2', source='abstract', quote=adjacent_quote)],
    )
    llm = SummaryReviewLLM({'summary': 'The supported direction remains conditional.'})

    asyncio.run(EvidenceVerifier(llm).verify_summary(
        'An unreviewed summary.', [supported], [weak], language='en',
    ))

    payload = llm.calls[0]['payload']
    assert payload['audited_relations'][0]['evidence_quotes'] == [{
        'paper_id': 'p1', 'source': 'abstract', 'quote': supported_quote,
    }]
    assert len(payload['audited_relations']) == 1
    payload_text = json.dumps(payload, ensure_ascii=False)
    assert '98%' not in payload_text
    assert 'SNR' not in payload_text
    assert 'Adjacent system performance' not in payload_text
    assert weak.evidence_quotes[0].quote == adjacent_quote


def test_summary_review_sends_empty_relations_when_none_are_supported():
    adjacent_quote = 'The adjacent setup reports 99% accuracy outside the target system.'
    weak = FieldRelation(
        name='Unconfirmed adjacent branch',
        reason='The adjacent setup reports 99% accuracy.',
        confidence=.3,
        evidence_paper_ids=['p2'],
        evidence_status='weak',
        claim_level='title_only',
        evidence_quotes=[EvidenceQuote(paper_id='p2', source='abstract', quote=adjacent_quote)],
    )
    llm = SummaryReviewLLM({'summary': 'No direct research branch was confirmed in this review.'})

    result = asyncio.run(EvidenceVerifier(llm).verify_summary(
        'The field has no established branches.', [], [weak], language='en',
    ))

    assert result == 'No direct research branch was confirmed in this review.'
    assert llm.calls == []
    assert weak.evidence_quotes[0].quote == adjacent_quote


def test_summary_review_provider_failure_does_not_return_fallback_summary():
    llm = SummaryReviewLLM(error=ProviderError('summary unavailable', 503))

    with pytest.raises(ProviderError, match='摘要证据边界复核未完成') as error:
        asyncio.run(EvidenceVerifier(llm).verify_summary(
            'The current summary.', [supported_summary_relation()], [],
        ))

    assert error.value.status_code == 503
    assert len(llm.calls) == 1


def test_summary_review_accepts_exact_json_object_format_echo():
    reviewed_summary = 'The audited evidence remains bounded.'
    llm = SummaryReviewLLM({
        'summary': reviewed_summary,
        'type': 'json_object',
    })

    result = asyncio.run(EvidenceVerifier(llm).verify_summary(
        'An unreviewed summary with extra claims.', [supported_summary_relation()], [], language='en',
    ))

    assert result == reviewed_summary
    assert len(llm.calls) == 1


def test_summary_review_discards_only_empty_relocated_evidence_without_mutating_raw():
    response = {'summary': 'The supported direction remains conditional.', 'evidence_quotes': []}
    result = asyncio.run(EvidenceVerifier(SummaryReviewLLM(response)).verify_summary(
        'Unreviewed text', [supported_summary_relation()], [], language='en',
    ))
    assert result == response['summary']
    assert response['evidence_quotes'] == []


@pytest.mark.parametrize('extra', [
    {'evidence_quotes': [{'quote': 'New evidence cannot be inserted here.'}]},
    {'unknown_scientific_claims': []},
])
def test_summary_review_still_rejects_nonempty_or_unknown_relocated_evidence(extra):
    with pytest.raises(ProviderError, match='Summary evidence review did not complete'):
        asyncio.run(EvidenceVerifier(SummaryReviewLLM({
            'summary': 'A summary', **extra,
        })).verify_summary('Unreviewed text', [supported_summary_relation()], [], language='en'))


def test_summary_review_accepts_exact_summary_length_format_echo_without_trusting_count():
    reviewed_summary = 'The audited evidence remains bounded.'
    response = {
        'summary': reviewed_summary,
        'summary_length': 0,
    }
    llm = SummaryReviewLLM(response)

    result = asyncio.run(EvidenceVerifier(llm).verify_summary(
        'An unreviewed summary with extra claims.', [supported_summary_relation()], [], language='en',
    ))

    assert result == reviewed_summary
    assert response == {
        'summary': reviewed_summary,
        'summary_length': 0,
    }
    assert len(llm.calls) == 1


@pytest.mark.parametrize('response', [
    {
        'summary': 'The audited evidence remains bounded.',
        'type': 'anything_else',
    },
    {
        'summary': 'The audited evidence remains bounded.',
        'type': 'json_object',
        'papers': ['unsupported science extra'],
    },
    {
        'summary': 'The audited evidence remains bounded.',
        'unsupported_science': 'extra claim',
    },
    {
        'summary': 'The audited evidence remains bounded.',
        'summary_length': True,
    },
    {
        'summary': 'The audited evidence remains bounded.',
        'summary_length': -1,
    },
    {
        'summary': 'The audited evidence remains bounded.',
        'summary_length': 1.5,
    },
    {
        'summary': 'The audited evidence remains bounded.',
        'summary_length': 430,
        'type': 'json_object',
    },
])
def test_summary_review_rejects_non_exact_format_echo_or_science_extra(response):
    llm = SummaryReviewLLM(response)

    with pytest.raises(ProviderError, match='Summary evidence review did not complete') as error:
        asyncio.run(EvidenceVerifier(llm).verify_summary(
            'The current summary.', [supported_summary_relation()], [], language='en',
        ))

    assert error.value.status_code == 502
    assert len(llm.calls) == 1


def test_summary_review_checks_actual_length_after_summary_length_echo():
    llm = SummaryReviewLLM({
        'summary': 'x' * 801,
        'summary_length': 430,
    })

    with pytest.raises(ProviderError, match='Summary evidence review did not complete') as error:
        asyncio.run(EvidenceVerifier(llm).verify_summary(
            'The current summary.', [supported_summary_relation()], [], language='en',
        ))

    assert error.value.status_code == 502
    assert len(llm.calls) == 1


def test_summary_review_preserves_complete_600_char_summary_without_truncation():
    tail = 'The conclusion remains conditional on the stated noise model.'
    reviewed_summary = 'x' * 540 + ' ' + tail
    assert 480 < len(reviewed_summary) <= 800
    llm = SummaryReviewLLM({'summary': reviewed_summary})

    result = asyncio.run(EvidenceVerifier(llm).verify_summary(
        'The current summary.', [supported_summary_relation()], [], language='en',
    ))

    assert result == reviewed_summary
    assert result.endswith(tail)
    assert len(llm.calls) == 1


def test_summary_review_invalid_schema_does_not_return_unreviewed_summary():
    llm = SummaryReviewLLM({'summary': 'x' * 801})

    with pytest.raises(ProviderError, match='Summary evidence review did not complete') as error:
        asyncio.run(EvidenceVerifier(llm).verify_summary(
            'The current summary.', [supported_summary_relation()], [], language='en',
        ))

    assert error.value.status_code == 502
    assert len(llm.calls) == 1



def test_short_single_token_quote_is_not_treated_as_semantic_evidence():
    paper = SentPaper('p1', 'A superconductivity paper', 'The abstract reports strong superconductivity observed at low temperature.')
    assert exact_quote_source('superconductivity', paper) is None
    assert exact_quote_source('strong superconductivity observed', paper) == 'abstract'


def test_supported_theory_direction_is_not_presented_as_an_established_mechanism():
    class LLM:
        async def generate_structured(self, **kwargs):
            scoped = source_scope_response(kwargs)
            if scoped is not None:
                return scoped
            return {'audits': [{'relation_id': 'r1', 'verdict': 'supported',
                               'reason': '论文提出该配对候选机制，支持研究方向。',
                               'corrected_name': 'Phonon pairing mechanisms',
                               'supported_quote_ids': ['r1:q1'], 'scope_relation': 'direct'}]}
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
    def __init__(self, result, reason_result=None):
        self.result = result
        self.reason_result = reason_result
        self.calls = []

    async def generate_structured(self, **kwargs):
        self.calls.append(kwargs)
        if len(self.calls) == 1:
            return self.result
        if self.reason_result is not None:
            return self.reason_result
        return {
            'audits': [
                {'paper_id': item['paper_id'], 'reason': item['reason']}
                for item in self.result.get('audits', [])
                if item.get('verdict') == 'direct'
            ]
        }


class SummaryReviewLLM:
    def __init__(self, result=None, error=None):
        self.result = result
        self.error = error
        self.calls = []

    async def generate_structured(self, **kwargs):
        self.calls.append(kwargs)
        if self.error is not None:
            raise self.error
        return self.result


def supported_summary_relation():
    quote = 'The audited relation reports a bounded research result.'
    return FieldRelation(
        name='Audited research direction',
        reason='The supplied metadata supports this direction.',
        confidence=.9,
        evidence_paper_ids=['summary-p1'],
        evidence_status='supported',
        claim_level='research_direction',
        evidence_quotes=[EvidenceQuote(
            paper_id='summary-p1', source='abstract', quote=quote,
        )],
    )


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

    assert len(llm.calls) == 2
    assert [paper['id'] for paper in llm.calls[0]['payload']['papers']] == ['p1', 'p2']
    assert llm.calls[0]['payload']['research_question'] == 'Keep this scope narrow.'
    assert list(llm.calls[1]['payload']) == ['papers']
    assert llm.calls[1]['payload']['papers'] == [{
        'paper_id': 'p1',
        'scope_title': papers[0].title,
        'evidence_quote': papers[0].abstract,
    }]
    assert [item.paper.id for item in result] == ['p1']
    assert any('背景' in warning for warning in warnings)


def test_core_audit_uses_original_scope_context_without_expanding_display_evidence():
    contribution = 'We introduce DDRM, an efficient, unsupervised posterior sampling method.'
    scope_context = (
        f'{contribution} It solves linear inverse problems with noisy measurements and reports '
        '0.02% error on a held-out reconstruction benchmark.'
    )
    paper = Paper(id='p1', title='DDRM for diffusion inverse problems', abstract=scope_context)
    llm = CoreAuditLLM({
        'audits': [{
            'paper_id': 'p1', 'verdict': 'direct', 'role': 'primary',
            'reason': '该方法直接覆盖含噪线性逆问题的后验采样。0.02% error 仅来自完整摘要上下文。',
            'evidence_quote': contribution,
        }]
    })

    result, warnings = asyncio.run(EvidenceVerifier(llm).verify_core(
        'Diffusion inverse problems',
        [core_paper(paper, quote=contribution)],
        {'p1': SentPaper.from_paper(paper)},
        'How can diffusion models solve noisy linear inverse problems while preserving posterior uncertainty?',
    ))

    payload_paper = llm.calls[0]['payload']['papers'][0]
    assert payload_paper['abstract'] == contribution
    assert payload_paper['scope_context'] == scope_context
    assert len(result) == 1
    assert result[0].evidence_quote == contribution
    assert '0.02%' not in result[0].reason
    assert any('定量值' in warning for warning in warnings)


def test_core_audit_keeps_adjacent_system_as_context_with_scope_context():
    contribution = 'We develop reference mapping for single-cell RNA-seq cell-type annotation.'
    scope_context = f'{contribution} The study uses dissociated cells rather than spatial transcriptomics spots.'
    paper = Paper(id='p1', title='Single-cell reference mapping', abstract=scope_context)
    llm = CoreAuditLLM({'audits': [{
        'paper_id': 'p1', 'verdict': 'context', 'role': 'background',
        'reason': '该方法可作参考方法背景，但未直接验证空间转录组 spot 解卷积。',
        'evidence_quote': contribution,
    }]})

    result, warnings = asyncio.run(EvidenceVerifier(llm).verify_core(
        'Spatial transcriptomics spot deconvolution',
        [core_paper(paper, quote=contribution)],
        {'p1': SentPaper.from_paper(paper)},
        'How should spatial transcriptomics spots be deconvolved while handling platform effects?',
    ))

    assert llm.calls[0]['payload']['papers'][0]['scope_context'] == scope_context
    assert result == []
    assert any('背景' in warning for warning in warnings)


def test_core_scope_context_cannot_supply_an_unquoted_result():
    contribution = 'We introduce an efficient, unsupervised posterior sampling method.'
    scope_context = f'{contribution} It recovers noisy linear inverse problems from corrupted observations.'
    paper = Paper(id='p1', title='Posterior sampling for inverse problems', abstract=scope_context)
    llm = CoreAuditLLM({'audits': [{
        'paper_id': 'p1', 'verdict': 'direct', 'role': 'primary',
        'reason': '该方法恢复含噪线性逆问题。',
        'evidence_quote': 'recovers noisy linear inverse problems from corrupted observations',
    }]})

    result, warnings = asyncio.run(EvidenceVerifier(llm).verify_core(
        'Diffusion inverse problems',
        [core_paper(paper, quote=contribution)],
        {'p1': SentPaper.from_paper(paper)},
        'How can diffusion models solve noisy linear inverse problems?',
    ))

    assert llm.calls[0]['payload']['papers'][0]['abstract'] == contribution
    assert llm.calls[0]['payload']['papers'][0]['scope_context'] == scope_context
    assert result == []
    assert any('超出实际审查证据' in warning for warning in warnings)


def test_core_reason_review_excludes_scope_context_and_narrows_leaked_reason(monkeypatch):
    monkeypatch.setattr(evidence_verifier_module, 'scope_mismatch', lambda *args: None)
    contribution = 'We use GW170817 to study tidal deformability and neutron-star radii.'
    scope_context = (
        f'{contribution} EM_DISTANCE_ONLY_CONTEXT: we combine electromagnetic distance, '
        'a common equation of state, and mass priors.'
    )
    paper = Paper(id='p1', title='Inference from GW170817', abstract=scope_context)
    llm = CoreAuditLLM(
        {'audits': [{
            'paper_id': 'p1', 'verdict': 'direct', 'role': 'primary',
            'reason': '该研究用GW170817研究形变和半径，并涉及EM距离、共同EOS和质量先验。',
            'evidence_quote': contribution,
        }]},
        reason_result={'audits': [{
            'paper_id': 'p1',
            'reason': '该研究利用GW170817约束潮汐形变和中子星半径。',
        }]},
    )

    result, warnings = asyncio.run(EvidenceVerifier(llm).verify_core(
        'Gravitational-wave neutron-star inference',
        [core_paper(paper, quote=contribution)],
        {'p1': SentPaper.from_paper(paper)},
        'How does GW170817 constrain tidal deformability and neutron-star radii?',
        evidence_needs=[{
            'id': 'need-1',
            'label': 'Tidal deformability and radii',
            'focused_query': 'GW170817 tidal deformability neutron-star radii',
        }],
    ))

    assert len(result) == 1
    assert result[0].reason == '该研究利用GW170817约束潮汐形变和中子星半径。'
    assert not warnings
    assert len(llm.calls) == 2
    first_payload = llm.calls[0]['payload']
    assert first_payload['papers'][0]['scope_context'] == scope_context
    assert first_payload['evidence_needs'] == [{
        'id': 'need-1',
        'label': 'Tidal deformability and radii',
        'focused_query': 'GW170817 tidal deformability neutron-star radii',
    }]
    narrow_payload = llm.calls[1]['payload']
    assert list(narrow_payload) == ['papers']
    assert narrow_payload['papers'] == [{
        'paper_id': 'p1',
        'scope_title': paper.title,
        'evidence_quote': contribution,
    }]
    assert 'scope_context' not in narrow_payload
    assert 'evidence_needs' not in narrow_payload
    assert 'field' not in narrow_payload
    assert 'research_question' not in narrow_payload
    assert 'EM_DISTANCE_ONLY_CONTEXT' not in json.dumps(narrow_payload, ensure_ascii=False)


def test_core_reason_review_preserves_distinct_physical_quantity(monkeypatch):
    monkeypatch.setattr(evidence_verifier_module, 'scope_mismatch', lambda *args: None)
    quote = 'Under higher external voltages, the electronic conductivity increases.'
    paper = Paper(id='p1', title='Voltage-dependent conductivity', abstract=quote)
    llm = CoreAuditLLM(
        {'audits': [{
            'paper_id': 'p1', 'verdict': 'direct', 'role': 'primary',
            'reason': '高外压下电子导电率增加。',
            'evidence_quote': quote,
        }]},
        reason_result={'audits': [{
            'paper_id': 'p1',
            'reason': '在较高外加电压下，电子导电率增加。',
        }]},
    )

    result, _ = asyncio.run(EvidenceVerifier(llm).verify_core(
        'Electronic conductivity under applied voltage',
        [core_paper(paper)],
        {'p1': SentPaper.from_paper(paper)},
    ))

    assert result[0].reason == '在较高外加电压下，电子导电率增加。'
    assert llm.calls[1]['payload'] == {
        'papers': [{
            'paper_id': 'p1',
            'scope_title': paper.title,
            'evidence_quote': quote,
        }]
    }


def test_core_reason_review_is_blind_to_old_waveform_claim(monkeypatch):
    monkeypatch.setattr(evidence_verifier_module, 'scope_mismatch', lambda *args: None)
    quote = 'We find tighter constraints on the masses, spins, and tidal parameters.'
    old_reason = '直接对应波形模型差异相关系统误差。'
    paper = Paper(id='p1', title='Tighter parameter constraints', abstract=quote)
    llm = CoreAuditLLM(
        {'audits': [{
            'paper_id': 'p1', 'verdict': 'direct', 'role': 'primary',
            'reason': old_reason,
            'evidence_quote': quote,
        }]},
        reason_result={'audits': [{
            'paper_id': 'p1',
            'reason': '该研究对质量、自旋和潮汐参数给出更紧约束。',
        }]},
    )

    result, _ = asyncio.run(EvidenceVerifier(llm).verify_core(
        'Gravitational-wave parameter inference',
        [core_paper(paper, reason=old_reason)],
        {'p1': SentPaper.from_paper(paper)},
    ))

    assert len(result) == 1
    assert result[0].reason == '该研究对质量、自旋和潮汐参数给出更紧约束。'
    assert len(llm.calls) == 2
    narrow_payload = llm.calls[1]['payload']
    assert narrow_payload == {'papers': [{
        'paper_id': 'p1',
        'scope_title': paper.title,
        'evidence_quote': quote,
    }]}
    assert 'waveform' not in json.dumps(narrow_payload, ensure_ascii=False).lower()
    assert 'systematic' not in json.dumps(narrow_payload, ensure_ascii=False).lower()


def test_core_reason_review_drops_unscoped_spelled_factor_and_only_sees_scope_title(monkeypatch):
    monkeypatch.setattr(evidence_verifier_module, 'scope_mismatch', lambda *args: None)
    quote = (
        'The estimated parameters can differ by more than a factor of two '
        'depending on the employed model.'
    )
    paper = Paper(id='p1', title='Tidal parameter inference', abstract=quote)
    llm = CoreAuditLLM(
        {'audits': [{
            'paper_id': 'p1', 'verdict': 'direct', 'role': 'primary',
            'reason': 'The estimated parameters can differ by more than a factor of two.',
            'evidence_quote': quote,
        }]},
        reason_result={'audits': [{
            'paper_id': 'p1',
            'reason': 'The estimated parameters can differ by more than a factor of two depending on the employed model.',
        }]},
    )

    result, warnings = asyncio.run(EvidenceVerifier(llm).verify_core(
        'Parameter inference',
        [core_paper(paper)],
        {'p1': SentPaper.from_paper(paper)},
    ))

    assert len(result) == 1
    assert 'factor' not in result[0].reason.lower()
    assert 'more than' not in result[0].reason.lower()
    assert 'depending on the employed model' in result[0].reason
    assert any('定量幅度缺少' in warning for warning in warnings)
    assert llm.calls[1]['payload'] == {
        'papers': [{
            'paper_id': 'p1',
            'scope_title': paper.title,
            'evidence_quote': quote,
        }]
    }
    narrow_payload = json.dumps(llm.calls[1]['payload'], ensure_ascii=False)
    assert 'scope_context' not in narrow_payload
    assert 'full abstract' not in narrow_payload.lower()
    assert 'The estimated parameters can differ' not in narrow_payload.split(quote)[0]


@pytest.mark.parametrize('reason_result', [
    {'audits': []},
    {'audits': [{'paper_id': 'p1'}]},
])
def test_core_reason_review_failure_does_not_return_unreviewed_core(reason_result):
    paper = Paper(id='p1', title='Direct contribution', abstract='The abstract supports a direct contribution.')
    llm = CoreAuditLLM({
        'audits': [{
            'paper_id': 'p1', 'verdict': 'direct', 'role': 'primary',
            'reason': '摘要支持该贡献。',
            'evidence_quote': 'supports a direct contribution',
        }]
    }, reason_result=reason_result)

    with pytest.raises(ProviderError, match='理由摘录复核|未覆盖全部候选') as error:
        asyncio.run(EvidenceVerifier(llm).verify_core(
            'Test field',
            [core_paper(paper)],
            {'p1': SentPaper.from_paper(paper)},
        ))

    assert error.value.status_code == 502
    assert len(llm.calls) == 2


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
        evidence_needs=[{
            'id': 'need-1',
            'label': 'Interface superconducting evidence',
            'focused_query': 'measured interface superconductivity evidence',
        }],
    ))

    assert len(result) == 1
    assert len(llm.calls) == 1
    assert llm.calls[0]['payload']['evidence_needs'] == [{
        'id': 'need-1',
        'label': 'Interface superconducting evidence',
        'focused_query': 'measured interface superconductivity evidence',
    }]
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
    assert len(llm.calls) == 2
    assert llm.calls[0]['payload']['papers'][0]['abstract'] == paper.abstract[:300].strip()
    assert result[0].evidence_quote == paper.abstract[:300].strip()
    assert llm.calls[0]['payload']['research_question'] == 'A narrow question.'
    assert list(llm.calls[1]['payload']) == ['papers']
    assert llm.calls[1]['payload']['papers'][0]['scope_title'] == paper.title
    assert llm.calls[1]['payload']['papers'][0]['evidence_quote'] == paper.abstract[:300].strip()


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
        'Prime editing', [core_paper(
            paper,
            role='unknown',
            quote='This nonexistent excerpt cannot enter the audit.',
        )],
        {'p1': SentPaper.from_paper(paper)},
        evidence_needs=[{
            'id': 'need-1',
            'label': 'Editing outcome',
            'focused_query': 'measured editing outcome in mammalian cells',
        }],
    ))
    assert llm.calls[0]['payload']['papers'][0]['abstract'] is None
    assert llm.calls[0]['payload']['evidence_needs'] == [{
        'id': 'need-1',
        'label': 'Editing outcome',
        'focused_query': 'measured editing outcome in mammalian cells',
    }]
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


def test_original_data_benchmark_is_not_forced_into_review_role():
    quote = 'We benchmark existing methods on 50 real-world and simulated datasets.'
    paper = Paper(id='p1', title='A comprehensive method comparison', abstract=quote, work_type='article')
    class LLM:
        async def generate_structured(self, **kwargs):
            if kwargs['schema'].get('title') == 'CoreReasonAuditBatch':
                return {'audits': [{'paper_id': 'p1', 'reason': '比较方法在给定数据集上的表现。'}]}
            return {'audits': [{'paper_id': 'p1', 'verdict': 'direct', 'role': 'review',
                               'reason': '比较方法在给定数据集上的表现。', 'evidence_quote': quote}]}
    verifier = EvidenceVerifier(LLM())
    judgment = PaperJudgment(paper_id='p1', importance=.9, relevance=.9,
                            reason='A benchmark', role='review', evidence_basis='abstract', evidence_quote=quote)
    checked = verifier.validate_judgments([judgment], {'p1': SentPaper.from_paper(paper)})
    assert checked[0].role == 'primary'
    cores, _ = asyncio.run(verifier.verify_core('Method comparison', [CorePaper(
        paper=paper, score=.8, reason='A benchmark', role='review',
        evidence_basis='abstract', evidence_quote=quote)], {'p1': SentPaper.from_paper(paper)}))
    assert len(cores) == 1 and cores[0].role == 'primary'
    assert cores[0].evidence_quote == quote


def test_review_of_benchmarks_does_not_become_original_data_research():
    quote = 'We review existing benchmarks and discuss datasets from the literature.'
    paper = SentPaper('p1', 'A review of benchmarks', quote)
    judgment = PaperJudgment(paper_id='p1', importance=.8, relevance=.8,
                            reason='Review', role='review', evidence_basis='abstract', evidence_quote=quote)
    checked = EvidenceVerifier(AuditLLM()).validate_judgments([judgment], {'p1': paper})
    assert checked[0].role == 'review'
