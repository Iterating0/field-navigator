import asyncio
from copy import deepcopy

import pytest

from app.models.schemas import Paper
from app.providers.base import ProviderError
from app.services.field_decomposer import FieldDecomposer


ABSTRACT = 'This study measures the requested spatial response.'
PAPER = Paper(id='W1', title='Spatial response study', abstract=ABSTRACT)


class RawLLM:
    def __init__(self, raw):
        self.raw = raw
        self.last_kwargs = None

    async def generate_structured(self, **kwargs):
        self.last_kwargs = kwargs
        return self.raw


def judgment(**extra):
    value = {
        'paper_id': 'p1',
        'importance': .8,
        'relevance': .9,
        'reason': 'The supplied abstract supports the scoped contribution.',
        'role': 'primary',
        'evidence_basis': 'abstract',
        'evidence_quote': ABSTRACT,
    }
    value.update(extra)
    return value


def judgment_with_key(key, value):
    item = judgment()
    item.pop('relevance')
    item[key] = value
    return item


def judge(raw):
    return asyncio.run(FieldDecomposer(RawLLM(raw)).judge_papers('Spatial response', [PAPER]))


def decompose_without_evidence(raw, *, part='all'):
    return asyncio.run(FieldDecomposer(RawLLM(raw), require_evidence=False).decompose(
        'Spatial response', [PAPER], part=part
    ))


def empty_map(**extra):
    value = {
        'summary': 'Supported research directions remain bounded by the supplied metadata.',
        'prerequisites': [],
        'subfields': [],
        'paper_judgments': [],
    }
    value.update(extra)
    return value


def relation(**extra):
    value = {
        'name': 'Spatial response branch',
        'reason': 'The supplied metadata supports this research direction.',
        'confidence': .8,
        'evidence_paper_ids': ['p1'],
        'evidence_quotes': [],
    }
    value.update(extra)
    return value


class RecordingMapVerifier:
    def __init__(self):
        self.seen = None

    async def verify_map(self, field, prerequisites, subfields, papers, **kwargs):
        self.seen = [*prerequisites, *subfields]
        audited = [item.model_copy(update={'claim_level': 'title_only'}) for item in subfields]
        return prerequisites, audited, [], True

    def validate_judgments(self, judgments, papers):
        return judgments


def test_ascii_edge_whitespace_in_nested_relevance_key_is_consumed():
    raw = {'paper_judgments': [judgment_with_key(' relevance ', .73)]}

    result = judge(raw)

    assert result[0].relevance == .73
    assert result[0].paper_id == PAPER.id
    assert ' relevance ' in raw['paper_judgments'][0]
    assert 'relevance' not in raw['paper_judgments'][0]


def test_unknown_science_extra_remains_rejected_after_key_normalization():
    raw = {'paper_judgments': [judgment(**{' science_extra ': 'unexpected'})]}

    with pytest.raises(ProviderError, match='JSON schema'):
        judge(raw)


def test_normalized_key_collision_fails_closed():
    raw = {'paper_judgments': [judgment_with_key(' relevance ', .73)]}
    raw['paper_judgments'][0][' relevance'] = .74
    before = deepcopy(raw)

    with pytest.raises(ProviderError, match='JSON schema'):
        judge(raw)

    assert raw == before


def test_key_normalization_does_not_mutate_nested_provider_response():
    raw = {'paper_judgments': [judgment_with_key('\trelevance\n', .73)]}
    before = deepcopy(raw)

    result = judge(raw)

    assert result[0].relevance == .73
    assert raw == before


def test_summary_note_is_discarded_before_result_and_claim_processing():
    note = 'This unsupported note claims a universal room-temperature superconducting phase.'
    raw = empty_map(summary_note=note)
    before = deepcopy(raw)
    result = decompose_without_evidence(raw)

    assert note not in result.model_dump_json()
    assert 'summary_note' not in result.model_dump()
    assert raw == before


def test_unknown_top_level_field_still_fails_closed():
    with pytest.raises(ProviderError, match='JSON schema'):
        decompose_without_evidence(empty_map(unknown_top_field='ignore me'))


@pytest.mark.parametrize('note', [
    {'claim': 'not display text'},
    'x' * 2001,
])
def test_invalid_summary_note_is_rejected(note):
    with pytest.raises(ProviderError, match='JSON schema'):
        decompose_without_evidence(empty_map(summary_note=note))


def test_summary_note_cannot_fill_missing_current_phase_field():
    raw = {
        'prerequisites': [],
        'subfields': [],
        'summary_note': 'This is commentary, not the requested summary.',
    }

    with pytest.raises(ProviderError, match='JSON schema'):
        decompose_without_evidence(raw, part='map')


def test_map_claim_level_is_omitted_from_provider_schema_and_owned_by_audit():
    raw = empty_map(subfields=[relation(claim_level='review')])
    before = deepcopy(raw)
    llm = RawLLM(raw)
    verifier = RecordingMapVerifier()
    result = asyncio.run(FieldDecomposer(llm, evidence_verifier=verifier).decompose(
        'Spatial response', [PAPER]
    ))

    assert verifier.seen[0].claim_level == 'research_direction'
    assert result.subfields[0].claim_level == 'title_only'
    relation_schema = llm.last_kwargs['schema']['$defs']['CompactRelation']
    assert 'claim_level' not in relation_schema['properties']
    assert raw == before


def test_unknown_map_relation_field_remains_rejected():
    with pytest.raises(ProviderError, match='JSON schema'):
        decompose_without_evidence(empty_map(
            subfields=[relation(unknown_science_field='ignore me')]
        ))


def test_empty_relocated_root_evidence_is_discarded_without_changing_the_raw_response():
    raw = empty_map(evidence_quotes=[])
    before = deepcopy(raw)
    result = decompose_without_evidence(raw, part='map')
    assert result.summary == raw['summary'] and not result.subfields
    assert raw == before


@pytest.mark.parametrize('extra', [
    {'evidence_quotes': [{'paper_id': 'p1', 'source': 'abstract', 'quote': ABSTRACT}]},
    {'unknown_science_field': []},
])
def test_nonempty_or_unknown_root_evidence_is_not_silently_dropped(extra):
    with pytest.raises(ProviderError, match='JSON schema'):
        decompose_without_evidence(empty_map(**extra), part='map')


def test_null_root_note_is_absent_commentary_and_does_not_mutate_raw_response():
    raw = empty_map(prerequisites_note=None)
    before = deepcopy(raw)
    result = decompose_without_evidence(raw, part='map')
    assert result.summary == raw['summary']
    assert raw == before


@pytest.mark.parametrize('extra', [
    {'prerequisites_note': 'An unsupported scientific finding.'},
    {'prerequisites_note': []},
    {'unknown_science_field': None},
    {'summary': None},
    {'subfields': [relation(prerequisites_note=None)]},
])
def test_null_note_compatibility_does_not_relax_scientific_fields(extra):
    with pytest.raises(ProviderError, match='JSON schema'):
        decompose_without_evidence(empty_map(**extra), part='map')
