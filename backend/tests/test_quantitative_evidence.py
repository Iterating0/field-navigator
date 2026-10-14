from app.services.evidence_verifier import (
    _benchmark_result_needs_scope_limit,
    _benchmark_scope_reason,
    _quantitative_result_needs_scope_limit,
    _quantitative_token_in_excerpts,
    _sanitize_unverified_quantitative_reason,
)


def test_benchmark_scope_detects_correlation_and_ranking_values():
    assert _benchmark_result_needs_scope_limit([
        "Kendall's tau correlation ranged from 0.168 to 0.494."
    ])
    assert _benchmark_result_needs_scope_limit([
        'Kendall τ correlation ranged from 0.168–0.494.'
    ])
    assert _benchmark_result_needs_scope_limit([
        '相关系数为0.168至0.494。'
    ])
    assert _benchmark_result_needs_scope_limit([
        'The best retrieval accuracy was P@5 >= 0.68 and nDCG@10 >= 0.67.'
    ])
    assert not _quantitative_result_needs_scope_limit([
        'In 2024, GPT-4o and a 2D model were evaluated.'
    ])
    long_reason = _benchmark_scope_reason('该评测描述具体结果。' * 40, limit=220)
    assert len(long_reason) <= 220
    assert long_reason.startswith('在所引论文的具体评测设置中：')
    assert long_reason.endswith('；不外推其他模型或任务。')
    assert not _quantitative_result_needs_scope_limit([
        'Kendall tau was discussed in 2024 using a 2D model and GPT-4o.'
    ])
    assert not _quantitative_result_needs_scope_limit([
        'The reported decimal was 1,5% rather than a measured percentage.'
    ])


def test_metric_values_require_exact_metric_and_endpoint_support():
    source = [
        "eRAG reports Kendall's tau correlation ranging from 0.168 to 0.494."
    ]
    assert _quantitative_token_in_excerpts(
        'Kendall tau 0.168–0.494', source,
    )
    assert _quantitative_token_in_excerpts(
        'Kendall τ 0.168–0.494',
        ['eRAG reports Kendall τ correlation ranging from 0.168 to 0.494.'],
    )
    assert _quantitative_token_in_excerpts(
        '相关系数0.168–0.494', ['相关系数为0.168至0.494。'],
    )
    assert not _quantitative_token_in_excerpts(
        'Kendall tau 0.168–0.495', source,
    )
    assert _quantitative_token_in_excerpts(
        'P@5≥0.68', ['The retrieval result reached P@5 >= 0.68.'],
    )


def test_grouped_question_counts_and_unicode_percent_ranges_are_atomic():
    assert _quantitative_result_needs_scope_limit([
        'The benchmark includes 7,663 questions from five datasets.'
    ])
    assert _quantitative_token_in_excerpts(
        '7,663问题', ['The benchmark includes 7,663 questions.'],
    )
    assert _quantitative_token_in_excerpts(
        '17％–33％', ['The tools hallucinated between 17% and 33% of the time.'],
    )
    assert not _quantitative_result_needs_scope_limit([
        'The locale-formatted decimal is 1,5% and is not a benchmark result.'
    ])

    redacted, changed = _sanitize_unverified_quantitative_reason(
        '该医学基准含7,663问题。',
        ['The excerpt reports a qualitative benchmark.'],
        limit=220,
    )
    assert changed
    assert '7,' not in redacted
    assert '663' not in redacted
    assert '相关定量值' in redacted
    assert '7,相关定量值' not in redacted


def test_percent_range_from_separate_source_endpoints_is_preserved():
    assert _quantitative_token_in_excerpts(
        '17%-33%', ['The tools hallucinated between 17% and 33% of the time.'],
    )
    redacted, changed = _sanitize_unverified_quantitative_reason(
        '法律工具的幻觉率为17%-33%。',
        ['The excerpt reports a qualitative difference between systems.'],
        limit=220,
    )
    assert changed
    assert '17' not in redacted and '33' not in redacted
    assert '具体定量值未由核对摘录确认' in redacted


def test_unverified_range_redaction_falls_back_instead_of_leaving_two_placeholders():
    redacted, changed = _sanitize_unverified_quantitative_reason(
        '该结果位于17%-33%的范围。',
        ['The excerpt reports a qualitative difference between systems.'],
        limit=220,
    )
    assert changed
    assert '17' not in redacted and '33' not in redacted
    assert '相关定量值-相关定量值' not in redacted
    assert '具体定量值未由核对摘录确认' in redacted
