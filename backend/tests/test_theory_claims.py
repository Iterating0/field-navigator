from app.services.evidence_verifier import theoretical_claim


def test_theoretical_model_can_support_a_spin_charge_pairing_branch():
    assert theoretical_claim(
        'Pairing mechanism from spin and charge fluctuations',
        '摘要覆盖该研究方向。',
        [
            'We performed random-phase-approximation calculations of electron '
            'instabilities in the repulsive Hubbard model.'
        ],
    )


def test_model_prediction_can_support_pairing_symmetry_without_repeating_title_terms():
    assert theoretical_claim(
        'Pairing symmetry and gap structure',
        '该分支来自理论建模。',
        ['A two-band model predicts a chiral d+id state.'],
    )


def test_mediated_plasmon_and_phonon_mechanisms_are_theoretical_when_qualified():
    assert theoretical_claim(
        'Plasmon-mediated superconductivity',
        '论文提出一种可能的集体激发解释。',
        ['Collective excitations such as plasmons can mediate superconductivity.'],
    )
    assert theoretical_claim(
        'Electron-phonon coupling and pairing mechanism',
        '摘要讨论该机制。',
        ['Electron-phonon coupling might explain the pairing mechanism.'],
    )


def test_measured_coupling_or_pairing_is_not_theory_without_a_qualification():
    assert not theoretical_claim(
        'Spin-orbit coupling transport',
        '报告测量结果。',
        ['We measured spin-orbit coupling and transport.'],
    )
    assert not theoretical_claim(
        'Pairing mechanism',
        '报告实验转变。',
        ['We observed a transition in the pairing channel.'],
    )


def test_generic_prediction_and_design_proposal_do_not_become_physical_theory():
    assert not theoretical_claim(
        'Machine learning prediction of editing efficiency',
        '模型预测编辑效率并辅助设计。',
        ['We train a predictive model for editing outcomes.'],
    )
    assert not theoretical_claim(
        'pegRNA design',
        '论文提出并测试新的设计。',
        ['We propose a stable design and experimentally measure editing efficiency.'],
    )


def test_explicit_hypothesis_under_a_causal_name_can_be_in_another_sentence():
    assert theoretical_claim(
        'Origin of superconductivity',
        '摘要覆盖相关研究。该解释仍是一个 hypothesis。',
        [],
    )


def test_a_title_like_causal_name_without_theory_evidence_stays_unclassified():
    assert not theoretical_claim(
        'Pairing symmetry and gap structure',
        '摘要仅说明该研究方向。',
        [],
    )
