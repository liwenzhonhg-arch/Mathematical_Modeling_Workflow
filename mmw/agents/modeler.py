"""Modeler Agent：数学模型建立。"""

from __future__ import annotations

from mmw.agents.base import BaseAgent
from mmw.llm import LLMClient


class ModelerAgent(BaseAgent):

    role = "modeler"
    system_prompt_template = "system/modeler.j2"

    def build_model(
        self,
        analysis: str,
        methods: str,
        approach: str,
        assumptions: str,
        data_summary: str = "",
    ) -> dict[str, str]:
        user_prompt = self.render_prompt(
            "model.j2",
            analysis=analysis,
            methods=methods,
            approach=approach,
            assumptions=assumptions,
            data_summary=data_summary,
        )
        response = self.run_stream(user_prompt)
        artifacts = self.parse_artifacts(response)
        if not artifacts:
            artifacts = {"model.md": response}
        return artifacts

    def build_alternative_model(
        self,
        analysis: str,
        methods: str,
        approach: str,
        assumptions: str,
        data_summary: str,
        existing_model: str,
        existing_version: int,
    ) -> dict[str, str]:
        """生成与已有方案显著不同的备选建模方案（branch）。"""
        user_prompt = self.render_prompt(
            "model_branch.j2",
            analysis=analysis,
            methods=methods,
            approach=approach,
            assumptions=assumptions,
            data_summary=data_summary,
            existing_model=existing_model,
            existing_version=existing_version,
        )
        response = self.run_stream(user_prompt)
        artifacts = self.parse_artifacts(response)
        if not artifacts:
            artifacts = {"model.md": response}
        return artifacts
