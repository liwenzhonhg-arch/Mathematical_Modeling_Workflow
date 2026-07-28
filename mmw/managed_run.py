"""显式托管运行：复用现有阶段入口、质量门禁和检查点。"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any, Callable
from uuid import uuid4

from mmw.models import STAGE_ORDER, CheckpointStatus, StageID
from mmw.pipeline.state_machine import PipelineStateMachine
from mmw.project import ProjectPaths
from mmw.utils.checkpoint import CheckpointManager
from mmw.utils.file_io import read_json, write_json

RunStage = Callable[[StageID, Path, CheckpointManager], bool | None]
RecordDecision = Callable[..., None]
Progress = Callable[[StageID | None, str, str, int, int], None]


def managed_run_path(workspace: Path) -> Path:
    return ProjectPaths(workspace).internal / "managed-run.json"


def load_managed_run(workspace: Path) -> dict[str, Any]:
    path = managed_run_path(workspace)
    if not path.is_file():
        return {}
    try:
        data = read_json(path)
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def run_managed_pipeline(
    workspace: Path,
    mgr: CheckpointManager,
    run_stage: RunStage,
    record_decision: RecordDecision,
    progress: Progress,
    finalize: Callable[[], None],
    *,
    max_stage_reworks: int = 2,
    max_total_reworks: int = 8,
    run_id: str | None = None,
) -> dict[str, Any]:
    if not 0 <= max_stage_reworks <= 10 or not 0 <= max_total_reworks <= 40:
        raise ValueError("托管重做预算超出允许范围")

    previous = load_managed_run(workspace)
    continuing = bool(run_id and previous.get("run_id") == run_id)
    state: dict[str, Any] = {
        "run_id": run_id or uuid4().hex,
        "policy": "managed-v1",
        "status": "running",
        "stage": None,
        "version": None,
        "max_stage_reworks": max_stage_reworks,
        "max_total_reworks": max_total_reworks,
        "stage_reworks": previous.get("stage_reworks", {}) if continuing else {},
        "total_reworks": int(previous.get("total_reworks", 0)) if continuing else 0,
        "error_counts": previous.get("error_counts", {}) if continuing else {},
        "last_error": previous.get("last_error", "") if continuing else "",
        "last_action": "started",
        "started_at": previous.get("started_at") or _now(),
        "updated_at": _now(),
    }
    error_counts: dict[str, int] = state["error_counts"]

    def save() -> None:
        state["updated_at"] = _now()
        write_json(managed_run_path(workspace), state)

    save()
    sm = PipelineStateMachine(mgr)
    for index, stage in enumerate(STAGE_ORDER, 1):
        state["stage"] = stage.value
        while True:
            latest = mgr.get_latest_version(stage)
            active = mgr.get_active_version(stage)
            active_status = mgr.load_status(stage, active) if active else None
            if (
                active_status
                and active_status.status == CheckpointStatus.APPROVED
                and not active_status.upstream_changed
                and not sm.quality_error(stage, active)
            ):
                state["version"] = active
                state["last_action"] = "skipped-approved"
                save()
                break

            if latest:
                can_approve, gate_error = sm.can_approve(stage, latest)
            else:
                can_approve, gate_error = False, ""
            if not can_approve:
                can_run, run_error = sm.can_run(stage)
                if not can_run:
                    return _pause(state, save, progress, stage, run_error, index)
                if latest:
                    sm.apply_rework(stage)
                repair = int(state["stage_reworks"].get(stage.value, 0))
                progress(
                    stage,
                    "running_stage",
                    f"执行阶段，自动修复 {repair}/{max_stage_reworks}",
                    index,
                    len(STAGE_ORDER) + 1,
                )
                state["last_action"] = "running-stage"
                save()
                try:
                    ran = run_stage(stage, workspace, mgr)
                except Exception as exc:
                    return _pause(
                        state,
                        save,
                        progress,
                        stage,
                        f"{exc.__class__.__name__}，请查看工作区日志",
                        index,
                    )
                latest = mgr.get_latest_version(stage)
                can_approve, gate_error = sm.can_approve(stage, latest) if latest else (
                    False,
                    "阶段没有生成新检查点",
                )
                if ran is False and not gate_error:
                    gate_error = "阶段执行失败"

            if can_approve:
                mgr.approve(stage, version=latest, approved_by="托管控制器")
                record_decision(
                    workspace,
                    stage,
                    latest,
                    "activate",
                    "机器质量门禁通过",
                    actor="managed-controller",
                    policy="managed-v1",
                    gate_snapshot={"quality_error": "", "contract": "passed"},
                )
                state["version"] = latest
                state["last_error"] = ""
                state["last_action"] = "activated"
                save()
                break

            error_key = f"{stage.value}:{gate_error}"
            error_counts[error_key] = error_counts.get(error_key, 0) + 1
            stage_reworks = int(state["stage_reworks"].get(stage.value, 0))
            if (
                _must_pause(gate_error)
                or error_counts[error_key] > 1
                or stage_reworks >= max_stage_reworks
                or int(state["total_reworks"]) >= max_total_reworks
            ):
                return _pause(state, save, progress, stage, gate_error, index)

            state["stage_reworks"][stage.value] = stage_reworks + 1
            state["total_reworks"] = int(state["total_reworks"]) + 1
            state["last_error"] = gate_error
            state["last_action"] = "repairing"
            record_decision(
                workspace,
                stage,
                latest,
                "rework",
                gate_error,
                actor="managed-controller",
                policy="managed-v1",
            )
            save()

    progress(None, "finalizing", "编译论文并导出提交包", len(STAGE_ORDER) + 1, len(STAGE_ORDER) + 1)
    state["stage"] = None
    state["last_action"] = "finalizing"
    save()
    try:
        finalize()
    except (OSError, RuntimeError, ValueError) as exc:
        return _pause(state, save, progress, None, str(exc), len(STAGE_ORDER) + 1)
    state["status"] = "completed"
    state["last_action"] = "completed"
    state["finished_at"] = _now()
    save()
    return state


def _pause(
    state: dict[str, Any],
    save: Callable[[], None],
    progress: Progress,
    stage: StageID | None,
    error: str,
    index: int,
) -> dict[str, Any]:
    state["status"] = "waiting_user"
    state["stage"] = stage.value if stage else None
    state["last_error"] = error or "需要人工处理"
    state["last_action"] = "paused"
    state["finished_at"] = _now()
    save()
    progress(stage, "waiting_user", state["last_error"], index, len(STAGE_ORDER) + 1)
    return state


def _must_pause(error: str) -> bool:
    lowered = error.casefold()
    return any(
        token in lowered
        for token in (
            "api key",
            "凭据",
            ".env",
            "题目正文",
            "原始数据",
            "oracle",
            "reference_expected",
            "硬约束缺失",
            "非有限数值",
            "不是有限数值",
            "占位结果",
            "罚函数值",
        )
    )


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")
