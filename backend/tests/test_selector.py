from app.models.schemas import Paper
from app.services.paper_selector import select_analysis_papers


def test_shortlist_preserves_retrieval_anchors_and_includes_distinct_evidence():
    papers = [Paper(id=str(i), title=f'Quantum transport direction {i}', year=2000, citation_count=1) for i in range(20)]
    papers[6] = Paper(id='6', title='Quantum transport recent advance', year=2026, citation_count=0)
    papers[9] = Paper(id='9', title='Quantum transport established theory', year=1990, citation_count=10000)
    papers[12] = Paper(id='12', title='Quantum transport review', year=2020, citation_count=100)
    selected = select_analysis_papers('Quantum transport', papers, 8)
    ids = [p.id for p in selected]
    assert len(ids) == len(set(ids)) == 8
    assert {'0', '1', '6', '9', '12'} <= set(ids)
    assert ids == sorted(ids, key=int)
    assert selected == select_analysis_papers('Quantum transport', papers, 8)
    assert select_analysis_papers('Quantum transport', papers, 0) == papers
    assert select_analysis_papers('Quantum transport', papers[:2], 16) == papers[:2]
