from app.services.evidence_verifier import (
    _benchmark_result_needs_scope_limit,
    _benchmark_scope_reason,
    _quantitative_excerpt_has_setting,
    _qualitative_core_reason_without_unscoped_amplitude,
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


def test_spelled_factor_amplitude_requires_explicit_study_setting_for_core_reason():
    quote = 'The estimated parameters can differ by more than a factor of two depending on the employed model.'
    assert _quantitative_result_needs_scope_limit([quote])
    assert _quantitative_token_in_excerpts('两倍以上', [quote])
    assert not _quantitative_excerpt_has_setting(quote)

    english, changed = _qualitative_core_reason_without_unscoped_amplitude(
        quote, quote, language='en', limit=220,
    )
    assert changed
    assert 'factor' not in english.lower()
    assert 'more than' not in english.lower()
    assert 'depending on the employed model' in english

    chinese, changed = _qualitative_core_reason_without_unscoped_amplitude(
        '估计参数可能相差两倍以上，取决于所用描述。',
        quote,
        language='zh',
        limit=220,
    )
    assert changed
    assert '两倍' not in chinese
    assert '存在差异' in chinese

    bounded = 'On the benchmark, the method differs by a factor of two in accuracy.'
    assert _quantitative_excerpt_has_setting(bounded)


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


def test_translated_count_dimensions_keep_methods_datasets_and_tissue_types_distinct():
    excerpts = [
        'we benchmark 18 existing methods resolving a cellular deconvolution task '
        'with 50 real-world and simulated datasets',
        'We compile cell profile matrices for 75 tissue types.',
    ]
    assert _quantitative_token_in_excerpts('18种方法', excerpts)
    assert _quantitative_token_in_excerpts('18个方法', excerpts)
    assert _quantitative_token_in_excerpts('50种数据集', excerpts)
    assert _quantitative_token_in_excerpts('75种组织类型', excerpts)

    # Equal numerals do not transfer evidence between semantic dimensions.
    assert not _quantitative_token_in_excerpts('18种模型', excerpts)
    assert not _quantitative_token_in_excerpts('18种数据集', excerpts)
    assert not _quantitative_token_in_excerpts('50种方法', excerpts)
    assert not _quantitative_token_in_excerpts('75种数据集', excerpts)


def test_unknown_count_modifiers_are_removed_without_repeated_placeholders():
    reason, changed = _sanitize_unverified_quantitative_reason(
        '该基准评估18种方法、50种模型并覆盖75种数据集。',
        ['we benchmark 18 existing methods.'],
        limit=220,
    )
    assert changed
    assert '18种方法' in reason
    assert '50种模型' not in reason
    assert '75种数据集' not in reason
    assert reason.count('相关定量值') == 1
    assert '相关定量值模型' not in reason


def test_same_numeric_value_different_measurement_units_never_cross_support():
    source = ['The benchmark evaluated 18 existing methods.']
    assert _quantitative_token_in_excerpts('18种方法', source)
    assert not _quantitative_token_in_excerpts('18个模型', source)
    assert not _quantitative_token_in_excerpts('18%', source)
    assert not _quantitative_token_in_excerpts('18倍', source)


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


def test_type_counts_do_not_support_specimen_or_individual_cell_counts():
    excerpts = ['We compile matrices for 75 tissue types and identify 8 cell types.']
    assert _quantitative_token_in_excerpts('75种组织', excerpts)
    assert _quantitative_token_in_excerpts('8种细胞', excerpts)
    assert not _quantitative_token_in_excerpts('75个组织', excerpts)
    assert not _quantitative_token_in_excerpts('8个细胞', excerpts)
    assert not _quantitative_token_in_excerpts('8组细胞', excerpts)


def test_count_modifiers_do_not_hide_the_counted_dimension():
    excerpts = ['we benchmark 18 existing methods with 50 real-world and simulated datasets']
    assert _quantitative_token_in_excerpts('18种现有方法', excerpts)
    reason, changed = _sanitize_unverified_quantitative_reason(
        '该基准评测18种现有方法，使用50个真实与模拟数据集。', excerpts, limit=220)
    assert not changed
    assert '18种现有方法' in reason and '50个真实与模拟数据集' in reason
    assert not _quantitative_token_in_excerpts('18种现有模型', excerpts)
