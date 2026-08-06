"""Coder 反思循环测试：同错误连续出现时提前终止，避免空转烧 token。"""

import json
from pathlib import Path

import httpx
import pytest
from openai import APIError

import mmw.agents.coder as coder_mod
from mmw.agents.coder import (
    MAX_RETRIES,
    CoderAgent,
    _apply_compatibility_fixes,
    _issue_notice,
    apply_solution_patch,
    moving_heat_code_error,
    requires_moving_heat_helper,
)
from mmw.utils.executor import ExecutionResult


class StubLLM:
    model = "stub"
    total_input_tokens = 0
    total_output_tokens = 0

    def __init__(self, responses: list[str]):
        self.responses = list(responses)
        self.calls = 0
        self.messages = []

    def chat(self, messages, **kwargs):
        self.calls += 1
        return self.responses.pop(0)

    def chat_stream(self, messages, **kwargs):
        self.calls += 1
        self.messages.append(messages)
        return iter([self.responses.pop(0)])


def _code_response(i: int) -> str:
    return f'<artifact name="solution.py">print({i})</artifact>'


def _fail(summary: str) -> ExecutionResult:
    return ExecutionResult(
        success=False, stdout="", stderr=f"Traceback...\n{summary}",
        return_code=1, error_summary=summary,
    )


def _run_with_errors(monkeypatch, errors: list[str], llm: StubLLM):
    """按序返回预设错误的 run_python_code 替身。"""
    seq = iter(errors)

    def fake_run(code, work_dir, timeout=300):
        return _fail(next(seq))

    monkeypatch.setattr(coder_mod, "run_python_code", fake_run)
    agent = CoderAgent(llm)
    return agent.implement_with_retry(model="模型", params="{}", work_dir=Path("."))


def test_same_error_twice_stops_early(monkeypatch):
    # 同一错误允许一次升级反思，第 3 次仍相同才停止。
    llm = StubLLM([_code_response(0)] + [_code_response(i) for i in range(1, MAX_RETRIES)])
    _, result = _run_with_errors(
        monkeypatch, ["SyntaxError: line 10"] * MAX_RETRIES, llm
    )
    assert result is not None and not result.success
    assert llm.calls == 3


def test_different_errors_run_full_rounds(monkeypatch):
    llm = StubLLM([_code_response(i) for i in range(MAX_RETRIES)])
    errors = [f"Error_{i}" for i in range(MAX_RETRIES)]
    _, result = _run_with_errors(monkeypatch, errors, llm)
    assert result is not None and not result.success
    # 每轮错误都不同：implement 1 次 + 反思 MAX_RETRIES - 1 次
    assert llm.calls == MAX_RETRIES


def test_implement_strips_fences_when_no_artifact_tags(monkeypatch):
    # 格式漂移：整个回复是 Markdown 代码块（无 artifact 标签）时剥栅栏兜底
    llm = StubLLM(["```python\nprint('ok')\n```"])
    agent = CoderAgent(llm)
    artifacts = agent.implement(model="模型", params="{}")
    assert artifacts["solution.py"] == "print('ok')"


def test_implement_recovers_python_fence_after_explanation():
    llm = StubLLM(["修订说明如下：\n```python\nprint('ok')\n```"])

    artifacts = CoderAgent(llm).implement(model="模型", params="{}")

    assert artifacts["solution.py"] == "print('ok')"


def test_implement_receives_original_problem_requirements():
    llm = StubLLM([_code_response(0)])

    CoderAgent(llm).implement(
        model="模型", params="{}", problem_text="求温区3中点的温度",
    )

    assert any("求温区3中点的温度" in message["content"] for message in llm.messages[0])


def test_reflection_receives_stdout_diagnostics(monkeypatch):
    llm = StubLLM([_code_response(0), _code_response(1)])
    calls = {"n": 0}

    def fake_run(code, work_dir, timeout=300):
        calls["n"] += 1
        if calls["n"] == 1:
            return ExecutionResult(
                success=False,
                stdout="R2=0.76, peak=230.7",
                stderr="RuntimeError: 无可行解",
                return_code=1,
                error_summary="RuntimeError: 无可行解",
            )
        return ExecutionResult(success=True, stdout="ok", stderr="", return_code=0)

    monkeypatch.setattr(coder_mod, "run_python_code", fake_run)
    CoderAgent(llm).implement_with_retry(model="模型", params="{}", work_dir=Path("."))

    assert any("R2=0.76" in message["content"] for message in llm.messages[1])


def test_reflection_updates_method_contract_with_revised_code(monkeypatch):
    llm = StubLLM([
        '<artifact name="solution.py">print(0)</artifact>'
        '<artifact name="method_contract.json">{"implementation":{"covers":[]}}</artifact>',
        '<artifact name="solution.py">print(1)</artifact>'
        '<artifact name="method_contract.json">{"implementation":{"covers":["CON-1"]}}</artifact>',
    ])
    calls = {"n": 0}
    snapshots = []

    def fake_run(code, work_dir, timeout=300):
        calls["n"] += 1
        return (
            _fail("方法契约失败: 未覆盖 CON-1")
            if calls["n"] == 1
            else ExecutionResult(success=True, stdout="ok", stderr="", return_code=0)
        )

    monkeypatch.setattr(coder_mod, "run_python_code", fake_run)
    artifacts, result = CoderAgent(llm).implement_with_retry(
        model="模型", params="{}", work_dir=Path("."),
        method_contract='{"implementation":{"covers":["CON-1"]}}',
        on_candidate=snapshots.append,
    )

    assert result.success
    assert json.loads(artifacts["method_contract.json"])["implementation"]["covers"] == ["CON-1"]
    assert json.loads(snapshots[-1]["method_contract.json"])["implementation"]["covers"] == ["CON-1"]
    assert any('"covers":[]' in message["content"] for message in llm.messages[1])


def test_reflection_strips_fences_when_no_artifact_tags(monkeypatch):
    # 反思回复漂移为裸代码块：剥栅栏后作为修正代码，第 2 轮执行成功
    llm = StubLLM([
        _code_response(0),
        "```python\nprint('fixed')\n```",
    ])
    calls = {"n": 0}

    def fake_run(code, work_dir, timeout=300):
        calls["n"] += 1
        if calls["n"] == 1:
            return _fail("NameError: x")
        assert code == "print('fixed')"
        return ExecutionResult(success=True, stdout="ok", stderr="", return_code=0)

    monkeypatch.setattr(coder_mod, "run_python_code", fake_run)
    agent = CoderAgent(llm)
    artifacts, result = agent.implement_with_retry(model="模型", params="{}", work_dir=Path("."))
    assert result.success
    assert artifacts["solution.py"] == "print('fixed')"


def test_success_first_round_no_reflection(monkeypatch):
    llm = StubLLM([_code_response(0)])

    def fake_run(code, work_dir, timeout=300):
        return ExecutionResult(
            success=True, stdout="ok", stderr="", return_code=0
        )

    monkeypatch.setattr(coder_mod, "run_python_code", fake_run)
    agent = CoderAgent(llm)
    artifacts, result = agent.implement_with_retry(
        model="模型", params="{}", work_dir=Path(".")
    )
    assert result is not None and result.success
    assert llm.calls == 1
    history = json.loads(artifacts["attempt_history.json"])
    assert history == [{
        "attempt": 1,
        "success": True,
        "timed_out": False,
        "error_summary": "",
        "stdout_tail": "ok",
        "stderr_tail": "",
    }]


def test_method_candidates_run_pilot_before_full_execution(monkeypatch):
    llm = StubLLM([_code_response(0)])
    calls = []

    def fake_run(code, work_dir, timeout=300, extra_env=None):
        calls.append((timeout, extra_env))
        return ExecutionResult(success=True, stdout="ok", stderr="", return_code=0)

    monkeypatch.setattr(coder_mod, "run_python_code", fake_run)
    _, result = CoderAgent(llm).implement_with_retry(
        model="模型",
        params="{}",
        work_dir=Path("."),
        method_candidates='{"schema_version":1}',
        pilot_validator=lambda result: "",
    )

    assert result is not None and result.success
    assert calls == [(30, {"MMW_PILOT": "1"}), (300, None)]


def test_moving_heat_model_must_reuse_runtime_helper(monkeypatch):
    llm = StubLLM([
        _code_response(0),
        '<artifact name="solution.py">'
        "from _mmw_moving_heat import "
        "MovingSlabConfig, assess_multistart_identifiability\n"
        "assess_multistart_identifiability([[1],[1],[1]],[0,0,0],"
        "initial_parameter_sets=[[0],[1],[2]])\nprint('ok')"
        "</artifact>",
    ])
    executed = []

    def fake_run(code, work_dir, timeout=300):
        executed.append(code)
        return ExecutionResult(success=True, stdout="ok", stderr="", return_code=0)

    monkeypatch.setattr(coder_mod, "run_python_code", fake_run)
    artifacts, result = CoderAgent(llm).implement_with_retry(
        model="采用一维瞬态导热模型",
        params="{}",
        work_dir=Path("."),
    )

    assert result.success
    assert executed == [
        "from _mmw_moving_heat import "
        "MovingSlabConfig, assess_multistart_identifiability\n"
        "assess_multistart_identifiability([[1],[1],[1]],[0,0,0],"
        "initial_parameter_sets=[[0],[1],[2]])\nprint('ok')"
    ]
    history = json.loads(artifacts["attempt_history.json"])
    assert "结构复用门禁失败" in history[0]["error_summary"]


def test_moving_heat_helper_detection_covers_common_wording():
    assert requires_moving_heat_helper("建立一维瞬态导热模型")
    assert requires_moving_heat_helper("采用一维非稳态导热 PDE")
    assert requires_moving_heat_helper("移动热过程的参数标定")
    assert requires_moving_heat_helper("采用少量炉区组经验一阶响应")
    assert requires_moving_heat_helper("采用有效平板状态空间")
    assert not requires_moving_heat_helper("普通车辆路径优化")


def test_reduced_moving_heat_model_must_call_tested_helper():
    model = "采用经验一阶响应并调用 simulate_piecewise_first_order"
    code = (
        "from _mmw_moving_heat import assess_multistart_identifiability\n"
        "assess_multistart_identifiability([[1],[1],[1]],[0,0,0],"
        "initial_parameter_sets=[[0],[1],[2]])"
    )

    assert "结构复用门禁失败" in moving_heat_code_error(model, code)
    assert moving_heat_code_error(
        model,
        code
        + "\nsimulate_piecewise_first_order([0], speed=1, "
        "air_position_knots=[0,1], air_temperatures=[20,20], "
        "response_position_knots=[0,1], response_rates=[1,1], "
        "initial_temperature=20)",
    ) == ""


def test_effective_slab_model_must_call_tested_helper():
    model = "采用有效平板状态空间并调用 simulate_effective_slab"
    code = (
        "from _mmw_moving_heat import assess_multistart_identifiability\n"
        "assess_multistart_identifiability([[1],[1],[1]],[0,0,0],"
        "initial_parameter_sets=[[0],[1],[2]])"
    )

    assert "结构复用门禁失败" in moving_heat_code_error(model, code)
    assert moving_heat_code_error(
        model,
        code + "\nsimulate_effective_slab([0,1], speed=1)",
    ) == ""


def test_moving_heat_prompts_distinguish_explicit_stability_and_report_shape():
    agent = CoderAgent(StubLLM([]))
    system_prompt = agent.render_system_prompt()
    user_prompt = agent.render_prompt(
        "code.j2",
        model="",
        params="",
        problem_text="",
        data_summary="",
        verify_notes="",
        data_files=[],
        deliverables=[],
        runtime_summary="",
        figures_dir="figures",
        results_dir="results",
        method_contract="{}",
    )

    for prompt in (coder_mod.REFLECTION_PROMPT, system_prompt):
        assert "只约束 `scheme='explicit'`" in prompt or "只有 `scheme='explicit'`" in prompt
        assert "隐式格式不得被显式扩散数条件阻断" in prompt
    assert "单位与 `thickness` 的倒数一致" in coder_mod.REFLECTION_PROMPT
    assert "`speed/60`（`cm/s`）" in coder_mod.REFLECTION_PROMPT
    assert "不能靠新增时间偏移等自由度改变模型" in coder_mod.REFLECTION_PROMPT
    assert "附件非零首时刻直接作为物理时刻" in coder_mod.REFLECTION_PROMPT
    assert "环境温度固定使用设定平台与真实间隙线性过渡" in coder_mod.REFLECTION_PROMPT
    assert "只实现现役降阶 formulation" in coder_mod.REFLECTION_PROMPT
    assert "不得用任意 `区域均值残差 / 全局 RMSE` 比例单独 raise" in coder_mod.REFLECTION_PROMPT
    assert "附件非零首时刻直接作为物理时刻" in system_prompt
    assert "只实现和证明现役降阶 formulation" in system_prompt
    assert "不得用任意 `区域均值残差 / 全局 RMSE` 比例单独 raise" in system_prompt
    assert "触边距离也必须按对数搜索区间计算" in system_prompt
    assert "附件的非零首时刻就是物理时刻" in user_prompt
    assert "不得用任意 `区域均值残差 / 全局 RMSE` 比例单独 raise" in user_prompt
    for prompt in (coder_mod.REFLECTION_PROMPT, system_prompt, user_prompt):
        assert "原始返回对象必须直接、无包装地写入" in prompt
        assert "identifiability.json" in prompt
        assert "失败约束 ID" in prompt
    assert "solution.patch" in coder_mod.REFLECTION_PROMPT


def test_reflection_partial_patch_does_not_replace_complete_candidate(monkeypatch):
    complete = (
        "print('first')\n"
        "# results.json sensitivity.json method_runtime.json\n"
    )
    partial = "def replacement_only():\n    return 1\n"
    fixed = (
        "print('fixed')\n"
        "# results.json sensitivity.json method_runtime.json\n"
    )
    llm = StubLLM([
        f'<artifact name="solution.py">{complete}</artifact>',
        f'<artifact name="solution.py">{partial}</artifact>',
        f'<artifact name="solution.py">{fixed}</artifact>',
    ])
    executed = []
    recovered = []

    def fake_run(code, work_dir, timeout=300):
        executed.append(code)
        if len(executed) < 2:
            return _fail("RuntimeError: retry")
        return ExecutionResult(success=True, stdout="ok", stderr="", return_code=0)

    monkeypatch.setattr(coder_mod, "run_python_code", fake_run)
    artifacts, result = CoderAgent(llm).implement_with_retry(
        model="普通模型",
        params="{}",
        work_dir=Path("."),
        on_candidate=recovered.append,
    )

    assert result.success
    assert executed == [complete.strip(), fixed.strip()]
    assert [item["solution.py"] for item in recovered] == [
        complete.strip(),
        fixed.strip(),
    ]
    assert artifacts["solution.py"] == fixed.strip()


def test_successful_process_with_invalid_output_is_reflected(monkeypatch):
    llm = StubLLM([_code_response(0), _code_response(1)])
    calls = {"n": 0}

    def fake_run(code, work_dir, timeout=300):
        calls["n"] += 1
        return ExecutionResult(
            success=True,
            stdout="近似方案" if calls["n"] == 1 else "严格可行方案",
            stderr="",
            return_code=0,
        )

    def validate(result):
        return "未找到可行解却输出近似方案" if "近似" in result.stdout else ""

    monkeypatch.setattr(coder_mod, "run_python_code", fake_run)
    artifacts, result = CoderAgent(llm).implement_with_retry(
        model="模型",
        params="{}",
        work_dir=Path("."),
        output_validator=validate,
    )

    assert result.success
    assert artifacts["solution.py"] == "print(1)"
    assert llm.calls == 2
    history = json.loads(artifacts["attempt_history.json"])
    assert [item["success"] for item in history] == [False, True]
    assert "输出质量门禁失败" in history[0]["error_summary"]
    assert any(
        "输出质量门禁失败" in message["content"]
        for batch in llm.messages
        for message in batch
    )


def test_numpy_trapz_is_fixed_when_unavailable(monkeypatch):
    import numpy as np

    monkeypatch.delattr(np, "trapz", raising=False)
    code = "import numpy as np\ny = np.trapz([1, 2])"

    assert "np.trapezoid(" in _apply_compatibility_fixes(code)


def test_singular_inverse_is_replaced_before_llm_reflection(monkeypatch):
    llm = StubLLM([
        '<artifact name="solution.py">import numpy as np\nnp.linalg.inv([[1]])</artifact>'
    ])

    def fake_run(code, work_dir, timeout=300):
        if "np.linalg.pinv(" in code:
            return ExecutionResult(success=True, stdout="ok", stderr="", return_code=0)
        return _fail("numpy.linalg.LinAlgError: Singular matrix")

    monkeypatch.setattr(coder_mod, "run_python_code", fake_run)
    artifacts, result = CoderAgent(llm).implement_with_retry(
        model="模型", params="{}", work_dir=Path(".")
    )

    assert result.success
    assert "np.linalg.pinv(" in artifacts["solution.py"]
    assert llm.calls == 1


def test_same_name_error_gets_escalated_reflection(monkeypatch):
    llm = StubLLM([
        '<artifact name="solution.py">print(ok_q4)</artifact>',
        '<artifact name="solution.py">print(ok_q4)</artifact>',
        '<artifact name="solution.py">ok_q4 = False\nprint(ok_q4)</artifact>',
    ])

    def fake_run(code, work_dir, timeout=300):
        if "ok_q4 = False" in code:
            return ExecutionResult(success=True, stdout="ok", stderr="", return_code=0)
        return _fail("NameError: name 'ok_q4' is not defined")

    monkeypatch.setattr(coder_mod, "run_python_code", fake_run)
    _, result = CoderAgent(llm).implement_with_retry(
        model="模型", params="{}", work_dir=Path(".")
    )

    assert result.success
    assert llm.calls == 3


def test_timeout_stops_after_one_complexity_reflection(monkeypatch):
    llm = StubLLM([_code_response(0), _code_response(1), _code_response(2)])

    def fake_run(code, work_dir, timeout=300):
        return ExecutionResult(
            success=False, stdout="", stderr="", return_code=-1,
            timed_out=True, error_summary="执行超时（300秒）",
        )

    monkeypatch.setattr(coder_mod, "run_python_code", fake_run)
    _, result = CoderAgent(llm).implement_with_retry(
        model="模型", params="{}", work_dir=Path(".")
    )

    assert result.timed_out
    assert llm.calls == 2


def test_rerun_revises_previous_failed_code_before_execution(monkeypatch):
    llm = StubLLM([_code_response(1)])

    def fake_run(code, work_dir, timeout=300):
        assert code == "print(1)"
        return ExecutionResult(success=True, stdout="ok", stderr="", return_code=0)

    monkeypatch.setattr(coder_mod, "run_python_code", fake_run)
    artifacts, result = CoderAgent(llm).implement_with_retry(
        model="模型",
        params="{}",
        work_dir=Path("."),
        previous_code="print(0)",
        revision_feedback="代码运行明确产生占位结果",
    )

    assert result.success
    assert artifacts["solution.py"] == "print(1)"
    assert llm.calls == 1
    assert "raise" in _issue_notice("占位结果")
    assert "距离缩放" in _issue_notice("参数 v 的扰动结果全为零")


def test_missing_constraint_coverage_revises_code_and_contract_together(monkeypatch):
    llm = StubLLM([
        '<artifact name="solution.py">print(1)</artifact>'
        '<artifact name="method_contract.json">'
        '{"implementation":{"covers":["CON-1"]}}</artifact>',
    ])
    monkeypatch.setattr(
        coder_mod,
        "run_python_code",
        lambda *args: ExecutionResult(
            success=True, stdout="ok", stderr="", return_code=0,
        ),
    )

    artifacts, result = CoderAgent(llm).implement_with_retry(
        model="模型",
        params="{}",
        work_dir=Path("."),
        previous_code="print(0)",
        revision_feedback="code 方法契约失败: 实现未覆盖硬约束: CON-1",
        method_contract='{"implementation":{"covers":[]}}',
    )

    assert result.success
    assert json.loads(artifacts["method_contract.json"])["implementation"]["covers"] == ["CON-1"]
    assert artifacts["solution.py"] == "print(1)"
    assert llm.calls == 1


def test_incomplete_directed_revision_fails_before_old_code_runs(monkeypatch):
    old = "print('old')\n# results.json sensitivity.json method_runtime.json"
    fixed = "print('fixed')\n# results.json sensitivity.json method_runtime.json"
    llm = StubLLM([
        '<artifact name="solution.py">def patch_only(): return 1</artifact>',
        f'<artifact name="solution.py">{fixed}</artifact>',
    ])
    executed = []

    def fake_run(code, work_dir, timeout=300):
        executed.append(code)
        return ExecutionResult(success=True, stdout="ok", stderr="", return_code=0)

    monkeypatch.setattr(coder_mod, "run_python_code", fake_run)
    artifacts, result = CoderAgent(llm).implement_with_retry(
        model="普通模型",
        params="{}",
        work_dir=Path("."),
        previous_code=old,
        revision_feedback="缺少 result.csv 和 q2/q3/q4",
    )

    assert result.success
    assert executed == [fixed]
    assert artifacts["solution.py"] == fixed
    latest_user = next(
        message["content"] for message in reversed(llm.messages[1])
        if message["role"] == "user"
    )
    assert "缺少 result.csv 和 q2/q3/q4" in latest_user


def test_incomplete_reflection_does_not_reexecute_stale_code(monkeypatch):
    old = "print('old')\n# results.json sensitivity.json method_runtime.json"
    fixed = "print('fixed')\n# results.json sensitivity.json method_runtime.json"
    llm = StubLLM([
        f'<artifact name="solution.py">{old}</artifact>',
        '<artifact name="solution.py">def patch_only(): return 1</artifact>',
        f'<artifact name="solution.py">{fixed}</artifact>',
    ])
    executed = []

    def fake_run(code, work_dir, timeout=300):
        executed.append(code)
        if code == old:
            return _fail("RuntimeError: fit failed")
        return ExecutionResult(success=True, stdout="ok", stderr="", return_code=0)

    monkeypatch.setattr(coder_mod, "run_python_code", fake_run)
    artifacts, result = CoderAgent(llm).implement_with_retry(
        model="普通模型",
        params="{}",
        work_dir=Path("."),
    )

    assert result.success
    assert executed == [old, fixed]
    assert artifacts["solution.py"] == fixed


def test_model_rework_marker_stops_code_reflection(monkeypatch):
    llm = StubLLM([_code_response(0)])
    monkeypatch.setattr(
        coder_mod,
        "run_python_code",
        lambda *args: _fail(
            "RuntimeError: MODEL_REWORK_REQUIRED: current formulation is insufficient"
        ),
    )

    artifacts, result = CoderAgent(llm).implement_with_retry(
        model="模型", params="{}", work_dir=Path("."),
    )

    assert result is not None and not result.success
    assert llm.calls == 1
    assert "MODEL_REWORK_REQUIRED" in result.error_summary
    assert json.loads(artifacts["attempt_history.json"])[-1]["attempt"] == 1


def test_effective_slab_output_dimension_marker_requires_code_reflection():
    assert not coder_mod.model_rework_requested(
        "RuntimeError: MODEL_REWORK_REQUIRED: "
        "actual_runtime_center_output_dimension=1 required_state_nodes=7"
    )
    assert not coder_mod.model_rework_requested(
        "RuntimeError: MODEL_REWORK_REQUIRED: api_state_dimension=1"
    )


def test_interrupted_candidate_resumes_without_new_llm_request(monkeypatch):
    llm = StubLLM([])
    saved = []

    def fake_run(code, work_dir, timeout=300):
        assert code == "print('recovered')"
        return ExecutionResult(success=True, stdout="ok", stderr="", return_code=0)

    monkeypatch.setattr(coder_mod, "run_python_code", fake_run)
    artifacts, result = CoderAgent(llm).implement_with_retry(
        model="模型",
        params="{}",
        work_dir=Path("."),
        previous_code="print('recovered')",
        method_contract='{"implementation":{"class":"heuristic"}}',
        on_candidate=saved.append,
    )

    assert result.success
    assert artifacts["solution.py"] == "print('recovered')"
    assert [item["solution.py"] for item in saved] == ["print('recovered')"]
    assert saved[0]["method_contract.json"] == '{"implementation":{"class":"heuristic"}}'
    assert llm.calls == 0


def test_exact_unified_patch_revises_long_candidate(monkeypatch):
    original = "print('old')\n# results.json sensitivity.json method_runtime.json\n"
    response = (
        '<artifact name="solution.patch">@@ -1,2 +1,2 @@\n'
        "-print('old')\n+print('fixed')\n"
        " # results.json sensitivity.json method_runtime.json</artifact>"
        '<artifact name="method_contract.json">'
        '{"implementation":{"class":"heuristic"}}</artifact>'
    )
    llm = StubLLM([response])
    executed = []

    def fake_run(code, work_dir, timeout=300):
        executed.append(code)
        return ExecutionResult(success=True, stdout="ok", stderr="", return_code=0)

    monkeypatch.setattr(coder_mod, "run_python_code", fake_run)
    artifacts, result = CoderAgent(llm).implement_with_retry(
        model="普通模型",
        params="{}",
        work_dir=Path("."),
        previous_code=original,
        revision_feedback="旧实现需要定向修订",
        method_contract='{"implementation":{"class":"heuristic"}}',
    )

    assert result.success
    assert executed == [
        "print('fixed')\n# results.json sensitivity.json method_runtime.json\n"
    ]
    assert artifacts["solution.py"] == executed[0]
    assert "solution.patch" not in artifacts


def test_fenced_unified_patch_is_not_misread_as_solution(monkeypatch):
    original = "print('old')\n# results.json sensitivity.json method_runtime.json\n"
    response = (
        '<artifact name="solution.patch">```diff\n@@ -1,2 +1,2 @@\n'
        "-print('old')\n+print('fixed')\n"
        " # results.json sensitivity.json method_runtime.json\n```</artifact>"
        '<artifact name="method_contract.json">```json\n'
        '{"implementation":{"class":"heuristic"}}\n```</artifact>'
    )
    llm = StubLLM([response])
    executed = []

    def fake_run(code, work_dir, timeout=300):
        executed.append(code)
        return ExecutionResult(success=True, stdout="ok", stderr="", return_code=0)

    monkeypatch.setattr(coder_mod, "run_python_code", fake_run)
    artifacts, result = CoderAgent(llm).implement_with_retry(
        model="普通模型",
        params="{}",
        work_dir=Path("."),
        previous_code=original,
        revision_feedback="旧实现需要定向修订",
        method_contract='{"implementation":{"class":"heuristic"}}',
    )

    assert result.success
    assert executed == [
        "print('fixed')\n# results.json sensitivity.json method_runtime.json\n"
    ]
    assert artifacts["solution.py"] == executed[0]
    assert "solution.patch" not in artifacts


def test_unified_patch_rejects_context_mismatch_and_missing_hunk():
    with pytest.raises(ValueError, match="不匹配"):
        apply_solution_patch("a\nb\n", "@@ -1,1 +1,1 @@\n-x\n+y")
    with pytest.raises(ValueError, match="缺少"):
        apply_solution_patch("a\n", "--- a.py\n+++ a.py")


def test_unified_patch_recounts_incorrect_header_counts():
    patch = "@@ -1,99 +1,88 @@\n-old\n+new\n tail"

    assert apply_solution_patch("old\ntail\n", patch) == "new\ntail\n"


def test_unified_patch_relocates_unique_exact_context():
    original = "header\nalpha\nold\nomega\n"
    patch = "@@ -20,3 +20,3 @@\n alpha\n-old\n+new\n omega"

    assert apply_solution_patch(original, patch) == "header\nalpha\nnew\nomega\n"


def test_unified_patch_rejects_ambiguous_relocated_context():
    original = "old\nmiddle\nold\n"
    patch = "@@ -20,1 +20,1 @@\n-old\n+new"

    with pytest.raises(ValueError, match="不唯一"):
        apply_solution_patch(original, patch)


def test_recovered_candidate_reflection_keeps_original_task_context(monkeypatch):
    llm = StubLLM([_code_response(1)])
    executed = []

    def fake_run(code, work_dir, timeout=300):
        executed.append(code)
        if code == "print('recovered')":
            return _fail("RuntimeError: missing calibrated input")
        return ExecutionResult(success=True, stdout="ok", stderr="", return_code=0)

    monkeypatch.setattr(coder_mod, "run_python_code", fake_run)
    artifacts, result = CoderAgent(llm).implement_with_retry(
        model="分区一阶响应模型 MODEL-CONTEXT",
        params='{"alpha": 0.1}',
        problem_text="ORIGINAL-PROBLEM-CONTEXT",
        data_summary="DATA-SUMMARY-CONTEXT",
        data_files=["E:/case/附件.xlsx"],
        deliverables=[{"name": "result.csv"}],
        work_dir=Path("."),
        previous_code="print('recovered')",
        method_contract='{"implementation":{"class":"heuristic"}}',
    )

    assert result.success
    assert artifacts["solution.py"] == "print(1)"
    assert executed == ["print('recovered')", "print(1)"]
    assert llm.calls == 1
    request = "\n".join(message["content"] for message in llm.messages[0])
    assert "ORIGINAL-PROBLEM-CONTEXT" in request
    assert "MODEL-CONTEXT" in request
    assert "E:/case/附件.xlsx" in request
    assert '"class":"heuristic"' in request


def test_reflection_provider_failure_keeps_candidate_and_history(monkeypatch):
    llm = StubLLM([_code_response(0)])
    agent = CoderAgent(llm)
    original_run_stream = agent.run_stream
    calls = {"n": 0}

    def fail_only_reflection(prompt):
        calls["n"] += 1
        if calls["n"] == 2:
            raise APIError("provider busy", request=httpx.Request("POST", "https://example.test"), body=None)
        return original_run_stream(prompt)

    monkeypatch.setattr(agent, "run_stream", fail_only_reflection)
    monkeypatch.setattr(coder_mod, "run_python_code", lambda *args: _fail("RuntimeError: 无可行解"))

    artifacts, result = agent.implement_with_retry(model="模型", params="{}", work_dir=Path("."))

    assert result is not None and not result.success
    assert artifacts["solution.py"] == "print(0)"
    history = json.loads(artifacts["attempt_history.json"])
    assert history[-1]["phase"] == "reflection"
    assert "LLM 修订请求失败" in history[-1]["error_summary"]
