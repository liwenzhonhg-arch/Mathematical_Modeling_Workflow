"""Reviewer Agent：论文评审与提交清单检查。"""

from __future__ import annotations

from mmw.agents.base import BaseAgent
from mmw.llm import LLMClient


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
        return artifacts
