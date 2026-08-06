"""数值一致性审计测试：提取、忽略规则、匹配容差、报告渲染。"""

import json

import pytest

from mmw.utils.numeric_audit import (
    audit_paper,
    build_candidates,
    extract_explicit_derived_values,
    extract_numbers,
    render_audit_md,
    strip_tex_noise,
    value_matches,
)


def _results(*values: float) -> str:
    return json.dumps(
        [{"name": f"q{i}_指标", "value": v, "unit": ""} for i, v in enumerate(values, 1)],
        ensure_ascii=False,
    )


# ── 提取与忽略规则 ──────────────────────────────────────


def test_extract_basic_decimal():
    nums, _ = extract_numbers("最优总成本为 1234.56 元。", "a.tex")
    assert len(nums) == 1
    assert nums[0].value == 1234.56


def test_subtraction_operator_is_not_treated_as_negative_sign():
    nums, _ = extract_numbers("差值为 (0.55-0.450329)/0.55。温度为 -11.07。", "a.tex")
    assert [num.value for num in nums] == [0.55, 0.450329, 0.55, -11.07]


def test_unicode_minus_is_treated_as_negative_sign():
    nums, _ = extract_numbers("时间范围为 −100 s 到 100 s。", "a.tex")
    assert [num.value for num in nums] == [-100, 100]


def test_year_ignored():
    nums, ignored = extract_numbers("根据 2023 年的数据分析。", "a.tex")
    assert nums == []
    assert ignored == 1


def test_small_integer_ignored():
    nums, ignored = extract_numbers("将问题分为 3 个子问题求解。", "a.tex")
    assert nums == []
    assert ignored >= 1


def test_ref_not_extracted():
    nums, _ = extract_numbers(r"由式 \eqref{eq:31} 和文献 \cite{ref2008} 可知。", "a.tex")
    assert nums == []


def test_label_adjacent_ignored():
    nums, ignored = extract_numbers("如图 12 和表 35 所示。", "a.tex")
    assert nums == []
    assert ignored == 2


def test_section_number_at_line_start_ignored():
    nums, ignored = extract_numbers("3.1 模型的建立\n误差为 3.7", "a.tex")
    # 行首 3.1 是章节号被忽略；正文中的 3.7 保留
    assert ignored == 1
    assert len(nums) == 1
    assert nums[0].value == 3.7


def test_symbol_range_with_units_ignored_only_in_symbols():
    text = r"$\beta$ & 水平夹角 & 参数 & $[0^\circ, 360^\circ)$ \\"
    nums, ignored = extract_numbers(text, "sections/symbols.tex")
    assert nums == []
    assert ignored >= 2

    nums, _ = extract_numbers(text, "sections/model_solution.tex")
    assert any(num.value == 360 for num in nums)


def test_all_symbol_table_numbers_are_ignored():
    nums, ignored = extract_numbers(
        r"$t$ & 时间范围 & $[20,273]\ \mathrm{min}$ \\",
        "sections/symbols.tex",
    )
    assert nums == []
    assert ignored >= 1


def test_constraint_bounds_are_not_result_numbers():
    nums, ignored = extract_numbers(
        r"\mathrm{s.t.}\quad 250 \leq T \leq 450",
        "sections/model_solution.tex",
    )
    assert nums == []
    assert ignored == 2


def test_thousands_separator_parsed():
    nums, _ = extract_numbers("总产值达 1,234,567.89 万元。", "a.tex")
    assert len(nums) == 1
    assert nums[0].value == 1234567.89


def test_minutes_and_seconds_are_scaled_matches():
    assert value_matches("3600", 3600, [60]) == "scaled"


def test_opposite_sign_does_not_match_without_reduction_context():
    assert value_matches("43.75", 43.75, [-43.75]) == ""
    assert value_matches("43.75", 43.75, [-43.75], allow_abs=True) == "exact"


def test_scientific_notation_parsed():
    nums, _ = extract_numbers(r"样本量为 $3.2 \times 10^{4}$ 条。", "a.tex")
    assert len(nums) == 1
    assert nums[0].value == 32000.0


def test_comment_line_stripped():
    text = strip_tex_noise("正文 45.6\n% 注释里的 999.9 不算\n")
    assert "999.9" not in text
    assert "45.6" in text


def test_bibliography_page_ranges_are_ignored():
    tex = "pages={182--197},\n正文最优值为 46.5。"
    nums, _ = extract_numbers(tex, "sections/evaluation.tex")
    assert [num.value for num in nums] == [46.5]


# ── 匹配容差 ────────────────────────────────────────────


def test_exact_match():
    assert value_matches("1234.56", 1234.56, [1234.56]) == "exact"


def test_rounded_decimal_match():
    # 论文写 1234.6，真实值 1234.56：小数位舍入应匹配
    assert value_matches("1234.6", 1234.6, [1234.56]) == "exact"


def test_sig_fig_rounding_match():
    # 论文写 0.99，真实值 0.987：有效数字舍入是合法书写
    assert value_matches("0.99", 0.99, [0.987]) == "exact"


def test_genuinely_different_no_match():
    assert value_matches("0.95", 0.95, [0.987]) == ""


def test_scaled_match_unit_conversion():
    # 论文写 12.3（万元），真实值 123000（元）：缩放匹配
    assert value_matches("12.3", 12.3, [123000.0]) == "scaled"


def test_percent_scale_match():
    # 论文写 3.2（%），真实值 0.032
    assert value_matches("3.2", 3.2, [0.032]) == "scaled"


def test_explicit_derived_expression_matches_when_operands_are_trusted():
    text = "相对差异为 (0.55-0.450329)/0.55=18.12%。"
    derived = extract_explicit_derived_values(text, [0.55, 0.450329])
    assert len(derived) == 1
    assert derived[0] == pytest.approx((0.55 - 0.450329) / 0.55)

    report = audit_paper({"a.tex": text}, _results(0.55, 0.450329))
    assert not report.unmatched_high


def test_explicit_derived_expression_rejected_when_operand_has_no_source():
    text = "相对差异为 (0.55-0.450329)/0.55=18.12%。"
    assert extract_explicit_derived_values(text, [0.55]) == []

    report = audit_paper({"a.tex": text}, _results(0.55))
    assert any(num.raw == "0.450329" for num in report.unmatched_high)
    assert any(num.raw == "18.12" for num in report.unmatched_high)


# ── 审计与报告 ──────────────────────────────────────────


def test_audit_empty_results_all_unmatched():
    sections = {"abstract.tex": "最优成本为 1234.56 元，误差 3.21%。"}
    report = audit_paper(sections, "[]")
    assert report.matched == 0
    assert len(report.unmatched_high) == 2


def test_audit_matched_against_results():
    sections = {"abstract.tex": "最优成本为 1234.56 元。"}
    report = audit_paper(sections, _results(1234.56))
    assert report.matched == 1
    assert not report.unmatched_high


def test_audit_uses_params_as_candidates():
    sections = {"model.tex": "取折现率 0.085 进行计算。"}
    params = json.dumps([{"symbol": "r", "value": 0.085}])
    report = audit_paper(sections, "[]", params_json=params)
    assert report.matched == 1


def test_audit_uses_sensitivity_candidates():
    sections = {"sensitivity.tex": "参数扰动 +20% 时目标值变为 1481.4。"}
    sens = json.dumps({"experiments": [{"param": "a", "delta_pct": 20, "objective": 1481.4}]})
    report = audit_paper(sections, "[]", sensitivity_json=sens)
    assert report.matched >= 1


def test_low_confidence_classified_separately():
    # 2 位有效数字且 < 1000 → 低置信警示
    sections = {"a.tex": "约为 45 件。"}
    report = audit_paper(sections, "[]")
    assert len(report.unmatched_low) == 1
    assert not report.unmatched_high


def test_build_candidates_skips_invalid_json():
    values = build_candidates("{broken", _results(7.5))
    assert values == [7.5]


def test_params_text_numbers_are_valid_provenance():
    params = '{"parameters":[{"value":"候选范围为 0.80 至 1.20 倍"}]}'
    report = audit_paper({"a.tex": "参数上界为 1.20。"}, "[]", params_json=params)
    assert not report.unmatched_high


def test_comma_separated_parameter_tuple_is_not_a_thousands_number():
    params = json.dumps({"parameters": [
        {"value": 175}, {"value": 195}, {"value": 235}, {"value": 255},
    ]})

    report = audit_paper(
        {"model_solution.tex": r"标定设温为$(175,195,235,255,25)$。"},
        "[]",
        params_json=params,
    )

    assert not report.unmatched_high


def test_subtraction_after_symbol_is_not_parsed_as_negative_constant():
    report = audit_paper(
        {"model_solution.tex": r"$S_N=S/[\tau(T_p-217)]$"},
        "[]",
        raw_output="题面阈值为 217 摄氏度",
    )
    assert not report.unmatched_high


def test_method_contract_values_are_candidates():
    report = audit_paper(
        {"model_solution.tex": "总计算截止为 260 秒。"},
        "[]",
        method_contract_json='{"compute_deadline_seconds": 260}',
    )
    assert not report.unmatched_high


def test_render_audit_md_contains_stats():
    sections = {"abstract.tex": "最优成本为 1234.56 元。"}
    report = audit_paper(sections, "[]")
    md = render_audit_md(report)
    assert "高置信缺出处" in md
    assert "1234.56" in md


def test_render_audit_md_all_clean():
    report = audit_paper({"a.tex": "无任何具体数字的章节。"}, "[]")
    md = render_audit_md(report)
    assert "均能在求解产出中找到出处" in md


def test_audit_ignores_bibliography_numbers():
    report = audit_paper({
        "references.bib": "pages = {261--272}, year = {2020}",
        "sections/model.tex": "正文无结果数字。",
    }, "[]")

    assert report.total == 0
    assert not report.unmatched_high
