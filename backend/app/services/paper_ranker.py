"""Replace this module to experiment with ranking; no UI/provider changes needed."""
import math
import re
from collections import Counter
from datetime import date
from app.models.schemas import CorePaper, Paper, PaperJudgment, normalize_field
from app.services.paper_quality import quality_filter_and_dedupe

STOPWORDS = {'the', 'of', 'and', 'in', 'a', 'an', 'for', 'on', 'with', 'to', 'by',
             'or', 'not', 'research', 'topic', 'literature', 'papers', 'studies'}


def tokens(text: str) -> set[str]:
    return {t for t in re.findall(r'[\w]+', normalize_field(text)) if t not in STOPWORDS}


def lexical_relevance(field: str, paper: Paper) -> float:
    query = tokens(field)
    if not query:
        return 0.0
    title, abstract = tokens(paper.title), tokens(paper.abstract or '')
    return min(1.0, len(query & title) / len(query) * .8 + len(query & abstract) / len(query) * .2)


def core_paper_score(signals: dict[str, float], weights: dict[str, float]) -> float:
    denominator = sum(weights.get(k, 0) for k in signals)
    if not denominator:
        return 0.0
    return round(sum(v * weights.get(k, 0) for k, v in signals.items()) / denominator, 4)


class PaperRanker:
    def __init__(self, weights: dict[str, float]):
        self.weights = weights

    def rank(self, field: str, papers: list[Paper], judgments: list[PaperJudgment],
             limit: int = 8, analysis_source: str = 'llm') -> list[CorePaper]:
        papers = quality_filter_and_dedupe(papers)
        aliases = {record_id: p.id for p in papers for record_id in [p.id, *p.source_record_ids]}
        assessment = {aliases.get(j.paper_id, j.paper_id): j for j in judgments}
        relevance = {}
        for paper in papers:
            judgment = assessment.get(paper.id)
            value = judgment.relevance if judgment else lexical_relevance(field, paper)
            if judgment and analysis_source == 'llm' and judgment.evidence_basis == 'unverified':
                # A failed excerpt check cannot preserve an arbitrary semantic
                # relevance boost. Keep only conservative, visible text matching.
                value = min(value, lexical_relevance(field, paper))
            relevance[paper.id] = value
        citations = {p.id: math.log1p(max(0, p.citation_count)) for p in papers if p.citation_count is not None}
        yearly = {p.id: math.log1p(max(0, p.citation_count) / max(1, date.today().year - p.year + 1))
                  for p in papers if p.citation_count is not None and p.year is not None}
        ref_counts = Counter(r for p in papers if relevance[p.id] >= .4
                             for r in {aliases.get(ref, ref) for ref in p.referenced_works})
        max_citations = max(citations.values(), default=0) or 1
        max_yearly = max(yearly.values(), default=0) or 1
        max_refs = max((ref_counts[p.id] for p in papers), default=0)
        ranked = []
        for p in papers:
            judgment = assessment.get(p.id)
            # Scope is an eligibility condition. A famous adjacent-field paper
            # must not buy its way into the core list through citation signals.
            if analysis_source != 'mock':
                if judgment and (relevance[p.id] < .55 or judgment.role == 'non_research'):
                    continue
                if not judgment and assessment and analysis_source == 'llm':
                    continue
            signals = {'relevance': relevance[p.id]}
            if p.id in citations:
                signals['citation'] = citations[p.id] / max_citations
            if p.id in yearly:
                signals['age_normalized'] = yearly[p.id] / max_yearly
            if max_refs:
                signals['shared_references'] = ref_counts[p.id] / max_refs
            if judgment:
                signals['llm_importance'] = judgment.importance
            reason = judgment.reason if judgment else '根据标题与可用摘要的关键词匹配筛选；尚无模型贡献判断。'
            explanation = []
            if p.id in citations:
                explanation.append(f'{p.citation_count:,} 次引用')
            if p.id in yearly:
                explanation.append('已按发表年限归一化')
            if ref_counts[p.id]:
                explanation.append(f'被候选集中 {ref_counts[p.id]} 篇高相关论文引用')
            if judgment and analysis_source == 'mock':
                explanation.append('含演示阅读优先级')
            if explanation:
                reason += ' 排序信号：' + '；'.join(explanation) + '。'
            score = core_paper_score(signals, self.weights)
            if judgment and analysis_source != 'mock':
                score = round(score * (.35 + .65 * relevance[p.id]), 4)
            overview = (p.work_type == 'review' or (judgment and judgment.role == 'review')
                        or (not judgment and bool(re.search(
                            r'\b(a (?:comprehensive |systematic |critical )?(?:review|survey)|'
                            r'review of|survey of|overview of)\b', p.title.lower()))))
            role = 'review' if overview else judgment.role if judgment else 'unknown'
            ranked.append(CorePaper(paper=p, score=score, reason=reason,
                                    signals={k: round(v, 4) for k, v in signals.items()},
                                    role=role,
                                    evidence_basis=judgment.evidence_basis if judgment else 'unverified',
                                    evidence_quote=judgment.evidence_quote if judgment else ''))
        # Reading routes may include one useful overview, but versions/reviews
        # must not displace the primary evidence a researcher came to find.
        ranked.sort(key=lambda x: (-x.score, x.paper.id))
        selected: list[CorePaper] = []
        overview_count = 0
        for core in ranked:
            if analysis_source != 'mock' and core.role == 'review':
                if overview_count >= 1:
                    continue
                overview_count += 1
            selected.append(core)
            if len(selected) == limit:
                break
        return selected
