from pathlib import Path

from mmw.managed_run import load_managed_run, run_managed_pipeline
from mmw.models import STAGE_ORDER, MetaData, StageID
from mmw.pipeline.state_machine import PipelineStateMachine
from mmw.utils.checkpoint import CheckpointManager
from mmw.utils.file_io import write_yaml


def _manager(tmp_path: Path) -> CheckpointManager:
    write_yaml(tmp_path / "config.yaml", {"name": "test", "active_versions": {}})
    return CheckpointManager(tmp_path)


def _runner(calls: list[StageID]):
    def run(stage: StageID, workspace: Path, mgr: CheckpointManager) -> bool:
        calls.append(stage)
        mgr.save(
            stage,
            {"artifact.txt": f"{stage.value}-{mgr.get_next_version(stage)}"},
            MetaData(stage=stage.value, version=0),
        )
        return True

    return run


def test_managed_run_activates_all_stages_and_finalizes(tmp_path: Path, monkeypatch):
    mgr = _manager(tmp_path)
    calls: list[StageID] = []
    decisions = []
    finalized = []
    monkeypatch.setattr(
        PipelineStateMachine,
        "can_approve",
        lambda self, stage, version=None: (bool(version), "" if version else "missing"),
    )
    monkeypatch.setattr(PipelineStateMachine, "quality_error", lambda *args: "")

    result = run_managed_pipeline(
        tmp_path,
        mgr,
        _runner(calls),
        lambda *args, **kwargs: decisions.append((args, kwargs)),
        lambda *args: None,
        lambda: finalized.append(True),
    )

    assert result["status"] == "completed"
    assert calls == STAGE_ORDER
    assert finalized == [True]
    assert len(decisions) == len(STAGE_ORDER)
    assert decisions[0][1]["actor"] == "managed-controller"
    assert mgr.load_status(StageID.ANALYZE, 1).approved_by == "托管控制器"
    assert load_managed_run(tmp_path)["last_action"] == "completed"


def test_managed_run_retries_once_then_activates(tmp_path: Path, monkeypatch):
    mgr = _manager(tmp_path)
    calls: list[StageID] = []

    def gate(self, stage, version=None):
        if stage == StageID.ANALYZE and version == 1:
            return False, "缺少分析证据"
        return bool(version), "" if version else "missing"

    monkeypatch.setattr(PipelineStateMachine, "can_approve", gate)
    monkeypatch.setattr(PipelineStateMachine, "quality_error", lambda *args: "")
    result = run_managed_pipeline(
        tmp_path,
        mgr,
        _runner(calls),
        lambda *args, **kwargs: None,
        lambda *args: None,
        lambda: None,
    )

    assert result["status"] == "completed"
    assert calls.count(StageID.ANALYZE) == 2
    assert result["total_reworks"] == 1
    assert mgr.get_active_version(StageID.ANALYZE) == 2


def test_managed_run_pauses_on_repeated_identical_error(tmp_path: Path, monkeypatch):
    mgr = _manager(tmp_path)
    monkeypatch.setattr(
        PipelineStateMachine,
        "can_approve",
        lambda self, stage, version=None: (False, "同一错误"),
    )
    result = run_managed_pipeline(
        tmp_path,
        mgr,
        _runner([]),
        lambda *args, **kwargs: None,
        lambda *args: None,
        lambda: None,
    )

    assert result["status"] == "waiting_user"
    assert result["stage"] == "analyze"
    assert result["last_error"] == "同一错误"
    assert result["total_reworks"] == 1


def test_managed_run_hard_stop_does_not_retry(tmp_path: Path, monkeypatch):
    mgr = _manager(tmp_path)
    calls: list[StageID] = []
    monkeypatch.setattr(
        PipelineStateMachine,
        "can_approve",
        lambda self, stage, version=None: (False, "结果包含非有限数值"),
    )
    result = run_managed_pipeline(
        tmp_path,
        mgr,
        _runner(calls),
        lambda *args, **kwargs: None,
        lambda *args: None,
        lambda: None,
    )

    assert result["status"] == "waiting_user"
    assert calls == [StageID.ANALYZE]
    assert result["total_reworks"] == 0


def test_managed_run_redacts_unexpected_stage_error(tmp_path: Path):
    mgr = _manager(tmp_path)

    def fail(*args):
        raise RuntimeError("provider response with secret")

    result = run_managed_pipeline(
        tmp_path,
        mgr,
        fail,
        lambda *args, **kwargs: None,
        lambda *args: None,
        lambda: None,
    )

    assert result["status"] == "waiting_user"
    assert result["last_error"] == "RuntimeError，请查看工作区日志"
