"""Coder 反思循环测试：同错误连续出现时提前终止，避免空转烧 token。"""

from pathlib import Path

import mmw.agents.coder as coder_mod
from mmw.agents.coder import MAX_RETRIES, CoderAgent
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
    # 第 1 轮失败后反思 1 次，第 2 轮同一错误 → 提前终止
    llm = StubLLM([_code_response(0)] + [_code_response(i) for i in range(1, MAX_RETRIES)])
    _, result = _run_with_errors(
        monkeypatch, ["SyntaxError: line 10"] * MAX_RETRIES, llm
    )
    assert result is not None and not result.success
    # 调用：implement 1 次 + 反思 1 次 = 2，远小于走满的 1 + (MAX_RETRIES - 1)
    assert llm.calls == 2


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
