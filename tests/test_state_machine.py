"""状态机测试：阶段转移门控、审批条件、rework 影响范围。"""

import json

import pytest

from mmw.models import MetaData, StageID
from mmw.pipeline.state_machine import PipelineStateMachine, _invalid_physical_results
from mmw.utils.checkpoint import CheckpointManager


@pytest.fixture
def mgr(tmp_path):
    return CheckpointManager(tmp_path)


@pytest.fixture
def sm(mgr):
    return PipelineStateMachine(mgr)


def _meta(stage: StageID) -> MetaData:
    return MetaData(stage=stage.value, version=0)


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


def test_physical_percentage_results_must_stay_in_range():
    results = [
        {"name": "q3_最优收率", "value": 1000000.0, "unit": "%"},
        {"name": "q3_转化率预测", "value": -1291.52, "unit": "%"},
        {"name": "普通变化率", "value": -20, "unit": "%"},
    ]

    invalid = _invalid_physical_results(results)

    assert len(invalid) == 2
    assert any("最优收率" in item for item in invalid)


def test_paper_approval_rejects_missing_upstream_data(sm, mgr):
    mgr.save(StageID.PAPER, {
        "abstract_score.json": json.dumps({"score": 70, "needs_upstream_data": True}),
    }, _meta(StageID.PAPER))

    ok, reason = sm.can_approve(StageID.PAPER)

    assert not ok
    assert "上游求解数据" in reason


def test_paper_requires_actual_citations_when_bibliography_exists(sm, mgr):
    mgr.save(StageID.PAPER, {
        "abstract_score.json": '{"score": 90, "needs_upstream_data": false}',
        "sections/model_solution.tex": "正文没有引用",
        "references.bib": "@book{x, title={X}}",
    }, _meta(StageID.PAPER))
    ok, reason = sm.can_approve(StageID.PAPER)
    assert not ok
    assert "cite" in reason


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
            "sensitivity.json": '{"baseline": {"objective": 1}, "experiments": [{"param": "a", "delta_pct": -10, "objective": 1, "change_pct": 0}, {"param": "b", "delta_pct": 10, "objective": 2, "change_pct": 100}]}',
            "deliverables_manifest.json": '{}',
        }),
        (StageID.PAPER, {
            "abstract_score.json": '{"score": 90, "needs_upstream_data": false}',
        }),
        (StageID.REVIEW, {
            "checklist.json": '{"items": [{"check": "ok", "status": "pass"}]}',
        }),
    ],
)
def test_quality_gates_allow_valid_artifacts(sm, mgr, stage, artifacts):
    mgr.save(stage, artifacts, _meta(stage))

    ok, reason = sm.can_approve(stage)

    assert ok, reason


def test_warnings_after_upstream_change(sm, mgr):
    _run_and_approve(mgr, StageID.ANALYZE)
    _run_and_approve(mgr, StageID.EDA)

    assert sm.get_warnings() == []

    mgr.save(StageID.ANALYZE, {"out.md": "变更"}, _meta(StageID.ANALYZE))
    mgr.approve(StageID.ANALYZE)
    mgr.refresh_upstream_flags()
    warnings = sm.get_warnings()
    assert any("eda" in w for w in warnings)
