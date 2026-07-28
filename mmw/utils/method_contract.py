"""模型、实现、求解与论文之间的结构化方法契约。"""

from __future__ import annotations

import hashlib
import json
import math
import re
from copy import deepcopy
from typing import Any


IMPLEMENTATION_CLASSES = {
    "exact", "heuristic", "simulation", "statistical", "unclassified",
}


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _json_object(raw: str) -> dict[str, Any] | None:
    try:
        value = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return None
    return value if isinstance(value, dict) else None


def contract_hash(contract: dict[str, Any]) -> str:
    return _sha256(json.dumps(contract, ensure_ascii=False, sort_keys=True))


def build_model_contract(equations_raw: str) -> dict[str, Any]:
    """从 equations.json 确定性生成稳定目标/约束 ID。"""
    equations = _json_object(equations_raw) or {}
    sub_problems = equations.get("sub_problems")
    if not isinstance(sub_problems, dict):
        sub_problems = {}
    objectives: list[dict[str, Any]] = []
    constraints: list[dict[str, Any]] = []
    methods: list[str] = []
    for raw_id, value in sub_problems.items():
        if not isinstance(value, dict):
            continue
        problem_id = str(raw_id).strip() or f"q{len(objectives) + 1}"
        suffix = re.sub(r"[^A-Za-z0-9]+", "-", problem_id).strip("-").upper()
        objective = str(value.get("objective", "")).strip()
        if objective:
            objectives.append({
                "id": f"OBJ-{suffix}",
                "meaning": objective,
                "unit": "",
            })
        raw_constraints = value.get("constraints", [])
        if isinstance(raw_constraints, list):
            constraints.extend({
                "id": f"CON-{suffix}-{index}",
                "meaning": str(item),
                "hard": True,
            } for index, item in enumerate(raw_constraints, 1) if str(item).strip())
        method = str(value.get("method", "")).strip()
        if method and method not in methods:
            methods.append(method)
    return {
        "schema_version": 1,
        "problem_scope": [str(key) for key in sub_problems],
        "formulation": {
            "model_family": "；".join(methods) or "未分类模型",
            "objectives": objectives,
            "constraints": constraints,
        },
        "implementation": {
            "algorithm": "",
            "class": "unclassified",
            "solver": "",
            "randomized": False,
            "seed": None,
            "covers": [],
            "deviations": [],
        },
        "claims": {
            "optimality": "unverified",
            "approximation": None,
            "limitations": [],
        },
        "bindings": {
            "model_version": 0,
            "code_version": 0,
            "solve_version": 0,
            "solution_sha256": "",
            "results_sha256": "",
        },
    }


def validate_model_contract(raw: str) -> list[str]:
    contract = _json_object(raw)
    return ["model 缺少合法 method_contract.json"] if contract is None else _base_failures(contract)


def finalize_code_contract(
    model_raw: str,
    candidate_raw: str,
    *,
    solution: str,
    model_version: int,
    code_version: int,
) -> dict[str, Any]:
    model = _json_object(model_raw)
    if model is None:
        raise ValueError("model 缺少合法 method_contract.json")
    candidate = _json_object(candidate_raw) or {}
    implementation = candidate.get("implementation")
    claims = candidate.get("claims")
    result = deepcopy(model)
    if isinstance(implementation, dict):
        result["implementation"].update({
            key: implementation[key]
            for key in result["implementation"]
            if key in implementation
        })
    if isinstance(claims, dict):
        result["claims"].update({
            key: claims[key] for key in result["claims"] if key in claims
        })
    result["bindings"].update({
        "model_version": model_version,
        "code_version": code_version,
        "solution_sha256": _sha256(solution),
        "results_sha256": "",
    })
    return result


def validate_code_contract(
    model_raw: str,
    code_raw: str,
    solution: str,
) -> list[str]:
    model = _json_object(model_raw)
    contract = _json_object(code_raw)
    if model is None:
        return ["model 方法契约非法"]
    if contract is None:
        return ["code 缺少合法 method_contract.json"]
    failures = _base_failures(contract)
    if contract.get("problem_scope") != model.get("problem_scope"):
        failures.append("code 方法契约修改了子问题范围")
    if contract.get("formulation") != model.get("formulation"):
        failures.append("code 方法契约修改了数学 formulation")
    implementation = contract.get("implementation", {})
    hard_ids = {
        item["id"]
        for item in contract.get("formulation", {}).get("constraints", [])
        if isinstance(item, dict) and item.get("hard") is True and isinstance(item.get("id"), str)
    }
    covers = set(implementation.get("covers", [])) if isinstance(
        implementation.get("covers"), list
    ) else set()
    missing = sorted(hard_ids - covers)
    if missing:
        failures.append("实现未覆盖硬约束: " + ", ".join(missing))
    cls = implementation.get("class")
    if cls == "unclassified" or not str(implementation.get("algorithm", "")).strip():
        failures.append("实现算法或类别未声明")
    claims = contract.get("claims", {})
    optimality = str(claims.get("optimality", "")).casefold()
    if cls == "heuristic" and "global" in optimality:
        failures.append("启发式实现不得声明全局最优")
    undisclosed_approximation = (
        cls == "exact"
        and re.search(
            r"\btop[_-]?k\b|top-k|greedy|heuristic|"
            r"beam[_ -]?search|penalty[_ -]?(?:method|search|relaxation)|"
            r"罚函数|贪心|启发式|截断",
            solution,
            re.IGNORECASE,
        )
        and not implementation.get("deviations")
    )
    if undisclosed_approximation:
        failures.append("exact 实现包含未披露的 top-k、截断、罚函数或启发式")
    if implementation.get("randomized") is True and implementation.get("seed") is None:
        failures.append("随机实现未记录 seed")
    if contract.get("bindings", {}).get("solution_sha256") != _sha256(solution):
        failures.append("方法契约与 solution.py 哈希不一致")
    return failures


def build_solve_contract(
    code_raw: str,
    *,
    solution: str,
    results: str,
    runtime: str,
    solve_version: int,
) -> tuple[dict[str, Any], dict[str, Any]]:
    contract = _json_object(code_raw)
    if contract is None:
        raise ValueError("code 缺少合法 method_contract.json")
    result = deepcopy(contract)
    result["bindings"].update({
        "solve_version": solve_version,
        "results_sha256": _sha256(results),
        "runtime_sha256": _sha256(runtime),
    })
    failures = _base_failures(result)
    if result["bindings"].get("solution_sha256") != _sha256(solution):
        failures.append("solution.py 哈希不一致")
    runtime_data = _json_object(runtime)
    if runtime_data is None:
        failures.append("缺少合法 method_runtime.json")
    else:
        failures.extend(_runtime_failures(result, runtime_data))
    report = {
        "schema_version": 2,
        "passed": not failures,
        "contract_sha256": contract_hash(result),
        "runtime_sha256": _sha256(runtime),
        "covered_ids": sorted(_contract_ids(result)),
        "failures": failures,
        "bindings": deepcopy(result["bindings"]),
    }
    return result, report


def validate_solve_contract(
    contract_raw: str,
    validation_raw: str,
    *,
    results: str,
    runtime: str,
) -> list[str]:
    contract = _json_object(contract_raw)
    report = _json_object(validation_raw)
    if contract is None or report is None:
        return ["solve 缺少合法方法契约或验证报告"]
    failures = _base_failures(contract)
    if report.get("passed") is not True:
        failures.extend(str(item) for item in report.get("failures", []) if str(item))
        if not report.get("failures"):
            failures.append("方法验证未通过")
    if report.get("contract_sha256") != contract_hash(contract):
        failures.append("方法验证报告与当前契约不一致")
    if contract.get("bindings", {}).get("results_sha256") != _sha256(results):
        failures.append("方法契约与 results.json 哈希不一致")
    if contract.get("bindings", {}).get("runtime_sha256") != _sha256(runtime):
        failures.append("方法契约与 method_runtime.json 哈希不一致")
    if report.get("runtime_sha256") != _sha256(runtime):
        failures.append("方法验证报告与运行证据不一致")
    return failures


def _runtime_failures(
    contract: dict[str, Any],
    runtime: dict[str, Any],
) -> list[str]:
    failures = []
    implementation = contract.get("implementation", {})
    claims = contract.get("claims", {})
    if runtime.get("schema_version") != 1:
        failures.append("运行证据 schema_version 非法")
    if runtime.get("algorithm_class") != implementation.get("class"):
        failures.append("运行证据算法类别与方法契约不一致")
    if runtime.get("feasible") is not True:
        failures.append("运行证据未确认最终方案可行")
    checked = runtime.get("constraints_checked", [])
    checked = set(checked) if isinstance(checked, list) else set()
    hard_ids = {
        item["id"]
        for item in contract.get("formulation", {}).get("constraints", [])
        if isinstance(item, dict) and item.get("hard") is True and isinstance(item.get("id"), str)
    }
    if missing := sorted(hard_ids - checked):
        failures.append("运行证据未检查硬约束: " + ", ".join(missing))
    if implementation.get("randomized") is True and runtime.get("seed") != implementation.get("seed"):
        failures.append("运行 seed 与方法契约不一致")

    optimality = str(claims.get("optimality", "")).casefold()
    if "global" not in optimality:
        return failures
    if implementation.get("class") != "exact":
        failures.append("非 exact 实现不得声明全局最优")
        return failures
    if runtime.get("termination_status") != "optimal":
        failures.append("全局最优声明缺少 optimal 终止状态")
    objective = runtime.get("objective_value")
    if isinstance(objective, bool) or not isinstance(objective, (int, float)) or not math.isfinite(objective):
        failures.append("全局最优声明缺少有限目标值")
    certificate = runtime.get("optimality_certificate")
    if not isinstance(certificate, dict):
        failures.append("全局最优声明缺少运行级证书")
        return failures
    kind = certificate.get("type")
    if kind == "exhaustive_enumeration":
        total = certificate.get("search_space_size")
        evaluated = certificate.get("evaluated_candidates")
        if (
            isinstance(total, bool)
            or isinstance(evaluated, bool)
            or not isinstance(total, int)
            or not isinstance(evaluated, int)
            or total < 1
            or evaluated < total
        ):
            failures.append("穷举证书未覆盖完整搜索空间")
    elif kind in {"solver_certificate", "bound_certificate"}:
        gap = certificate.get("relative_gap")
        tolerance = certificate.get("tolerance", 1e-6)
        if (
            isinstance(gap, bool)
            or isinstance(tolerance, bool)
            or not isinstance(gap, (int, float))
            or not isinstance(tolerance, (int, float))
            or not math.isfinite(gap)
            or not math.isfinite(tolerance)
            or gap < 0
            or tolerance < 0
            or gap > tolerance
        ):
            failures.append("最优性证书 gap 超出容差")
    else:
        failures.append("全局最优声明缺少受支持的运行级证书")
    return failures


def build_paper_traceability(
    contract_raw: str,
    model_solution_tex: str,
) -> tuple[str, dict[str, Any]]:
    contract = _json_object(contract_raw)
    if contract is None:
        raise ValueError("solve 缺少合法 method_contract.json")
    digest = contract_hash(contract)
    ids = sorted(_contract_ids(contract))
    marker = f"% MMW-METHOD-CONTRACT: {digest}\n"
    tex = re.sub(
        r"^% MMW-METHOD-CONTRACT: .*\n(?:% MMW-METHOD-IDS: .*\n)?",
        "",
        model_solution_tex,
    )
    covered_ids = sorted(set(re.findall(r"(?m)^%\s*MMW-ID:\s*([A-Za-z0-9-]+)\s*$", tex)))
    algorithm_markers = re.findall(r"(?m)^%\s*MMW-ALGORITHM:\s*(.+?)\s*$", tex)
    implementation = contract.get("implementation", {})
    algorithm = str(implementation.get("algorithm", "")).strip()
    required_limitations = [
        *implementation.get("deviations", []),
        *contract.get("claims", {}).get("limitations", []),
    ]
    limitation_markers = set(
        re.findall(r"(?m)^%\s*MMW-LIMITATION:\s*([DL]\d+)\s*$", tex)
    )
    failures = []
    missing_ids = sorted(set(ids) - set(covered_ids))
    if missing_ids:
        failures.append("论文方法章节缺少 ID 标记: " + ", ".join(missing_ids))
    if algorithm and algorithm not in algorithm_markers:
        failures.append("论文方法章节未标记实际算法")
    required_markers = {
        *(f"D{index}" for index in range(1, len(implementation.get("deviations", [])) + 1)),
        *(f"L{index}" for index in range(1, len(contract.get("claims", {}).get("limitations", [])) + 1)),
    }
    if missing := sorted(required_markers - limitation_markers):
        failures.append("论文未追踪偏差/局限: " + ", ".join(missing))
    if not _allows_global_claim(contract) and _has_positive_global_claim(tex):
        failures.append("论文使用了高于方法契约允许等级的全局最优表述")
    report = {
        "schema_version": 1,
        "passed": not failures,
        "contract_sha256": digest,
        "covered_ids": covered_ids,
        "algorithm": algorithm,
        "algorithm_marked": algorithm in algorithm_markers,
        "limitations_required": len(required_limitations),
        "limitations_marked": len(required_markers & limitation_markers),
        "failures": failures,
    }
    return marker + tex, report


def validate_paper_traceability(
    contract_raw: str,
    trace_raw: str,
    model_solution_tex: str,
) -> list[str]:
    contract = _json_object(contract_raw)
    trace = _json_object(trace_raw)
    if contract is None or trace is None:
        return ["paper 缺少合法方法契约或追踪报告"]
    digest = contract_hash(contract)
    failures = []
    if trace.get("passed") is not True or trace.get("contract_sha256") != digest:
        failures.append("方法追踪报告与当前契约不一致")
        failures.extend(str(item) for item in trace.get("failures", []) if str(item))
    if f"% MMW-METHOD-CONTRACT: {digest}" not in model_solution_tex:
        failures.append("模型求解章节未绑定当前方法契约")
    missing = sorted(_contract_ids(contract) - set(trace.get("covered_ids", [])))
    if missing:
        failures.append("论文方法追踪缺少 ID: " + ", ".join(missing))
    return failures


def validate_paper_method_language(
    contract_raw: str,
    abstract_tex: str,
    symbols_tex: str,
    model_solution_tex: str,
) -> list[str]:
    """检查论文是否把 formulation、实际实现和核心符号如实写清。"""
    contract = _json_object(contract_raw)
    if contract is None:
        return ["paper 缺少合法方法契约"]
    failures: list[str] = []
    implementation = contract.get("implementation", {})
    implementation_class = implementation.get("class")
    heuristic_cues = ("启发式", "贪心", "枚举", "搜索")
    if implementation_class == "heuristic" and not any(
        cue in abstract_tex for cue in heuristic_cues
    ):
        failures.append("摘要未如实说明 heuristic 实现")

    model_family = str(contract.get("formulation", {}).get("model_family", ""))
    if implementation_class == "heuristic" and re.search(
        r"\bMILP\b|混合整数", model_family, re.IGNORECASE,
    ):
        has_formulation = bool(re.search(
            r"\bMILP\b|混合整数", model_solution_tex, re.IGNORECASE,
        ))
        has_implementation = any(cue in model_solution_tex for cue in heuristic_cues)
        has_contrast = any(
            cue in model_solution_tex for cue in ("但", "实际", "并非", "未直接", "不同")
        )
        if not (has_formulation and has_implementation and has_contrast):
            failures.append("模型求解章节未明确区分 MILP formulation 与 heuristic implementation")

    formulation_text = "\n".join(
        str(item.get("meaning", ""))
        for key in ("objectives", "constraints")
        for item in contract.get("formulation", {}).get(key, [])
        if isinstance(item, dict)
    )
    symbol_pattern = r"(?<![A-Za-z\\])([A-Z])(?![A-Za-z])"
    required_symbols = set(re.findall(symbol_pattern, formulation_text))
    documented_symbols = set(re.findall(symbol_pattern, symbols_tex))
    if missing := sorted(required_symbols - documented_symbols):
        failures.append(
            "符号说明缺少 formulation 使用的大写符号: " + ", ".join(missing)
        )
    return failures


def _allows_global_claim(contract: dict[str, Any]) -> bool:
    implementation = contract.get("implementation", {})
    optimality = str(contract.get("claims", {}).get("optimality", "")).casefold()
    return implementation.get("class") == "exact" and optimality in {
        "global",
        "global-optimal",
        "global optimum",
    }


def _has_positive_global_claim(tex: str) -> bool:
    text = tex.casefold()
    for phrase in ("全局最优", "global optimum", "globally optimal"):
        start = 0
        while (index := text.find(phrase, start)) >= 0:
            context = text[max(0, index - 24):index]
            if not any(
                qualifier in context
                for qualifier in ("不保证", "无法保证", "不能保证", "不一定", "not", "cannot")
            ):
                return True
            start = index + len(phrase)
    return False


def build_review_consistency(
    solve_contract_raw: str,
    paper_contract_raw: str,
    trace_raw: str,
    model_solution_tex: str,
) -> dict[str, Any]:
    failures = validate_paper_traceability(
        solve_contract_raw, trace_raw, model_solution_tex,
    )
    solve_contract = _json_object(solve_contract_raw)
    paper_contract = _json_object(paper_contract_raw)
    if solve_contract != paper_contract:
        failures.append("paper 使用的方法契约与 solve 不一致")
    return {
        "schema_version": 1,
        "passed": not failures,
        "failures": failures,
        "contract_sha256": contract_hash(solve_contract) if solve_contract else "",
    }


def _base_failures(contract: dict[str, Any]) -> list[str]:
    failures: list[str] = []
    if contract.get("schema_version") != 1:
        failures.append("方法契约 schema_version 非法")
    formulation = contract.get("formulation")
    if not isinstance(formulation, dict):
        return [*failures, "方法契约缺少 formulation"]
    ids = list(_contract_ids(contract))
    expected_count = sum(
        len(formulation.get(key, [])) if isinstance(formulation.get(key), list) else 0
        for key in ("objectives", "constraints")
    )
    if len(ids) != expected_count:
        failures.append("目标或约束 ID 缺失/重复")
    implementation = contract.get("implementation")
    if not isinstance(implementation, dict):
        failures.append("方法契约缺少 implementation")
    elif implementation.get("class") not in IMPLEMENTATION_CLASSES:
        failures.append("实现类别非法")
    return failures


def _contract_ids(contract: dict[str, Any]) -> set[str]:
    formulation = contract.get("formulation", {})
    ids = [
        item.get("id")
        for key in ("objectives", "constraints")
        for item in formulation.get(key, [])
        if isinstance(item, dict) and isinstance(item.get("id"), str) and item["id"]
    ]
    return set(ids)
