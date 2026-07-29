"""Coder Agent：代码实现，含错误反思循环。"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Callable

from openai import APIError

from mmw.agents.base import RETRYABLE_ERRORS, BaseAgent
from mmw.llm import LLMClient
from mmw.utils.display import print_error, print_info
from mmw.utils.executor import ExecutionResult, run_python_code

MAX_RETRIES = 5
MAX_SAME_ERROR_OCCURRENCES = 3
LLM_REQUEST_ERRORS = (APIError,) + RETRYABLE_ERRORS
HARD_OUTPUT_MARKERS = ("results.json", "sensitivity.json", "method_runtime.json")
MODEL_REWORK_MARKER = "MODEL_REWORK_REQUIRED:"


def requires_moving_heat_helper(model: str) -> bool:
    return (
        "移动热过程" in model
        or "simulate_piecewise_first_order" in model
        or "经验一阶响应" in model
        or "一维" in model
        and any(token in model for token in ("瞬态导热", "非稳态导热", "瞬态热传导"))
    )


def moving_heat_code_error(model: str, code: str) -> str:
    if not requires_moving_heat_helper(model):
        return ""
    reduced = (
        "simulate_piecewise_first_order" in model
        or "经验一阶响应" in model
    )
    if (
        "_mmw_moving_heat" in code
        and re.search(r"\bassess_multistart_identifiability\s*\(", code)
        and (
            not reduced
            or re.search(r"\bsimulate_piecewise_first_order\s*\(", code)
        )
    ):
        return ""
    return (
        "结构复用门禁失败: 移动热代码必须导入 _mmw_moving_heat，按模型调用受测"
        "仿真函数并调用 assess_multistart_identifiability，禁止重复手写求解循环"
        "或跳过多起点诊断"
    )


def candidate_replacement_error(model: str, current: str, candidate: str) -> str:
    """拒绝把完整候选替换成缺少既有硬交付物的局部补丁。"""
    if not candidate.strip():
        return "修订未返回完整 solution.py"
    missing = [
        marker for marker in HARD_OUTPUT_MARKERS
        if marker in current and marker not in candidate
    ]
    if missing:
        return f"修订候选不完整，删除了既有硬输出: {', '.join(missing)}"
    if not moving_heat_code_error(model, current):
        return moving_heat_code_error(model, candidate)
    return ""


def model_rework_requested(error: str) -> bool:
    lowered = error.casefold()
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
- 移动热过程优先使用 `_mmw_moving_heat` 中已审批模型指定的 `simulate_moving_slab` 或 `simulate_piecewise_first_order`；这是沙箱临时注入的受测模块。不要再次手写有限差分或一阶响应循环
- API 精确签名：`MovingSlabConfig(thickness, grid_points, sample_dt, substeps, diffusivity, initial_temperature, scheme='explicit'|'implicit')`；`simulate_moving_slab(sample_times, *, speed, air_position_knots, air_temperatures, transfer_position_knots, surface_transfer_rates, config)`。不要臆造 `zones`、`slab_thickness` 等参数名
- `surface_transfer_rates` 必须直接传 Robin 系数 `gamma=h/lambda`，单位与 `thickness` 的倒数一致；模块内部负责边界离散，不要乘时间步或按网格手工换成 `1/time`
- `speed * sample_times` 必须与位置节点同单位；题面速度为 `cm/min`、采样时间为秒时，传给模块的是 `speed/60`（`cm/s`），不能把 `70 cm/min` 当成 `70 cm/s`
- `simulate_moving_slab` 只返回一维中心温度 ndarray，不返回 `(times, temperatures)`；`sample_times` 必须严格等间隔且等于 `sample_dt`，`grid_points` 必须为不小于 3 的奇数。只有 `scheme='explicit'` 才须通过增加 `substeps` 使 `config.diffusion_number <= 0.5`
- `simulate_piecewise_first_order(sample_times, *, speed, air_position_knots, air_temperatures, response_position_knots, response_rates, initial_temperature)` 用于已审批的经验降阶路径；`response_rates` 单位为 `1/time`，只表示中心温度有效响应率。首个采样时刻可大于零，模块会从物理时刻零积分
- 经验降阶只按题面不同设定值的受控炉区组及冷却区标定响应率，环境温度固定使用设定平台与真实间隙线性过渡，不得再拟合过渡形状。题面明确进入设备开始计时时，附件非零首时刻直接作为物理时刻，不能再加传感器阈值穿越时间
- 已审批模型已依据真实 code 证据选定经验降阶结构时，只实现现役降阶 formulation；不要重新实现已被否决且不在现役硬约束中的 PDE 候选
- 对薄层刚性传热，使用 `scheme='implicit'`、`sample_dt=真实输出间隔`、`substeps=1`；隐式格式不得被显式扩散数条件阻断，但仍须做网格或时间步收敛检查
- 分区换热参数必须用至少 3 个不同初值重复标定；若多起点最优参数或下游关键结果明显不一致，应 raise 报告不可辨识，不能任选一组继续
- 多起点标定必须调用 `_mmw_moving_heat.assess_multistart_identifiability`，把至少 3 个不同初值作为 `initial_parameter_sets`、优化终值作为 `parameter_sets`；该函数的原始返回对象必须直接、无包装地写入结果目录 `identifiability.json` 顶层，其他标定元数据另存；通过后在 `results.json` 写入名称含 `参数可辨识性`、值为 1 的状态项，失败时 raise，不能调宽阈值继续

请分析错误原因，给出修正后的完整代码和与代码事实一致的方法契约。
必须同时使用 <artifact name="solution.py"> 和 <artifact name="method_contract.json"> 标签输出；
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


def _issue_notice(error: str) -> str:
    if "非零敏感参数" in error or "扰动结果全为零" in error:
        return (
            "## 灵敏度专用要求\n上一版选择了对当前最优解无影响的参数。每组扰动完成后，"
            "先检查 max(abs(change_pct))；全为零就丢弃该参数并实际重跑另一个参数。"
            "路径题可依次检验运输单价、距离缩放、需求缩放或车辆容量（必要时扩大仍合理的扰动范围），"
            "最终至少保留两个真实改变目标值的参数。不得把零变化改写成非零，也不得只改 JSON。"
        )
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
    if any(token in error for token in (
        "占位结果", "罚函数值", "未找到可行", "无可行", "无法满足", "未找到满足约束",
    )) or "placeholder" in error.casefold():
        return (
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
        problem_text: str = "",
        data_summary: str = "",
        verify_notes: str = "",
        data_files: list[str] | None = None,
        deliverables: list[dict] | None = None,
        runtime_summary: str = "",
        figures_dir: str = "figures",
        results_dir: str = ".",
        method_contract: str = "{}",
    ) -> dict[str, str]:
        user_prompt = self.render_prompt(
            "code.j2",
            model=model,
            params=params,
            problem_text=problem_text,
            data_summary=data_summary,
            verify_notes=verify_notes,
            data_files=data_files or [],
            deliverables=deliverables or [],
            runtime_summary=runtime_summary,
            figures_dir=figures_dir,
            results_dir=results_dir,
            method_contract=method_contract,
        )
        response = self.run_stream(user_prompt)
        return self._parse_code_response(response)

    def implement_with_retry(
        self,
        model: str,
        params: str,
        work_dir: Path,
        problem_text: str = "",
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
        on_candidate: Callable[[str], None] | None = None,
        output_validator: Callable[[ExecutionResult], str] | None = None,
    ) -> tuple[dict[str, str], ExecutionResult | None]:
        """实现代码并尝试运行，失败则反思重试。"""
        initial_revision_error = ""
        if previous_code and revision_feedback:
            try:
                response = self.run_stream(REFLECTION_PROMPT.format(
                    error=revision_feedback,
                    code=previous_code,
                    method_contract=method_contract,
                    repeat_notice="## 重跑要求\n这是上一检查点的失败代码，必须针对失败证据修订，不得重新盲写同类实现。",
                    issue_notice=_issue_notice(revision_feedback),
                ))
            except LLM_REQUEST_ERRORS as exc:
                return {"solution.py": previous_code}, ExecutionResult(
                    success=False, stdout="", stderr="", return_code=-1,
                    error_summary=f"LLM 修订请求失败: {type(exc).__name__}: {exc}",
                )
            revised = self._parse_code_response(response)
            candidate = revised.get("solution.py", "")
            initial_revision_error = candidate_replacement_error(
                model, previous_code, candidate,
            )
            if initial_revision_error:
                artifacts = {"solution.py": previous_code}
            else:
                artifacts = revised
        elif previous_code:
            artifacts = {"solution.py": previous_code}
        else:
            artifacts = self.implement(
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
            )

        code = artifacts.get("solution.py", "")
        if not code:
            return artifacts, None
        if on_candidate:
            on_candidate(code)

        prev_error = None
        same_error_count = 0
        attempt_history: list[dict] = []
        requires_moving_heat = requires_moving_heat_helper(model)
        for attempt in range(1, MAX_RETRIES + 1):
            print_info(f"执行代码（第 {attempt} 次）...")
            structure_error = moving_heat_code_error(model, code)
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
                result = run_python_code(code, work_dir)

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
                        artifacts.update(self.parse_artifacts(contract_response))
                    except LLM_REQUEST_ERRORS:
                        pass
                artifacts["attempt_history.json"] = json.dumps(
                    attempt_history, ensure_ascii=False, indent=2,
                )
                print_info("代码执行成功")
                return artifacts, result

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
                    on_candidate(code)
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
            evidence = (
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
                issue_notice=_issue_notice(result.error_summary),
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
            new_artifacts = self._parse_code_response(response)
            if "solution.py" in new_artifacts:
                replacement_error = candidate_replacement_error(
                    model, code, new_artifacts["solution.py"],
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
                    on_candidate(code)

        artifacts["attempt_history.json"] = json.dumps(
            attempt_history, ensure_ascii=False, indent=2,
        )
        return artifacts, result
