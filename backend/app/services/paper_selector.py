"""Deterministic shortlist experiment; retrieval order remains the main signal."""
import math
import re

from app.models.schemas import Paper
from app.services.paper_ranker import lexical_relevance, tokens
from app.services.paper_quality import quality_filter_and_dedupe


def select_analysis_papers(field: str, papers: list[Paper], limit: int = 0, *,
                           evidence_needs: list[dict] | None = None,
                           candidate_focus_ids: dict[str, list[str]] | None = None) -> list[Paper]:
    papers = quality_filter_and_dedupe(papers)
    limit = max(0, limit)
    if not limit or len(papers) <= limit:
        return list(papers)
    selected: set[int] = set()
    # Retrieval provenance only reserves a chance to be assessed, never a core
    # recommendation or a scientific coverage claim. Keep one candidate per
    # requested dimension before broad, highly cited anchors fill the budget.
    focus = candidate_focus_ids or {}
    for need in list(evidence_needs or [])[:3]:
        if not isinstance(need, dict):
            continue
        need_id = need.get('id')
        if not need_id or len(selected) >= limit:
            break
        pool_for_need = [i for i, paper in enumerate(papers)
                         if any(need_id in focus.get(record_id, [])
                                for record_id in [paper.id, *paper.source_record_ids])]
        if any(i in selected for i in pool_for_need):
            continue
        if pool_for_need:
            selected.add(max(pool_for_need, key=lambda i: (
                bool(papers[i].abstract), lexical_relevance(field, papers[i]), -i)))
    for index in range(min(2, limit)):
        if len(selected) < limit:
            selected.add(index)
    # Reserve a little space for recent, established, and overview work without
    # searching outside the retrieved evidence or relying only on citations.
    pool = range(max(2, math.ceil(len(papers) * .75)))
    anchors = [
        max(pool, key=lambda i: (papers[i].year or 0, -i)),
        max(pool, key=lambda i: (papers[i].citation_count or 0, -i)),
    ]
    overview = next((i for i in pool if re.search(r'\b(review|survey|perspective|roadmap)\b', papers[i].title, re.I)), None)
    if overview is not None:
        anchors.append(overview)
    for index in anchors:
        if len(selected) < limit:
            selected.add(index)
    words = [tokens(p.title) for p in papers]
    while len(selected) < limit:
        covered = set().union(*(words[i] for i in selected))
        def score(i):
            relevance = lexical_relevance(field, papers[i])
            retrieval = 1 - i / len(papers)
            novelty = len(words[i] - covered) / max(1, len(words[i]))
            return (.45 * relevance + .35 * retrieval + .20 * novelty, -i)
        selected.add(max((i for i in range(len(papers)) if i not in selected), key=score))
    return [paper for i, paper in enumerate(papers) if i in selected]
