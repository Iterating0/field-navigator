from typing import Any
from app.data.demo import PAPERS, REASONS, lookup


class MockLLMProvider:
    async def generate_structured(self, *, system: str, payload: dict[str, Any],
                                  schema: dict[str, Any]) -> dict[str, Any]:
        found = lookup(payload['field'])
        if not found:
            return {'summary': '已检索该领域的候选论文。当前未配置 LLM，演示拆分库也不覆盖此领域，因此暂不推断前置领域和研究分支。配置 LLM 后点击重新分析。',
                    'prerequisites': [], 'subfields': [], 'paper_judgments': []}
        name, (summary, prerequisites, subfields, indexes) = found
        ids = {p['id'] for p in payload['papers']}
        def relation(child: str, kind: str, n: int):
            child_entry = lookup(child)[1]
            shared = [PAPERS[i].id for i in indexes if i in child_entry[3] and PAPERS[i].id in ids]
            return {'name': child, 'reason': f'学习 {name} 的概念基础。' if kind == 'pre' else f'从 {name} 延伸到这一研究方向。',
                    'confidence': round(.94 - n * .04, 2), 'evidence_paper_ids': shared[:2]}
        judgments = [{'paper_id': PAPERS[i].id, 'importance': max(.55, .97 - n * .035),
                      'relevance': max(.50, .99 - n * .045), 'reason': REASONS[i]}
                     for n, i in enumerate(indexes) if PAPERS[i].id in ids]
        return {'summary': summary,
                'prerequisites': [relation(c, 'pre', i) for i, c in enumerate(prerequisites)],
                'subfields': [relation(c, 'sub', i) for i, c in enumerate(subfields)],
                'paper_judgments': judgments}
