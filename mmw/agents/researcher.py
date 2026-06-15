"""Researcher Agent：方法调研与策略推荐。"""

from __future__ import annotations

from mmw.agents.base import BaseAgent
from mmw.llm import LLMClient


class ResearcherAgent(BaseAgent):

    role = "researcher"
    system_prompt_template = "system/researcher.j2"

    def research(
        self,
        analysis: str,
        sub_problems: list[dict],
        assumptions: str,
        data_summary: str = "",
        knowledge_context: str = "",
        references: list[str] | None = None,
    ) -> dict[str, str]:
        user_prompt = self.render_prompt(
            "research.j2",
            analysis=analysis,
            sub_problems=sub_problems,
            assumptions=assumptions,
            data_summary=data_summary,
            knowledge_context=knowledge_context,
            references=references or [],
        )
        response = self.run_stream(user_prompt)
        artifacts = self.parse_artifacts(response)
        if not artifacts:
            artifacts = {"methods.md": response}
        return artifacts
