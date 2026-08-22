"""可选的领域质量合同；默认不启用，不向全局 prompt 注入领域规则。"""

from __future__ import annotations

import math
from typing import Any


def _object(value: Any) -> dict[str, Any] | None:
    return value if isinstance(value, dict) else None


def _nonempty_list(value: Any) -> bool:
    return isinstance(value, list) and bool(value)


def _validate_prediction(value: Any) -> list[str]:
    contract = _object(value)
    if contract is None:
        return ["prediction 合同必须是对象"]
    issues: list[str] = []
    validation = _object(contract.get("validation"))
    if validation is None or validation.get("strategy") != "rolling_origin":
        issues.append("prediction.validation.strategy 必须为 rolling_origin")
    metrics = {str(item).casefold() for item in contract.get("metrics", [])} if isinstance(
        contract.get("metrics"), list
    ) else set()
    required = {"macro_wape", "micro_wape", "system_aggregate_wape"}
    missing = sorted(required - metrics)
    if missing:
        issues.append("prediction.metrics 缺少：" + ", ".join(missing))
    if not _nonempty_list(contract.get("provenance")):
        issues.append("prediction.provenance 必须为非空数组")
    return issues


def _validate_scheduling(value: Any) -> list[str]:
    contract = _object(value)
    if contract is None:
        return ["scheduling 合同必须是对象"]
    issues: list[str] = []
    if not _nonempty_list(contract.get("candidate_key_fields")):
        issues.append("scheduling.candidate_key_fields 必须为非空数组")
    if not _nonempty_list(contract.get("source_refs")):
        issues.append("scheduling.source_refs 必须为非空数组")
    closure = _object(contract.get("closure"))
    if closure is None or closure.get("all_required_tasks_covered") is not True:
        issues.append("scheduling.closure 必须确认 all_required_tasks_covered=true")
    if closure is None or closure.get("feasible") is not True:
        issues.append("scheduling.closure 必须确认 feasible=true")
    return issues


def _validate_energy(value: Any) -> list[str]:
    contract = _object(value)
    if contract is None:
        return ["energy 合同必须是对象"]
    issues: list[str] = []
    tolerance = contract.get("balance_tolerance")
    if (
        isinstance(tolerance, bool)
        or not isinstance(tolerance, (int, float))
        or not math.isfinite(tolerance)
        or tolerance < 0
    ):
        issues.append("energy.balance_tolerance 必须为有限非负数")
    if not _nonempty_list(contract.get("flows")):
        issues.append("energy.flows 必须为非空数组")
    if not _nonempty_list(contract.get("recomputed_outputs")):
        issues.append("energy.recomputed_outputs 必须为非空数组")
    if contract.get("closure_passed") is not True:
        issues.append("energy.closure_passed 必须为 true")
    return issues


def validate_optional_domain_contracts(value: Any) -> list[str]:
    """校验 method_contract.domain_contracts；缺省时返回空列表。"""
    contracts = _object(value)
    if contracts is None:
        return []
    validators = {
        "prediction": _validate_prediction,
        "scheduling": _validate_scheduling,
        "energy": _validate_energy,
    }
    issues: list[str] = []
    for name, contract in contracts.items():
        validator = validators.get(str(name))
        if validator is None:
            issues.append(f"未知领域合同：{name}")
            continue
        issues.extend(validator(contract))
    return issues
