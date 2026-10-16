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


def test_requested_dimension_gets_assessed_before_broad_anchors_fill_small_budget():
    papers = [Paper(id=str(i), title=f'Target system general method {i}', citation_count=1000)
              for i in range(35)]
    papers[30] = Paper(id='30', source_record_ids=['old30'], title='Target system measurement limitation',
                       abstract='We measure the limitation under a changed reference.', citation_count=0)
    papers[34] = Paper(id='34', title='Target system independent validation',
                       abstract='We validate against independent observations.', citation_count=0)
    needs = [{'id': 'need-1'}, {'id': 'need-2'}]
    focus = {'old30': ['need-1'], '34': ['need-2'], '33': ['unknown']}
    selected = select_analysis_papers('Target system', papers, 2,
                                      evidence_needs=needs, candidate_focus_ids=focus)
    assert [p.id for p in selected] == ['30', '34']
    assert all(p.citation_count == 0 for p in selected)
    assert [p.id for p in select_analysis_papers('Target system', papers, 0,
            evidence_needs=needs, candidate_focus_ids=focus)] == [p.id for p in papers]
