"""Deterministic shortlist experiment; retrieval order remains the main signal."""
import math
import re

from app.models.schemas import Paper
from app.services.paper_ranker import lexical_relevance, tokens


def select_analysis_papers(field: str, papers: list[Paper], limit: int = 0) -> list[Paper]:
    if not limit or len(papers) <= limit:
        return list(papers)
    selected = set(range(min(2, limit)))
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
