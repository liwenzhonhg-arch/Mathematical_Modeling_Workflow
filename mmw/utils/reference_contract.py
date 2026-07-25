"""独立评估器使用的人工参考结果契约。"""

from __future__ import annotations

import json
import math
from pathlib import Path

MAX_CONTRACT_BYTES = 64 * 1024


def load_reference_contract(case_dir: Path) -> dict | None:
    """从真题案例目录读取 evaluator-only Oracle。"""
    path = case_dir / "reference_expected.json"
    if not path.is_file():
        return None
    if path.stat().st_size > MAX_CONTRACT_BYTES:
        raise ValueError("参考契约超过 64 KiB")
    try:
        contract = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"参考契约读取失败: {exc}") from exc
    error = contract_error(contract)
    if error:
        raise ValueError(error)
    return contract


def contract_error(contract) -> str:
    if not isinstance(contract, dict) or contract.get("schema_version") not in {1, 2}:
        return "参考契约 schema_version 必须为 1 或 2"
    expected = contract.get("results")
    if not isinstance(expected, list) or not expected:
        return "参考契约 results 必须是非空列表"
    groups = [("results", expected)]
    if contract.get("schema_version") == 2:
        invariants = contract.get("invariants", [])
        if not isinstance(invariants, list):
            return "参考契约 invariants 必须是列表"
        groups.append(("invariants", invariants))
        scenarios = contract.get("stress_scenarios", [])
        if not isinstance(scenarios, list):
            return "参考契约 stress_scenarios 必须是列表"
        for scenario in scenarios:
            if (
                not isinstance(scenario, dict)
                or not isinstance(scenario.get("name"), str)
                or not scenario["name"].strip()
                or not isinstance(scenario.get("results"), list)
                or not scenario["results"]
            ):
                return "参考契约 stress_scenarios 项非法"
            groups.append((f"stress:{scenario['name']}", scenario["results"]))
        repeatability = contract.get("repeatability")
        if repeatability is not None:
            if not isinstance(repeatability, dict):
                return "参考契约 repeatability 必须是对象"
            names_to_compare = repeatability.get("results")
            abs_tol = repeatability.get("absolute_tolerance", 0)
            rel_tol = repeatability.get("relative_tolerance", 0)
            if (
                not isinstance(names_to_compare, list)
                or not names_to_compare
                or any(not isinstance(name, str) or not name.strip() for name in names_to_compare)
                or isinstance(abs_tol, bool)
                or isinstance(rel_tol, bool)
                or not isinstance(abs_tol, (int, float))
                or not isinstance(rel_tol, (int, float))
                or not math.isfinite(abs_tol)
                or not math.isfinite(rel_tol)
                or abs_tol < 0
                or rel_tol < 0
            ):
                return "参考契约 repeatability 配置非法"
    names = set()
    for _, items in groups:
        for item in items:
            if not isinstance(item, dict) or not isinstance(item.get("name"), str):
                return "参考契约结果项缺少 name"
            name = item["name"].strip()
            lower, upper = item.get("min"), item.get("max")
            if not name or name in names:
                return f"参考契约结果名为空或重复: {name}"
            aliases = item.get("aliases", [])
            if (
                not isinstance(aliases, list)
                or any(not isinstance(alias, str) or not alias.strip() for alias in aliases)
                or len(set(aliases)) != len(aliases)
            ):
                return f"参考契约 {name} 的 aliases 非法"
            duplicate = next((alias for alias in aliases if alias in names or alias == name), "")
            if duplicate:
                return f"参考契约结果名为空或重复: {duplicate}"
            if (
                isinstance(lower, bool)
                or isinstance(upper, bool)
                or not isinstance(lower, (int, float))
                or not isinstance(upper, (int, float))
                or not math.isfinite(lower)
                or not math.isfinite(upper)
                or lower > upper
            ):
                return f"参考契约 {name} 的范围非法"
            names.update([name, *aliases])
    return ""


def contract_result_groups(contract: dict) -> list[tuple[str, list[dict]]]:
    groups = [("oracle", contract["results"])]
    if contract.get("schema_version") == 2:
        groups.append(("invariant", contract.get("invariants", [])))
        groups.extend(
            (f"stress:{scenario['name']}", scenario["results"])
            for scenario in contract.get("stress_scenarios", [])
        )
    return groups


def validate_reference_results(contract: dict, results) -> str:
    error = contract_error(contract)
    if error:
        return error
    if not isinstance(results, list):
        return "results.json 不是列表"
    actual = {
        item.get("name"): item.get("value")
        for item in results
        if isinstance(item, dict) and isinstance(item.get("name"), str)
    }
    for _, items in contract_result_groups(contract):
        for item in items:
            name = item["name"]
            value = next(
                (
                    actual[candidate]
                    for candidate in [name, *item.get("aliases", [])]
                    if candidate in actual
                ),
                None,
            )
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(value)
            ):
                return f"results.json 缺少参考结果或数值非法: {name}"
            if not item["min"] <= value <= item["max"]:
                return (
                    f"参考结果越界: {name}={value}，"
                    f"期望 [{item['min']}, {item['max']}]"
                )
    return ""


def reference_result_failures(contract: dict, results) -> list[dict]:
    """返回不泄露期望范围的结构化失败列表。"""
    error = contract_error(contract)
    if error:
        raise ValueError(error)
    if not isinstance(results, list):
        return [{"name": "", "actual": None, "category": "invalid_results"}]
    actual = {
        item.get("name"): item.get("value")
        for item in results
        if isinstance(item, dict) and isinstance(item.get("name"), str)
    }
    failures = []
    for group, items in contract_result_groups(contract):
        for item in items:
            name = item["name"]
            value = next(
                (actual[candidate] for candidate in [name, *item.get("aliases", [])] if candidate in actual),
                None,
            )
            category_prefix = "" if group == "oracle" else f"{group}:"
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(value)
            ):
                failures.append({
                    "name": name, "actual": None,
                    "category": f"{category_prefix}missing_or_invalid",
                })
            elif not item["min"] <= value <= item["max"]:
                failures.append({
                    "name": name, "actual": value,
                    "category": f"{category_prefix}out_of_range",
                })
    return failures
