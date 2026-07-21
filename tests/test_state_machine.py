"""状态机测试：阶段转移门控、审批条件、rework 影响范围。"""

import json

import pytest

from mmw.models import MetaData, StageID
from mmw.pipeline.state_machine import (
    PipelineStateMachine,
    _invalid_figure_aspect_ratios,
    _invalid_physical_results,
    _sensitivity_schema_error,
)
from mmw.utils.checkpoint import CheckpointManager


@pytest.fixture
def mgr(tmp_path):
    return CheckpointManager(tmp_path)


@pytest.fixture
def sm(mgr):
    return PipelineStateMachine(mgr)


def _meta(stage: StageID) -> MetaData:
    return MetaData(stage=stage.value, version=0)


def _valid_paper_artifacts() -> dict[str, str]:
    return {
        "sections/abstract.tex": "摘要",
        "sections/problem_restatement.tex": "问题重述",
        "sections/assumptions.tex": "假设",
        "sections/symbols.tex": "符号",
        "sections/model_solution.tex": "模型",
        "sections/sensitivity.tex": "灵敏度",
        "sections/evaluation.tex": "评价",
        "abstract_score.json": '{"score": 90, "needs_upstream_data": false}',
    }


def _run_and_approve(mgr, stage: StageID, content: str = "x"):
    mgr.save(stage, {"out.md": content}, _meta(stage))
    mgr.approve(stage)


def test_next_runnable_starts_at_analyze(sm):
    assert sm.get_next_runnable() == StageID.ANALYZE


def test_next_runnable_blocked_until_approval(sm, mgr):
    # analyze 已完成但未审批 → 没有可运行阶段（等待人工审批）
    mgr.save(StageID.ANALYZE, {"a.md": "x"}, _meta(StageID.ANALYZE))
    assert sm.get_next_runnable() is None

    # 审批后下一个可运行阶段是 eda
    mgr.approve(StageID.ANALYZE)
    assert sm.get_next_runnable() == StageID.EDA


def test_can_run_gate(sm, mgr):
    ok, _ = sm.can_run(StageID.ANALYZE)
    assert ok

    ok, reason = sm.can_run(StageID.EDA)
    assert not ok
    assert "analyze" in reason

    _run_and_approve(mgr, StageID.ANALYZE)
    ok, _ = sm.can_run(StageID.EDA)
    assert ok


def test_can_approve_states(sm, mgr):
    # 未运行 → 不可审批
    ok, reason = sm.can_approve(StageID.ANALYZE)
    assert not ok
    assert "尚未运行" in reason

    # completed → 可审批
    mgr.save(StageID.ANALYZE, {"a.md": "x"}, _meta(StageID.ANALYZE))
    ok, _ = sm.can_approve(StageID.ANALYZE)
    assert ok

    # 已审批 → 不可重复审批
    mgr.approve(StageID.ANALYZE)
    ok, reason = sm.can_approve(StageID.ANALYZE)
    assert not ok
    assert "已审批" in reason


def test_apply_rework_marks_downstream(sm, mgr):
    _run_and_approve(mgr, StageID.ANALYZE)
    _run_and_approve(mgr, StageID.EDA)
    _run_and_approve(mgr, StageID.RESEARCH)

    # analyze 重跑产生 v2，内容变了
    mgr.save(StageID.ANALYZE, {"out.md": "rework 后"}, _meta(StageID.ANALYZE))
    affected = sm.apply_rework(StageID.ANALYZE)

    assert "analyze" in affected
    assert "eda" in affected
    assert "research" in affected


def test_can_run_downstream_with_active_approved_version(sm, mgr, tmp_path):
    # model v1 已审批激活，v2 是 branch 出的未审批方案：下游 code 仍可运行
    from mmw.utils.file_io import write_yaml

    write_yaml(tmp_path / "config.yaml", {"name": "test", "active_versions": {}})

    for s in (StageID.ANALYZE, StageID.EDA, StageID.RESEARCH, StageID.MODEL):
        if s == StageID.MODEL:
            mgr.save(s, {
                "model.md": "模型",
                "verify_status.json": '{"severity": "pass", "issues": []}',
            }, _meta(s))
            mgr.approve(s)
        else:
            _run_and_approve(mgr, s)
    mgr.save(StageID.MODEL, {"out.md": "branch 方案"}, _meta(StageID.MODEL))

    ok, _ = sm.can_run(StageID.CODE)
    assert ok


def test_can_approve_specific_version(sm, mgr):
    verified = {"verify_status.json": '{"severity": "pass", "issues": []}'}
    mgr.save(StageID.MODEL, {"out.md": "v1", **verified}, _meta(StageID.MODEL))
    mgr.approve(StageID.MODEL)
    mgr.save(StageID.MODEL, {"out.md": "v2", **verified}, _meta(StageID.MODEL))

    # v2 是 completed，可审批；v1 已审批不可重复
    ok, _ = sm.can_approve(StageID.MODEL, version=2)
    assert ok
    ok, reason = sm.can_approve(StageID.MODEL, version=1)
    assert not ok
    assert "已审批" in reason


def test_code_approval_requires_successful_execution(sm, mgr):
    mgr.save(StageID.CODE, {
        "solution.py": "print('ok')",
        "run_log.txt": "[执行失败]\nSyntaxError",
    }, _meta(StageID.CODE))

    ok, reason = sm.can_approve(StageID.CODE)

    assert not ok
    assert "执行未成功" in reason


def test_code_approval_rejects_empty_stdout_and_stderr(sm, mgr):
    mgr.save(StageID.CODE, {
        "solution.py": "def unfinished():\n    return None",
        "run_log.txt": "STDOUT:\n\n\nSTDERR:\n",
    }, _meta(StageID.CODE))

    ok, reason = sm.can_approve(StageID.CODE)

    assert not ok
    assert "没有任何可验证输出" in reason


def test_code_approval_rejects_explicit_placeholder_result(sm, mgr):
    mgr.save(StageID.CODE, {
        "solution.py": "print('ok')",
        "run_log.txt": "未找到满足约束的速度解，使用默认值输出占位结果",
    }, _meta(StageID.CODE))

    ok, reason = sm.can_approve(StageID.CODE)

    assert not ok
    assert "可信可行解" in reason


def test_code_approval_rejects_penalty_as_optimum(sm, mgr):
    mgr.save(StageID.CODE, {
        "solution.py": "print('ok')",
        "run_log.txt": "警告：未找到严格满足约束的解，A_opt可能是罚函数值",
    }, _meta(StageID.CODE))

    ok, reason = sm.can_approve(StageID.CODE)

    assert not ok
    assert "罚函数值" in reason or "未找到满足约束" in reason


def test_code_allows_structured_infeasible_conclusion_without_placeholder(sm, mgr):
    mgr.save(StageID.CODE, {
        "solution.py": "print('done')",
        "run_log.txt": "未找到满足约束的方案；结构化记录可行方案数为0",
    }, _meta(StageID.CODE))

    ok, reason = sm.can_approve(StageID.CODE)

    assert ok, reason


def test_code_rejects_failed_optimization_replaced_by_reference_solution(sm, mgr):
    mgr.save(StageID.CODE, {
        "solution.py": "print('done')",
        "run_log.txt": (
            "[X] 加权优化未找到可行解,使用子问题3解计算对称性作参考.\n"
            "折中解 (基于单目标): A=476.26, S_ref=3.61"
        ),
    }, _meta(StageID.CODE))

    ok, reason = sm.can_approve(StageID.CODE)

    assert not ok
    assert "替代/参考解" in reason


def test_code_rejects_no_feasible_solution_replaced_by_other_subproblem(sm, mgr):
    mgr.save(StageID.CODE, {
        "solution.py": "print('done')",
        "run_log.txt": "无可行解,使用问题3解作为替代",
    }, _meta(StageID.CODE))

    ok, reason = sm.can_approve(StageID.CODE)

    assert not ok
    assert "替代/参考解" in reason


def test_code_rejects_final_constraint_failure(sm, mgr):
    mgr.save(StageID.CODE, {
        "solution.py": "print('done')",
        "run_log.txt": "最大可行速度: 60\n约束满足: False",
    }, _meta(StageID.CODE))

    ok, reason = sm.can_approve(StageID.CODE)

    assert not ok
    assert "违反约束" in reason


def test_code_rejects_explicitly_unfinished_subproblem(sm, mgr):
    mgr.save(StageID.CODE, {
        "solution.py": "print('done')",
        "run_log.txt": "聚焦搜索未找到可行解,无法完成子问题3",
    }, _meta(StageID.CODE))

    ok, reason = sm.can_approve(StageID.CODE)

    assert not ok
    assert "无法完成子问题" in reason


def test_code_rejects_no_feasible_or_approximate_solution(sm, mgr):
    mgr.save(StageID.CODE, {
        "solution.py": "print('严重: 未找到任何可行或近似解')",
        "run_log.txt": "严重: 未找到任何可行或近似解.请检查模型参数.",
    }, _meta(StageID.CODE))

    ok, reason = sm.can_approve(StageID.CODE)

    assert not ok
    assert "未找到任何可行或近似解" in reason


def test_code_rejects_infeasible_penalty_optimum(sm, mgr):
    mgr.save(StageID.CODE, {
        "solution.py": "print('近似最优(违反约束)')",
        "run_log.txt": "[结果] 近似最优(违反约束)传送带速度: 99.29 cm/min",
    }, _meta(StageID.CODE))

    ok, reason = sm.can_approve(StageID.CODE)

    assert not ok
    assert "违反约束" in reason


def test_old_reference_contract_does_not_affect_normal_approval(sm, mgr):
    contract = {
        "schema_version": 1,
        "results": [{"name": "q2_最大允许速度", "min": 76, "max": 80}],
    }
    mgr.save(StageID.CODE, {
        "solution.py": "print('done')",
        "run_log.txt": "STDOUT:\ndone",
        "reference_contract.json": json.dumps(contract, ensure_ascii=False),
        "results_preview.json": json.dumps([
            {"name": "q2_最大允许速度", "value": 99.29},
        ], ensure_ascii=False),
    }, _meta(StageID.CODE))

    ok, reason = sm.can_approve(StageID.CODE)

    assert ok, reason


def test_code_approval_rejects_non_finite_output(sm, mgr):
    mgr.save(StageID.CODE, {
        "solution.py": "print('ok')",
        "run_log.txt": "RMSE=nan, temperature=+inf",
    }, _meta(StageID.CODE))

    ok, reason = sm.can_approve(StageID.CODE)

    assert not ok
    assert "非有限数值" in reason


def test_model_approval_rejects_blocking_verifier_result(sm, mgr):
    mgr.save(StageID.MODEL, {
        "model.md": "模型",
        "verify_status.json": '{"severity": "block", "issues": []}',
    }, _meta(StageID.MODEL))

    ok, reason = sm.can_approve(StageID.MODEL)

    assert not ok
    assert "严重问题" in reason


def test_solve_approval_requires_non_empty_results(sm, mgr):
    mgr.save(StageID.SOLVE, {
        "run_log.txt": "STDOUT:\nok",
        "results.json": "[]",
    }, _meta(StageID.SOLVE))

    ok, reason = sm.can_approve(StageID.SOLVE)

    assert not ok
    assert "非空列表" in reason


def test_solve_requires_result_for_each_analyzed_subproblem(sm, mgr):
    mgr.save(StageID.ANALYZE, {
        "sub_problems.json": json.dumps({
            "sub_problems": [{"id": "q1"}, {"id": "q2"}],
        }),
    }, _meta(StageID.ANALYZE))
    mgr.save(StageID.SOLVE, {
        "run_log.txt": "STDOUT:\nok",
        "results.json": '[{"name": "q1_value", "value": 1, "unit": "", "desc": "结果"}]',
        "sensitivity.json": '{"baseline": {"objective": 1}, "experiments": [{"param": "a", "delta_pct": -10, "objective": 0.9, "change_pct": -10}, {"param": "b", "delta_pct": 10, "objective": 2, "change_pct": 100}]}',
        "deliverables_manifest.json": '{}',
    }, _meta(StageID.SOLVE))

    ok, reason = sm.can_approve(StageID.SOLVE)

    assert not ok
    assert "q2" in reason


def test_solve_rejects_explicit_validation_failure(sm, mgr):
    mgr.save(StageID.SOLVE, {
        "run_log.txt": "STDOUT:\nok",
        "results.json": '[{"name": "q2_验证状态", "value": 0, "unit": "", "desc": "1=通过, 0=失败"}]',
        "sensitivity.json": '{"baseline": {"objective": 1}, "experiments": [{"param": "a", "delta_pct": -10, "objective": 0.9, "change_pct": -10}, {"param": "b", "delta_pct": 10, "objective": 1.1, "change_pct": 10}]}',
        "figures_list.json": "[]",
        "deliverables_manifest.json": "{}",
    }, _meta(StageID.SOLVE))

    ok, reason = sm.can_approve(StageID.SOLVE)

    assert not ok
    assert "验证或校准失败" in reason


def test_solve_allows_honestly_unavailable_validation(sm, mgr):
    mgr.save(StageID.SOLVE, {
        "run_log.txt": "STDOUT:\nok",
        "results.json": '[{"name": "q2_验证状态", "value": 0, "unit": "", "desc": "代理序列为常数，验证不可用"}]',
        "sensitivity.json": '{"baseline": {"objective": 1}, "experiments": [{"param": "a", "delta_pct": -10, "objective": 0.9, "change_pct": -10}, {"param": "b", "delta_pct": 10, "objective": 1.1, "change_pct": 10}]}',
        "figures_list.json": "[]",
        "deliverables_manifest.json": "{}",
    }, _meta(StageID.SOLVE))

    ok, reason = sm.can_approve(StageID.SOLVE)

    assert ok, reason


def test_physical_percentage_results_must_stay_in_range():
    results = [
        {"name": "q3_最优收率", "value": 1000000.0, "unit": "%"},
        {"name": "q3_转化率预测", "value": -1291.52, "unit": "%"},
        {"name": "普通变化率", "value": -20, "unit": "%"},
    ]

    invalid = _invalid_physical_results(results)

    assert len(invalid) == 2
    assert any("最优收率" in item for item in invalid)


def test_physical_counts_times_and_distances_cannot_use_negative_sentinels():
    results = [
        {"name": "q3_推荐上车点数量", "value": -1, "unit": "个"},
        {"name": "q3_推荐等待时间", "value": -1, "unit": "分钟"},
        {"name": "q3_推荐步行距离", "value": -1, "unit": "米"},
        {"name": "q1_空载收益", "value": -7.58, "unit": "元"},
    ]

    invalid = _invalid_physical_results(results)

    assert len(invalid) == 3
    assert all("空载收益" not in item for item in invalid)


def test_bounded_dimensionless_results_must_stay_in_range():
    results = [
        {"name": "q4_最优基尼系数", "value": 1.12, "unit": ""},
        {"name": "q4_最优吞吐量下降", "value": -3.83, "unit": ""},
        {"name": "q2_方向一致性比率", "value": 0.04, "unit": ""},
        {"name": "q4_基尼系数降低百分比", "value": 2.7, "unit": "%"},
        {"name": "q2_航班缺失率", "value": 1.35, "unit": ""},
        {"name": "q4_插队概率", "value": 120, "unit": "%"},
    ]

    invalid = _invalid_physical_results(results)

    assert len(invalid) == 4
    assert any("基尼系数" in item for item in invalid)
    assert any("吞吐量下降" in item for item in invalid)
    assert any("缺失率" in item for item in invalid)
    assert any("插队概率" in item for item in invalid)


def test_rejects_extreme_png_aspect_ratio(tmp_path):
    png = tmp_path / "clusters.png"
    png.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\0" * 8 + (2065).to_bytes(4, "big") + (19939).to_bytes(4, "big"))

    assert _invalid_figure_aspect_ratios(tmp_path) == ["clusters.png=2065x19939"]


def test_solve_gate_checks_only_figures_listed_by_current_run(sm, mgr, tmp_path):
    figures = tmp_path / "figures"
    figures.mkdir()
    png = figures / "clusters.png"
    png.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\0" * 8 + (2065).to_bytes(4, "big") + (19939).to_bytes(4, "big"))
    mgr.save(StageID.SOLVE, {
        "run_log.txt": "STDOUT:\nok",
        "results.json": '[{"name": "q1_value", "value": 1, "unit": "", "desc": "结果"}]',
        "sensitivity.json": '{"baseline": {"objective": 1}, "experiments": [{"param": "a", "delta_pct": -10, "objective": 0.9, "change_pct": -10}, {"param": "b", "delta_pct": 10, "objective": 2, "change_pct": 100}]}',
        "figures_list.json": '["clusters.png"]',
        "deliverables_manifest.json": "{}",
    }, _meta(StageID.SOLVE))

    ok, reason = sm.can_approve(StageID.SOLVE)

    assert not ok
    assert "clusters.png=2065x19939" in reason


def test_paper_approval_rejects_missing_upstream_data(sm, mgr):
    mgr.save(StageID.PAPER, {
        **_valid_paper_artifacts(),
        "abstract_score.json": json.dumps({"score": 70, "needs_upstream_data": True}),
    }, _meta(StageID.PAPER))

    ok, reason = sm.can_approve(StageID.PAPER)

    assert not ok
    assert "上游求解数据" in reason


def test_paper_approval_rejects_missing_sections(sm, mgr):
    mgr.save(StageID.PAPER, {
        "sections/abstract.tex": "摘要",
        "abstract_score.json": '{"score": 90, "needs_upstream_data": false}',
    }, _meta(StageID.PAPER))

    ok, reason = sm.can_approve(StageID.PAPER)

    assert not ok
    assert "sections/model_solution.tex" in reason


def test_paper_approval_rejects_low_score_or_overlong_abstract(sm, mgr):
    sections = {
        "sections/abstract.tex": "摘要",
        "sections/problem_restatement.tex": "问题重述",
        "sections/assumptions.tex": "假设",
        "sections/symbols.tex": "符号",
        "sections/model_solution.tex": "模型",
        "sections/sensitivity.tex": "灵敏度",
        "sections/evaluation.tex": "评价",
    }
    mgr.save(StageID.PAPER, {
        **sections,
        "abstract_score.json": '{"score": 84, "needs_upstream_data": false}',
    }, _meta(StageID.PAPER))
    ok, reason = sm.can_approve(StageID.PAPER, version=1)
    assert not ok
    assert "低于 85" in reason

    mgr.save(StageID.PAPER, {
        **sections,
        "sections/abstract.tex": "摘" * 601,
        "abstract_score.json": '{"score": 90, "needs_upstream_data": false}',
    }, _meta(StageID.PAPER))
    ok, reason = sm.can_approve(StageID.PAPER, version=2)
    assert not ok
    assert "超过 600" in reason


def test_paper_requires_actual_citations_when_bibliography_exists(sm, mgr):
    mgr.save(StageID.PAPER, {
        **_valid_paper_artifacts(),
        "sections/model_solution.tex": "正文没有引用",
        "references.bib": "@book{x, title={X}}",
    }, _meta(StageID.PAPER))
    ok, reason = sm.can_approve(StageID.PAPER)
    assert not ok
    assert "cite" in reason


def test_paper_requires_all_core_solve_figures(sm, mgr):
    mgr.save(StageID.SOLVE, {
        "figures_list.json": '["fig_2_validation.png", "sensitivity_alpha.png"]',
    }, _meta(StageID.SOLVE))
    mgr.approve(StageID.SOLVE)
    mgr.save(StageID.PAPER, {
        **_valid_paper_artifacts(),
        "sections/model_solution.tex": "正文没有图",
    }, _meta(StageID.PAPER))

    ok, reason = sm.can_approve(StageID.PAPER)

    assert not ok
    assert "fig_2_validation.png" in reason
    assert "sensitivity_alpha.png" not in reason


def test_review_approval_rejects_fail_or_missing_checklist(sm, mgr):
    mgr.save(StageID.REVIEW, {"review.md": "无结构化清单"}, _meta(StageID.REVIEW))
    ok, reason = sm.can_approve(StageID.REVIEW, version=1)
    assert not ok
    assert "checklist.json" in reason

    mgr.save(StageID.REVIEW, {
        "checklist.json": json.dumps({
            "items": [{"check": "数值可追溯", "status": "fail", "note": "缺结果"}]
        }, ensure_ascii=False),
    }, _meta(StageID.REVIEW))
    ok, reason = sm.can_approve(StageID.REVIEW, version=2)
    assert not ok
    assert "fail" in reason


@pytest.mark.parametrize(
    ("stage", "artifacts"),
    [
        (StageID.MODEL, {
            "model.md": "模型",
            "verify_status.json": '{"severity": "warning", "issues": []}',
        }),
        (StageID.CODE, {"solution.py": "print('ok')", "run_log.txt": "STDOUT:\nok"}),
        (StageID.SOLVE, {
            "run_log.txt": "STDOUT:\nok",
            "results.json": '[{"name": "q1", "value": 1, "unit": "", "desc": "结果"}]',
            "sensitivity.json": '{"baseline": {"objective": 1}, "experiments": [{"param": "a", "delta_pct": -10, "objective": 0.9, "change_pct": -10}, {"param": "b", "delta_pct": 10, "objective": 2, "change_pct": 100}]}',
            "deliverables_manifest.json": '{}',
        }),
        (StageID.PAPER, _valid_paper_artifacts()),
        (StageID.REVIEW, {
            "checklist.json": '{"items": [{"check": "ok", "status": "pass"}]}',
        }),
    ],
)
def test_quality_gates_allow_valid_artifacts(sm, mgr, stage, artifacts):
    mgr.save(stage, artifacts, _meta(stage))

    ok, reason = sm.can_approve(stage)

    assert ok, reason


def test_sensitivity_rejects_parameters_with_only_zero_changes():
    error = _sensitivity_schema_error({
        "baseline": {"objective": 1},
        "experiments": [
            {"param": "a", "delta_pct": -10, "objective": 1, "change_pct": 0},
            {"param": "a", "delta_pct": 10, "objective": 1, "change_pct": 0},
            {"param": "b", "delta_pct": -10, "objective": 0.9, "change_pct": -10},
            {"param": "b", "delta_pct": 10, "objective": 1.1, "change_pct": 10},
        ],
    })

    assert "参数 a" in error
    assert "全为零" in error


def test_sensitivity_allows_extra_zero_parameters_when_two_are_informative():
    error = _sensitivity_schema_error({
        "baseline": {"objective": 1},
        "experiments": [
            {"param": "a", "delta_pct": -10, "objective": 1, "change_pct": 0},
            {"param": "b", "delta_pct": 10, "objective": 1, "change_pct": 0},
            {"param": "c", "delta_pct": -10, "objective": 0.9, "change_pct": -10},
            {"param": "d", "delta_pct": 10, "objective": 1.1, "change_pct": 10},
        ],
    })

    assert error == ""


def test_sensitivity_change_pct_must_match_objective_and_baseline():
    error = _sensitivity_schema_error({
        "baseline": {"objective": 0.5995},
        "experiments": [
            {
                "param": "lambda_f",
                "delta_pct": -20,
                "objective": 0.0,
                "change_pct": -98.2607,
            },
            {
                "param": "mu0",
                "delta_pct": 20,
                "objective": 0.0,
                "change_pct": 6759.3982,
            },
        ],
    })

    assert "不一致" in error


def test_sensitivity_zero_baseline_cannot_claim_nonzero_percentage_change():
    error = _sensitivity_schema_error({
        "baseline": {"objective": 0.0},
        "experiments": [
            {
                "param": "lambda_f",
                "delta_pct": -20,
                "objective": 0.0,
                "change_pct": -98.2607,
            },
            {
                "param": "mu0",
                "delta_pct": 20,
                "objective": 0.0,
                "change_pct": 6759.3982,
            },
        ],
    })

    assert "baseline.objective 为零" in error


def test_warnings_after_upstream_change(sm, mgr):
    _run_and_approve(mgr, StageID.ANALYZE)
    _run_and_approve(mgr, StageID.EDA)

    assert sm.get_warnings() == []

    mgr.save(StageID.ANALYZE, {"out.md": "变更"}, _meta(StageID.ANALYZE))
    mgr.approve(StageID.ANALYZE)
    mgr.refresh_upstream_flags()
    warnings = sm.get_warnings()
    assert any("eda" in w for w in warnings)
