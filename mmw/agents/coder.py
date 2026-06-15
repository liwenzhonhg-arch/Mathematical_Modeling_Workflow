"""Coder Agent：代码实现，含错误反思循环。"""

from __future__ import annotations

from pathlib import Path

from mmw.agents.base import BaseAgent
from mmw.llm import LLMClient
from mmw.utils.display import print_error, print_info
from mmw.utils.executor import ExecutionResult, run_python_code

MAX_RETRIES = 5

REFLECTION_PROMPT = """代码执行出错，请分析原因并修正。

## 错误信息
```
{error}
```

## 原始代码
```python
{code}
```

注意：
- 如果是编码错误（UnicodeEncodeError / gbk），请移除所有 Unicode 特殊符号（✓✗→★●▲等），只用 ASCII 和中文
- 在代码开头添加 `import sys; sys.stdout.reconfigure(encoding='utf-8')`
- **铁律：严禁用生成模拟/示例数据的方式绕过「找不到数据文件」类错误**——结果将是编造的，比报错严重得多。数据文件名以任务提示中给出的清单为准；若确实读不到，打印 `os.listdir('data/raw')` 的实际内容后 raise，让人来处理

请分析错误原因，给出修正后的完整代码。仍然使用 <artifact name="solution.py"> 标签输出。
"""


class CoderAgent(BaseAgent):

    role = "coder"
    system_prompt_template = "system/coder.j2"

    def implement(
        self,
        model: str,
        params: str,
        data_summary: str = "",
        verify_notes: str = "",
        data_files: list[str] | None = None,
        deliverables: list[dict] | None = None,
    ) -> dict[str, str]:
        user_prompt = self.render_prompt(
            "code.j2",
            model=model,
            params=params,
            data_summary=data_summary,
            verify_notes=verify_notes,
            data_files=data_files or [],
            deliverables=deliverables or [],
        )
        response = self.run_stream(user_prompt)
        artifacts = self.parse_artifacts(response)
        if not artifacts:
            # 格式漂移兜底：整个回复是裸代码（常带 Markdown 栅栏）时剥栅栏后使用
            from mmw.agents.base import _strip_code_fences
            artifacts = {"solution.py": _strip_code_fences(response)}
        if "solution.py" in artifacts:
            from mmw.agents.base import _sanitize_python
            artifacts["solution.py"] = _sanitize_python(artifacts["solution.py"])
        return artifacts

    def implement_with_retry(
        self,
        model: str,
        params: str,
        work_dir: Path,
        data_summary: str = "",
        verify_notes: str = "",
        data_files: list[str] | None = None,
        deliverables: list[dict] | None = None,
    ) -> tuple[dict[str, str], ExecutionResult | None]:
        """实现代码并尝试运行，失败则反思重试。"""
        artifacts = self.implement(
            model, params, data_summary, verify_notes, data_files, deliverables
        )

        code = artifacts.get("solution.py", "")
        if not code:
            return artifacts, None

        prev_error = None
        for attempt in range(1, MAX_RETRIES + 1):
            print_info(f"执行代码（第 {attempt} 次）...")
            result = run_python_code(code, work_dir)

            if result.success:
                print_info("代码执行成功")
                return artifacts, result

            print_error(f"执行失败: {result.error_summary}")

            # 连续两轮同一错误：反思已无效，根因通常不在代码本身（输出截断/数据说明缺失）
            if result.error_summary == prev_error:
                print_error(
                    "连续两轮出现同一错误，提前终止反思循环。"
                    "疑似根因不在代码本身（如输出被 max_tokens 截断、数据访问说明缺失），请人工排查"
                )
                break
            prev_error = result.error_summary

            if attempt == MAX_RETRIES:
                print_error(f"已达最大重试次数 ({MAX_RETRIES})")
                break

            print_info("反思错误并修正...")
            reflection = REFLECTION_PROMPT.format(
                error=result.stderr[-2000:],
                code=code,
            )
            response = self.run_stream(reflection)
            new_artifacts = self.parse_artifacts(response)
            if "solution.py" not in new_artifacts and response.lstrip().startswith("```"):
                # 反思回复同样可能漂移为裸代码块
                from mmw.agents.base import _strip_code_fences
                new_artifacts["solution.py"] = _strip_code_fences(response)
            if "solution.py" in new_artifacts:
                from mmw.agents.base import _sanitize_python
                code = _sanitize_python(new_artifacts["solution.py"])
                artifacts["solution.py"] = code

        return artifacts, result
