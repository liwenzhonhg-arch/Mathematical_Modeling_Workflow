"""Verifier Agent：独立验证数学模型正确性。"""

from __future__ import annotations

from mmw.agents.base import (
    BaseAgent,
    _extract_json_artifact_by_key,
    _extract_named_json_artifact,
)
from mmw.llm import LLMClient


class VerifierAgent(BaseAgent):

    role = "verifier"
    system_prompt_template = "system/verifier.j2"

    def verify(
        self,
        problem_summary: str,
        assumptions: str,
        model: str,
        equations: str,
    ) -> dict[str, str]:
        user_prompt = self.render_prompt(
            "verify.j2",
            problem_summary=problem_summary,
            assumptions=assumptions,
            model=model,
            equations=equations,
        )
        response = self.run_stream(user_prompt)
        artifacts = self.parse_artifacts(response)
        if not artifacts:
            artifacts = {"verify_report.md": response}
        if "verify_status.json" not in artifacts:
            status = _extract_named_json_artifact(response, "verify_status.json")
            if not status:
                status = _extract_json_artifact_by_key(response, "severity")
            if status:
                artifacts["verify_status.json"] = status
        return artifacts
