"""代码沙箱执行器测试：正常执行、错误检测、超时、截断。"""

import pytest

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
