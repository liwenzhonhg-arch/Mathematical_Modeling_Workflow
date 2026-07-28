"""Coder 反思循环测试：同错误连续出现时提前终止，避免空转烧 token。"""

import json
from pathlib import Path

import httpx
from openai import APIError

import mmw.agents.coder as coder_mod
from mmw.agents.coder import (
    MAX_RETRIES,
    CoderAgent,
    _apply_compatibility_fixes,
    _issue_notice,
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
    )

    assert result.success
    assert json.loads(artifacts["method_contract.json"])["implementation"]["covers"] == ["CON-1"]
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
    assert not requires_moving_heat_helper("普通车辆路径优化")


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
    for prompt in (coder_mod.REFLECTION_PROMPT, system_prompt, user_prompt):
        assert "原始返回对象必须直接、无包装地写入" in prompt
        assert "identifiability.json" in prompt


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


def test_rerun_repairs_omitted_method_contract_separately(monkeypatch):
    llm = StubLLM([
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
    assert artifacts["solution.py"] == "print(0)"
    assert llm.calls == 1


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
        on_candidate=saved.append,
    )

    assert result.success
    assert artifacts["solution.py"] == "print('recovered')"
    assert saved == ["print('recovered')"]
    assert llm.calls == 0


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
