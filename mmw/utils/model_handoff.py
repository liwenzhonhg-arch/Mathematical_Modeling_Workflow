"""模型假设合同、结构化逻辑和人工交接件。"""

from __future__ import annotations

import json
import re
from typing import Any


ASSUMPTION_FIELDS = (
    "id",
    "statement",
    "basis",
    "scope",
    "model_effect",
    "relaxation",
)
CLASSIFICATION_KINDS = {
    "given",
    "hard_constraint",
    "definition",
    "implementation_choice",
}
CONSTRAINT_SOURCE_TYPES = CLASSIFICATION_KINDS | {"modeling_assumption", "derived"}
MODEL_V2_FIELDS = (
    "title",
    "requirement",
    "inputs",
    "outputs",
    "logic_chain",
    "variables",
    "formulas",
    "objective",
    "constraints",
    "method",
    "validation",
    "assumption_refs",
)


def _json_object(raw: str) -> dict[str, Any] | None:
    try:
        value = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return None
    return value if isinstance(value, dict) else None


def _nonempty_text(value: Any) -> str:
    return str(value).strip() if isinstance(value, (str, int, float)) else ""


def validate_assumptions_contract(raw: str) -> list[str]:
    """验证 analyze 阶段的唯一假设合同。"""
    contract = _json_object(raw)
    if contract is None:
        return ["assumptions.json 必须是 JSON 对象"]
    issues: list[str] = []
    if contract.get("schema_version") != 1:
        issues.append("assumptions.json schema_version 必须为 1")
    assumptions = contract.get("assumptions")
    if not isinstance(assumptions, list):
        return [*issues, "assumptions.json 的 assumptions 必须是数组"]
    if not assumptions and not _nonempty_text(contract.get("no_assumptions_reason")):
        issues.append("没有模型假设时必须提供 no_assumptions_reason")
    if len(assumptions) > 12:
        issues.append("真正模型假设不得超过 12 条；应继续分类、合并或删除")
    elif len(assumptions) > 8 and not _nonempty_text(contract.get("overflow_reason")):
        issues.append("模型假设超过 8 条时必须提供 overflow_reason")

    seen: set[str] = set()
    for index, item in enumerate(assumptions, 1):
        prefix = f"assumptions[{index}]"
        if not isinstance(item, dict):
            issues.append(f"{prefix} 必须是对象")
            continue
        for field in ASSUMPTION_FIELDS:
            if field == "scope":
                scope = item.get(field)
                if not isinstance(scope, list) or not scope or not all(
                    _nonempty_text(value) for value in scope
                ):
                    issues.append(f"{prefix}.scope 必须是非空子问题 ID 数组")
            elif not _nonempty_text(item.get(field)):
                issues.append(f"{prefix}.{field} 不能为空")
        assumption_id = _nonempty_text(item.get("id"))
        if assumption_id and not re.fullmatch(r"ASM-[A-Za-z0-9-]+", assumption_id):
            issues.append(f"{prefix}.id 必须使用 ASM- 前缀")
        if assumption_id in seen:
            issues.append(f"模型假设 ID 重复：{assumption_id}")
        seen.add(assumption_id)

    notes = contract.get("classification_notes", [])
    if not isinstance(notes, list):
        issues.append("classification_notes 必须是数组")
    else:
        for index, item in enumerate(notes, 1):
            if not isinstance(item, dict):
                issues.append(f"classification_notes[{index}] 必须是对象")
                continue
            kind = item.get("kind")
            if kind not in CLASSIFICATION_KINDS:
                issues.append(
                    f"classification_notes[{index}].kind 必须是题面事实、硬约束、定义或实现选择"
                )
            for field in ("item", "destination"):
                if not _nonempty_text(item.get(field)):
                    issues.append(f"classification_notes[{index}].{field} 不能为空")
    return issues


def render_assumptions_markdown(raw: str) -> str:
    """只渲染真正假设，分类备注留在 JSON 中供审计。"""
    contract = _json_object(raw)
    if contract is None:
        raise ValueError("assumptions.json 必须是 JSON 对象")
    issues = validate_assumptions_contract(raw)
    if issues:
        raise ValueError("；".join(issues))
    lines = ["# 模型假设", ""]
    assumptions = contract.get("assumptions", [])
    if not assumptions:
        lines.extend((
            "本题不需要引入题面之外的模型假设。",
            "",
            f"说明：{contract['no_assumptions_reason']}",
        ))
    for index, item in enumerate(assumptions, 1):
        scope = "、".join(str(value) for value in item["scope"])
        lines.extend((
            f"{index}. **{item['id']}**：{item['statement']}",
            f"   - 依据：{item['basis']}",
            f"   - 作用范围：{scope}",
            f"   - 模型影响：{item['model_effect']}",
            f"   - 放宽后：{item['relaxation']}",
            "",
        ))
    return "\n".join(lines).rstrip() + "\n"


def normalize_assumption_artifacts(artifacts: dict[str, str]) -> dict[str, str]:
    """验证唯一 JSON 来源并覆盖 LLM 自由生成的假设 Markdown。"""
    raw = artifacts.get("assumptions.json", "")
    if not raw.strip():
        raise ValueError("分析阶段缺少 assumptions.json")
    issues = validate_assumptions_contract(raw)
    if issues:
        raise ValueError("；".join(issues))
    contract = _json_object(raw)
    assert contract is not None
    normalized = dict(artifacts)
    normalized["assumptions.json"] = json.dumps(
        contract, ensure_ascii=False, indent=2,
    )
    normalized["assumptions.md"] = render_assumptions_markdown(
        normalized["assumptions.json"],
    )
    return normalized


def _item_text(item: Any, *fields: str) -> str:
    if isinstance(item, dict):
        for field in fields:
            if text := _nonempty_text(item.get(field)):
                return text
        return ""
    return _nonempty_text(item)


def _list_lines(values: Any, *fields: str) -> list[str]:
    if not isinstance(values, list):
        return []
    return [text for item in values if (text := _item_text(item, *fields))]


def _meaning_and_expression(item: Any) -> str:
    """保留人读含义和代码可实现表达式，避免交接件丢公式。"""
    if not isinstance(item, dict):
        return _nonempty_text(item)
    meaning = _nonempty_text(item.get("meaning"))
    expression = _nonempty_text(item.get("expression"))
    if meaning and expression:
        return f"{meaning}；表达式：{expression}"
    return meaning or expression or _nonempty_text(item.get("id"))


def _traceable_items(values: Any, *, symbol: bool = False) -> list[str]:
    if not isinstance(values, list):
        return []
    rendered: list[str] = []
    for item in values:
        if not isinstance(item, dict):
            if text := _nonempty_text(item):
                rendered.append(text)
            continue
        label = _nonempty_text(item.get("symbol" if symbol else "id"))
        meaning = _nonempty_text(item.get("meaning"))
        unit = _nonempty_text(item.get("unit"))
        text = f"{label}={meaning}" if label and meaning else label or meaning
        if text and unit:
            text += f" [{unit}]"
        if text:
            rendered.append(text)
    return rendered


def _assumption_map(raw: str) -> dict[str, dict[str, Any]]:
    contract = _json_object(raw) or {}
    assumptions = contract.get("assumptions", [])
    if not isinstance(assumptions, list):
        return {}
    return {
        str(item.get("id")): item
        for item in assumptions
        if isinstance(item, dict) and _nonempty_text(item.get("id"))
    }


def build_model_handoff(
    equations_raw: str,
    params_raw: str = "{}",
    assumptions_raw: str = "{}",
) -> str:
    """从结构化模型确定性生成面向 Coder/Writer 的短交接件。"""
    equations = _json_object(equations_raw) or {}
    sub_problems = equations.get("sub_problems")
    if not isinstance(sub_problems, dict):
        sub_problems = {}
    schema_v2 = equations.get("schema_version") == 2
    assumptions = _assumption_map(assumptions_raw)
    params = _json_object(params_raw) or {}
    lines = [
        "# 模型交接摘要",
        "",
        "本文件由 `equations.json`、`params.json` 和 `assumptions.json` 确定性生成。",
        "Coder 与 Writer 应优先读取本文件；完整推导见 `model.md`。",
        "",
    ]
    parameters = params.get("parameters")
    if isinstance(parameters, list) and parameters:
        lines.extend(("## 参数口径", ""))
        for item in parameters:
            if not isinstance(item, dict):
                continue
            label = _nonempty_text(item.get("id")) or _nonempty_text(item.get("symbol"))
            name = _nonempty_text(item.get("name"))
            value = item.get("value")
            value_text = "待代码标定" if value is None else _nonempty_text(value)
            unit = _nonempty_text(item.get("unit")) or "未注明单位"
            source = _nonempty_text(item.get("source_ref")) or "未注明来源"
            lines.append(
                f"- **{label or 'PAR'}**：{name or '未命名参数'}；值：{value_text}；"
                f"单位：{unit}；来源：{source}"
            )
        lines.append("")
    if not schema_v2:
        lines.extend((
            "> 兼容模式：当前是旧版 equations.json，未提供结构化逻辑链；以下仅整理可识别字段。",
            "",
        ))
    for raw_id, value in sub_problems.items():
        if not isinstance(value, dict):
            continue
        problem_id = str(raw_id)
        title = _nonempty_text(value.get("title")) or "未命名子问题"
        lines.extend((f"## {problem_id}：{title}", ""))
        requirement = _nonempty_text(value.get("requirement"))
        if requirement:
            lines.extend(("### 题目要求", requirement, ""))

        inputs = _traceable_items(value.get("inputs"))
        outputs = _traceable_items(value.get("outputs"))
        lines.extend(("### 输入与输出", ""))
        lines.append("- 输入：" + ("；".join(inputs) if inputs else "未结构化列出"))
        lines.append("- 输出：" + ("；".join(outputs) if outputs else "未结构化列出"))
        lines.append("")

        lines.extend(("### 建模逻辑链", ""))
        logic = value.get("logic_chain")
        if isinstance(logic, list) and logic:
            for item in logic:
                if not isinstance(item, dict):
                    continue
                path = " → ".join(filter(None, (
                    _nonempty_text(item.get("from")),
                    _nonempty_text(item.get("action")),
                    _nonempty_text(item.get("to")),
                )))
                reason = _nonempty_text(item.get("reason"))
                lines.append(f"- **{_nonempty_text(item.get('id')) or 'LOG'}**：{path}。理由：{reason}")
        else:
            lines.append("- 未提供结构化逻辑链。")
        lines.append("")

        lines.extend(("### 变量、目标与约束", ""))
        variables = _traceable_items(value.get("variables"), symbol=True)
        lines.append("- 变量：" + ("；".join(variables) if variables else "未结构化列出"))
        formulas = value.get("formulas")
        if isinstance(formulas, list) and formulas:
            lines.append("- 核心方程：")
            for formula in formulas:
                if not isinstance(formula, dict):
                    continue
                formula_id = _nonempty_text(formula.get("id")) or "EQ"
                formula_text = _meaning_and_expression(formula)
                lines.append(f"  - **{formula_id}**：{formula_text}")
        else:
            lines.append("- 核心方程：未结构化列出")
        objective = _meaning_and_expression(value.get("objective"))
        lines.append("- 目标：" + (objective or "未结构化列出"))
        constraints = value.get("constraints")
        if isinstance(constraints, list) and constraints:
            lines.append("- 约束：")
            for item in constraints:
                meaning = _meaning_and_expression(item)
                source_type = (
                    _nonempty_text(item.get("source_type"))
                    if isinstance(item, dict) else ""
                )
                suffix = f"（来源：{source_type}）" if source_type else ""
                lines.append(f"  - {meaning}{suffix}")
        else:
            lines.append("- 约束：未结构化列出")
        lines.append("")

        refs = value.get("assumption_refs", [])
        lines.extend(("### 假设引用", ""))
        if isinstance(refs, list) and refs:
            for ref in refs:
                item = assumptions.get(str(ref), {})
                statement = _nonempty_text(item.get("statement"))
                lines.append(f"- **{ref}**：{statement or '假设正文见 assumptions.md'}")
        else:
            lines.append("- 无题面外假设，或旧合同未提供引用。")
        lines.append("")

        method = value.get("method")
        lines.extend(("### 求解与停止", ""))
        if isinstance(method, dict):
            lines.append(f"- 方法：{_nonempty_text(method.get('name')) or '未列出'}")
            lines.append(f"- 选择理由：{_nonempty_text(method.get('rationale')) or '未列出'}")
            lines.append(f"- 停止条件：{_nonempty_text(method.get('termination')) or '未列出'}")
        else:
            lines.append(f"- 方法：{_nonempty_text(method) or '未列出'}")
            lines.append("- 选择理由和停止条件：旧合同未结构化列出")
        lines.append("")

        lines.extend(("### 验证和失败条件", ""))
        validation = _traceable_items(value.get("validation"))
        if validation:
            lines.extend(f"- {item}" for item in validation)
        else:
            lines.append("- 未结构化列出。")
        observability = _nonempty_text(value.get("observability"))
        if observability:
            lines.append(f"- 可观测性：{observability}")
        lines.append("")
    if not sub_problems:
        lines.append("未找到可交接的顶层子问题。")
    return "\n".join(lines).rstrip() + "\n"


def model_structure_issues(
    model_text: str,
    equations_raw: str,
    assumptions_raw: str = "{}",
) -> list[str]:
    """检查当前模型是否仍是单一现役定义，并验证 schema v2 逻辑闭环。"""
    issues: list[str] = []
    version_heading = re.compile(
        r"(?im)^#{1,6}\s+.*(?:v\d+.*(?:修复|增量|合同)|(?:修复|增量|合同).*v\d+)"
    )
    if version_heading.search(model_text):
        issues.append("model.md 不得追加历史版本合同；版本差异应写入 revision_history.json")
    headings = re.findall(r"(?im)^##\s+(?:子问题\s*)?q?(\d+)\b", model_text)
    duplicates = sorted({item for item in headings if headings.count(item) > 1})
    if duplicates:
        issues.append("model.md 顶层子问题章节重复：" + "、".join(duplicates))

    equations = _json_object(equations_raw)
    if equations is None:
        return [*issues, "equations.json 必须是 JSON 对象"]
    if equations.get("schema_version") != 2:
        return issues
    sub_problems = equations.get("sub_problems")
    if not isinstance(sub_problems, dict) or not sub_problems:
        return [*issues, "schema v2 equations.json 缺少 sub_problems"]
    known_assumptions = set(_assumption_map(assumptions_raw))
    for raw_id, value in sub_problems.items():
        prefix = str(raw_id)
        if not isinstance(value, dict):
            issues.append(f"{prefix} 必须是对象")
            continue
        for field in MODEL_V2_FIELDS:
            item = value.get(field)
            if field in {
                "inputs", "outputs", "logic_chain", "variables", "formulas",
                "constraints", "validation",
            }:
                if not isinstance(item, list) or not item:
                    issues.append(f"{prefix}.{field} 必须是非空数组")
            elif field == "assumption_refs":
                if not isinstance(item, list):
                    issues.append(f"{prefix}.assumption_refs 必须是数组")
            elif field == "method":
                if not isinstance(item, dict) or any(
                    not _nonempty_text(item.get(name))
                    for name in ("name", "rationale", "termination")
                ):
                    issues.append(f"{prefix}.method 必须包含 name/rationale/termination")
            elif field == "objective":
                if not isinstance(item, dict) or not _nonempty_text(item.get("meaning")):
                    issues.append(f"{prefix}.objective 必须是含 meaning 的对象")
            elif not _nonempty_text(item):
                issues.append(f"{prefix}.{field} 不能为空")

        for index, step in enumerate(value.get("logic_chain", []), 1):
            if not isinstance(step, dict) or any(
                not _nonempty_text(step.get(field))
                for field in ("id", "from", "action", "to", "reason")
            ):
                issues.append(
                    f"{prefix}.logic_chain[{index}] 必须包含 id/from/action/to/reason"
                )
        for field in ("inputs", "outputs"):
            for index, item in enumerate(value.get(field, []), 1):
                if not isinstance(item, dict) or any(
                    not _nonempty_text(item.get(name)) for name in ("id", "meaning")
                ):
                    issues.append(f"{prefix}.{field}[{index}] 必须包含 id/meaning")
                elif field == "inputs" and not _nonempty_text(item.get("source")):
                    issues.append(f"{prefix}.inputs[{index}] 必须包含 source")
        for index, variable in enumerate(value.get("variables", []), 1):
            if not isinstance(variable, dict) or any(
                not _nonempty_text(variable.get(name))
                for name in ("symbol", "meaning", "unit")
            ):
                issues.append(
                    f"{prefix}.variables[{index}] 必须包含 symbol/meaning/unit"
                )
        for index, formula in enumerate(value.get("formulas", []), 1):
            if not isinstance(formula, dict) or any(
                not _nonempty_text(formula.get(name))
                for name in ("id", "meaning", "expression")
            ):
                issues.append(
                    f"{prefix}.formulas[{index}] 必须包含 id/meaning/expression"
                )
        objective = value.get("objective")
        if isinstance(objective, dict) and any(
            not _nonempty_text(objective.get(name))
            for name in ("id", "meaning", "expression")
        ):
            issues.append(f"{prefix}.objective 必须包含 id/meaning/expression")
        for index, constraint in enumerate(value.get("constraints", []), 1):
            if not isinstance(constraint, dict):
                issues.append(f"{prefix}.constraints[{index}] 必须是对象")
                continue
            if any(
                not _nonempty_text(constraint.get(name))
                for name in ("id", "meaning", "expression", "source_ref")
            ) or not isinstance(constraint.get("hard"), bool):
                issues.append(
                    f"{prefix}.constraints[{index}] 缺少 id/meaning/expression/hard/source_ref"
                )
            if constraint.get("source_type") not in CONSTRAINT_SOURCE_TYPES:
                issues.append(f"{prefix}.constraints[{index}] 缺少合法 source_type")
        for index, check in enumerate(value.get("validation", []), 1):
            if not isinstance(check, dict) or any(
                not _nonempty_text(check.get(name)) for name in ("id", "meaning")
            ):
                issues.append(f"{prefix}.validation[{index}] 必须包含 id/meaning")
        refs = value.get("assumption_refs", [])
        if isinstance(refs, list):
            for ref in refs:
                if str(ref) not in known_assumptions:
                    issues.append(f"{prefix} 引用了不存在的模型假设 {ref}")
    return issues
