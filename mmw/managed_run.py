"""显式托管运行：复用现有阶段入口、质量门禁和检查点。"""

from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path
import time
from typing import Any, Callable
from uuid import uuid4

from mmw.agents.reviewer import get_review_rework_stage
from mmw.llm import observe_token_usage
from mmw.models import STAGE_ORDER, CheckpointStatus, StageID
from mmw.pipeline.state_machine import PipelineStateMachine
from mmw.project import ProjectPaths
from mmw.utils.checkpoint import CheckpointManager
from mmw.utils.file_io import read_json, write_json

RunStage = Callable[[StageID, Path, CheckpointManager], bool | None]
RecordDecision = Callable[..., None]
Progress = Callable[[StageID | None, str, str, int, int], None]


class TokenBudgetExceeded(RuntimeError):
    pass


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
    max_total_tokens: int = 0,
    max_total_minutes: int = 0,
    run_id: str | None = None,
) -> dict[str, Any]:
    if (
        not 0 <= max_stage_reworks <= 10
        or not 0 <= max_total_reworks <= 40
        or not 0 <= max_total_tokens <= 100_000_000
        or not 0 <= max_total_minutes <= 10_080
    ):
        raise ValueError("托管重做预算超出允许范围")

    previous = load_managed_run(workspace)
    continuing = bool(run_id and previous.get("run_id") == run_id)
    session_started = time.monotonic()
    elapsed_before = float(previous.get("elapsed_seconds", 0)) if continuing else 0.0
    token_total, token_available = _token_total(mgr)
    state: dict[str, Any] = {
        "run_id": run_id or uuid4().hex,
        "policy": "managed-v1",
        "status": "running",
        "stage": None,
        "version": None,
        "max_stage_reworks": max_stage_reworks,
        "max_total_reworks": max_total_reworks,
        "max_total_tokens": max_total_tokens,
        "max_total_minutes": max_total_minutes,
        "stage_reworks": previous.get("stage_reworks", {}) if continuing else {},
        "total_reworks": int(previous.get("total_reworks", 0)) if continuing else 0,
        "error_counts": previous.get("error_counts", {}) if continuing else {},
        "last_error": previous.get("last_error", "") if continuing else "",
        "last_action": "started",
        "started_at": (previous.get("started_at") or _now()) if continuing else _now(),
        "elapsed_seconds": elapsed_before,
        "wall_elapsed_seconds": 0.0,
        "token_baseline": int(previous.get("token_baseline", token_total)) if continuing else token_total,
        "tokens_used": 0,
        "token_usage_available": token_available,
        "updated_at": _now(),
    }
    error_counts: dict[str, int] = state["error_counts"]
    observed_tokens = max(0, token_total - int(state["token_baseline"]))
    token_budget_reached = False
    if continuing and not token_available:
        observed_tokens = max(
            observed_tokens,
            int(previous.get("tokens_used", 0)),
        )

    def save() -> None:
        current_tokens, available = _token_total(mgr)
        state["elapsed_seconds"] = round(
            elapsed_before + time.monotonic() - session_started, 3,
        )
        state["wall_elapsed_seconds"] = _wall_elapsed_seconds(state["started_at"])
        state["tokens_used"] = max(
            observed_tokens,
            max(0, current_tokens - int(state["token_baseline"])),
        )
        state["token_usage_available"] = available or observed_tokens > 0
        state["updated_at"] = _now()
        write_json(managed_run_path(workspace), state)

    def observe_usage(input_tokens: int, output_tokens: int) -> None:
        nonlocal observed_tokens, token_budget_reached
        observed_tokens += input_tokens + output_tokens
        state["tokens_used"] = observed_tokens
        state["token_usage_available"] = True
        if max_total_tokens and observed_tokens >= max_total_tokens:
            token_budget_reached = True
        save()
        progress(
            StageID(state["stage"]) if state.get("stage") else None,
            "running_stage",
            f"LLM 请求完成 · {_budget_summary(state)}",
            index,
            len(STAGE_ORDER) + 1,
        )

    def guard_request() -> None:
        if token_budget_reached:
            raise TokenBudgetExceeded(
                f"托管 token 请求边界预算已用尽（{max_total_tokens}）"
            )

    save()
    sm = PipelineStateMachine(mgr)
    index = 1
    while index <= len(STAGE_ORDER):
        stage = STAGE_ORDER[index - 1]
        restart_index = None
        state["stage"] = stage.value
        while True:
            save()
            if budget_error := _budget_error(state):
                return _pause(state, save, progress, stage, budget_error, index)
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
                gate_error = _actionable_stage_error(stage, mgr, latest, gate_error)
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
                    f"执行阶段，自动修复 {repair}/{max_stage_reworks} · {_budget_summary(state)}",
                    index,
                    len(STAGE_ORDER) + 1,
                )
                state["last_action"] = "running-stage"
                save()
                try:
                    with observe_token_usage(observe_usage, guard_request):
                        ran = run_stage(stage, workspace, mgr)
                except TokenBudgetExceeded as exc:
                    return _pause(state, save, progress, stage, str(exc), index)
                except Exception as exc:
                    return _pause(
                        state,
                        save,
                        progress,
                        stage,
                        _actionable_stage_error(
                            stage,
                            mgr,
                            mgr.get_latest_version(stage),
                            f"{exc.__class__.__name__}，请查看工作区日志",
                        ),
                        index,
                    )
                latest = mgr.get_latest_version(stage)
                can_approve, gate_error = sm.can_approve(stage, latest) if latest else (
                    False,
                    "阶段没有生成新检查点",
                )
                gate_error = _actionable_stage_error(stage, mgr, latest, gate_error)
                save()
                if budget_error := _budget_error(state):
                    return _pause(state, save, progress, stage, budget_error, index)
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
            repair_stage = _upstream_repair_stage(stage, gate_error, mgr, latest)
            if (
                repair_stage
                and error_counts[error_key] == 1
                and int(state["stage_reworks"].get(repair_stage.value, 0)) < max_stage_reworks
                and int(state["total_reworks"]) < max_total_reworks
            ):
                repair_version = mgr.get_latest_version(repair_stage)
                sm.apply_rework(repair_stage)
                state["stage_reworks"][repair_stage.value] = (
                    int(state["stage_reworks"].get(repair_stage.value, 0)) + 1
                )
                state["total_reworks"] = int(state["total_reworks"]) + 1
                state["last_error"] = gate_error
                state["last_action"] = "repairing-upstream"
                record_decision(
                    workspace,
                    repair_stage,
                    repair_version,
                    "rework",
                    f"{stage.value} 门禁反馈：{gate_error}",
                    actor="managed-controller",
                    policy="managed-v1",
                )
                restart_index = STAGE_ORDER.index(repair_stage) + 1
                save()
                break
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
        index = restart_index or (index + 1)

    save()
    if budget_error := _budget_error(state):
        return _pause(
            state, save, progress, None, budget_error, len(STAGE_ORDER) + 1,
        )
    progress(
        None,
        "finalizing",
        f"编译论文并导出提交包 · {_budget_summary(state)}",
        len(STAGE_ORDER) + 1,
        len(STAGE_ORDER) + 1,
    )
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


def _actionable_stage_error(
    stage: StageID,
    mgr: CheckpointManager,
    version: int,
    fallback: str,
) -> str:
    """只从结构化检查点提取可公开的首要失败原因。"""
    if version <= 0:
        return fallback
    artifacts = mgr.load_artifacts(stage, version)
    candidates: list[str] = []
    if stage == StageID.MODEL:
        try:
            status = json.loads(artifacts.get("verify_status.json", "{}"))
        except json.JSONDecodeError:
            status = {}
        issues = status.get("issues") if isinstance(status, dict) else None
        if (
            status.get("severity") == "block"
            and isinstance(issues, list)
            and issues
            and isinstance(issues[0], dict)
        ):
            candidates.append(str(issues[0].get("summary", "")))
    elif stage == StageID.CODE:
        try:
            request = json.loads(artifacts.get("rework_request.json", "{}"))
        except json.JSONDecodeError:
            request = {}
        if isinstance(request, dict):
            candidates.append(str(request.get("reason", "")))
    for candidate in candidates:
        summary = " ".join(candidate.split())[:300]
        if summary:
            return f"{stage.value} v{version}：{summary}"
    return fallback


def _upstream_repair_stage(
    stage: StageID,
    error: str,
    mgr: CheckpointManager,
    version: int,
) -> StageID | None:
    if (
        stage == StageID.CODE
        and error.startswith("代码实证要求重做 model")
    ):
        return StageID.MODEL
    if stage == StageID.SOLVE and error.startswith((
        "results.json 缺少子问题结果",
        "sensitivity.json ",
    )):
        return StageID.CODE
    if stage == StageID.REVIEW and version:
        target = get_review_rework_stage(mgr.load_artifacts(stage, version))
        if target and target != "none":
            return StageID(target)
    return None


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


def _token_total(mgr: CheckpointManager) -> tuple[int, bool]:
    log_total = 0
    log_count = 0
    for path in mgr.paths.logs.glob("*.json"):
        try:
            item = read_json(path)
        except (OSError, ValueError):
            continue
        input_tokens = item.get("input_tokens") if isinstance(item, dict) else None
        output_tokens = item.get("output_tokens") if isinstance(item, dict) else None
        if (
            isinstance(input_tokens, int)
            and not isinstance(input_tokens, bool)
            and input_tokens >= 0
            and isinstance(output_tokens, int)
            and not isinstance(output_tokens, bool)
            and output_tokens >= 0
        ):
            log_total += input_tokens + output_tokens
            log_count += 1
    if log_count:
        return log_total, True

    total = 0
    available = False
    for stage in STAGE_ORDER:
        for version in range(1, mgr.get_latest_version(stage) + 1):
            meta = mgr.load_meta(stage, version)
            if meta is None:
                continue
            tokens = max(0, meta.tokens_input) + max(0, meta.tokens_output)
            total += tokens
            available = available or tokens > 0
    return total, available


def _budget_error(state: dict[str, Any]) -> str:
    minutes = int(state.get("max_total_minutes", 0))
    if minutes and float(state.get("elapsed_seconds", 0)) >= minutes * 60:
        return f"托管总时长预算已用尽（{minutes} 分钟）"
    tokens = int(state.get("max_total_tokens", 0))
    if tokens and int(state.get("tokens_used", 0)) >= tokens:
        return f"托管 token 预算已用尽（{tokens}）"
    return ""


def _budget_summary(state: dict[str, Any]) -> str:
    elapsed = int(float(state.get("elapsed_seconds", 0)))
    wall_elapsed = int(float(state.get("wall_elapsed_seconds", elapsed)))
    minutes = int(state.get("max_total_minutes", 0))
    time_text = (
        f"活跃 {elapsed // 60}/{minutes} 分钟"
        if minutes else f"活跃 {elapsed // 60} 分钟"
    )
    if wall_elapsed > elapsed + 60:
        time_text += f"（墙钟 {wall_elapsed // 60} 分钟）"
    tokens = int(state.get("tokens_used", 0))
    token_limit = int(state.get("max_total_tokens", 0))
    token_text = (
        f"{tokens}/{token_limit} tokens"
        if token_limit and state.get("token_usage_available")
        else f"{tokens} tokens"
        if state.get("token_usage_available")
        else "token 用量不可用"
    )
    return f"{time_text} · {token_text}"


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _wall_elapsed_seconds(started_at: str) -> float:
    try:
        started = datetime.fromisoformat(started_at)
        elapsed = (datetime.now().astimezone() - started).total_seconds()
    except (TypeError, ValueError):
        return 0.0
    return round(max(0.0, elapsed), 3)
