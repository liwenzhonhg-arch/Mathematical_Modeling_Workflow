"""Coder Agent：代码实现，含错误反思循环。"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Callable

from openai import APIError

from mmw.agents.base import RETRYABLE_ERRORS, BaseAgent
from mmw.config import get_settings
from mmw.llm import LLMClient
from mmw.project import restore_attachment_paths
from mmw.utils.display import print_error, print_info
from mmw.utils.executor import ExecutionResult, run_python_code
from mmw.utils.method_contract import (
    CAPABILITY_MOVING_HEAT,
    CAPABILITY_MOVING_HEAT_EFFECTIVE,
    CAPABILITY_MOVING_HEAT_REDUCED,
    contract_capabilities,
    contract_has_capability,
)

MAX_RETRIES = 5
MAX_SAME_ERROR_OCCURRENCES = 3
LLM_REQUEST_ERRORS = (APIError,) + RETRYABLE_ERRORS
HARD_OUTPUT_MARKERS = ("results.json", "sensitivity.json", "method_runtime.json")
MODEL_REWORK_MARKER = "MODEL_REWORK_REQUIRED:"

MOVING_HEAT_REPAIR_GUIDANCE = """## 移动热专用修订要求
- 移动热过程优先使用 `_mmw_moving_heat` 中已审批模型指定的 `simulate_moving_slab`、`simulate_piecewise_first_order` 或 `simulate_effective_slab`；不要手写新的有限差分或一阶响应循环。
- 必须遵守受测 API 的精确签名、单位、采样间隔和状态空间约定，并调用 `assess_multistart_identifiability`。
- 只有 `scheme='explicit'` 检查扩散数稳定性；隐式格式不得被显式扩散数条件阻断。
- 多起点诊断的原始返回对象必须直接、无包装地写入 `identifiability.json`；诊断失败必须 raise，不能调宽阈值继续。
"""


def requires_moving_heat_helper(method_contract: str | dict) -> bool:
    """仅按结构化方法合同启用移动热运行时，禁止扫描自然语言模型全文。"""
    return contract_has_capability(method_contract, CAPABILITY_MOVING_HEAT)


def moving_heat_code_error(method_contract: str | dict, code: str) -> str:
    if not requires_moving_heat_helper(method_contract):
        return ""
    capabilities = contract_capabilities(method_contract)
    reduced = CAPABILITY_MOVING_HEAT_REDUCED in capabilities
    effective = CAPABILITY_MOVING_HEAT_EFFECTIVE in capabilities
    calls_approved_solver = (
        bool(re.search(r"\bsimulate_effective_slab\s*\(", code))
        if effective
        else bool(re.search(r"\bsimulate_piecewise_first_order\s*\(", code))
        if reduced
        else True
    )
    if (
        "_mmw_moving_heat" in code
        and re.search(r"\bassess_multistart_identifiability\s*\(", code)
        and calls_approved_solver
    ):
        return ""
    return (
        "结构复用门禁失败: 移动热代码必须导入 _mmw_moving_heat，按模型调用受测"
        "仿真函数并调用 assess_multistart_identifiability，禁止重复手写求解循环"
        "或跳过多起点诊断"
    )


def candidate_replacement_error(
    method_contract: str | dict,
    current: str,
    candidate: str,
) -> str:
    """拒绝把完整候选替换成缺少既有硬交付物的局部补丁。"""
    if not candidate.strip():
        return "修订未返回完整 solution.py"
    missing = [
        marker for marker in HARD_OUTPUT_MARKERS
        if marker in current and marker not in candidate
    ]
    if missing:
        return f"修订候选不完整，删除了既有硬输出: {', '.join(missing)}"
    if not moving_heat_code_error(method_contract, current):
        return moving_heat_code_error(method_contract, candidate)
    return ""


def apply_solution_patch(original: str, patch: str) -> str:
    """对单个内存字符串应用上下文精确匹配的 unified diff。"""
    source = original.splitlines()
    patch_lines = patch.splitlines()
    result: list[str] = []
    source_index = 0
    saw_hunk = False
    relocated_hunk = False
    index = 0
    hunk_pattern = re.compile(
        r"^@@ -(?P<old_start>\d+)(?:,(?P<old_count>\d+))? "
        r"\+(?P<new_start>\d+)(?:,(?P<new_count>\d+))? @@"
    )

    while index < len(patch_lines):
        line = patch_lines[index]
        match = hunk_pattern.match(line)
        if not match:
            if (
                not saw_hunk
                and (
                    not line.strip()
                    or line.startswith(("diff --git ", "index ", "--- ", "+++ "))
                )
            ):
                index += 1
                continue
            raise ValueError(f"unified diff 含 hunk 外内容: {line[:80]}")

        saw_hunk = True
        old_start = int(match.group("old_start"))
        old_count = int(match.group("old_count") or "1")
        new_start = int(match.group("new_start"))
        new_count = int(match.group("new_count") or "1")
        index += 1
        hunk_lines: list[str] = []
        while index < len(patch_lines) and not hunk_pattern.match(patch_lines[index]):
            hunk_lines.append(patch_lines[index])
            index += 1

        consumed_old = 0
        produced_new = 0
        old_block: list[str] = []
        for hunk_line in hunk_lines:
            if hunk_line == r"\ No newline at end of file":
                continue
            if not hunk_line or hunk_line[0] not in {" ", "+", "-"}:
                raise ValueError(f"unified diff hunk 行格式无效: {hunk_line[:80]}")
            marker, content = hunk_line[0], hunk_line[1:]
            if marker in {" ", "-"}:
                old_block.append(content)
                consumed_old += 1
            if marker in {" ", "+"}:
                produced_new += 1

        old_count = consumed_old
        new_count = produced_new

        target_index = old_start if old_count == 0 else old_start - 1
        nominal_match = (
            source_index <= target_index <= len(source)
            and source[target_index:target_index + old_count] == old_block
        )
        if not nominal_match and old_count:
            matches = [
                start for start in range(source_index, len(source) - old_count + 1)
                if source[start:start + old_count] == old_block
            ]
            if len(matches) != 1:
                detail = "不匹配" if not matches else "匹配不唯一"
                raise ValueError(f"unified diff 旧行或上下文与当前 solution.py {detail}")
            target_index = matches[0]
            relocated_hunk = True
        elif not nominal_match:
            raise ValueError("unified diff hunk 旧行号越界或重叠")

        result.extend(source[source_index:target_index])
        source_index = target_index
        if not relocated_hunk and len(result) != new_start - 1:
            raise ValueError("unified diff hunk 新行号与前序修改不一致")

        for hunk_line in hunk_lines:
            if hunk_line == r"\ No newline at end of file":
                continue
            marker, content = hunk_line[0], hunk_line[1:]
            if marker in {" ", "-"}:
                if source_index >= len(source) or source[source_index] != content:
                    raise ValueError("unified diff 旧行或上下文与当前 solution.py 不匹配")
                source_index += 1
            if marker in {" ", "+"}:
                result.append(content)

    if not saw_hunk:
        raise ValueError("unified diff 缺少 @@ hunk")
    result.extend(source[source_index:])
    merged = "\n".join(result)
    if original.endswith("\n"):
        merged += "\n"
    return merged


def _resolved_revision(
    current: str,
    revised: dict[str, str],
    method_contract: str,
) -> tuple[dict[str, str], str]:
    """把完整文件或精确补丁归一化为可恢复的完整候选。"""
    artifacts = dict(revised)
    candidate = artifacts.get("solution.py", "")
    patch = artifacts.pop("solution.patch", "")
    if not candidate and patch:
        try:
            candidate = apply_solution_patch(current, patch)
        except ValueError as error:
            return {}, f"机器补丁无效: {error}"
        artifacts["solution.py"] = _apply_compatibility_fixes(candidate)
    if method_contract.strip() and "method_contract.json" not in artifacts:
        artifacts["method_contract.json"] = method_contract
    return artifacts, ""


def _recovered_artifacts(previous_code: str, method_contract: str) -> dict[str, str]:
    artifacts = {"solution.py": previous_code}
    if method_contract.strip():
        artifacts["method_contract.json"] = method_contract
    return artifacts


def model_rework_requested(error: str) -> bool:
    lowered = error.casefold()
    if (
        "runtime_center_output_dimension=1" in lowered
        or "api_state_dimension=1" in lowered
    ):
        return False
    return (
        MODEL_REWORK_MARKER.casefold() in lowered
        or "交回模型阶段" in error
        or "交回model阶段" in lowered
        or "模型阶段处理" in error
    )


REFLECTION_PROMPT = """代码执行出错，请分析原因并修正。

## 错误信息
```
{error}
```

## 原始代码
```python
{code}
```

## 当前方法契约
```json
{method_contract}
```

{repeat_notice}

{issue_notice}

注意：
- 如果是编码错误（UnicodeEncodeError / gbk），请移除所有 Unicode 特殊符号（✓✗→★●▲等），只用 ASCII 和中文
- 在代码开头添加 `import sys; sys.stdout.reconfigure(encoding='utf-8')`
- 若为 `NameError`，必须定位变量的所有读取位置，并保证它在每条执行路径上先赋值；不得只改报错附近的输出语句
- 不得新增当前方法契约 `formulation` 未声明的标定参数、决策变量或可行域；若现有模型无法通过拟合/可辨识性门禁，应诚实 raise 交回 model，不能靠新增时间偏移等自由度改变模型
- 已用多个结构或降维方案证明当前 formulation 无法同时通过硬门禁时，使用 `raise RuntimeError("MODEL_REWORK_REQUIRED: 简要原因")`，让托管器回退 model；普通代码错误不得使用该标记
- 若为奇异矩阵，禁止直接计算 `inv(X.T @ X)`，使用 `np.linalg.lstsq` 或 `np.linalg.pinv` 并检查矩阵秩
- **铁律：严禁用生成模拟/示例数据的方式绕过「找不到数据文件」类错误**——结果将是编造的，比报错严重得多。数据路径以任务提示中的清单为准；若确实读不到，打印对应父目录内容后 raise，让人来处理
- 已计算硬门禁后主动失败时，异常或 stdout 必须包含失败约束 ID、有限实际值和预声明阈值；不得只写“最终候选失败/约束复核失败”。证据表明 formulation 本身不可执行时使用 `MODEL_REWORK_REQUIRED` 交回 model
- 修订长文件时可以用 `<artifact name="solution.patch">` 返回仅针对当前 `solution.py` 的标准 unified diff；必须直接从 `---/+++` 或 `@@ -旧行,行数 +新行,行数 @@` 开始，hunk 带精确上下文。不要使用 `*** Begin Patch`/`*** Update File` 包装，不要返回自然语言替换说明、路径命令或省略未改代码的残缺 `solution.py`

请分析错误原因，给出修正后的完整代码和与代码事实一致的方法契约。
必须同时使用 `<artifact name="solution.py">`（或长文件修订时的 `<artifact name="solution.patch">`）和 `<artifact name="method_contract.json">` 标签输出；
`implementation.covers` 必须使用当前方法契约中的目标/硬约束 ID，不能改写成自然语言。
"""

CONTRACT_REPAIR_PROMPT = """只修订方法契约，不改代码。

## 门禁错误
{error}

## 当前方法契约
```json
{method_contract}
```

保留 formulation 和 problem_scope 原值。`implementation.covers` 必须改为当前契约中
实际实现的目标/硬约束 ID，不得使用自然语言名称。只输出：
<artifact name="method_contract.json">完整 JSON</artifact>
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


def _issue_notice(error: str, method_contract: str | dict = "") -> str:
    moving_heat_notice = (
        MOVING_HEAT_REPAIR_GUIDANCE
        if requires_moving_heat_helper(method_contract)
        else ""
    )
    if "非零敏感参数" in error or "扰动结果全为零" in error:
        return moving_heat_notice + (
            "## 灵敏度专用要求\n上一版选择了对当前最优解无影响的参数。每组扰动完成后，"
            "先检查 max(abs(change_pct))；全为零就丢弃该参数并实际重跑另一个参数。"
            "路径题可依次检验运输单价、距离缩放、需求缩放或车辆容量（必要时扩大仍合理的扰动范围），"
            "最终至少保留两个真实改变目标值的参数。不得把零变化改写成非零，也不得只改 JSON。"
        )
    if "非有限数值" in error or re.search(r"(?<![A-Za-z])(?:nan|[+-]?inf)(?![A-Za-z])", error, re.IGNORECASE):
        return moving_heat_notice + (
            "## 数值稳定性专用要求\n结果出现 NaN/Inf。检查有限差分稳定条件、单位和边界更新；"
            "每次校准/优化前先用基准参数运行并 assert np.isfinite。禁止把非有限值替换成默认最优解。"
        )
    if "方法试跑失败" in error:
        return moving_heat_notice + (
            "## 方法试跑专用要求\n必须在同一 solution.py 中实现 `MMW_PILOT=1` 分支，"
            "只读取真实输入并执行缩小规模或有限候选检查，在结果目录写出合法的 "
            "method_pilot.json 后立即退出。不得在试跑分支写 results.json、"
            "sensitivity.json、method_runtime.json 或正式图表。"
        )
    if "超时" in error or "timed out" in error.casefold():
        return moving_heat_notice + (
            "## 超时专用要求\n先估算 PDE/优化器调用次数；减少网格和候选规模，"
            "限制 maxiter/popsize，缓存重复仿真，采用粗到细两阶段。若单次目标函数包含 PDE/时空网格，"
            "必须向量化空间更新，并把正式优化的总目标函数调用控制在 100 次以内；"
            "differential_evolution 默认使用 maxiter<=5、popsize<=5。正式程序应以预声明候选数、"
            "最大迭代数或收敛条件确定性停止；不得只提高显式保护性超时，也不得用固定默认值、"
            "罚函数极值或占位结果伪装成功。"
        )
    if any(token in error for token in (
        "占位结果", "罚函数值", "未找到可行", "无可行", "无法满足", "未找到满足约束",
    )) or "placeholder" in error.casefold():
        return moving_heat_notice + (
            "## 占位结果专用要求\n禁止用默认参数、罚函数极值或占位结果冒充可行解。"
            "先结合 stdout 的校准误差和最接近可行候选诊断根因；如果全部候选不可行，"
            "应修正模型结构、参数标定、单位或边界，而不是调无关参数强行制造可行性。"
            "确实无可行解时必须 raise，让阶段失败。"
        )
    if "could not convert string to float" in error:
        return (
            "## 数据读取专用要求\n先以 header=None 打印前几行并定位真实表头；"
            "数值列使用 pd.to_numeric(errors='coerce') 后删除并核验非数据行，"
            "禁止直接对可能含表头字符串的整列 astype(float)。"
        )
    return moving_heat_notice


class CoderAgent(BaseAgent):

    role = "coder"
    system_prompt_template = "system/coder.j2"

    def _render_task_prompt(
        self,
        *,
        model: str,
        params: str,
        problem_text: str = "",
        completion_contract: str = "",
        data_summary: str = "",
        verify_notes: str = "",
        data_files: list[str] | None = None,
        deliverables: list[dict] | None = None,
        runtime_summary: str = "",
        figures_dir: str = "figures",
        results_dir: str = ".",
        method_contract: str = "{}",
        method_candidates: str = "",
        moving_heat_enabled: bool | None = None,
    ) -> str:
        if moving_heat_enabled is None:
            moving_heat_enabled = requires_moving_heat_helper(method_contract)
        return self.render_prompt(
            "code.j2",
            model=model,
            params=params,
            problem_text=problem_text,
            completion_contract=completion_contract,
            data_summary=data_summary,
            verify_notes=verify_notes,
            data_files=data_files or [],
            deliverables=deliverables or [],
            runtime_summary=runtime_summary,
            figures_dir=figures_dir,
            results_dir=results_dir,
            method_contract=method_contract,
            method_candidates=method_candidates,
            moving_heat_enabled=moving_heat_enabled,
        )

    def _seed_recovered_task_context(self, **kwargs) -> None:
        """为恢复候选的后续反思补回完整任务上下文，不触发 LLM 请求。"""
        if self.chat_history:
            return
        system_prompt = self.render_system_prompt(
            moving_heat_enabled=requires_moving_heat_helper(
                kwargs.get("method_contract", "")
            )
        )
        if system_prompt:
            self._append("system", system_prompt)
        self._append("user", self._render_task_prompt(**kwargs))
        self._append("assistant", "已接收恢复候选；先直接执行，失败后再按证据定向修订。")

    def _parse_code_response(self, response: str) -> dict[str, str]:
        artifacts = self.parse_artifacts(response)
        if "solution.py" not in artifacts and "solution.patch" not in artifacts:
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
        problem_text: str = "",
        completion_contract: str = "",
        data_summary: str = "",
        verify_notes: str = "",
        data_files: list[str] | None = None,
        deliverables: list[dict] | None = None,
        runtime_summary: str = "",
        figures_dir: str = "figures",
        results_dir: str = ".",
        method_contract: str = "{}",
        method_candidates: str = "",
    ) -> dict[str, str]:
        user_prompt = self._render_task_prompt(
            model=model,
            params=params,
            problem_text=problem_text,
            completion_contract=completion_contract,
            data_summary=data_summary,
            verify_notes=verify_notes,
            data_files=data_files or [],
            deliverables=deliverables or [],
            runtime_summary=runtime_summary,
            figures_dir=figures_dir,
            results_dir=results_dir,
            method_contract=method_contract,
            method_candidates=method_candidates,
        )
        if not self.chat_history:
            system_prompt = self.render_system_prompt(
                moving_heat_enabled=requires_moving_heat_helper(method_contract)
            )
            if system_prompt:
                self._append("system", system_prompt)
        response = self.run_stream(user_prompt)
        return self._parse_code_response(response)

    def implement_with_retry(
        self,
        model: str,
        params: str,
        work_dir: Path,
        problem_text: str = "",
        completion_contract: str = "",
        data_summary: str = "",
        verify_notes: str = "",
        data_files: list[str] | None = None,
        deliverables: list[dict] | None = None,
        runtime_summary: str = "",
        previous_code: str = "",
        revision_feedback: str = "",
        figures_dir: str = "figures",
        results_dir: str = ".",
        method_contract: str = "{}",
        method_candidates: str = "",
        on_candidate: Callable[[dict[str, str]], None] | None = None,
        output_validator: Callable[[ExecutionResult], str] | None = None,
        pilot_validator: Callable[[ExecutionResult], str] | None = None,
        before_pilot: Callable[[], None] | None = None,
    ) -> tuple[dict[str, str], ExecutionResult | None]:
        """实现代码并尝试运行，失败则反思重试。"""
        initial_revision_error = ""
        if previous_code:
            self._seed_recovered_task_context(
                model=model,
                params=params,
                problem_text=problem_text,
                data_summary=data_summary,
                verify_notes=verify_notes,
                data_files=data_files,
                deliverables=deliverables,
                runtime_summary=runtime_summary,
                figures_dir=figures_dir,
                results_dir=results_dir,
                method_contract=method_contract,
                method_candidates=method_candidates,
            )
        if previous_code and revision_feedback:
            try:
                response = self.run_stream(REFLECTION_PROMPT.format(
                    error=revision_feedback,
                    code=previous_code,
                    method_contract=method_contract,
                    repeat_notice="## 重跑要求\n这是上一检查点的失败代码，必须针对失败证据修订，不得重新盲写同类实现。",
                    issue_notice=_issue_notice(revision_feedback, method_contract),
                ))
            except LLM_REQUEST_ERRORS as exc:
                return {"solution.py": previous_code}, ExecutionResult(
                    success=False, stdout="", stderr="", return_code=-1,
                    error_summary=f"LLM 修订请求失败: {type(exc).__name__}: {exc}",
                )
            revised, patch_error = _resolved_revision(
                previous_code,
                self._parse_code_response(response),
                method_contract,
            )
            candidate = revised.get("solution.py", "")
            initial_revision_error = patch_error or candidate_replacement_error(
                method_contract, previous_code, candidate
            )
            if initial_revision_error:
                artifacts = _recovered_artifacts(previous_code, method_contract)
            else:
                artifacts = revised
        elif previous_code:
            artifacts = _recovered_artifacts(previous_code, method_contract)
        else:
            artifacts = self.implement(
                model=model,
                params=params,
                problem_text=problem_text,
                completion_contract=completion_contract,
                data_summary=data_summary,
                verify_notes=verify_notes,
                data_files=data_files,
                deliverables=deliverables,
                runtime_summary=runtime_summary,
                figures_dir=figures_dir,
                results_dir=results_dir,
                method_contract=method_contract,
                method_candidates=method_candidates,
            )

        attachment_paths = data_files or []
        code = restore_attachment_paths(
            artifacts.get("solution.py", ""), attachment_paths,
        )
        if not code:
            return artifacts, None
        artifacts["solution.py"] = code
        if on_candidate:
            on_candidate(dict(artifacts))

        prev_error = None
        same_error_count = 0
        failed_candidates: set[str] = set()
        attempt_history: list[dict] = []
        requires_moving_heat = requires_moving_heat_helper(method_contract)
        for attempt in range(1, MAX_RETRIES + 1):
            print_info(f"执行代码（第 {attempt} 次）...")
            structure_error = moving_heat_code_error(method_contract, code)
            if initial_revision_error:
                result = ExecutionResult(
                    success=False,
                    stdout="",
                    stderr="",
                    return_code=-1,
                    error_summary=initial_revision_error,
                )
                initial_revision_error = ""
            elif requires_moving_heat and structure_error:
                result = ExecutionResult(
                    success=False, stdout="", stderr="", return_code=-1,
                    error_summary=structure_error,
                )
            else:
                if method_candidates.strip():
                    if before_pilot:
                        before_pilot()
                    runtime_limit = get_settings().mmw_max_runtime_seconds
                    pilot_result = run_python_code(
                        code,
                        work_dir,
                        timeout=30,
                        extra_env={"MMW_PILOT": "1"},
                    )
                    pilot_error = ""
                    if pilot_result.success and pilot_validator:
                        pilot_error = pilot_validator(pilot_result)
                    if not pilot_result.success or pilot_error:
                        result = ExecutionResult(
                            success=False,
                            stdout=pilot_result.stdout,
                            stderr=pilot_result.stderr,
                            return_code=pilot_result.return_code,
                            timed_out=pilot_result.timed_out,
                            error_summary=(
                                "方法试跑失败: "
                                + (pilot_error or pilot_result.error_summary)
                            ),
                            truncated=pilot_result.truncated,
                        )
                    else:
                        print_info("方法试跑通过，开始正式运行...")
                        result = run_python_code(
                            code,
                            work_dir,
                            timeout=runtime_limit,
                        )
                else:
                    runtime_limit = get_settings().mmw_max_runtime_seconds
                    if runtime_limit is None:
                        result = run_python_code(code, work_dir)
                    else:
                        result = run_python_code(
                            code, work_dir, timeout=runtime_limit
                        )

            if result.success and output_validator:
                validation_error = output_validator(result)
                if validation_error:
                    result = ExecutionResult(
                        success=False,
                        stdout=result.stdout,
                        stderr=result.stderr,
                        return_code=result.return_code,
                        error_summary=f"输出质量门禁失败: {validation_error}",
                        truncated=result.truncated,
                    )
            attempt_history.append({
                "attempt": attempt,
                "success": result.success,
                "timed_out": result.timed_out,
                "error_summary": result.error_summary,
                "stdout_tail": result.stdout[-3000:],
                "stderr_tail": result.stderr[-1500:],
            })

            if result.success:
                if (
                    revision_feedback
                    and "方法契约失败" in revision_feedback
                    and "method_contract.json" not in artifacts
                ):
                    try:
                        contract_response = self.run_stream(CONTRACT_REPAIR_PROMPT.format(
                            error=revision_feedback,
                            method_contract=method_contract,
                        ))
                        repaired = self.parse_artifacts(contract_response)
                        artifacts.update(repaired)
                        if on_candidate and repaired.get("method_contract.json"):
                            on_candidate(dict(artifacts))
                    except LLM_REQUEST_ERRORS:
                        pass
                artifacts["attempt_history.json"] = json.dumps(
                    attempt_history, ensure_ascii=False, indent=2,
                )
                print_info("代码执行成功")
                return artifacts, result

            failed_candidates.add(code)

            print_error(f"执行失败: {result.error_summary}")

            if model_rework_requested(result.error_summary):
                print_info("代码证据表明当前模型契约不足，停止代码反思并交回 model")
                break

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
                if on_candidate:
                    on_candidate(dict(artifacts))
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
            directed_rework = (
                f"ORIGINAL DIRECTED REWORK:\n{revision_feedback}\n\n"
                if revision_feedback else ""
            )
            evidence = directed_rework + (
                f"ERROR:\n{result.error_summary}\n\n"
                f"STDOUT:\n{result.stdout[-6000:]}\n\n"
                f"STDERR:\n{result.stderr[-3000:]}"
            )
            reflection = REFLECTION_PROMPT.format(
                error=evidence,
                code=code,
                method_contract=artifacts.get("method_contract.json", method_contract),
                repeat_notice=(
                    "## 升级要求\n上一版修订后仍出现相同错误。必须检查变量定义/矩阵秩等根因，"
                    "不得原样返回或只修改说明文字。"
                    if same_error_count > 1 else ""
                ),
                issue_notice=_issue_notice(
                    result.error_summary,
                    artifacts.get("method_contract.json", method_contract),
                ),
            )
            try:
                response = self.run_stream(reflection)
            except LLM_REQUEST_ERRORS as exc:
                attempt_history.append({
                    "attempt": attempt,
                    "phase": "reflection",
                    "success": False,
                    "timed_out": False,
                    "error_summary": f"LLM 修订请求失败: {type(exc).__name__}: {exc}",
                    "stdout_tail": "",
                    "stderr_tail": "",
                })
                print_error(attempt_history[-1]["error_summary"])
                break
            new_artifacts, patch_error = _resolved_revision(
                code,
                self._parse_code_response(response),
                artifacts.get("method_contract.json", method_contract),
            )
            if patch_error:
                print_error(patch_error)
                attempt_history.append({
                    "attempt": attempt,
                    "phase": "reflection",
                    "success": False,
                    "timed_out": False,
                    "error_summary": patch_error,
                    "stdout_tail": "",
                    "stderr_tail": "",
                })
                initial_revision_error = patch_error
                continue
            if "solution.py" in new_artifacts:
                new_artifacts["solution.py"] = restore_attachment_paths(
                    new_artifacts["solution.py"], attachment_paths,
                )
                replacement_error = candidate_replacement_error(
                    artifacts.get("method_contract.json", method_contract),
                    code,
                    new_artifacts["solution.py"],
                )
                if not replacement_error and new_artifacts["solution.py"] in failed_candidates:
                    replacement_error = (
                        "duplicate_candidate: 修订代码与已失败候选完全相同，拒绝重复执行"
                    )
                if replacement_error:
                    print_error(replacement_error)
                    attempt_history.append({
                        "attempt": attempt,
                        "phase": "reflection",
                        "success": False,
                        "timed_out": False,
                        "error_summary": replacement_error,
                        "stdout_tail": "",
                        "stderr_tail": "",
                    })
                    initial_revision_error = replacement_error
                    continue
                code = new_artifacts["solution.py"]
                artifacts.update(new_artifacts)
                if on_candidate:
                    on_candidate(dict(artifacts))

        artifacts["attempt_history.json"] = json.dumps(
            attempt_history, ensure_ascii=False, indent=2,
        )
        return artifacts, result
