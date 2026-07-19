"""EDA Agent：探索性数据分析（生成代码 → 执行 → 基于真实输出写报告）。"""

from __future__ import annotations

from mmw.agents.base import BaseAgent, _sanitize_python

FIX_PROMPT = """eda_code.py 执行失败，错误信息：

```
{error}
```

请修复并重新输出完整的 eda_code.py（只输出该 artifact）。
注意：若是编码错误，确认代码开头有 sys.stdout.reconfigure(encoding='utf-8') 且未使用 Unicode 特殊符号。
"""


class EDAAgent(BaseAgent):

    role = "eda"
    system_prompt_template = "system/eda.j2"

    def generate_code(
        self, problem_summary: str, data_files: list[dict], figures_dir: str = "figures"
    ) -> str:
        """第一步：生成 EDA 代码。返回 eda_code.py 内容。"""
        user_prompt = self.render_prompt(
            "eda.j2",
            problem_summary=problem_summary,
            data_files=data_files,
            figures_dir=figures_dir,
        )
        response = self.run_stream(user_prompt)
        artifacts = self.parse_artifacts(response)
        code = artifacts.get("eda_code.py", "")
        return _sanitize_python(code) if code else ""

    def fix_code(self, error: str) -> str:
        """代码执行失败后的修复。返回修复后的 eda_code.py 内容。"""
        response = self.run_stream(FIX_PROMPT.format(error=error))
        artifacts = self.parse_artifacts(response)
        code = artifacts.get("eda_code.py", "")
        return _sanitize_python(code) if code else ""

    def write_summary(
        self, exec_output: str, figures: list[str] | None = None
    ) -> dict[str, str]:
        """第二步：基于真实执行输出撰写报告。"""
        user_prompt = self.render_prompt(
            "eda_summary.j2",
            exec_output=exec_output,
            figures=figures or [],
        )
        response = self.run_stream(user_prompt)
        artifacts = self.parse_artifacts(response)
        if not artifacts:
            artifacts = {"data_summary.md": response}
        return artifacts
