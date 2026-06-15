"""状态机测试：阶段转移门控、审批条件、rework 影响范围。"""

import pytest

from mmw.models import MetaData, StageID
from mmw.pipeline.state_machine import PipelineStateMachine
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
        _run_and_approve(mgr, s)
    mgr.save(StageID.MODEL, {"out.md": "branch 方案"}, _meta(StageID.MODEL))

    ok, _ = sm.can_run(StageID.CODE)
    assert ok


def test_can_approve_specific_version(sm, mgr):
    mgr.save(StageID.MODEL, {"out.md": "v1"}, _meta(StageID.MODEL))
    mgr.approve(StageID.MODEL)
    mgr.save(StageID.MODEL, {"out.md": "v2"}, _meta(StageID.MODEL))

    # v2 是 completed，可审批；v1 已审批不可重复
    ok, _ = sm.can_approve(StageID.MODEL, version=2)
    assert ok
    ok, reason = sm.can_approve(StageID.MODEL, version=1)
    assert not ok
    assert "已审批" in reason


def test_warnings_after_upstream_change(sm, mgr):
    _run_and_approve(mgr, StageID.ANALYZE)
    _run_and_approve(mgr, StageID.EDA)

    assert sm.get_warnings() == []

    mgr.save(StageID.ANALYZE, {"out.md": "变更"}, _meta(StageID.ANALYZE))
    mgr.refresh_upstream_flags()
    warnings = sm.get_warnings()
    assert any("eda" in w for w in warnings)
