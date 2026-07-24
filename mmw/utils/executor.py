"""代码沙箱执行器：subprocess 运行 Python 代码，捕获输出和错误。"""

from __future__ import annotations

import ast
import os
import re
import subprocess
import sys
import shutil
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
RUNTIME_HELPER_NAME = "_mmw_moving_heat.py"


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
    if not resolved.is_relative_to(work_dir.resolve()):
        raise ValueError(f"脚本必须位于工作目录内: {script_path}")
    unsafe = _unsafe_python(resolved.read_text(encoding="utf-8"))
    if unsafe:
        return ExecutionResult(
            success=False, stdout="", stderr="", return_code=-1,
            error_summary=f"安全检查拒绝执行: {unsafe}",
        )
    secret_name = re.compile(r"(?:KEY|TOKEN|SECRET|PASSWORD|CREDENTIAL)", re.IGNORECASE)
    env = {k: v for k, v in os.environ.items() if not secret_name.search(k)}
    env.update({"PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"})
    helper_path = work_dir / RUNTIME_HELPER_NAME
    if helper_path.exists():
        raise ValueError(f"运行时辅助模块路径已被占用: {helper_path}")
    helper_source = Path(__file__).with_name("moving_heat.py")
    shutil.copyfile(helper_source, helper_path)
    bootstrap = (
        "import runpy,sys;"
        "sys.path.insert(0,sys.argv[1]);"
        "runpy.run_path(sys.argv[2],run_name='__main__')"
    )
    try:
        proc = subprocess.run(
            [
                sys.executable, "-I", "-X", "utf8", "-c", bootstrap,
                str(work_dir.resolve()), str(resolved),
            ],
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
    finally:
        helper_path.unlink(missing_ok=True)

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


def _unsafe_python(code: str) -> str:
    """拒绝生成代码中的网络、子进程和动态执行入口。"""
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return ""
    banned_modules = {"subprocess", "socket", "requests", "urllib", "http", "ftplib", "smtplib"}
    banned_calls = {"eval", "exec", "compile", "__import__"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            module = next(
                (name.name for name in node.names if name.name.split(".")[0] in banned_modules),
                "",
            )
            if module:
                return f"禁止导入 {module}"
        elif isinstance(node, ast.ImportFrom) and (node.module or "").split(".")[0] in banned_modules:
            return f"禁止导入 {node.module}"
        elif isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name) and node.func.id in banned_calls:
                return f"禁止调用 {node.func.id}"
            if isinstance(node.func, ast.Attribute) and isinstance(node.func.value, ast.Name):
                if node.func.value.id == "os" and node.func.attr in {"system", "popen", "spawnl", "spawnv"}:
                    return f"禁止调用 os.{node.func.attr}"
    return ""


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
