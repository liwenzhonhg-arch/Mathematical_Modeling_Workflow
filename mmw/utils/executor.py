"""代码沙箱执行器：subprocess 运行 Python 代码，捕获输出和错误。"""

from __future__ import annotations

import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

ERROR_PATTERNS = [
    re.compile(r"Traceback \(most recent call last\):"),
    re.compile(r"SyntaxError:"),
    re.compile(r"IndentationError:"),
    re.compile(r"NameError:"),
    re.compile(r"TypeError:"),
    re.compile(r"ValueError:"),
    re.compile(r"ImportError:"),
    re.compile(r"ModuleNotFoundError:"),
]

MAX_OUTPUT_CHARS = 50000


@dataclass
class ExecutionResult:
    """代码执行结果。"""

    success: bool
    stdout: str
    stderr: str
    return_code: int
    timed_out: bool = False
    error_summary: str = ""
    truncated: bool = False


def run_python_script(
    script_path: Path,
    work_dir: Path,
    timeout: int = 300,
) -> ExecutionResult:
    """在指定工作目录下运行 Python 脚本。"""
    resolved = script_path.resolve()
    if not resolved.is_file() or resolved.suffix != ".py":
        raise ValueError(f"无效的脚本路径: {script_path}")
    env = {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"}
    try:
        proc = subprocess.run(
            ["python", str(resolved)],
            cwd=str(work_dir),
            capture_output=True,
            text=True,
            timeout=timeout,
            encoding="utf-8",
            errors="replace",
            env=env,
        )
    except subprocess.TimeoutExpired:
        return ExecutionResult(
            success=False,
            stdout="",
            stderr="",
            return_code=-1,
            timed_out=True,
            error_summary=f"执行超时（{timeout}秒）",
        )

    stdout = _truncate(proc.stdout or "")
    stderr = _truncate(proc.stderr or "")
    truncated = len(proc.stdout or "") > MAX_OUTPUT_CHARS or len(proc.stderr or "") > MAX_OUTPUT_CHARS

    has_error = proc.returncode != 0 or _detect_error(stderr)
    error_summary = ""
    if has_error:
        error_summary = _extract_error_summary(stderr)

    return ExecutionResult(
        success=not has_error,
        stdout=stdout,
        stderr=stderr,
        return_code=proc.returncode,
        error_summary=error_summary,
        truncated=truncated,
    )


def run_python_code(
    code: str,
    work_dir: Path,
    timeout: int = 300,
) -> ExecutionResult:
    """直接执行 Python 代码字符串。"""
    script_path = work_dir / "_mmw_temp_script.py"
    try:
        script_path.write_text(code, encoding="utf-8")
        return run_python_script(script_path, work_dir, timeout)
    finally:
        script_path.unlink(missing_ok=True)


def _detect_error(stderr: str) -> bool:
    """检测 stderr 中是否包含 Python 错误信息。"""
    return any(p.search(stderr) for p in ERROR_PATTERNS)


def _extract_error_summary(stderr: str) -> str:
    """从 stderr 中提取最后一个异常的摘要信息。"""
    lines = stderr.strip().splitlines()
    if not lines:
        return "未知错误"
    for i in range(len(lines) - 1, -1, -1):
        line = lines[i].strip()
        if line and not line.startswith("  "):
            return line
    return lines[-1].strip()


def _truncate(text: str) -> str:
    """截断过长的输出。"""
    if len(text) <= MAX_OUTPUT_CHARS:
        return text
    half = MAX_OUTPUT_CHARS // 2
    return text[:half] + f"\n\n... [截断：原始长度 {len(text)} 字符] ...\n\n" + text[-half:]
