"""状态机：管理 8 个流水线阶段的转移、rework 回退和 upstream 变更检测。"""

from __future__ import annotations

from mmw.models import (
    STAGE_ORDER,
    CheckpointStatus,
    StageID,
    StageResult,
    next_stage,
)
from mmw.utils.checkpoint import CheckpointManager


class PipelineStateMachine:
    """流水线状态机。"""

    def __init__(self, checkpoint_mgr: CheckpointManager):
        self.mgr = checkpoint_mgr

    def get_next_runnable(self) -> StageID | None:
        """找到下一个可运行的阶段：前置阶段已 approved 且自身未 completed/approved。"""
        for i, stage in enumerate(STAGE_ORDER):
            version = self.mgr.get_latest_version(stage)

            if version > 0:
                status = self.mgr.load_status(stage, version)
                if status is not None and status.status in (
                    CheckpointStatus.COMPLETED,
                    CheckpointStatus.APPROVED,
                ):
                    continue

            if i == 0:
                return stage

            prev = STAGE_ORDER[i - 1]
            if self.mgr.is_approved(prev):
                return stage

            return None
        return None

    def can_run(self, stage: StageID) -> tuple[bool, str]:
        """检查某阶段是否可以运行。返回 (可否, 原因)。"""
        idx = STAGE_ORDER.index(stage)

        if idx == 0:
            return True, ""

        prev = STAGE_ORDER[idx - 1]
        if not self.mgr.is_approved(prev):
            prev_label = prev.value
            return False, f"前置阶段 '{prev_label}' 尚未审批"

        return True, ""

    def can_approve(self, stage: StageID, version: int | None = None) -> tuple[bool, str]:
        """检查某阶段（的指定版本）是否可以审批。必须已 completed 但未 approved。"""
        if version is None:
            version = self.mgr.get_latest_version(stage)
        if version == 0:
            return False, f"阶段 '{stage.value}' 尚未运行"

        status = self.mgr.load_status(stage, version)
        if status is None:
            return False, f"阶段 '{stage.value}' 状态异常"

        if status.status == CheckpointStatus.APPROVED:
            return False, f"阶段 '{stage.value}' 已审批"

        if status.status != CheckpointStatus.COMPLETED:
            return False, f"阶段 '{stage.value}' 尚未完成"

        return True, ""

    def apply_rework(self, target_stage: StageID) -> list[str]:
        """执行 rework：将目标阶段标记为需要重跑，刷新下游 upstream_changed 标记。

        返回受影响的下游阶段列表。
        """
        affected: list[str] = [target_stage.value]
        self.mgr.refresh_upstream_flags()

        target_idx = STAGE_ORDER.index(target_stage)
        for downstream in STAGE_ORDER[target_idx + 1 :]:
            version = self.mgr.get_latest_version(downstream)
            if version > 0:
                changed = self.mgr.check_upstream_changed(downstream, version)
                if changed:
                    affected.append(downstream.value)

        return affected

    def get_warnings(self) -> list[str]:
        """检查所有阶段的 upstream_changed 警告。"""
        warnings: list[str] = []
        for stage in STAGE_ORDER:
            version = self.mgr.get_latest_version(stage)
            if version == 0:
                continue
            status = self.mgr.load_status(stage, version)
            if status is not None and status.upstream_changed:
                warnings.append(
                    f"阶段 '{stage.value}' 的上游已变更，建议重新运行"
                )
        return warnings
