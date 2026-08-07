"""分析师 Agent：对竞赛题目进行结构化分析。"""

from __future__ import annotations

from mmw.agents.base import BaseAgent
from mmw.llm import LLMClient


class AnalystAgent(BaseAgent):

    role = "analyst"
    system_prompt_template = "system/analyst.j2"

    def analyze(
        self,
        problem_text: str,
        data_files: list[dict] | None = None,
        input_evidence: str = "",
        visual_inputs: list[dict] | None = None,
    ) -> dict[str, str]:
        """分析题目，返回产出文件字典。"""
        user_prompt = self.render_prompt(
            "analyze.j2",
            problem_text=problem_text,
            data_files=data_files or [],
            input_evidence=input_evidence,
        )

        content: str | list[dict] = user_prompt
        if visual_inputs:
            content = [{"type": "text", "text": user_prompt}]
            for item in visual_inputs:
                content.extend((
                    {"type": "text", "text": f"视觉证据 ID：{item['id']}"},
                    {"type": "image_url", "image_url": {"url": item["url"], "detail": "low"}},
                ))

        response = self.run_stream(content)
        artifacts = self.parse_artifacts(response)

        if not artifacts:
            artifacts = {"analysis.md": response}

        return artifacts
