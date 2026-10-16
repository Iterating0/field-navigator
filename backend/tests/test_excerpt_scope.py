import asyncio

from app.models.schemas import CorePaper, EvidenceQuote, FieldRelation, Paper
from app.services.evidence_verifier import EvidenceVerifier, SentPaper


class Auditor:
    def __init__(self, result=None):
        self.calls = []
        self.result = result or {'audits': [{'relation_id': 'r1', 'verdict': 'supported',
                                           'reason': '摘录直接支持该方向。',
                                           'corrected_name': 'Audited research direction',
                                           'supported_quote_ids': ['r1:q1'],
                                           'scope_relation': 'direct'}]}

    async def generate_structured(self, **kwargs):
        self.calls.append(kwargs)
        if 'source-scope classifier' in kwargs.get('system', ''):
            return {'papers': [
                {'paper_id': paper['id'], 'scope_relation': 'direct',
                 'reason': 'The paper matches the requested study object.'}
                for paper in kwargs['payload']['papers']
            ]}
        return self.result


def relation(quotes, name='Experimental diagnostics'):
    return FieldRelation(name=name, reason='A current direction.', confidence=.9,
                         evidence_paper_ids=list(dict.fromkeys(pid for pid, _ in quotes)),
                         evidence_quotes=[EvidenceQuote(paper_id=pid, source='abstract', quote=text)
                                          for pid, text in quotes])


def test_one_dimensional_background_cannot_make_two_dimensional_excerpt_in_scope():
    excerpt = 'We demonstrate a higher-order skin effect in a two-dimensional acoustic topological insulator.'
    paper = SentPaper('p1', 'Higher-order skin effects',
                      'One-dimensional chains provide background. ' + excerpt)
    auditor = Auditor()
    _, branches, warnings, complete = asyncio.run(EvidenceVerifier(auditor).verify_map(
        'Non-Hermitian skin effect', [], [relation([('p1', excerpt)])], {'p1': paper},
        research_question='Study a one-dimensional nonreciprocal chain.'))
    assert complete and branches == []
    assert auditor.calls == []
    assert any('实际摘录没有范围内摘要证据' in warning for warning in warnings)


def test_mixed_dimensional_excerpts_keep_only_direct_in_scope_evidence():
    inside = 'We demonstrate boundary accumulation in a one-dimensional circuit.'
    outside = 'We demonstrate corner accumulation in a two-dimensional acoustic system.'
    papers = {'good': SentPaper('good', 'Boundary diagnostics', inside),
              'bad': SentPaper('bad', 'Higher-order diagnostics',
                               'One-dimensional chains provide background. ' + outside)}
    auditor = Auditor()
    _, branches, _, _ = asyncio.run(EvidenceVerifier(auditor).verify_map(
        'Non-Hermitian skin effect', [], [relation([('good', inside), ('bad', outside)])], papers,
        research_question='Study a one-dimensional nonreciprocal chain.'))
    assert branches[0].evidence_status == 'supported'
    assert branches[0].evidence_paper_ids == ['good']
    assert [quote.paper_id for quote in branches[0].evidence_quotes] == ['good']
    assert [paper['id'] for paper in auditor.calls[0]['payload']['papers']] == ['good']


def test_mammalian_background_cannot_make_zebrafish_excerpt_in_scope():
    excerpt = 'We deliver prime-editor RNPs by microinjection into zebrafish embryos.'
    paper = SentPaper('p1', 'Prime-editor delivery formats',
                      'Mammalian cells motivate delivery development. ' + excerpt)
    auditor = Auditor()
    _, branches, warnings, complete = asyncio.run(EvidenceVerifier(auditor).verify_map(
        'Prime editing', [], [relation([('p1', excerpt)], name='Delivery and expression formats')],
        {'p1': paper}, research_question='Improve editing efficiency in mammalian cells.'))
    assert complete and branches == []
    assert auditor.calls == []
    assert any('物种范围冲突' in warning for warning in warnings)


def test_explicit_cross_dimensional_and_cross_species_questions_keep_comparative_evidence():
    cases = [
        ('Non-Hermitian skin effect', 'Compare one-dimensional and two-dimensional realizations.',
         'We demonstrate boundary accumulation in a two-dimensional acoustic system.'),
        ('Prime editing', 'Compare mammalian cells with zebrafish embryo delivery.',
         'We deliver prime-editor RNPs by microinjection into zebrafish embryos.'),
    ]
    for field, question, excerpt in cases:
        auditor = Auditor()
        _, branches, _, _ = asyncio.run(EvidenceVerifier(auditor).verify_map(
            field, [], [relation([('p1', excerpt)])], {'p1': SentPaper('p1', 'Comparative diagnostics', excerpt)},
            research_question=question))
        assert len(branches) == 1
        assert len(auditor.calls) == 2


def test_core_own_excerpt_scope_overrides_other_background_in_the_same_abstract():
    excerpt = 'We demonstrate higher-order boundary accumulation in a two-dimensional acoustic system.'
    paper = Paper(id='p1', title='Higher-order boundary diagnostics',
                  abstract='One-dimensional chains provide background. ' + excerpt)
    auditor = Auditor({'audits': [{'paper_id': 'p1', 'verdict': 'direct', 'role': 'primary',
                                  'reason': '摘录支持实验结果。', 'evidence_quote': excerpt}]})
    cores, warnings = asyncio.run(EvidenceVerifier(auditor).verify_core(
        'Non-Hermitian skin effect', [CorePaper(paper=paper, score=.9, reason='Old contribution',
                                              evidence_quote=excerpt, evidence_basis='abstract')],
        {'p1': SentPaper.from_paper(paper)}, 'Study a one-dimensional nonreciprocal chain.'))
    assert cores == []
    assert any('维度范围冲突' in warning for warning in warnings)
