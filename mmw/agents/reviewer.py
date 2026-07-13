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


def _markdown_check_status(mark: str, text: str) -> str:
    if mark.casefold() == "x":
        return "pass"
    if re.search(r"(?:——|—|--)\s*是(?:\s|$|，|,)", text):
        return "pass"
    if any(token in text for token in ("缺失", "不完整", "未通过", "错误", "无法")):
        return "fail"
    return "warning"


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
        return artifacts
