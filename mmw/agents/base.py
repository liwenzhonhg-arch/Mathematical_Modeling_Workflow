"""Agent 基类：消息历史、上下文压缩、流式输出、产出解析。"""

from __future__ import annotations

import ast
import io
import json
import re
import sys
import time
from pathlib import Path

import httpx
from jinja2 import Environment, FileSystemLoader
from openai import APIConnectionError, APITimeoutError, InternalServerError, RateLimitError
from rich.console import Console
from rich.live import Live
from rich.panel import Panel
from rich.text import Text

from mmw.llm import LLMClient

# 网络抖动/服务端断流等可重试的异常
RETRYABLE_ERRORS = (
    APIConnectionError,
    APITimeoutError,
    RateLimitError,
    InternalServerError,
    httpx.TimeoutException,
    httpx.NetworkError,
    httpx.RemoteProtocolError,
    ConnectionError,
    TimeoutError,
)
MAX_STREAM_RETRIES = 3

# Windows 下 Rich 使用 legacy renderer 导致 GBK 编码错误，强制用 UTF-8 包装
if sys.platform == "win32" and hasattr(sys.stdout, "buffer"):
    _stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    console = Console(file=_stdout, force_terminal=True)
else:
    console = Console()

PROMPTS_DIR = Path(__file__).parent.parent / "prompts"

_jinja_env: Environment | None = None


def _get_jinja_env() -> Environment:
    global _jinja_env
    if _jinja_env is None:
        _jinja_env = Environment(
            loader=FileSystemLoader(str(PROMPTS_DIR)),
            keep_trailing_newline=True,
        )
    return _jinja_env


ARTIFACT_PATTERN = re.compile(
    r"<artifact\s+name=[\"']([^\"']+)[\"']\s*>(.*?)</artifact>",
    re.DOTALL,
)

COMPRESS_PROMPT = "请将以下对话历史压缩为简洁的摘要，保留关键信息和决策：\n\n"

_CODE_FENCE_RE = re.compile(r"^```\w*\n?", re.MULTILINE)


def _strip_code_fences(text: str) -> str:
    """去掉 LLM 输出中混入的 Markdown 代码块标记。"""
    text = _CODE_FENCE_RE.sub("", text)
    return text.strip("`").strip()


def _extract_named_json_artifact(response: str, name: str) -> str:
    """从 `# name` 后的 JSON 代码块恢复格式漂移的 artifact。"""
    match = re.search(
        rf"(?:^|\n)#+\s*{re.escape(name)}\s*\n\s*```json\s*(\{{.*?\}})\s*```",
        response,
        re.IGNORECASE | re.DOTALL,
    )
    if not match:
        return ""
    try:
        data = json.loads(match.group(1))
    except json.JSONDecodeError:
        return ""
    return json.dumps(data, ensure_ascii=False, indent=2)


def _extract_json_artifact_by_key(response: str, key: str) -> str:
    """从未命名的 JSON 代码块中提取包含指定顶层键的对象。"""
    for block in re.findall(r"```json\s*(\{.*?\})\s*```", response, re.DOTALL | re.IGNORECASE):
        try:
            data = json.loads(block)
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict) and key in data:
            return json.dumps(data, ensure_ascii=False, indent=2)
    return ""


# 中文全角标点 → 半角，仅用于 .py 文件后处理
_FULLWIDTH_MAP = str.maketrans({
    "，": ",", "：": ":", "；": ";", "（": "(", "）": ")",
    "【": "[", "】": "]", "“": '"', "”": '"',
    "‘": "'", "’": "'", "！": "!", "？": "?",
    "。": ".",
})


def _sanitize_python(code: str) -> str:
    """修复 LLM 生成的 Python 代码中的常见问题：将非字符串区域的全角标点替换为半角。"""
    lines: list[str] = []
    for line in code.splitlines():
        stripped = line.lstrip()
        # 注释行保留原样（中文注释）
        if stripped.startswith("#"):
            lines.append(line)
        else:
            lines.append(line.translate(_FULLWIDTH_MAP))
    # 只识别明确的 Markdown 列表/栅栏起点；其前缀能通过语法检查才裁掉尾部说明。
    trailer_index = next((
        index for index, line in enumerate(lines)
        if re.match(r"^\s*(?:```|\d+\.\s+\*\*|[-*]\s+\*\*)", line)
    ), None)
    variants = [lines[:trailer_index]] if trailer_index is not None else []
    variants.append(lines)
    for working_lines in variants:
        cleaned = "\n".join(working_lines).rstrip()
        try:
            ast.parse(cleaned)
            return cleaned
        except SyntaxError:
            pass

        # LLM 偶尔把一句说明塞进 artifact 首行；仅在删去说明后能通过语法检查时修复。
        for index, line in enumerate(working_lines[1:], 1):
            if not line.lstrip().startswith(("import ", "from ", "#", '"""', "'''")):
                continue
            candidate = "\n".join(working_lines[index:])
            try:
                ast.parse(candidate)
                return candidate
            except SyntaxError:
                continue
    return "\n".join(lines)


class BaseAgent:
    """所有 Agent 的基类。

    功能：
    - 消息历史管理 + token 近似计数
    - 上下文压缩（超阈值时 LLM 总结旧消息）
    - 流式输出到终端
    - XML artifact 标签解析为多文件产出
    """

    role: str = "base"
    system_prompt_template: str = ""
    context_window: int = 128000
    token_threshold_ratio: float = 0.7
    chars_per_token: int = 2  # 中文近似

    def __init__(self, llm: LLMClient):
        self.llm = llm
        self.chat_history: list[dict] = []
        self.current_token_count: int = 0

    # ── 提示词渲染 ────────────────────────────────────────

    def render_system_prompt(self, **kwargs) -> str:
        """渲染系统提示词模板。"""
        if not self.system_prompt_template:
            return ""
        env = _get_jinja_env()
        tmpl = env.get_template(self.system_prompt_template)
        return tmpl.render(**kwargs)

    def render_prompt(self, template_name: str, **kwargs) -> str:
        """渲染任务提示词模板。"""
        env = _get_jinja_env()
        tmpl = env.get_template(template_name)
        return tmpl.render(**kwargs)

    # ── 消息管理 ──────────────────────────────────────────

    def _estimate_tokens(self, text: str) -> int:
        return len(text) // self.chars_per_token

    def _append(self, role: str, content: str) -> None:
        self.chat_history.append({"role": role, "content": content})
        self.current_token_count += self._estimate_tokens(content)

    def _should_compress(self) -> bool:
        threshold = int(self.context_window * self.token_threshold_ratio)
        return self.current_token_count > threshold

    def _compress_history(self) -> None:
        """压缩旧消息：保留系统提示 + 最近 2 轮，中间部分让 LLM 总结。"""
        if len(self.chat_history) <= 5:
            return

        system_msgs = [m for m in self.chat_history if m["role"] == "system"]
        recent = self.chat_history[-4:]
        middle = self.chat_history[len(system_msgs):-4]

        if not middle:
            return

        middle_text = "\n".join(
            f"[{m['role']}]: {m['content'][:500]}" for m in middle
        )
        summary = self.llm.chat(
            [{"role": "user", "content": COMPRESS_PROMPT + middle_text}],
            temperature=0.3,
            max_tokens=1000,
        )

        self.chat_history = system_msgs + [
            {"role": "system", "content": f"[对话历史摘要]\n{summary}"},
        ] + recent

        self.current_token_count = sum(
            self._estimate_tokens(m["content"]) for m in self.chat_history
        )

    # ── 执行 ──────────────────────────────────────────────

    def run(self, user_input: str, system_kwargs: dict | None = None) -> str:
        """执行 Agent 任务，返回完整响应文本。"""
        if not self.chat_history:
            sys_prompt = self.render_system_prompt(**(system_kwargs or {}))
            if sys_prompt:
                self._append("system", sys_prompt)

        self._append("user", user_input)

        if self._should_compress():
            self._compress_history()

        response = self.llm.chat(self.chat_history)
        self._append("assistant", response)
        return response

    def run_stream(self, user_input: str, system_kwargs: dict | None = None) -> str:
        """流式执行，实时显示输出，返回完整响应文本。"""
        if not self.chat_history:
            sys_prompt = self.render_system_prompt(**(system_kwargs or {}))
            if sys_prompt:
                self._append("system", sys_prompt)

        self._append("user", user_input)

        if self._should_compress():
            self._compress_history()

        full_text = ""
        for attempt in range(1, MAX_STREAM_RETRIES + 1):
            try:
                stream = self.llm.chat_stream(self.chat_history)
                full_text = ""
                if not (getattr(sys.stdout, "isatty", lambda: False)() and console.is_terminal):
                    for chunk in stream:
                        full_text += chunk
                else:
                    with Live(console=console, refresh_per_second=4) as live:
                        for chunk in stream:
                            full_text += chunk
                            tail = full_text[-2000:] if len(full_text) > 2000 else full_text
                            live.update(Panel(Text(tail), title=f"[{self.role}]"))
                break
            except RETRYABLE_ERRORS as exc:
                if attempt == MAX_STREAM_RETRIES:
                    raise
                console.print(
                    f"[red]LLM 流式调用中断（{type(exc).__name__}: {exc}），"
                    f"{2 * attempt} 秒后进行第 {attempt + 1}/{MAX_STREAM_RETRIES} 次尝试...[/red]"
                )
                time.sleep(2 * attempt)

        self._append("assistant", full_text)
        return full_text

    # ── 产出解析 ──────────────────────────────────────────

    @staticmethod
    def parse_artifacts(response: str) -> dict[str, str]:
        """从响应中解析 <artifact name="...">...</artifact> 标签为文件字典。"""
        response = response.replace(r"\end{artifact}", "</artifact>")
        artifacts: dict[str, str] = {}
        for match in ARTIFACT_PATTERN.finditer(response):
            name = match.group(1).strip()
            content = match.group(2).strip()
            content = _strip_code_fences(content)
            artifacts[name] = content
        return artifacts

    @staticmethod
    def extract_section(response: str, section_name: str) -> str:
        """从 Markdown 响应中提取指定标题下的内容。"""
        pattern = rf"^##\s+{re.escape(section_name)}\s*\n(.*?)(?=^##\s|\Z)"
        match = re.search(pattern, response, re.MULTILINE | re.DOTALL)
        return match.group(1).strip() if match else ""
