"""Reviewer Agent：论文评审与提交清单检查。"""

from __future__ import annotations

import json
import re

from mmw.agents.base import (
    BaseAgent,
    _extract_json_artifact_by_key,
    _extract_named_json_artifact,
)
from mmw.llm import LLMClient

REWORK_STAGES = {"none", "model", "code", "paper"}


def _markdown_check_status(mark: str, text: str) -> str:
    if re.search(r"(?:[（(：:]|——|—|--)\s*否(?:\s|$|，|,|）|\))", text):
        return "fail"
    if any(token in text for token in ("缺失", "不完整", "未通过", "错误", "无法")):
        return "fail"
    if any(token in text for token in ("未提供", "需确认", "需检查", "自行检查")):
        return "warning"
    if mark.casefold() == "x":
        return "pass"
    if re.search(r"(?:——|—|--)\s*是(?:\s|$|，|,)", text):
        return "pass"
    return "warning"


def _infer_rework_stage(items: list) -> str:
    failed = [item for item in items if isinstance(item, dict) and item.get("status") == "fail"]
    if not failed:
        return "none"
    stages: set[str] = set()
    for item in failed:
        text = f"{item.get('check', '')} {item.get('note', '')}"
        explicit_code_evidence = any(
            token in text
            for token in ("results.json", "solution.py", "运行失败", "schema")
        )
        model_evidence = any(
            token in text
            for token in ("模型", "建模", "假设", "方程", "边界", "可行", "约束", "验证", "逻辑", "MILP", "ρ", "rho")
        )
        if any(token in text for token in ("缺出处", "数值审计")) and not explicit_code_evidence:
            stages.add("paper")
        elif explicit_code_evidence:
            stages.add("code")
        elif model_evidence:
            stages.add("model")
        elif any(token in text for token in ("求解", "灵敏度")):
            stages.add("code")
        elif any(
            token in text
            for token in ("论文", "摘要", "正文", "图表", "附录", "参考文献", "格式", "引用", "排版", "页数", "语言")
        ):
            stages.add("paper")
    if "model" in stages:
        return "model"
    if "code" in stages:
        return "code"
    if "paper" in stages:
        return "paper"
    return ""


def get_review_rework_stage(artifacts: dict[str, str]) -> str:
    try:
        checklist = json.loads(artifacts.get("checklist.json", ""))
    except json.JSONDecodeError:
        return ""
    if not isinstance(checklist, dict):
        return ""
    items = checklist.get("items")
    if isinstance(items, list):
        inferred = _infer_rework_stage(items)
        if inferred:
            return inferred
    stage = checklist.get("rework_stage")
    return stage if stage in REWORK_STAGES else ""


def _ensure_rework_stage(artifacts: dict[str, str]) -> None:
    try:
        checklist = json.loads(artifacts.get("checklist.json", ""))
    except json.JSONDecodeError:
        return
    items = checklist.get("items") if isinstance(checklist, dict) else None
    if not isinstance(items, list):
        return
    inferred = _infer_rework_stage(items)
    if inferred:
        checklist["rework_stage"] = inferred
    elif checklist.get("rework_stage") not in REWORK_STAGES - {"none"}:
        checklist["rework_stage"] = "paper"
    artifacts["checklist.json"] = json.dumps(checklist, ensure_ascii=False, indent=2)


class ReviewerAgent(BaseAgent):

    role = "reviewer"
    system_prompt_template = "system/reviewer.j2"

    def review(self, sections: dict[str, str], numeric_audit: str = "") -> dict[str, str]:
        user_prompt = self.render_prompt(
            "review.j2",
            sections=sections,
            numeric_audit=numeric_audit,
        )
        response = self.run_stream(user_prompt)
        artifacts = self.parse_artifacts(response)
        if not artifacts:
            artifacts = {"review.md": response}
        elif "review.md" not in artifacts:
            artifacts["review.md"] = response
        if "checklist.json" not in artifacts:
            checklist = _extract_named_json_artifact(response, "checklist.json")
            if not checklist:
                checklist = _extract_json_artifact_by_key(response, "items")
            if checklist:
                artifacts["checklist.json"] = checklist
            else:
                items = [
                    {
                        "check": text.strip(),
                        "status": _markdown_check_status(mark, text),
                        "note": "由 review.md 勾选项恢复",
                    }
                    for mark, text in re.findall(
                        r"^-\s*\[([ xX])\]\s*(.+)$", response, re.MULTILINE
                    )
                ]
                if items:
                    artifacts["checklist.json"] = json.dumps(
                        {"items": items}, ensure_ascii=False, indent=2
                    )
        _ensure_rework_stage(artifacts)
        return artifacts
