"""Quality gates and conservative identity merging for bibliographic works.

OpenAlex returns works, while a search result can still contain a preprint and
its published counterpart as separate records.  This module keeps that
provider-specific cleanup deterministic and reusable by both retrieval and
shortlisting.  It deliberately prefers false negatives over merging two
records merely because their titles are short or their metadata is incomplete.
"""

from __future__ import annotations

import re
import unicodedata
from collections import defaultdict
from collections.abc import Iterable

from app.models.schemas import Paper


# These are publication artifacts or non-research records for the navigator's
# core-paper list.  ``letter`` and ``conference-paper`` intentionally remain
# usable: both can carry original research in physics and other fields.
HARD_EXCLUDED_TYPES = frozenset({
    'book-review',
    'conference-abstract',
    'dataset',
    'editorial',
    'erratum',
    'libguides',
    'paratext',
    'peer-review',
    'reference-entry',
    'retraction',
    'software',
    'supplementary-materials',
})

_DOI_PREFIX = re.compile(r'^(?:https?://)?(?:dx\.)?doi\.org/', re.IGNORECASE)
_DOI_LABEL = re.compile(r'^doi:\s*', re.IGNORECASE)
_TITLE_NONWORD = re.compile(r'[^\w]+', re.UNICODE)
_AUTHOR_NONWORD = re.compile(r'[^\w]+', re.UNICODE)


def normalize_doi(value: str | None) -> str | None:
    """Return a stable DOI key, or ``None`` for missing/empty values."""
    if not value or not isinstance(value, str):
        return None
    value = unicodedata.normalize('NFKC', value).strip().lower()
    value = _DOI_LABEL.sub('', value)
    value = _DOI_PREFIX.sub('', value)
    value = value.strip().rstrip('.,;:)]}')
    return value or None


def normalize_title(value: str | None) -> str:
    """Normalize a title without applying field aliases or fuzzy matching."""
    if not value:
        return ''
    value = unicodedata.normalize('NFKC', value).casefold()
    value = re.sub(r'\\(?:mathrm|textrm|text|mathit|mathbf)\s*', '', value)
    value = re.sub(r'[$^{}]', '', value)
    # Subscript rendering varies between publisher and preprint metadata.
    # Join only letter/number separators; distinct numeric labels stay distinct.
    value = re.sub(r'(?<=[a-z])[\s_]+(?=\d)', '', value)
    return ' '.join(_TITLE_NONWORD.sub(' ', value).split())


def _author_key(value: str | None) -> str:
    if not value:
        return ''
    value = unicodedata.normalize('NFKC', value).casefold()
    return ''.join(_AUTHOR_NONWORD.sub('', value))


def _author_keys(paper: Paper) -> set[str]:
    return {_author_key(author) for author in paper.authors if _author_key(author)}


def _specific_title(title: str) -> bool:
    """Avoid merging generic short titles on title text alone."""
    normalized = normalize_title(title)
    return len(normalized) >= 32 and len(normalized.split()) >= 5


def _same_work(left: Paper, right: Paper) -> bool:
    if left.id == right.id:
        return True
    left_sources = set(getattr(left, 'source_record_ids', []))
    right_sources = set(getattr(right, 'source_record_ids', []))
    if left.id in right_sources or right.id in left_sources or left_sources & right_sources:
        return True

    left_doi, right_doi = normalize_doi(left.doi), normalize_doi(right.doi)
    if left_doi and right_doi and left_doi == right_doi:
        return True

    left_title = normalize_title(left.title)
    right_title = normalize_title(right.title)
    if not left_title or left_title != right_title or not _specific_title(left.title):
        return False
    # Missing authors or year are not enough to merge records with different
    # identifiers.  This protects distinct works with generic titles and
    # preserves citation-graph fixtures that intentionally share a title.
    if left.year is None or right.year is None or abs(left.year - right.year) > 2:
        return False
    left_authors, right_authors = _author_keys(left), _author_keys(right)
    return bool(left_authors and right_authors and left_authors & right_authors)


def _version_rank(paper: Paper) -> int:
    return {
        'publishedVersion': 4,
        'acceptedVersion': 3,
        'submittedVersion': 2,
    }.get(getattr(paper, 'work_version', None), 0)


def _type_rank(paper: Paper) -> int:
    # A published article/conference paper is generally the best canonical
    # record when a location version is absent.  Reviews are retained but do
    # not outrank an original article solely because they are reviews.
    return {
        'article': 4,
        'conference-paper': 4,
        'review': 3,
        'data-paper': 3,
        'software-paper': 3,
        'report': 2,
        'preprint': 1,
    }.get((getattr(paper, 'work_type', None) or '').casefold(), 0)


def _preferred_key(paper: Paper, position: int) -> tuple[int, int, int, int, int, int, int]:
    info = sum(bool(value) for value in (
        paper.doi, paper.abstract, paper.journal, paper.url,
    ))
    return (
        _version_rank(paper),
        _type_rank(paper),
        info,
        len(paper.referenced_works),
        len(paper.authors),
        paper.citation_count if paper.citation_count is not None else -1,
        -position,
    )


def _union_ordered(values: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value and value not in seen:
            seen.add(value)
            result.append(value)
    return result


def _merge_group(group: list[tuple[int, Paper]]) -> Paper:
    position, preferred = max(group, key=lambda item: _preferred_key(item[1], item[0]))
    del position  # The position is only part of the deterministic preference key.

    # Keep the canonical record's identifiers and publication role.  Fill
    # sparse metadata from its merged versions without changing its identity.
    # An abstract is content, rather than a generic completeness field.  Once
    # the preferred (usually published) record has one, keep that record's
    # wording even when an older version has a longer preprint abstract.  Only
    # use a version fallback when the preferred record has no abstract, and
    # retain the record that supplied the text for evidence provenance.
    abstract = preferred.abstract
    abstract_source_record_id = None
    if abstract:
        abstract_source_record_id = (
            getattr(preferred, 'abstract_source_record_id', None) or preferred.id
        )
    else:
        abstract_candidates = [
            (index, paper) for index, paper in group if paper.abstract
        ]
        if abstract_candidates:
            _, fallback = max(
                abstract_candidates,
                key=lambda item: _preferred_key(item[1], item[0]),
            )
            abstract = fallback.abstract
            abstract_source_record_id = (
                getattr(fallback, 'abstract_source_record_id', None) or fallback.id
            )
    authors = _union_ordered(preferred.authors)
    for _, paper in group:
        authors = _union_ordered([*authors, *paper.authors])
    references = _union_ordered(
        reference
        for _, paper in group
        for reference in paper.referenced_works
    )
    source_ids = _union_ordered(
        source_id
        for _, paper in group
        for source_id in [*getattr(paper, 'source_record_ids', []), paper.id,
                          *([f'https://doi.org/{normalize_doi(paper.doi)}']
                            if (normalize_doi(paper.doi) or '').startswith('10.48550/arxiv.') else []),
                          *([paper.url] if paper.url and re.fullmatch(
                              r'https?://arxiv\.org/abs/[a-zA-Z0-9./-]+', paper.url) else [])]
        if source_id != preferred.id
    )

    updates = {
        'abstract': abstract,
        'abstract_source_record_id': abstract_source_record_id,
        'authors': authors,
        'referenced_works': references,
        'source_record_ids': source_ids,
    }
    # Counts belong to one indexed version; an unknown published-version count
    # must not inherit a preprint's unrelated or inflated count.
    for field in ('year', 'doi', 'url', 'journal'):
        if getattr(preferred, field) is None:
            fallback = next((getattr(paper, field) for _, paper in group
                             if getattr(paper, field) is not None), None)
            if fallback is not None:
                updates[field] = fallback
    return preferred.model_copy(update=updates)


def canonical_id_map(papers: Iterable[Paper]) -> dict[str, str]:
    """Map canonical and merged source IDs to the surviving work ID."""
    mapping: dict[str, str] = {}
    for paper in papers:
        mapping[paper.id] = paper.id
        for source_id in getattr(paper, 'source_record_ids', []):
            mapping[source_id] = paper.id
    return mapping


def is_usable(paper: Paper) -> bool:
    """Return whether a paper can enter retrieval/analysis candidates."""
    if getattr(paper, 'is_retracted', False) or getattr(paper, 'is_paratext', False):
        return False
    work_type = (getattr(paper, 'work_type', None) or '').casefold()
    return work_type not in HARD_EXCLUDED_TYPES


def quality_filter_and_dedupe(papers: Iterable[Paper]) -> list[Paper]:
    """Drop explicit artifacts and merge confidently identical work versions.

    The input order is preserved at group level.  No title-only fuzzy match is
    attempted, and missing author/year metadata prevents cross-ID merging.
    """
    usable = [paper for paper in papers if is_usable(paper)]
    if not usable:
        return []

    parent = list(range(len(usable)))

    def find(index: int) -> int:
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

    def union(left: int, right: int):
        left, right = find(left), find(right)
        if left != right:
            parent[right] = left

    for left in range(len(usable)):
        for right in range(left + 1, len(usable)):
            if _same_work(usable[left], usable[right]):
                union(left, right)

    groups: dict[int, list[tuple[int, Paper]]] = defaultdict(list)
    for index, paper in enumerate(usable):
        groups[find(index)].append((index, paper))
    merged = [_merge_group(group) for group in sorted(groups.values(), key=lambda items: items[0][0])]

    # References can point at an older record ID from the same result page.
    # Rewrite only known aliases; leave external references untouched.
    aliases = canonical_id_map(merged)
    normalized: list[Paper] = []
    for paper in merged:
        refs = _union_ordered(aliases.get(reference, reference)
                              for reference in paper.referenced_works)
        normalized.append(paper.model_copy(update={'referenced_works': refs}))
    return normalized
