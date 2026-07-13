"""状态机：管理 8 个流水线阶段的转移、rework 回退和 upstream 变更检测。"""

from __future__ import annotations

import json
import math
import re
import hashlib

from mmw.models import (
    STAGE_ORDER,
    CheckpointStatus,
    StageID,
    StageResult,
    next_stage,
)
from mmw.utils.checkpoint import CheckpointManager


def _invalid_physical_results(results: list) -> list[str]:
    """检查确定具有物理上下界的结果，避免荒谬外推进入论文。"""
    invalid: list[str] = []
    bounded_names = ("收率", "转化率", "选择性", "yield", "conversion", "selectivity")
    for item in results:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name", ""))
        value = item.get("value")
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            continue
        if not math.isfinite(value):
            invalid.append(f"{name}={value}")
        elif any(token in name.casefold() for token in bounded_names) and "%" in str(item.get("unit", "")):
            if not 0 <= value <= 100:
                invalid.append(f"{name}={value}%")
    return invalid


def _result_schema_error(results: list) -> str:
    names: set[str] = set()
    for index, item in enumerate(results):
        if not isinstance(item, dict):
            return f"results.json 第 {index + 1} 项不是对象"
        name = item.get("name")
        value = item.get("value")
        if not isinstance(name, str) or not name.strip():
            return f"results.json 第 {index + 1} 项缺少 name"
        if name in names:
            return f"results.json 存在重复 name: {name}"
        names.add(name)
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            return f"results.json 的 {name} 不是有限数值"
        if not isinstance(item.get("unit"), str) or not isinstance(item.get("desc"), str):
            return f"results.json 的 {name} 缺少字符串 unit/desc"
    return ""


def _sensitivity_schema_error(data) -> str:
    if not isinstance(data, dict) or not isinstance(data.get("baseline"), dict):
        return "sensitivity.json 缺少 baseline"
    baseline = data["baseline"].get("objective")
    if isinstance(baseline, bool) or not isinstance(baseline, (int, float)) or not math.isfinite(baseline):
        return "sensitivity.json baseline.objective 必须是有限数值"
    experiments = data.get("experiments")
    if not isinstance(experiments, list) or not experiments:
        return "sensitivity.json experiments 必须是非空列表"
    changes_by_param: dict[str, list[float]] = {}
    for item in experiments:
        if not isinstance(item, dict) or not isinstance(item.get("param"), str):
            return "sensitivity.json 实验缺少 param"
        param = item["param"]
        for key in ("delta_pct", "objective", "change_pct"):
            value = item.get(key)
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
                return f"sensitivity.json 的 {key} 必须是有限数值"
        changes_by_param.setdefault(param, []).append(item["change_pct"])
    if len(changes_by_param) < 2:
        return "sensitivity.json 至少覆盖 2 个参数"
    uninformative = [
        param for param, changes in changes_by_param.items()
        if all(abs(change) < 1e-9 for change in changes)
    ]
    if uninformative:
        return f"sensitivity.json 参数 {', '.join(uninformative)} 的扰动结果全为零"
    return ""


def _invalid_run_marker(run_log: str) -> str:
    """识别明确承认结果是占位/伪造的运行输出。"""
    if re.search(r"(?<![A-Za-z])(?:nan|[+-]?inf)(?![A-Za-z])", run_log, re.IGNORECASE):
        return "非有限数值"
    markers = (
        "输出占位结果",
        "占位结果",
        "罚函数值",
        "未找到满足约束",
        "未找到可行",
        "placeholder result",
        "dummy result",
    )
    lowered = run_log.casefold()
    return next((marker for marker in markers if marker.casefold() in lowered), "")


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
        upstream_error = self.quality_error(prev)
        if upstream_error:
            return False, f"前置阶段 '{prev.value}' 当前质量门禁失败: {upstream_error}"

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

        gate_error = self.quality_error(stage, version)
        if gate_error:
            return False, gate_error

        return True, ""

    def quality_error(self, stage: StageID, version: int | None = None) -> str:
        """返回机器可验证的质量错误；空字符串表示通过。"""
        if version is None:
            version = self.mgr.get_active_version(stage)
        if version == 0:
            return f"阶段 '{stage.value}' 尚未运行"
        artifacts = self.mgr.load_artifacts(stage, version)

        if stage == StageID.MODEL:
            try:
                verify_status = json.loads(artifacts.get("verify_status.json", ""))
            except json.JSONDecodeError:
                verify_status = None
            severity = verify_status.get("severity") if isinstance(verify_status, dict) else None
            if severity not in {"pass", "warning", "block"}:
                return "model 缺少合法 verify_status.json"
            if severity == "block":
                return "Verifier 发现会使模型结论失效的严重问题，不能审批 model"

        elif stage == StageID.CODE:
            if not artifacts.get("solution.py", "").strip():
                return "代码阶段缺少非空 solution.py"
            run_log = artifacts.get("run_log.txt", "")
            if not run_log or run_log.lstrip().startswith("[执行失败]"):
                return "代码执行未成功，不能审批；请 rework code"
            marker = _invalid_run_marker(run_log)
            if marker:
                return f"代码运行明确未得到可信可行解（{marker}），不能审批"

        elif stage == StageID.SOLVE:
            run_log = artifacts.get("run_log.txt", "")
            if not run_log or run_log.lstrip().startswith("[失败]"):
                return "求解运行失败，不能审批；请 rework code"
            marker = _invalid_run_marker(run_log)
            if marker:
                return f"求解运行明确未得到可信可行解（{marker}），不能审批"
            try:
                results = json.loads(artifacts.get("results.json", ""))
            except json.JSONDecodeError:
                results = None
            if not isinstance(results, list) or not results:
                return "results.json 必须是非空列表，不能审批空求解结果"
            schema_error = _result_schema_error(results)
            if schema_error:
                return schema_error
            invalid_results = _invalid_physical_results(results)
            if invalid_results:
                return "求解结果违反物理范围: " + ", ".join(invalid_results[:5])
            try:
                sensitivity = json.loads(artifacts.get("sensitivity.json", ""))
            except json.JSONDecodeError:
                sensitivity = None
            sensitivity_error = _sensitivity_schema_error(sensitivity)
            if sensitivity_error:
                return sensitivity_error

            from mmw.pipeline.stage_code import load_deliverables

            missing = [
                item["file"]
                for item in load_deliverables(self.mgr, report_ignored=False)
                if not (self.mgr.workspace / item["file"]).is_file()
                or (self.mgr.workspace / item["file"]).stat().st_size == 0
            ]
            if missing:
                return f"题目硬交付文件缺失或为空: {', '.join(missing)}"
            try:
                deliverable_manifest = json.loads(
                    artifacts.get("deliverables_manifest.json", "{}")
                )
            except json.JSONDecodeError:
                deliverable_manifest = None
            if not isinstance(deliverable_manifest, dict):
                return "solve 缺少合法 deliverables_manifest.json"
            required_deliverables = {
                item["file"] for item in load_deliverables(self.mgr, report_ignored=False)
            }
            if set(deliverable_manifest) != required_deliverables:
                return "solve 的硬交付文件清单与题面要求不一致，请重跑 solve"
            mismatched = [
                name for name, digest in deliverable_manifest.items()
                if not (self.mgr.workspace / name).is_file()
                or hashlib.sha256((self.mgr.workspace / name).read_bytes()).hexdigest() != digest
            ]
            if mismatched:
                return f"硬交付文件与已审批 solve 版本不一致: {', '.join(mismatched)}"

        elif stage == StageID.PAPER:
            try:
                score = json.loads(artifacts.get("abstract_score.json", ""))
            except json.JSONDecodeError:
                score = None
            if not isinstance(score, dict):
                return "paper 缺少合法 abstract_score.json"
            if score.get("needs_upstream_data") is True:
                return "摘要评审确认缺少上游求解数据，不能审批 paper"
            references = artifacts.get("references.bib", "").strip()
            tex = "\n".join(
                content for name, content in artifacts.items() if name.endswith(".tex")
            )
            if references and "\\cite{" not in tex:
                return "paper 存在 references.bib，但正文没有任何 \\cite 引用"

        elif stage == StageID.REVIEW:
            try:
                checklist = json.loads(artifacts.get("checklist.json", ""))
            except json.JSONDecodeError:
                checklist = None
            items = checklist.get("items") if isinstance(checklist, dict) else None
            if not isinstance(items, list) or not items:
                return "review 缺少合法且非空的 checklist.json"
            statuses = [
                str(item.get("status", "")).casefold()
                for item in items
                if isinstance(item, dict)
            ]
            if len(statuses) != len(items) or any(s not in {"pass", "warning"} for s in statuses):
                return "review checklist 存在 fail 或非法状态，不能审批"

        return ""

    def apply_rework(self, target_stage: StageID) -> list[str]:
        """执行 rework：将目标阶段标记为需要重跑，刷新下游 upstream_changed 标记。

        返回受影响的下游阶段列表。
        """
        affected: list[str] = [target_stage.value]
        self.mgr.mark_pending(target_stage)
        self.mgr.refresh_upstream_flags()

        target_idx = STAGE_ORDER.index(target_stage)
        for downstream in STAGE_ORDER[target_idx + 1 :]:
            version = self.mgr.get_latest_version(downstream)
            if version > 0:
                if self.mgr.mark_upstream_changed(downstream):
                    affected.append(downstream.value)

        return affected

    def get_warnings(self) -> list[str]:
        """检查所有阶段的 upstream_changed 警告。"""
        warnings: list[str] = []
        for stage in STAGE_ORDER:
            version = self.mgr.get_active_version(stage)
            if version == 0:
                continue
            status = self.mgr.load_status(stage, version)
            if status is not None and status.upstream_changed:
                warnings.append(
                    f"阶段 '{stage.value}' 的上游已变更，建议重新运行"
                )
        return warnings
