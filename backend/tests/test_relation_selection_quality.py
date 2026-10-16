import asyncio

from app.models.schemas import Paper
from app.services.field_decomposer import FieldDecomposer


def _source_scope_response(kwargs):
    if 'source-scope classifier' not in kwargs.get('system', ''):
        return None
    return {'papers': [
        {'paper_id': paper['id'], 'scope_relation': 'direct',
         'reason': 'The paper matches the requested study object.'}
        for paper in kwargs['payload']['papers']
    ]}


def _audit_selected(llm):
    """Return a bounded supported audit for exactly the relations selected."""
    relations = llm.audit_payload['relations']
    names = getattr(llm, 'audit_names', {})
    return {
        'audits': [
            {
                'relation_id': item['relation_id'],
                'verdict': 'supported',
                'reason': '核对摘录支持该研究方向。',
                'corrected_name': names.get(
                    item['relation_id'], f"Audited relation {item['relation_id']}"
                ),
                'supported_quote_ids': [
                    item['evidence_quotes'][0]['quote_id']
                ] if item['evidence_quotes'] else [],
                'scope_relation': 'direct',
            }
            for item in relations
        ]
    }


def test_exact_abstract_evidence_survives_high_confidence_title_overflow():
    papers = [
        Paper(id=f'W{i}', title=f'Title clue paper {i}')
        for i in range(1, 9)
    ]
    papers.append(Paper(
        id='W9',
        title='Abstract evidence paper',
        abstract='This paper directly measures the abstract-backed direction.',
    ))

    def relation(name, alias, confidence, quote, source):
        return {
            'name': name,
            'reason': 'The supplied metadata describes this direction.',
            'confidence': confidence,
            'evidence_paper_ids': [alias],
            'evidence_quotes': [{'paper_id': alias, 'source': source, 'quote': quote}],
        }

    title_relations = [
        relation(
            f'Title branch {i}', f'p{i}', .99 - i * .01,
            f'Title clue paper {i}', 'title',
        )
        for i in range(1, 9)
    ]
    title_relations.append(relation(
        'Abstract-backed branch', 'p9', .10,
        'This paper directly measures the abstract-backed direction.', 'abstract',
    ))

    class LLM:
        audit_payload = None

        async def generate_structured(self, **kwargs):
            scoped = _source_scope_response(kwargs)
            if scoped is not None:
                return scoped
            if set(kwargs['schema']['properties']) == {'summary'}:
                return {'summary': 'A bounded map'}
            if 'audits' in kwargs['schema']['properties']:
                self.audit_payload = kwargs['payload']
                return _audit_selected(self)
            return {
                'summary': 'A bounded map',
                'prerequisites': [],
                'subfields': title_relations,
            }

    llm = LLM()
    result = asyncio.run(FieldDecomposer(llm).decompose_map('Research field', papers))

    assert len(result.subfields) == 7
    evidence_ids = {
        paper_id for item in result.subfields
        for paper_id in item.evidence_paper_ids
    }
    assert 'W9' in evidence_ids
    assert 'W8' not in evidence_ids
    assert result.evidence_audit_complete


def test_fabricated_abstract_excerpt_does_not_beat_real_title_evidence():
    papers = [
        Paper(id=f'W{i}', title=f'Real title branch paper {i}')
        for i in range(1, 8)
    ]
    papers.append(Paper(
        id='W8',
        title='Fabricated clue paper',
        abstract='The actual abstract contains a different statement.',
    ))

    def title_relation(i):
        return {
            'name': f'Real title branch {i}',
            'reason': 'The title provides a bounded clue.',
            'confidence': .50,
            'evidence_paper_ids': [f'p{i}'],
            'evidence_quotes': [{
                'paper_id': f'p{i}', 'source': 'title',
                'quote': f'Real title branch paper {i}',
            }],
        }

    fabricated = {
        'name': 'Fabricated abstract branch',
        'reason': 'The fabricated excerpt appears to support this direction.',
        'confidence': .99,
        'evidence_paper_ids': ['p8'],
        'evidence_quotes': [{
            'paper_id': 'p8', 'source': 'abstract',
            'quote': 'This fabricated abstract excerpt is absent.',
        }],
    }

    class LLM:
        audit_payload = None

        async def generate_structured(self, **kwargs):
            scoped = _source_scope_response(kwargs)
            if scoped is not None:
                return scoped
            if set(kwargs['schema']['properties']) == {'summary'}:
                return {'summary': 'A bounded map'}
            if 'audits' in kwargs['schema']['properties']:
                self.audit_payload = kwargs['payload']
                return _audit_selected(self)
            return {
                'summary': 'A bounded map',
                'prerequisites': [],
                'subfields': [*map(title_relation, range(1, 8)), fabricated],
            }

    llm = LLM()
    result = asyncio.run(FieldDecomposer(llm).decompose_map('Research field', papers))

    assert len(result.subfields) == 7
    evidence_ids = {
        paper_id for item in result.subfields
        for paper_id in item.evidence_paper_ids
    }
    assert evidence_ids == {f'W{i}' for i in range(1, 8)}
    assert result.evidence_audit_complete


def test_cross_bucket_duplicate_keeps_one_best_relation_without_merging_claims():
    papers = [
        Paper(id='W1', title='Shared branch title clue'),
        Paper(
            id='W2',
            title='Shared branch abstract paper',
            abstract='This abstract directly supports the shared branch direction.',
        ),
    ]

    class LLM:
        audit_payload = None
        audit_names = {'r1': 'Shared branch', 'r2': 'Shared branch'}

        async def generate_structured(self, **kwargs):
            scoped = _source_scope_response(kwargs)
            if scoped is not None:
                return scoped
            if set(kwargs['schema']['properties']) == {'summary'}:
                return {'summary': 'A duplicate map'}
            if 'audits' in kwargs['schema']['properties']:
                self.audit_payload = kwargs['payload']
                return _audit_selected(self)
            return {
                'summary': 'A duplicate map',
                'prerequisites': [{
                    'name': 'Shared branch',
                    'reason': 'Title-only claim that should be discarded.',
                    'confidence': .95,
                    'evidence_paper_ids': ['p1'],
                    'evidence_quotes': [{
                        'paper_id': 'p1', 'source': 'title',
                        'quote': 'Shared branch title clue',
                    }],
                }],
                'subfields': [{
                    'name': 'Shared branch',
                    'reason': 'Abstract-backed claim that should survive.',
                    'confidence': .20,
                    'evidence_paper_ids': ['p2'],
                    'evidence_quotes': [{
                        'paper_id': 'p2', 'source': 'abstract',
                        'quote': 'This abstract directly supports the shared branch direction.',
                    }],
                }],
            }

    llm = LLM()
    result = asyncio.run(FieldDecomposer(llm).decompose_map('Research field', papers))

    assert not result.prerequisites
    assert len(result.subfields) == 1
    assert result.subfields[0].name == 'Shared branch'
    assert result.subfields[0].evidence_paper_ids == ['W2']
    assert [quote.paper_id for quote in result.subfields[0].evidence_quotes] == ['W2']
    relation_payload = llm.audit_payload['relations'][0]
    assert set(relation_payload) == {
        'relation_id', 'kind', 'evidence_paper_ids', 'evidence_quotes',
    }
    assert 'name' not in relation_payload
    assert 'reason' not in relation_payload
    assert relation_payload['evidence_paper_ids'] == ['W2']
    assert relation_payload['evidence_quotes'] == [{
        'quote_id': 'r1:q1',
        'paper_id': 'W2',
        'source': 'abstract',
        'quote': 'This abstract directly supports the shared branch direction.',
    }]
    assert result.evidence_audit_complete


def test_relation_audit_captions_from_quotes_without_prior_name_anchoring():
    quote = 'Waveform residuals remain after subtraction of the universal relation.'
    paper = Paper(
        id='W1',
        title='Prior Dependence Study',
        abstract=quote,
    )

    class LLM:
        audit_payload = None

        async def generate_structured(self, **kwargs):
            scoped = _source_scope_response(kwargs)
            if scoped is not None:
                return scoped
            properties = set(kwargs['schema']['properties'])
            if properties == {'summary'}:
                return {'summary': 'The audited map is limited to waveform residuals.'}
            if 'audits' in properties:
                self.audit_payload = kwargs['payload']
                return {'audits': [{
                    'relation_id': 'r1',
                    'verdict': 'supported',
                    'corrected_name': 'Waveform residuals after universal relation subtraction',
                    'reason': 'The quoted abstract reports waveform residuals after subtracting a universal relation.',
                    'supported_quote_ids': ['r1:q1'],
                    'scope_relation': 'direct',
                }]}
            return {
                'summary': 'Prior Dependence',
                'prerequisites': [],
                'subfields': [{
                    'name': 'Prior Dependence',
                    'reason': 'A prior-dependent branch that should not anchor the audit.',
                    'confidence': .8,
                    'evidence_paper_ids': ['p1'],
                    'evidence_quotes': [{
                        'paper_id': 'p1', 'source': 'abstract', 'quote': quote,
                    }],
                }],
            }

    llm = LLM()
    result = asyncio.run(FieldDecomposer(llm).decompose_map(
        'Transport',
        [paper],
        research_question='How do waveform residuals relate to universal relations?',
        evidence_needs=[{
            'id': 'need-1',
            'label': 'Posterior uncertainty',
            'focused_query': 'posterior uncertainty waveform residuals',
        }],
    ))

    relation_payload = llm.audit_payload['relations'][0]
    assert set(relation_payload) == {
        'relation_id', 'kind', 'evidence_paper_ids', 'evidence_quotes',
    }
    assert 'name' not in relation_payload
    assert 'reason' not in relation_payload
    assert relation_payload['evidence_quotes'] == [{
        'quote_id': 'r1:q1',
        'paper_id': 'W1', 'source': 'abstract', 'quote': quote,
    }]
    assert llm.audit_payload['field'] == 'Transport'
    assert llm.audit_payload['research_question'].startswith('How do waveform')
    assert llm.audit_payload['evidence_needs'][0]['label'] == 'Posterior uncertainty'
    assert llm.audit_payload['papers'] == [{
        'id': 'W1', 'title': 'Prior Dependence Study', 'abstract': None,
        'scope_context': quote,
    }]
    assert result.subfields[0].name == 'Waveform residuals after universal relation subtraction'
    assert result.subfields[0].evidence_status == 'supported'
