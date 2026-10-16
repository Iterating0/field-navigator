from typing import Any
from app.data.demo import PAPERS, REASONS, lookup


# The offline map is intentionally small and editorial.  Keep a parallel
# English copy here rather than translating the generated result after the
# fact: the explanation remains tied to the same bundled topic and papers.
EN_SUMMARIES = {
    'Non-Hermitian Skin Effect':
        'The non-Hermitian skin effect (NHSE) describes extensive accumulation of eigenstates at the boundary of an open system. It highlights how boundary conditions reshape spectra and state distributions, and provides an entry point to non-Bloch bands and non-Hermitian topology. Start with band foundations, then explore theory, incoherent dynamics, and experimental platforms.',
    'Non-Hermitian band theory':
        'Complex spectra, left and right eigenstates, and point gaps provide the language for studying non-Hermitian periodic systems and distinguishing boundary localization from topological boundary states.',
    'Bloch theory':
        'Translation symmetry in a periodic potential organizes eigenstates by crystal momentum. Brillouin zones and bands are the starting point for comparing periodic and open-boundary problems. This demo node links to NHSE-related material rather than a complete Bloch-theory bibliography.',
    'Non-Bloch band theory':
        'When ordinary Bloch waves do not describe bulk states under open boundaries, the generalized Brillouin zone and complex wavevectors provide a revised band description and revisit bulk-boundary correspondence.',
    'Higher-dimensional NHSE':
        'Extending the skin effect from one-dimensional chains to two and higher dimensions reveals how geometry, boundary orientation, and complex spectra jointly determine localization.',
    'Incoherent NHSE':
        'This direction asks whether boundary accumulation can survive without phase coherence. Photonic quantum walks provide an entry point for comparing wave interference with probability-distribution dynamics.',
    'Experimental realizations':
        'Circuits and optical platforms make boundary accumulation and anomalous bulk-boundary correspondence observable. When reading, distinguish the measured quantity from a theoretical eigenstate.',
    'Point-gap topology':
        'Winding around a reference point in the complex-energy spectrum provides a topological view of some non-Hermitian skin phenomena. The conclusion depends on dimension, symmetry, and boundary conditions.',
    'Generalized Brillouin zone':
        'Complex propagation factors describe bulk states under open boundaries and form a central object in one-dimensional non-Bloch band methods.',
    'Geometry-dependent skin effect':
        'This direction studies how boundary geometry changes skin modes and spectra. The demo uses a higher-dimensional skin-effect paper as its main reading entry point.',
    'Photonic quantum walks':
        'Discrete evolution steps model transport while nonreciprocity and decoherence allow coherent and incoherent boundary accumulation to be compared. This is a reading entry point related to NHSE.',
    'Topolectrical circuits':
        'Circuit networks can implement non-Hermitian couplings and probe responses, providing an experimental platform for generalized bulk-boundary correspondence.',
}

EN_REASONS = [
    'A non-Hermitian topological model connects boundary states and topological invariants, making it a useful starting point for non-Bloch descriptions.',
    'A biorthogonal treatment of bulk-boundary correspondence can be read alongside non-Bloch methods.',
    'This work develops non-Bloch band theory for non-Hermitian systems and helps establish a computational framework.',
    'It connects the topological origin of the skin effect with complex-spectrum topology.',
    'It relates spectral winding numbers to skin modes, linking topological criteria with boundary phenomena.',
    'A non-Hermitian circuit platform connects generalized bulk-boundary correspondence with experiment.',
    'An optical platform demonstrates topological funneling and offers an experimental entry point to skin transport.',
    'The work studies skin effects in two and higher dimensions and helps expose geometry-dependent behavior.',
    'An early study of non-Hermitian localization provides historical context for nonreciprocal models.',
    'It directly studies an incoherent skin effect in photonic quantum walks and is a focused entry point to this branch.',
]


class MockLLMProvider:
    async def generate_structured(self, *, system: str, payload: dict[str, Any],
                                  schema: dict[str, Any]) -> dict[str, Any]:
        language = payload.get('language', 'zh-CN')
        english = language == 'en'
        found = lookup(payload['field'])
        if not found:
            return {'summary': ('Candidate papers were retrieved. No LLM is configured and the bundled teaching map does not cover this field, so prerequisites and research branches are not inferred. Configure an LLM and analyze again.'
                                if english else
                                '已检索该领域的候选论文。当前未配置 LLM，演示拆分库也不覆盖此领域，因此暂不推断前置领域和研究分支。配置 LLM 后点击重新分析。'),
                    'prerequisites': [], 'subfields': [], 'paper_judgments': []}
        name, (summary, prerequisites, subfields, indexes) = found
        ids = {p['id'] for p in payload['papers']}
        def relation(child: str, kind: str, n: int):
            child_entry = lookup(child)[1]
            # The child's primary bibliography comes first: an experimental
            # branch should cite its platform papers, not whichever generic
            # theory papers happened to lead the parent's list.
            shared = [PAPERS[i].id for i in child_entry[3] if i in indexes and PAPERS[i].id in ids]
            purpose = (('Builds the prerequisite concepts: ' if kind == 'pre' else
                        'A direction for further reading: ') if english else
                       ('用于补充前置概念：' if kind == 'pre' else '可以沿这个方向继续阅读：'))
            child_summary = EN_SUMMARIES.get(child, child_entry[0]) if english else child_entry[0]
            return {'name': child, 'reason': purpose + child_summary,
                    'confidence': round(.94 - n * .04, 2), 'evidence_paper_ids': shared[:2]}
        judgments = [{'paper_id': PAPERS[i].id, 'importance': max(.55, .97 - n * .035),
                      'relevance': max(.50, .99 - n * .045),
                      'reason': EN_REASONS[i] if english else REASONS[i]}
                     for n, i in enumerate(indexes) if PAPERS[i].id in ids]
        return {'summary': EN_SUMMARIES.get(name, summary) if english else summary,
                'prerequisites': [relation(c, 'pre', i) for i, c in enumerate(prerequisites)],
                'subfields': [relation(c, 'sub', i) for i, c in enumerate(subfields)],
                'paper_judgments': judgments}
