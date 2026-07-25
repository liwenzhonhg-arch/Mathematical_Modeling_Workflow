"""代码沙箱执行器测试：正常执行、错误检测、超时、截断。"""

from types import SimpleNamespace

import pytest

from mmw.utils import executor
from mmw.utils.executor import (
    MAX_OUTPUT_CHARS,
    _truncate,
    run_python_code,
    run_python_script,
)


def test_successful_execution(tmp_path):
    result = run_python_code('print("hello mmw")', tmp_path)
    assert result.success
    assert "hello mmw" in result.stdout
    assert result.return_code == 0
    assert not result.timed_out


def test_network_and_subprocess_imports_are_rejected(tmp_path):
    result = run_python_code("import requests\nprint('no')", tmp_path)
    assert not result.success
    assert "安全检查拒绝执行" in result.error_summary


def test_runtime_error_detected(tmp_path):
    result = run_python_code("raise ValueError('数据缺失')", tmp_path)
    assert not result.success
    assert "ValueError" in result.error_summary


def test_syntax_error_detected(tmp_path):
    result = run_python_code("def f(:\n    pass", tmp_path)
    assert not result.success
    assert "SyntaxError" in result.error_summary


def test_timeout(tmp_path):
    result = run_python_code("import time; time.sleep(30)", tmp_path, timeout=2)
    assert not result.success
    assert result.timed_out
    assert "超时" in result.error_summary


def test_temp_script_cleaned_up(tmp_path):
    run_python_code("print(1)", tmp_path)
    assert not (tmp_path / "_mmw_temp_script.py").exists()
    assert not (tmp_path / "_mmw_moving_heat.py").exists()


def test_moving_heat_runtime_helper_is_importable_and_cleaned(tmp_path):
    result = run_python_code(
        "from _mmw_moving_heat import MovingSlabConfig\n"
        "print(MovingSlabConfig.__name__)",
        tmp_path,
    )

    assert result.success
    assert "MovingSlabConfig" in result.stdout
    assert not (tmp_path / "_mmw_moving_heat.py").exists()


def test_frozen_executor_uses_desktop_script_dispatch(tmp_path, monkeypatch):
    script = tmp_path / "solution.py"
    script.write_text("print('ok')", encoding="utf-8")
    captured = {}
    monkeypatch.setattr(executor.sys, "frozen", True, raising=False)
    monkeypatch.setattr(
        executor.subprocess,
        "run",
        lambda command, **kwargs: captured.setdefault(
            "call", SimpleNamespace(command=command, stdout="ok", stderr="", returncode=0)
        ),
    )

    assert run_python_script(script, tmp_path).success
    assert captured["call"].command[1:] == [
        "--mmw-run-script", str(tmp_path.resolve()), str(script.resolve())
    ]


def test_rejects_non_python_path(tmp_path):
    bad = tmp_path / "script.txt"
    bad.write_text("print(1)", encoding="utf-8")
    with pytest.raises(ValueError):
        run_python_script(bad, tmp_path)


def test_unicode_output_no_crash(tmp_path):
    # Windows GBK 场景：子进程通过 PYTHONIOENCODING 强制 UTF-8
    result = run_python_code('print("校验 ✓ 完成 ₂")', tmp_path)
    assert result.success
    assert "校验" in result.stdout


def test_truncate_long_output():
    text = "x" * (MAX_OUTPUT_CHARS + 1000)
    truncated = _truncate(text)
    assert len(truncated) < len(text)
    assert "截断" in truncated


def test_short_output_not_truncated():
    assert _truncate("short") == "short"
