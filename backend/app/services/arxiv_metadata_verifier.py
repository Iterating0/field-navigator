"""Conservative arXiv metadata verification for OpenAlex candidates.

The verifier is intentionally a standalone enrichment step.  It only follows
identifiers already present in a Paper's DOI, URL, or strict arXiv abstract URL,
and it never changes a Paper's primary id.  This lets callers repair a known
metadata conflict while keeping relation provenance attached to the OpenAlex
work that produced the candidate.
"""
from __future__ import annotations

import asyncio
import time
import json
import html
from collections import OrderedDict
import re
import unicodedata
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime
from urllib.parse import urlsplit

import httpx

from app.models.schemas import Paper
from app.services.paper_quality import normalize_title, normalize_doi


ARXIV_API_URL = 'https://export.arxiv.org/api/query'
MAX_ARXIV_IDS_PER_REQUEST = 40
MAX_RESPONSE_BYTES = 2 * 1024 * 1024
MAX_REQUEST_TIMEOUT_SECONDS = 12.0

ATOM_NS = 'http://www.w3.org/2005/Atom'
ARXIV_NS = 'http://arxiv.org/schemas/atom'

# arXiv's current identifiers are YYMM.NNNN[N]; legacy identifiers use a
# subject class and a seven digit number.  Versions are removed before the API
# request so that v1/v2 references resolve to one canonical record.
_NEW_ID = re.compile(r'^(\d{4}\.\d{4,5})(?:v\d+)?$', re.IGNORECASE)
_OLD_ID = re.compile(
    r'^([a-z][a-z0-9-]*(?:\.[a-z0-9-]+)?/\d{7})(?:v\d+)?$',
    re.IGNORECASE,
)
_DOI_VALUE = re.compile(
    r'^(?:https?://(?:dx\.)?doi\.org/|doi:\s*)?'
    r'10\.48550/arxiv[.:](.+)$',
    re.IGNORECASE,
)


@dataclass(frozen=True)
class _ArxivRecord:
    arxiv_id: str
    title: str
    summary: str | None
    authors: list[str]
    year: int | None
    doi: str | None
    metadata_source: str = 'arxiv'

    @property
    def abstract_record_id(self):
        return (_canonical_abs(self.arxiv_id) if self.metadata_source == 'arxiv' else
                f'https://api.datacite.org/dois/10.48550/arxiv.{self.arxiv_id}')


def _canonical_arxiv_id(value: str | None) -> str | None:
    """Return a versionless, known-shaped arXiv id or ``None``."""
    if not isinstance(value, str):
        return None
    value = value.strip()
    match = _NEW_ID.fullmatch(value)
    if match:
        return match.group(1)
    match = _OLD_ID.fullmatch(value)
    if match:
        return match.group(1).lower()
    return None


def _from_doi_or_url(value: str | None) -> str | None:
    if not isinstance(value, str):
        return None
    value = value.strip()
    doi_match = _DOI_VALUE.fullmatch(value)
    if doi_match:
        return _canonical_arxiv_id(doi_match.group(1))

    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError:
        return None
    # Deliberately reject www.arxiv.org, export.arxiv.org, query strings,
    # fragments, PDF URLs, and any other path so user metadata cannot redirect
    # the verifier to an arbitrary host.
    if (
        parsed.scheme.lower() not in {'http', 'https'}
        or parsed.hostname != 'arxiv.org'
        or parsed.username
        or parsed.password
        or port is not None
        or parsed.query
        or parsed.fragment
    ):
        return None
    match = re.fullmatch(r'/abs/(.+)', parsed.path)
    return _canonical_arxiv_id(match.group(1)) if match else None


def _extract_candidate_id(paper: Paper) -> tuple[str | None, bool]:
    """Return one unambiguous arXiv id and whether metadata conflicts.

    A Paper can carry both a DOI and an URL.  Matching values are harmless;
    conflicting known values are left untouched rather than guessing which
    source is correct.
    """
    values = (paper.doi, paper.url, paper.id, *paper.source_record_ids)
    ids = {candidate for value in values if (candidate := _from_doi_or_url(value))}
    return (next(iter(ids)), False) if len(ids) == 1 else (None, len(ids) > 1)


def _text(element: ET.Element | None) -> str:
    if element is None:
        return ''
    return ' '.join(''.join(element.itertext()).split())


def _title_key(value: str | None) -> str:
    return normalize_title(value)


def _year(value: str) -> int | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace('Z', '+00:00')).year
    except ValueError:
        match = re.match(r'(\d{4})', value)
        return int(match.group(1)) if match else None


def _entry_id(entry: ET.Element) -> str | None:
    raw = _text(entry.find(f'{{{ATOM_NS}}}id'))
    if not raw:
        return None
    return _from_doi_or_url(raw)


def _parse_entry(entry: ET.Element, arxiv_id: str) -> _ArxivRecord | None:
    title = _text(entry.find(f'{{{ATOM_NS}}}title'))
    if not title:
        return None
    summary = _text(entry.find(f'{{{ATOM_NS}}}summary')) or None
    authors = [
        name
        for author in entry.findall(f'{{{ATOM_NS}}}author')
        if (name := _text(author.find(f'{{{ATOM_NS}}}name')))
    ]
    published = _text(entry.find(f'{{{ATOM_NS}}}published'))
    doi_text = _text(entry.find(f'{{{ARXIV_NS}}}doi')) or None
    doi = normalize_doi(doi_text)
    if doi and not re.fullmatch(r'10\.\d{4,9}/\S+', doi):
        doi = None
    return _ArxivRecord(
        arxiv_id=arxiv_id,
        title=title,
        summary=summary,
        authors=authors,
        year=_year(published),
        doi=doi,
    )


def _canonical_abs(arxiv_id: str) -> str:
    return f'https://arxiv.org/abs/{arxiv_id}'


def _is_arxiv_preprint(paper: Paper) -> bool:
    work_version = (paper.work_version or '').casefold()
    work_type = (paper.work_type or '').casefold()
    source = (paper.source or '').casefold()
    return (
        bool(_from_doi_or_url(paper.doi))
        or
        work_version in {'submittedversion', 'preprint'}
        or work_type == 'preprint'
        or source == 'arxiv'
    )


def _with_aliases(paper: Paper, canonical_abs: str) -> list[str]:
    return list(dict.fromkeys([*paper.source_record_ids, paper.id, canonical_abs]))


def _apply_record(paper: Paper, record: _ArxivRecord) -> Paper:
    canonical_abs = _canonical_abs(record.arxiv_id)
    source_record_ids = _with_aliases(paper, canonical_abs)
    title_conflict = _title_key(paper.title) != _title_key(record.title)

    # A linked preprint must never replace a different published work's
    # metadata merely because an index supplied its URL.
    published_doi = normalize_doi(paper.doi)
    if (title_conflict and published_doi and not _from_doi_or_url(paper.doi)
            and not _is_arxiv_preprint(paper)):
        return paper

    if title_conflict:
        updates = {
            'title': record.title,
            'abstract': record.summary,
            'authors': list(record.authors),
            'year': record.year,
            'doi': record.doi or f'https://doi.org/10.48550/arXiv.{record.arxiv_id}',
            'url': canonical_abs,
            'journal': 'arXiv',
            'work_type': 'preprint',
            'source': record.metadata_source,
            'work_version': 'submittedVersion',
            'citation_count': None,
            'referenced_works': [],
            'source_record_ids': source_record_ids,
            'abstract_source_record_id': record.abstract_record_id if record.summary else None,
        }
        return paper.model_copy(update=updates)

    updates = {'source_record_ids': source_record_ids}
    if _is_arxiv_preprint(paper):
        updates.update({
            'abstract': record.summary,
            'abstract_source_record_id': record.abstract_record_id if record.summary else None,
            'source': record.metadata_source,
            'url': canonical_abs,
            'work_type': 'preprint',
            'work_version': 'submittedVersion',
            'journal': 'arXiv',
        })
        if record.authors:
            updates['authors'] = list(record.authors)
        if record.year is not None:
            updates['year'] = record.year
        if record.doi:
            updates['doi'] = record.doi
    elif paper.abstract is None and record.summary:
        updates.update({'abstract': record.summary, 'abstract_source_record_id': record.abstract_record_id})
    return paper.model_copy(update=updates)


class ArxivMetadataVerifier:
    """Verify candidate arXiv metadata against the official Atom API."""

    def __init__(self, client: httpx.AsyncClient | None = None, *, timeout: float = 12.0):
        self.client = client
        self.timeout = min(max(float(timeout), 0.1), MAX_REQUEST_TIMEOUT_SECONDS)
        self._lock = asyncio.Lock()
        self._last_request = 0.0
        self._cache: OrderedDict[str, tuple[float, _ArxivRecord]] = OrderedDict()
        self.last_report: dict = {}

    async def _fetch_batch(
        self,
        client: httpx.AsyncClient,
        arxiv_ids: list[str],
    ) -> tuple[dict[str, _ArxivRecord], list[str]]:
        params = {
            'id_list': ','.join(arxiv_ids),
            'max_results': str(len(arxiv_ids)),
        }
        try:
            request = client.build_request('GET', ARXIV_API_URL, params=params,
                                           timeout=httpx.Timeout(self.timeout))
            # Credentials configured on a caller's HTTP client belong to that
            # service, never to this public metadata endpoint.
            for header in ('authorization', 'proxy-authorization', 'cookie', 'x-api-key', 'api-key'):
                request.headers.pop(header, None)
            response = await client.send(request, auth=None, follow_redirects=False, stream=True)
            try:
                if response.status_code != 200:
                    return {}, [f'arXiv 官方元数据请求 HTTP {response.status_code}，候选未核查。']
                content_length = response.headers.get('content-length')
                if content_length and int(content_length) > MAX_RESPONSE_BYTES:
                    return {}, ['arXiv 官方元数据响应超过 2 MiB，候选未核查。']
                body = bytearray()
                async for chunk in response.aiter_bytes():
                    body.extend(chunk)
                    if len(body) > MAX_RESPONSE_BYTES:
                        return {}, ['arXiv 官方元数据响应超过 2 MiB，候选未核查。']
            finally:
                await response.aclose()
        except (httpx.TimeoutException, asyncio.TimeoutError):
            return {}, ['arXiv 官方元数据请求超时，候选未核查。']
        except (httpx.HTTPError, ValueError):
            return {}, ['arXiv 官方元数据网络请求失败，候选未核查。']

        try:
            if b'<!DOCTYPE' in bytes(body).upper() or b'<!ENTITY' in bytes(body).upper():
                return {}, ['arXiv 官方元数据包含不支持的 XML 声明，候选未核查。']
            root = ET.fromstring(bytes(body))
        except ET.ParseError:
            return {}, ['arXiv 官方元数据不是有效 Atom 响应，候选未核查。']

        requested = set(arxiv_ids)
        records: dict[str, _ArxivRecord] = {}
        duplicate_ids: set[str] = set()
        warnings: list[str] = []
        entries = root.findall(f'{{{ATOM_NS}}}entry')
        for entry in entries:
            arxiv_id = _entry_id(entry)
            if arxiv_id is None or arxiv_id not in requested:
                warnings.append('arXiv 官方响应包含未知或无效 ID，已忽略。')
                continue
            if arxiv_id in records or arxiv_id in duplicate_ids:
                duplicate_ids.add(arxiv_id)
                records.pop(arxiv_id, None)
                warnings.append(f'arXiv 官方响应包含重复 ID {arxiv_id}，该候选未核查。')
                continue
            record = _parse_entry(entry, arxiv_id)
            if record is None:
                warnings.append(f'arXiv 条目 {arxiv_id} 缺少题名，该候选未核查。')
                continue
            records[arxiv_id] = record

        for arxiv_id in arxiv_ids:
            if arxiv_id not in records:
                warnings.append(f'arXiv 条目 {arxiv_id} 缺失或未形成唯一记录，候选未核查。')
        return records, warnings

    async def _fetch_datacite(self, client, arxiv_ids):
        """One exact-DOI batch from arXiv's DOI registration authority.

        This is a different metadata source, not a retry or a fabricated arXiv
        response. Unknown DOI records cannot enter the requested paper set.
        """
        query = ' OR '.join(f'doi:"10.48550/arXiv.{identifier}"' for identifier in arxiv_ids)
        try:
            request = client.build_request('GET', 'https://api.datacite.org/dois',
                params={'query': query, 'page[size]': len(arxiv_ids)}, timeout=httpx.Timeout(self.timeout))
            for header in ('authorization', 'proxy-authorization', 'cookie', 'x-api-key', 'api-key'):
                request.headers.pop(header, None)
            response = await client.send(request, auth=None, follow_redirects=False, stream=True)
            try:
                if response.status_code != 200:
                    return {}, ['DOI 注册元数据暂不可用，部分条目未核查。']
                body = bytearray()
                async for chunk in response.aiter_bytes():
                    body.extend(chunk)
                    if len(body) > MAX_RESPONSE_BYTES:
                        return {}, ['DOI 注册元数据超过大小预算，部分条目未核查。']
            finally:
                await response.aclose()
            data = json.loads(body)
            if not isinstance(data, dict) or not isinstance(data.get('data'), list):
                raise ValueError('invalid metadata shape')
        except (httpx.HTTPError, ValueError, TypeError, asyncio.TimeoutError):
            return {}, ['DOI 注册元数据核查未完成，部分条目仅保留题名线索。']
        records, duplicate_ids = {}, set()
        for item in data['data']:
            if not isinstance(item, dict):
                continue
            a = item.get('attributes')
            if not isinstance(a, dict):
                continue
            identifier = _from_doi_or_url(item.get('id'))
            if identifier not in arxiv_ids:
                continue
            if identifier in records or identifier in duplicate_ids:
                records.pop(identifier, None)
                duplicate_ids.add(identifier)
                continue
            titles = a.get('titles') or []
            title = next((value.get('title') for value in titles
                          if isinstance(value, dict) and isinstance(value.get('title'), str)), None)
            if not title:
                continue
            descriptions = a.get('descriptions') or []
            summary = next((value.get('description') for value in descriptions
                            if isinstance(value, dict) and value.get('descriptionType') == 'Abstract'
                            and isinstance(value.get('description'), str)), None)
            if summary:
                summary = html.unescape(re.sub(r'<[^>]*>', '', summary))[:8000]
            creators = a.get('creators') or []
            authors = [value['name'] for value in creators if isinstance(value, dict)
                       and isinstance(value.get('name'), str)]
            year = a.get('publicationYear')
            records[identifier] = _ArxivRecord(identifier, ' '.join(title.split()), summary, authors,
                year if isinstance(year, int) and 1900 <= year <= 2100 else None,
                f'https://doi.org/10.48550/arxiv.{identifier}', 'datacite')
        return records, []

    async def _verify_with_client(
        self,
        client: httpx.AsyncClient,
        papers: list[Paper],
    ) -> tuple[list[Paper], list[str]]:
        result = list(papers)
        warnings: list[str] = []
        candidates: dict[str, list[int]] = {}
        conflicted_work_ids: list[str] = []
        for index, paper in enumerate(papers):
            arxiv_id, conflict = _extract_candidate_id(paper)
            if conflict:
                warnings.append(f'候选 {paper.id} 包含多个冲突的 arXiv ID，未核查。')
                conflicted_work_ids.append(paper.id)
                if _is_arxiv_preprint(paper):
                    result[index] = paper.model_copy(update={
                        'abstract': None, 'abstract_source_record_id': None,
                        'citation_count': None, 'referenced_works': [],
                    })
            elif arxiv_id:
                candidates.setdefault(arxiv_id, []).append(index)

        all_records: dict[str, _ArxivRecord] = {}
        now = time.monotonic()
        for arxiv_id in candidates:
            cached = self._cache.get(arxiv_id)
            if cached and now - cached[0] < 21600:
                all_records[arxiv_id] = cached[1]
        requested = [arxiv_id for arxiv_id in candidates if arxiv_id not in all_records]
        batch_count = 0
        doi_batch_count = 0
        for start in range(0, len(requested), MAX_ARXIV_IDS_PER_REQUEST):
            batch = requested[start:start + MAX_ARXIV_IDS_PER_REQUEST]
            delay = 3.0 - (time.monotonic() - self._last_request)
            if delay > 0:
                await asyncio.sleep(delay)
            self._last_request = time.monotonic()
            batch_count += 1
            records, batch_warnings = await self._fetch_batch(client, batch)
            missing = [identifier for identifier in batch if identifier not in records]
            if missing:
                doi_batch_count += 1
                doi_records, doi_warnings = await self._fetch_datacite(client, missing)
                records.update(doi_records)
                if doi_records:
                    batch_warnings = ['arXiv API 路径暂不可用；已使用 arXiv 的 DOI 注册元数据核查。']
                batch_warnings.extend(doi_warnings)
            warnings.extend(batch_warnings)
            all_records.update(records)
            for arxiv_id, record in records.items():
                self._cache[arxiv_id] = (time.monotonic(), record)
                self._cache.move_to_end(arxiv_id)
                while len(self._cache) > 256:
                    self._cache.popitem(last=False)
        corrected_ids = []
        unresolved_ids = list(conflicted_work_ids)
        for arxiv_id, record in all_records.items():
            for index in candidates[arxiv_id]:
                result[index] = _apply_record(result[index], record)
                if _title_key(papers[index].title) != _title_key(record.title):
                    if result[index] is papers[index]:
                        unresolved_ids.append(papers[index].id)
                        warnings.append(
                            f'“{papers[index].title[:80]}”的预印本链接与出版题名冲突，未据此替换出版元数据。'
                        )
                    else:
                        corrected_ids.append(papers[index].id)
                        warnings.append(
                            f'“{record.title[:80]}”的索引题名存在错配，已按 arXiv 原始元数据修正；原引用次数未沿用。'
                        )
        self.last_report = {'candidate_id_count': len(candidates), 'batch_count': batch_count,
                            'doi_batch_count': doi_batch_count,
                            'verified_sources': {source: sum(record.metadata_source == source for record in all_records.values())
                                                 for source in ('arxiv', 'datacite')},
                            'checked_ids': list(all_records), 'corrected_work_ids': corrected_ids,
                            'unresolved_work_ids': unresolved_ids,
                            'missing_ids': [value for value in candidates if value not in all_records]}
        # When the identifier could not be verified, its index abstract must
        # not become confident semantic evidence for a possibly different work.
        for arxiv_id in self.last_report['missing_ids']:
            for index in candidates[arxiv_id]:
                if _is_arxiv_preprint(result[index]):
                    result[index] = result[index].model_copy(update={
                        'abstract': None, 'abstract_source_record_id': None,
                        'citation_count': None, 'referenced_works': [],
                    })
        return result, list(dict.fromkeys(warnings))

    async def verify(self, papers: list[Paper]) -> tuple[list[Paper], list[str]]:
        """Return verified copies and warnings without raising network errors."""
        async with self._lock:
            if not papers:
                self.last_report = {'candidate_id_count': 0, 'batch_count': 0, 'checked_ids': [],
                                    'corrected_work_ids': [], 'unresolved_work_ids': [], 'missing_ids': []}
                return [], []
            if self.client is not None:
                return await self._verify_with_client(self.client, papers)
            async with httpx.AsyncClient(follow_redirects=False) as client:
                return await self._verify_with_client(client, papers)


__all__ = [
    'ARXIV_API_URL',
    'ArxivMetadataVerifier',
    'MAX_ARXIV_IDS_PER_REQUEST',
    'MAX_RESPONSE_BYTES',
]
