from pathlib import Path

from mmw.managed_run import _budget_summary, load_managed_run, run_managed_pipeline
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

    assert result["status"] == "completed", result
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


def test_managed_run_routes_solve_data_failure_back_to_code(tmp_path: Path, monkeypatch):
    mgr = _manager(tmp_path)
    calls: list[StageID] = []

    def gate(self, stage, version=None):
        if not version:
            return False, "missing"
        status = self.mgr.load_status(stage, version)
        if status.status.value == "pending":
            return False, f"阶段 '{stage.value}' 尚未完成"
        if status.upstream_changed:
            return False, f"阶段 '{stage.value}' 的上游已变更，请重新运行"
        if stage == StageID.SOLVE and calls.count(StageID.CODE) == 1:
            return False, "sensitivity.json 至少需要 2 个非零敏感参数"
        return True, ""

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

    assert result["status"] == "completed", result
    assert calls.count(StageID.CODE) == 2
    assert calls.count(StageID.SOLVE) == 2


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


def test_managed_run_pauses_after_token_budget_is_spent(tmp_path: Path, monkeypatch):
    mgr = _manager(tmp_path)

    def run(stage: StageID, workspace: Path, manager: CheckpointManager) -> bool:
        manager.save(
            stage,
            {"artifact.txt": "ok"},
            MetaData(stage=stage.value, version=0, tokens_input=60, tokens_output=50),
        )
        return True

    monkeypatch.setattr(
        PipelineStateMachine,
        "can_approve",
        lambda self, stage, version=None: (bool(version), "" if version else "missing"),
    )
    result = run_managed_pipeline(
        tmp_path,
        mgr,
        run,
        lambda *args, **kwargs: None,
        lambda *args: None,
        lambda: None,
        max_total_tokens=100,
    )

    assert result["status"] == "waiting_user"
    assert result["tokens_used"] == 110
    assert "token 预算" in result["last_error"]
    assert mgr.get_active_version(StageID.ANALYZE) == 1
    assert not mgr.is_approved(StageID.ANALYZE, 1)


def test_managed_run_pauses_on_total_active_time_budget(tmp_path: Path, monkeypatch):
    mgr = _manager(tmp_path)
    ticks = iter(range(1000))
    monkeypatch.setattr("mmw.managed_run.time.monotonic", lambda: next(ticks) * 61.0)

    result = run_managed_pipeline(
        tmp_path,
        mgr,
        _runner([]),
        lambda *args, **kwargs: None,
        lambda *args: None,
        lambda: None,
        max_total_minutes=1,
    )

    assert result["status"] == "waiting_user"
    assert "总时长预算" in result["last_error"]
    assert result["stage"] == "analyze"


def test_new_managed_run_does_not_inherit_previous_start_time(tmp_path: Path, monkeypatch):
    mgr = _manager(tmp_path)
    first = run_managed_pipeline(
        tmp_path, mgr, _runner([]), lambda *args, **kwargs: None,
        lambda *args: None, lambda: None,
    )
    monkeypatch.setattr("mmw.managed_run._now", lambda: "2099-01-01T00:00:00")
    second = run_managed_pipeline(
        tmp_path, mgr, _runner([]), lambda *args, **kwargs: None,
        lambda *args: None, lambda: None,
    )

    assert second["run_id"] != first["run_id"]
    assert second["started_at"] == "2099-01-01T00:00:00"


def test_managed_run_reports_wall_time_separately_from_active_budget(
    tmp_path: Path, monkeypatch,
):
    mgr = _manager(tmp_path)
    monkeypatch.setattr(
        "mmw.managed_run._wall_elapsed_seconds",
        lambda started_at: 600.0,
    )
    result = run_managed_pipeline(
        tmp_path, mgr, _runner([]), lambda *args, **kwargs: None,
        lambda *args: None, lambda: None,
    )

    assert result["wall_elapsed_seconds"] == 600.0
    assert "墙钟 10 分钟" in _budget_summary(result)
