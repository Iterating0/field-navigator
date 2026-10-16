import asyncio
import json
import xml.etree.ElementTree as ET

import httpx

from app.models.schemas import Paper
from app.services.arxiv_metadata_verifier import (
    ARXIV_NS,
    ATOM_NS,
    ArxivMetadataVerifier,
    MAX_RESPONSE_BYTES,
    _parse_entry,
)


def feed(*entries):
    body = ''.join(f'<entry><id>http://arxiv.org/abs/{identifier}v1</id><title>{title}</title>'
                   '<published>2020-05-22T00:00:00Z</published><author><name>Public Author</name></author>'
                   '<summary>This study reports a direct result for the research object.</summary></entry>'
                   for identifier, title in entries)
    return f'<feed xmlns="http://www.w3.org/2005/Atom">{body}</feed>'


def status_entry(*, title='Canonical research object study', summary='A direct result for the research object.',
                 comment=''):
    return ET.fromstring(
        f'<entry xmlns="{ATOM_NS}" xmlns:arxiv="{ARXIV_NS}">'
        '<id>http://arxiv.org/abs/2401.12345v1</id>'
        f'<title>{title}</title><published>2024-05-22T00:00:00Z</published>'
        '<author><name>Public Author</name></author>'
        f'<summary>{summary}</summary><arxiv:comment>{comment}</arxiv:comment>'
        '</entry>'
    )


def indexed(**kwargs):
    return Paper(id='W1', title='A mismatched indexed title',
                 doi='https://doi.org/10.48550/arXiv.2005.11401',
                 abstract='A different paper discusses a different mechanism.',
                 citation_count=99999, referenced_works=['untrusted-reference'], **kwargs)


def test_conflicting_identifier_uses_canonical_metadata_without_old_citation_boost():
    requests = []
    def transport(request):
        requests.append(request)
        assert request.url.host == 'export.arxiv.org'
        for header in ('authorization', 'cookie', 'x-api-key'):
            assert header not in request.headers
        return httpx.Response(200, text=feed(('2005.11401', 'Canonical research object study')))

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(transport),
                                    headers={'Authorization': 'Bearer private', 'X-API-Key': 'private'},
                                    cookies={'secret': 'private'}) as client:
            verifier = ArxivMetadataVerifier(client)
            result, warnings = await verifier.verify([indexed()])
            paper = result[0]
            assert paper.id == 'W1' and paper.title == 'Canonical research object study'
            assert paper.source == 'arxiv' and paper.work_version == 'submittedVersion'
            assert paper.work_type == 'preprint' and paper.citation_count is None
            assert not paper.referenced_works and paper.year == 2020
            assert paper.abstract_source_record_id == 'https://arxiv.org/abs/2005.11401'
            assert 'W1' in paper.source_record_ids and warnings
            assert verifier.last_report['corrected_work_ids'] == ['W1']
            await verifier.verify([indexed()])
            assert len(requests) == 1  # bounded cache prevents redundant external calls
    asyncio.run(run())


def test_atom_status_parser_requires_an_explicit_record_status_marker():
    withdrawn_comment = (
        'arXiv admin comment: This version has been removed by arXiv administrators '
        'as the submitter did not have the rights to agree to the license at submission.'
    )
    cases = [
        ('A normal study', 'The authors withdrew a method during the experiment.', '', None),
        ('[Withdrawn] A study', 'A direct result.', '', 'withdrawn'),
        ('A study [retracted]', 'A direct result.', '', 'retracted'),
        ('A study', 'A direct result.', 'This paper has been retracted by the authors.', 'retracted'),
        ('A study', 'A direct result.', withdrawn_comment, 'withdrawn'),
    ]
    for title, summary, comment, expected in cases:
        record = _parse_entry(status_entry(title=title, summary=summary, comment=comment), '2401.12345')
        assert record is not None and record.status == expected


def test_withdrawn_preprint_is_excluded_without_marking_linked_published_version():
    withdrawn_comment = (
        'arXiv admin comment: This version has been removed by arXiv administrators '
        'as the submitter did not have the rights to agree to the license at submission.'
    )
    payload = (
        f'<feed xmlns="{ATOM_NS}" xmlns:arxiv="{ARXIV_NS}">'
        f'<entry><id>http://arxiv.org/abs/2401.12345v1</id>'
        '<title>Canonical research object study</title>'
        '<published>2024-05-22T00:00:00Z</published><author><name>Public Author</name></author>'
        '<summary>This abstract belongs to the withdrawn record.</summary>'
        f'<arxiv:comment>{withdrawn_comment}</arxiv:comment></entry></feed>'
    )

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(
                lambda _: httpx.Response(200, text=payload))) as client:
            preprint = Paper(
                id='Wpre', title='Indexed title', doi='https://doi.org/10.48550/arXiv.2401.12345',
                abstract='Untrusted indexed abstract.', citation_count=999,
                referenced_works=['untrusted-reference'])
            published = Paper(
                id='Wpub', title='Canonical research object study', doi='10.1234/published',
                url='https://arxiv.org/abs/2401.12345', abstract=None,
                authors=['Publisher Author'], work_version='publishedVersion')
            verifier = ArxivMetadataVerifier(client)
            result, warnings = await verifier.verify([preprint, published])
            assert result[0].is_retracted is True
            assert result[0].abstract is None and result[0].abstract_source_record_id is None
            assert result[0].citation_count is None and not result[0].referenced_works
            assert result[1].is_retracted is False
            assert result[1].abstract is None and result[1].authors == ['Publisher Author']
            assert verifier.last_report['status_by_id']['2401.12345'] == 'withdrawn'
            assert any('明确标记为 withdrawn' in warning for warning in warnings)
            assert any('正式发表版本' in warning for warning in warnings)

    asyncio.run(run())


def test_matching_published_version_keeps_its_own_abstract_and_authors():
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _: httpx.Response(
                200, text=feed(('2005.11401', 'Canonical research object study'))))) as client:
            original = Paper(id='Wpub', title='Canonical research object study', doi='10.1234/published',
                             url='https://arxiv.org/abs/2005.11401', abstract='Published-version abstract.',
                             authors=['Published Author'], year=2021, work_version='publishedVersion')
            result, _ = await ArxivMetadataVerifier(client).verify([original])
            assert result[0].abstract == original.abstract and result[0].authors == original.authors
            assert result[0].year == 2021 and result[0].doi == original.doi
    asyncio.run(run())


def test_conflicting_preprint_ids_cannot_supply_semantic_evidence_or_citation_boost():
    def transport(request):
        raise AssertionError('Conflicting identifiers must not choose one network record arbitrarily')

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(transport)) as client:
            verifier = ArxivMetadataVerifier(client)
            original = indexed(url='https://arxiv.org/abs/2307.09288', work_type='preprint')
            result, warnings = await verifier.verify([original])
            assert result[0].title == original.title and result[0].id == original.id
            assert result[0].abstract is None and result[0].abstract_source_record_id is None
            assert result[0].citation_count is None and not result[0].referenced_works
            assert verifier.last_report['unresolved_work_ids'] == ['W1']
            assert any('多个冲突' in warning for warning in warnings)

    asyncio.run(run())


def test_mismatching_preprint_link_cannot_rewrite_a_published_paper():
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _: httpx.Response(
                200, text=feed(('2005.11401', 'Another research object'))))) as client:
            original = Paper(id='Wpub', title='Published research study', doi='10.1234/published',
                             url='https://arxiv.org/abs/2005.11401', abstract='Actual published abstract.',
                             work_version='publishedVersion')
            result, warnings = await ArxivMetadataVerifier(client).verify([original])
            assert result[0] == original and any('冲突' in warning for warning in warnings)
            assert not result[0].source_record_ids
    asyncio.run(run())


def test_legacy_ids_work_and_invalid_hosts_or_ports_cannot_be_followed():
    calls = []
    def transport(request):
        calls.append(request)
        assert request.url.params['id_list'] == 'cond-mat/9603165'
        return httpx.Response(200, text=feed(('cond-mat/9603165', 'Canonical legacy study')))
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(transport)) as client:
            papers = [Paper(id='legacy', title='Legacy study', url='https://arxiv.org/abs/cond-mat/9603165v2'),
                      Paper(id='host', title='Host', url='https://arxiv.org.evil/abs/2005.11401'),
                      Paper(id='port', title='Port', url='https://arxiv.org:bad/abs/2005.11401')]
            result, _ = await ArxivMetadataVerifier(client).verify(papers)
            assert len(calls) == 1 and result[0].title == 'Canonical legacy study'
            assert result[1:] == papers[1:]
    asyncio.run(run())


def test_unknown_or_duplicate_atom_entries_are_not_trusted():
    for payload in (feed(('2301.00001', 'Unknown study')),
                    feed(('2005.11401', 'First'), ('2005.11401', 'Second'))):
        async def run():
            async with httpx.AsyncClient(transport=httpx.MockTransport(
                    lambda _: httpx.Response(200, text=payload))) as client:
                result, warnings = await ArxivMetadataVerifier(client).verify([indexed()])
                assert result[0].title == indexed().title and result[0].abstract is None
                assert result[0].citation_count is None and warnings
        asyncio.run(run())


def test_network_failures_are_bounded_and_cannot_expose_request_secrets():
    def transport(_):
        raise httpx.ConnectError('private-token-in-proxy-url')
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(transport)) as client:
            verifier = ArxivMetadataVerifier(client, timeout=90)
            result, warnings = await verifier.verify([indexed()])
            assert verifier.timeout == 12 and result[0].abstract is None
            assert 'private-token' not in ' '.join(warnings)
    asyncio.run(run())


def test_oversized_response_is_rejected_before_parsing():
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _: httpx.Response(
                200, headers={'content-length': str(MAX_RESPONSE_BYTES + 1)}, content=b'not xml'))) as client:
            result, warnings = await ArxivMetadataVerifier(client).verify([indexed()])
            assert result[0].abstract is None and any('2 MiB' in warning for warning in warnings)
    asyncio.run(run())


def test_datacite_registration_fallback_is_exact_id_checked_and_provenance_labelled():
    def transport(request):
        if request.url.host == 'export.arxiv.org':
            raise httpx.ReadTimeout('timeout')
        assert request.url.host == 'api.datacite.org'
        data = {'data': [{'id': '10.48550/arxiv.2005.11401', 'attributes': {
            'titles': [{'title': 'Canonical research object study'}], 'publicationYear': 2020,
            'creators': [{'name': 'Public Author'}],
            'descriptions': [{'descriptionType': 'Abstract', 'description': 'A direct result for the research object.'}],
        }}, {'id': '10.48550/arxiv.9999.99999', 'attributes': {'titles': [{'title': 'Unrequested title'}]}}]}
        return httpx.Response(200, content=json.dumps(data))
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(transport)) as client:
            verifier = ArxivMetadataVerifier(client)
            result, warnings = await verifier.verify([indexed()])
            assert result[0].source == 'datacite'
            assert result[0].title == 'Canonical research object study'
            assert result[0].abstract is None and result[0].abstract_source_record_id is None
            assert result[0].citation_count is None and len(result) == 1
            assert verifier.last_report['verified_sources'] == {'arxiv': 0, 'datacite': 1}
            assert verifier.last_report['status_by_id']['2005.11401'] is None
            assert any('DOI 注册' in value and '撤回状态' in value for value in warnings)
    asyncio.run(run())
