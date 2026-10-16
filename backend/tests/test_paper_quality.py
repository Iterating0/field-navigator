import asyncio

import httpx

from app.models.schemas import Paper
from app.providers.openalex import OpenAlexProvider, parse_work
from app.services.paper_quality import (
    canonical_id_map,
    normalize_doi,
    quality_filter_and_dedupe,
)
from app.services.paper_selector import select_analysis_papers


def make_paper(paper_id, title='Quantum transport in oxide interfaces', **kwargs):
    return Paper(id=paper_id, title=title, **kwargs)


def test_normalize_doi_accepts_common_forms():
    assert normalize_doi(' DOI:HTTPS://DOI.ORG/10.1000/Test.1. ') == '10.1000/test.1'
    assert normalize_doi('10.1000/test.1') == '10.1000/test.1'
    assert normalize_doi(None) is None


def test_versions_merge_across_doi_and_year_gap_preferring_published_record():
    title = 'Quantum transport in oxide interfaces under strong magnetic fields'
    preprint = make_paper(
        'W-preprint', title, year=2022, authors=['A. Researcher'],
        doi='10.1000/preprint', work_type='preprint', work_version='submittedVersion',
        abstract='A long preprint abstract with useful metadata.', referenced_works=['W1'],
    )
    published = make_paper(
        'W-published', title, year=2024, authors=['A. Researcher', 'B. Author'],
        doi='https://doi.org/10.1000/published', work_type='article',
        work_version='publishedVersion', abstract='Shorter record.', referenced_works=['W2'],
    )

    result = quality_filter_and_dedupe([preprint, published])

    assert [paper.id for paper in result] == ['W-published']
    merged = result[0]
    assert merged.source_record_ids == ['W-preprint']
    assert set(merged.referenced_works) == {'W1', 'W2'}
    assert merged.abstract == published.abstract
    assert getattr(merged, 'abstract_source_record_id', None) == published.id
    assert canonical_id_map(result) == {'W-published': 'W-published', 'W-preprint': 'W-published'}


def test_missing_preferred_abstract_uses_version_fallback_with_source_id():
    title = 'Quantum transport in oxide interfaces under strong magnetic fields'
    preprint = make_paper(
        'W-preprint', title, year=2022, authors=['A. Researcher'],
        doi='10.1000/preprint', work_type='preprint', work_version='submittedVersion',
        abstract='The preprint abstract is the only available summary.',
    )
    published = make_paper(
        'W-published', title, year=2024, authors=['A. Researcher'],
        doi='https://doi.org/10.1000/published', work_type='article',
        work_version='publishedVersion', abstract=None,
    )

    merged = quality_filter_and_dedupe([preprint, published])[0]

    assert merged.abstract == preprint.abstract
    assert getattr(merged, 'abstract_source_record_id', None) == preprint.id


def test_dedupe_requires_author_and_year_evidence_for_title_match():
    generic = [
        make_paper('W1', 'A Study', year=2024, authors=['Same Author']),
        make_paper('W2', 'A Study', year=2024, authors=['Same Author']),
    ]
    missing_metadata = [
        make_paper('W3', 'A Specific Quantum Transport Phenomenon in Interfaces'),
        make_paper('W4', 'A Specific Quantum Transport Phenomenon in Interfaces', year=2024),
    ]
    different_authors = [
        make_paper('W5', 'A Specific Quantum Transport Phenomenon in Interfaces',
                   year=2024, authors=['First Author']),
        make_paper('W6', 'A Specific Quantum Transport Phenomenon in Interfaces',
                   year=2024, authors=['Different Author']),
    ]

    assert len(quality_filter_and_dedupe(generic)) == 2
    assert len(quality_filter_and_dedupe(missing_metadata)) == 2
    assert len(quality_filter_and_dedupe(different_authors)) == 2


def test_quality_filter_excludes_artifacts_but_keeps_letters_conference_papers_and_unknowns():
    excluded = [
        make_paper('dataset', work_type='dataset'),
        make_paper('editorial', work_type='editorial'),
        make_paper('erratum', work_type='erratum'),
        make_paper('retraction', work_type='retraction'),
        make_paper('paratext', work_type='article', is_paratext=True),
        make_paper('withdrawn', work_type='article', is_retracted=True),
        make_paper('abstract', work_type='conference-abstract'),
        make_paper('software', work_type='software'),
    ]
    retained = [
        make_paper('letter', work_type='letter'),
        make_paper('conference', work_type='conference-paper'),
        make_paper('review', work_type='review'),
        make_paper('unknown', work_type=None),
        make_paper('other', work_type='other'),
    ]

    result = quality_filter_and_dedupe([*excluded, *retained])

    assert {paper.id for paper in result} == {paper.id for paper in retained}


def test_selector_applies_the_same_quality_gate():
    papers = [
        make_paper('dataset', work_type='dataset', citation_count=100000),
        make_paper('letter', title='Quantum transport in oxide interfaces', work_type='letter'),
        make_paper('conference', title='Quantum transport conference paper', work_type='conference-paper'),
    ]

    selected = select_analysis_papers('Quantum transport', papers)

    assert [paper.id for paper in selected] == ['letter', 'conference']


def test_openalex_maps_quality_metadata_and_dedupes_before_returning_results():
    title = 'Quantum transport in oxide interfaces under strong magnetic fields'
    work_results = [
        {
            'id': 'https://openalex.org/Wpre', 'title': title, 'publication_year': 2022,
            'type': 'preprint', 'is_retracted': False,
            'primary_location': {'version': 'submittedVersion', 'source': {'display_name': 'arXiv'}},
            'doi': '10.1000/pre', 'authorships': [{'author': {'display_name': 'A. Researcher'}}],
            'referenced_works': ['https://openalex.org/W1'],
        },
        {
            'id': 'https://openalex.org/Wpub', 'title': title, 'publication_year': 2024,
            'type': 'article', 'is_retracted': False,
            'primary_location': {'version': 'publishedVersion', 'source': {'display_name': 'Journal'}},
            'doi': '10.1000/pub', 'authorships': [{'author': {'display_name': 'A. Researcher'}}],
            'referenced_works': ['https://openalex.org/W2'],
        },
        {
            'id': 'https://openalex.org/Wdata', 'title': 'Quantum transport dataset',
            'publication_year': 2024, 'type': 'dataset', 'is_retracted': False,
            'primary_location': {'source': {'display_name': 'Repository'}},
            'authorships': [],
        },
    ]
    seen = []

    def handle(request):
        seen.append(request)
        return httpx.Response(200, json={'results': work_results})

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
            provider = OpenAlexProvider(client)
            return await provider.search_papers(
                'quantum transport', 40, sort='cited_by_count:desc')

    result = asyncio.run(run())

    assert [paper.id for paper in result] == ['https://openalex.org/Wpub']
    assert result[0].work_type == 'article'
    assert result[0].work_version == 'publishedVersion'
    assert result[0].source_record_ids == ['https://openalex.org/Wpre']
    assert seen[0].url.params['sort'] == 'cited_by_count:desc'
    assert seen[0].url.params['filter'] == 'is_retracted:false'


def test_parse_work_preserves_explicit_retraction_and_paratext_flags():
    paper = parse_work({
        'id': 'https://openalex.org/Wbad', 'title': 'A record', 'type': 'article',
        'is_retracted': True, 'is_paratext': True,
        'primary_location': {'version': 'publishedVersion', 'source': {'display_name': 'Journal'}},
        'authorships': [],
    })

    assert paper.is_retracted is True
    assert paper.is_paratext is True
    assert paper.work_type == 'article'
    assert paper.work_version == 'publishedVersion'
