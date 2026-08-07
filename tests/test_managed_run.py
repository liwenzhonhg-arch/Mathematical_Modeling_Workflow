import json
from pathlib import Path
from types import SimpleNamespace

from mmw.config import LLMConfig
from mmw.llm import LLMClient
from mmw.managed_run import (
    _actionable_stage_error,
    _budget_summary,
    _token_total,
    load_managed_run,
    run_managed_pipeline,
)
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


def test_managed_run_routes_code_model_failure_back_to_model(
    tmp_path: Path, monkeypatch,
):
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
        if stage == StageID.CODE and calls.count(StageID.MODEL) == 1:
            return False, "代码实证要求重做 model：当前模型契约无法通过硬门禁"
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
    assert calls.count(StageID.MODEL) == 2
    assert calls.count(StageID.CODE) == 2


def test_managed_run_routes_review_failure_to_declared_upstream_stage(
    tmp_path: Path, monkeypatch,
):
    mgr = _manager(tmp_path)
    calls: list[StageID] = []

    def run(stage: StageID, workspace: Path, manager: CheckpointManager) -> bool:
        calls.append(stage)
        artifacts = {"artifact.txt": "ok"}
        if stage == StageID.REVIEW:
            artifacts["checklist.json"] = json.dumps({
                "items": [{
                    "check": "模型与求解算法一致性",
                    "status": "fail" if calls.count(StageID.MODEL) == 1 else "pass",
                    "note": "MILP 缺少算法依赖的约束",
                }],
            })
        manager.save(stage, artifacts, MetaData(stage=stage.value, version=0))
        return True

    def gate(self, stage, version=None):
        if not version:
            return False, "missing"
        status = self.mgr.load_status(stage, version)
        if status.status.value == "pending":
            return False, f"阶段 '{stage.value}' 尚未完成"
        if status.upstream_changed:
            return False, f"阶段 '{stage.value}' 的上游已变更，请重新运行"
        if stage == StageID.REVIEW and calls.count(StageID.MODEL) == 1:
            return False, "review checklist 存在 fail 或非法状态，不能审批"
        return True, ""

    monkeypatch.setattr(PipelineStateMachine, "can_approve", gate)
    monkeypatch.setattr(PipelineStateMachine, "quality_error", lambda *args: "")
    result = run_managed_pipeline(
        tmp_path,
        mgr,
        run,
        lambda *args, **kwargs: None,
        lambda *args: None,
        lambda: None,
    )

    assert result["status"] == "completed", result
    assert calls.count(StageID.MODEL) == 2
    assert calls.count(StageID.REVIEW) == 2


def test_managed_run_distinguishes_changed_review_rework_target(
    tmp_path: Path, monkeypatch,
):
    mgr = _manager(tmp_path)
    calls: list[StageID] = []

    def run(stage: StageID, workspace: Path, manager: CheckpointManager) -> bool:
        calls.append(stage)
        artifacts = {"artifact.txt": "ok"}
        if stage == StageID.REVIEW:
            review_count = calls.count(StageID.REVIEW)
            if review_count == 1:
                item = {"check": "摘要格式", "status": "fail", "note": "论文摘要需修订"}
            elif review_count == 2:
                item = {"check": "模型约束", "status": "fail", "note": "方程逻辑需修订"}
            else:
                item = {"check": "结果", "status": "pass", "note": "通过"}
            artifacts["checklist.json"] = json.dumps({"items": [item]})
        manager.save(stage, artifacts, MetaData(stage=stage.value, version=0))
        return True

    def gate(self, stage, version=None):
        if not version:
            return False, "missing"
        status = self.mgr.load_status(stage, version)
        if status.status.value == "pending":
            return False, f"阶段 '{stage.value}' 尚未完成"
        if status.upstream_changed:
            return False, f"阶段 '{stage.value}' 的上游已变更，请重新运行"
        if stage == StageID.REVIEW and calls.count(StageID.REVIEW) <= 2:
            return False, "review checklist 存在 fail 或非法状态，不能审批"
        return True, ""

    monkeypatch.setattr(PipelineStateMachine, "can_approve", gate)
    monkeypatch.setattr(PipelineStateMachine, "quality_error", lambda *args: "")
    result = run_managed_pipeline(
        tmp_path,
        mgr,
        run,
        lambda *args, **kwargs: None,
        lambda *args: None,
        lambda: None,
        max_stage_reworks=3,
        max_total_reworks=4,
    )

    assert result["status"] == "completed", result
    assert calls.count(StageID.PAPER) == 3
    assert calls.count(StageID.MODEL) == 2
    assert calls.count(StageID.REVIEW) == 3


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


def test_managed_run_reports_first_structured_model_issue(tmp_path: Path):
    mgr = _manager(tmp_path)
    mgr.save(StageID.MODEL, {
        "verify_status.json": json.dumps({
            "severity": "block",
            "issues": [{"category": "公式", "summary": "空罐边界极值方向写反"}],
        }, ensure_ascii=False),
    }, MetaData(stage=StageID.MODEL.value, version=0))

    assert _actionable_stage_error(
        StageID.MODEL, mgr, 1, "Verifier 阻断",
    ) == "model v1：空罐边界极值方向写反"


def test_managed_run_reports_first_review_failure(tmp_path: Path):
    mgr = _manager(tmp_path)
    mgr.save(StageID.REVIEW, {
        "checklist.json": json.dumps({
            "items": [
                {"check": "原始参数表", "status": "fail", "note": "正文缺少输入数据"},
                {"check": "数值审计", "status": "pass", "note": "通过"},
            ],
        }, ensure_ascii=False),
    }, MetaData(stage=StageID.REVIEW.value, version=0))

    assert _actionable_stage_error(
        StageID.REVIEW, mgr, 1, "review checklist 存在 fail 或非法状态，不能审批",
    ) == "review v1：原始参数表：正文缺少输入数据"


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


def test_managed_run_stops_at_llm_request_boundary(tmp_path: Path):
    mgr = _manager(tmp_path)
    calls = []

    def run(stage: StageID, workspace: Path, manager: CheckpointManager) -> bool:
        client = LLMClient(LLMConfig(api_key="", backend="codex"))
        def fake_chat(messages):
            calls.append("request")
            client._track_usage(
                SimpleNamespace(prompt_tokens=60, completion_tokens=50),
                messages,
                "result",
            )
            return "result"

        client._chat_codex = fake_chat
        calls.append(client.chat([{"role": "user", "content": "first"}]))
        client.chat([{"role": "user", "content": "second"}])
        return True

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
    assert "请求边界预算" in result["last_error"]
    assert calls == ["request", "result"]
    persisted = json.loads((tmp_path / "managed-run.json").read_text(encoding="utf-8"))
    assert persisted["tokens_used"] == 110


def test_managed_run_stops_next_request_at_active_time_boundary(
    tmp_path: Path, monkeypatch,
):
    mgr = _manager(tmp_path)
    clock = [0.0]
    calls = []
    monkeypatch.setattr("mmw.managed_run.time.monotonic", lambda: clock[0])

    def run(stage: StageID, workspace: Path, manager: CheckpointManager) -> bool:
        client = LLMClient(LLMConfig(api_key="", backend="codex"))

        def fake_chat(messages):
            calls.append("request")
            clock[0] = 61.0
            return "result"

        client._chat_codex = fake_chat
        client.chat([{"role": "user", "content": "first"}])
        client.chat([{"role": "user", "content": "second"}])
        return True

    result = run_managed_pipeline(
        tmp_path,
        mgr,
        run,
        lambda *args, **kwargs: None,
        lambda *args: None,
        lambda: None,
        max_total_minutes=1,
    )

    assert result["status"] == "waiting_user"
    assert "活跃时间请求边界" in result["last_error"]
    assert calls == ["request"]


def test_token_total_prefers_unique_call_logs_over_cumulative_meta(tmp_path: Path):
    mgr = _manager(tmp_path)
    mgr.save(
        StageID.ANALYZE,
        {"artifact.txt": "v1"},
        MetaData(stage="analyze", version=0, tokens_input=100, tokens_output=20),
    )
    mgr.save(
        StageID.ANALYZE,
        {"artifact.txt": "v2"},
        MetaData(stage="analyze", version=0, tokens_input=200, tokens_output=40),
    )
    mgr.paths.logs.mkdir(parents=True, exist_ok=True)
    (mgr.paths.logs / "call-1.json").write_text(
        json.dumps({"input_tokens": 50, "output_tokens": 10}),
        encoding="utf-8",
    )
    (mgr.paths.logs / "call-2.json").write_text(
        json.dumps({"input_tokens": 40, "output_tokens": 5}),
        encoding="utf-8",
    )

    assert _token_total(mgr) == (105, True)


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
