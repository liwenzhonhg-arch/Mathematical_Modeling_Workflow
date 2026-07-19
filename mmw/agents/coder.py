"""Coder Agent：代码实现，含错误反思循环。"""

from __future__ import annotations

import re
from pathlib import Path

from mmw.agents.base import BaseAgent
from mmw.llm import LLMClient
from mmw.utils.display import print_error, print_info
from mmw.utils.executor import ExecutionResult, run_python_code

MAX_RETRIES = 5
MAX_SAME_ERROR_OCCURRENCES = 3

REFLECTION_PROMPT = """代码执行出错，请分析原因并修正。

## 错误信息
```
{error}
```

## 原始代码
```python
{code}
```

{repeat_notice}

{issue_notice}

注意：
- 如果是编码错误（UnicodeEncodeError / gbk），请移除所有 Unicode 特殊符号（✓✗→★●▲等），只用 ASCII 和中文
- 在代码开头添加 `import sys; sys.stdout.reconfigure(encoding='utf-8')`
- 若为 `NameError`，必须定位变量的所有读取位置，并保证它在每条执行路径上先赋值；不得只改报错附近的输出语句
- 若为奇异矩阵，禁止直接计算 `inv(X.T @ X)`，使用 `np.linalg.lstsq` 或 `np.linalg.pinv` 并检查矩阵秩
- **铁律：严禁用生成模拟/示例数据的方式绕过「找不到数据文件」类错误**——结果将是编造的，比报错严重得多。数据路径以任务提示中的清单为准；若确实读不到，打印对应父目录内容后 raise，让人来处理

请分析错误原因，给出修正后的完整代码。仍然使用 <artifact name="solution.py"> 标签输出。
"""


def _apply_compatibility_fixes(code: str) -> str:
    """只修复盲测已确认、且当前环境确实不支持的 API。"""
    import numpy as np

    if not hasattr(np, "trapz"):
        code = code.replace("np.trapz(", "np.trapezoid(")
        code = code.replace("numpy.trapz(", "numpy.trapezoid(")
    return code


def _apply_runtime_fix(code: str, error_summary: str) -> str:
    """对盲测已确认的确定性运行错误应用最小安全修复。"""
    if "Singular matrix" in error_summary and "np.linalg.inv(" in code:
        # ponytail: 只在实际发生奇异矩阵后改用 Moore-Penrose 伪逆。
        return code.replace("np.linalg.inv(", "np.linalg.pinv(")
    return code


def _issue_notice(error: str) -> str:
    if "非有限数值" in error or re.search(r"(?<![A-Za-z])(?:nan|[+-]?inf)(?![A-Za-z])", error, re.IGNORECASE):
        return (
            "## 数值稳定性专用要求\n结果出现 NaN/Inf。检查有限差分稳定条件、单位和边界更新；"
            "每次校准/优化前先用基准参数运行并 assert np.isfinite。禁止把非有限值替换成默认最优解。"
        )
    if "超时" in error or "timed out" in error.casefold():
        return (
            "## 超时专用要求\n先估算 PDE/优化器调用次数；减少网格和候选规模，"
            "限制 maxiter/popsize，缓存重复仿真，采用粗到细两阶段。若单次目标函数包含 PDE/时空网格，"
            "必须向量化空间更新，并把正式优化的总目标函数调用控制在 100 次以内；"
            "differential_evolution 默认使用 maxiter<=5、popsize<=5。代码阶段必须在 300 秒内完成，"
            "不得只提高超时时间，也不得用固定默认值、罚函数极值或占位结果伪装成功。"
        )
    if any(token in error for token in ("占位结果", "罚函数值", "未找到可行", "未找到满足约束")) or "placeholder" in error.casefold():
        return (
            "## 占位结果专用要求\n禁止用默认参数、罚函数极值或占位结果冒充可行解。"
            "修正可行性判断和优化边界；确实无可行解时必须 raise，让阶段失败。"
        )
    if "could not convert string to float" in error:
        return (
            "## 数据读取专用要求\n先以 header=None 打印前几行并定位真实表头；"
            "数值列使用 pd.to_numeric(errors='coerce') 后删除并核验非数据行，"
            "禁止直接对可能含表头字符串的整列 astype(float)。"
        )
    return ""


class CoderAgent(BaseAgent):

    role = "coder"
    system_prompt_template = "system/coder.j2"

    def _parse_code_response(self, response: str) -> dict[str, str]:
        artifacts = self.parse_artifacts(response)
        if "solution.py" not in artifacts:
            fenced = re.findall(r"```(?:python)?\s*(.*?)```", response, re.DOTALL | re.IGNORECASE)
            if fenced:
                artifacts["solution.py"] = max(fenced, key=len).strip()
            elif not artifacts:
                from mmw.agents.base import _strip_code_fences
                artifacts["solution.py"] = _strip_code_fences(response)
        if "solution.py" in artifacts:
            from mmw.agents.base import _sanitize_python
            artifacts["solution.py"] = _apply_compatibility_fixes(
                _sanitize_python(artifacts["solution.py"])
            )
        return artifacts

    def implement(
        self,
        model: str,
        params: str,
        data_summary: str = "",
        verify_notes: str = "",
        data_files: list[str] | None = None,
        deliverables: list[dict] | None = None,
        runtime_summary: str = "",
        figures_dir: str = "figures",
        results_dir: str = ".",
    ) -> dict[str, str]:
        user_prompt = self.render_prompt(
            "code.j2",
            model=model,
            params=params,
            data_summary=data_summary,
            verify_notes=verify_notes,
            data_files=data_files or [],
            deliverables=deliverables or [],
            runtime_summary=runtime_summary,
            figures_dir=figures_dir,
            results_dir=results_dir,
        )
        response = self.run_stream(user_prompt)
        return self._parse_code_response(response)

    def implement_with_retry(
        self,
        model: str,
        params: str,
        work_dir: Path,
        data_summary: str = "",
        verify_notes: str = "",
        data_files: list[str] | None = None,
        deliverables: list[dict] | None = None,
        runtime_summary: str = "",
        previous_code: str = "",
        revision_feedback: str = "",
        figures_dir: str = "figures",
        results_dir: str = ".",
    ) -> tuple[dict[str, str], ExecutionResult | None]:
        """实现代码并尝试运行，失败则反思重试。"""
        if previous_code and revision_feedback:
            response = self.run_stream(REFLECTION_PROMPT.format(
                error=revision_feedback,
                code=previous_code,
                repeat_notice="## 重跑要求\n这是上一检查点的失败代码，必须针对失败证据修订，不得重新盲写同类实现。",
                issue_notice=_issue_notice(revision_feedback),
            ))
            artifacts = self._parse_code_response(response)
        else:
            artifacts = self.implement(
                model, params, data_summary, verify_notes, data_files, deliverables,
                runtime_summary,
                figures_dir,
                results_dir,
            )

        code = artifacts.get("solution.py", "")
        if not code:
            return artifacts, None

        prev_error = None
        same_error_count = 0
        for attempt in range(1, MAX_RETRIES + 1):
            print_info(f"执行代码（第 {attempt} 次）...")
            result = run_python_code(code, work_dir)

            if result.success:
                print_info("代码执行成功")
                return artifacts, result

            print_error(f"执行失败: {result.error_summary}")

            if result.error_summary == prev_error:
                same_error_count += 1
            else:
                prev_error = result.error_summary
                same_error_count = 1

            runtime_fixed = _apply_runtime_fix(code, result.error_summary)
            if runtime_fixed != code:
                print_info("检测到奇异矩阵，已将直接求逆替换为伪逆后重试...")
                code = runtime_fixed
                artifacts["solution.py"] = code
                continue

            if same_error_count >= MAX_SAME_ERROR_OCCURRENCES:
                print_error(
                    f"连续 {same_error_count} 轮出现同一错误，提前终止反思循环。"
                    "疑似根因不在代码本身（如输出被 max_tokens 截断、数据访问说明缺失），请人工排查"
                )
                break

            if result.timed_out and same_error_count >= 2:
                print_error("连续 2 轮执行超时，停止继续消耗计算时间，请人工检查算法复杂度")
                break

            if attempt == MAX_RETRIES:
                print_error(f"已达最大重试次数 ({MAX_RETRIES})")
                break

            print_info("反思错误并修正...")
            reflection = REFLECTION_PROMPT.format(
                error=result.stderr[-2000:],
                code=code,
                repeat_notice=(
                    "## 升级要求\n上一版修订后仍出现相同错误。必须检查变量定义/矩阵秩等根因，"
                    "不得原样返回或只修改说明文字。"
                    if same_error_count > 1 else ""
                ),
                issue_notice=_issue_notice(result.error_summary),
            )
            response = self.run_stream(reflection)
            new_artifacts = self._parse_code_response(response)
            if "solution.py" in new_artifacts:
                code = new_artifacts["solution.py"]
                artifacts["solution.py"] = code

        return artifacts, result
