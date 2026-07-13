"""Coder 反思循环测试：同错误连续出现时提前终止，避免空转烧 token。"""

from pathlib import Path

import mmw.agents.coder as coder_mod
from mmw.agents.coder import (
    MAX_RETRIES,
    CoderAgent,
    _apply_compatibility_fixes,
    _issue_notice,
)
from mmw.utils.executor import ExecutionResult


class StubLLM:
    model = "stub"
    total_input_tokens = 0
    total_output_tokens = 0

    def __init__(self, responses: list[str]):
        self.responses = list(responses)
        self.calls = 0

    def chat(self, messages, **kwargs):
        self.calls += 1
        return self.responses.pop(0)

    def chat_stream(self, messages, **kwargs):
        self.calls += 1
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
    _, result = agent.implement_with_retry(model="模型", params="{}", work_dir=Path("."))
    assert result is not None and result.success
    assert llm.calls == 1


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
