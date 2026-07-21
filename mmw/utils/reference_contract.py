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
    if not isinstance(contract, dict) or contract.get("schema_version") != 1:
        return "参考契约 schema_version 必须为 1"
    expected = contract.get("results")
    if not isinstance(expected, list) or not expected:
        return "参考契约 results 必须是非空列表"
    names = set()
    for item in expected:
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
    for item in contract["results"]:
        name = item["name"]
        value = next(
            (actual[candidate] for candidate in [name, *item.get("aliases", [])] if candidate in actual),
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
    for item in contract["results"]:
        name = item["name"]
        value = next(
            (actual[candidate] for candidate in [name, *item.get("aliases", [])] if candidate in actual),
            None,
        )
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(value)
        ):
            failures.append({"name": name, "actual": None, "category": "missing_or_invalid"})
        elif not item["min"] <= value <= item["max"]:
            failures.append({"name": name, "actual": value, "category": "out_of_range"})
    return failures
