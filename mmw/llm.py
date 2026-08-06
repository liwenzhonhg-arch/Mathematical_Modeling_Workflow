"""LLM 客户端：基于 OpenAI SDK，兼容 DeepSeek / Claude / Kimi 等。"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import time
from collections.abc import Iterable
from collections.abc import Callable
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from openai import OpenAI

from mmw.config import LLMConfig
from mmw.utils.display import console


_token_usage_observer: ContextVar[Callable[[int, int], None] | None] = ContextVar(
    "mmw_token_usage_observer",
    default=None,
)
_token_request_guard: ContextVar[Callable[[], None] | None] = ContextVar(
    "mmw_token_request_guard",
    default=None,
)


@contextmanager
def observe_token_usage(
    observer: Callable[[int, int], None],
    request_guard: Callable[[], None] | None = None,
):
    observer_token = _token_usage_observer.set(observer)
    guard_token = _token_request_guard.set(request_guard)
    try:
        yield
    finally:
        _token_request_guard.reset(guard_token)
        _token_usage_observer.reset(observer_token)


def _guard_token_request() -> None:
    if guard := _token_request_guard.get():
        guard()


class CodexCLIError(RuntimeError):
    """Codex CLI 已配置但单次调用失败，可由 Agent 请求层重试。"""


def codex_cli_status(timeout: float = 10) -> dict[str, bool | str]:
    """只检查 Codex CLI 与登录状态，不读取或返回本机会话凭据。"""
    command = "codex.cmd" if sys.platform == "win32" else "codex"
    executable = shutil.which(command)
    if not executable:
        return {"installed": False, "logged_in": False, "message": "未安装 Codex CLI"}
    try:
        result = subprocess.run(
            [executable, "login", "status"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return {"installed": True, "logged_in": False, "message": "无法检查 Codex 登录状态"}
    logged_in = result.returncode == 0
    return {
        "installed": True,
        "logged_in": logged_in,
        "message": "Codex CLI 已登录" if logged_in else "Codex CLI 未登录",
    }


def _warn_truncated(model: str) -> None:
    """finish_reason=length 截断警告：不显式提示会表现为下游 SyntaxError，定位成本极高。"""
    console.print(
        f"[bold red]警告：{model} 输出被 max_tokens 截断（finish_reason=length），"
        f"产出不完整，请调大 LLM_MAX_TOKENS 或对应 Agent 的 <ROLE>_MAX_TOKENS[/bold red]"
    )


class StreamResult:
    """流式响应包装器（单次消费）。迭代获取 chunk，结束后通过 .text 获取完整文本。"""

    def __init__(self, stream, client: "LLMClient", messages: list[dict]):
        self._started_at = time.monotonic()
        self._iterator = self._consume(stream, client, messages)
        self.text: str = ""
        self.finish_reason: str | None = None

    def _consume(self, stream, client: "LLMClient", messages: list[dict]):
        usage = None
        for chunk in stream:
            if chunk.usage:
                usage = chunk.usage
            if chunk.choices:
                if chunk.choices[0].finish_reason:
                    self.finish_reason = chunk.choices[0].finish_reason
                if chunk.choices[0].delta.content:
                    text = chunk.choices[0].delta.content
                    self.text += text
                    yield text
        if self.finish_reason == "length":
            _warn_truncated(client.model)
        if usage:
            client._track_usage(usage, messages, self.text, time.monotonic() - self._started_at)

    def __iter__(self):
        return self

    def __next__(self):
        return next(self._iterator)


class LLMClient:
    """统一 LLM 调用封装。"""

    def __init__(self, config: LLMConfig, log_dir: Path | None = None):
        self.config = config
        self.client = None if config.backend == "codex" else OpenAI(
            api_key=config.api_key,
            base_url=config.base_url,
            timeout=config.request_timeout,
        )
        self.model = config.model
        self.log_dir = log_dir
        self.log_role = ""
        self.total_input_tokens = 0
        self.total_output_tokens = 0

    @staticmethod
    def _codex_prompt(messages: list[dict]) -> str:
        transcript = "\n\n".join(
            f"[{message['role']}]\n{message['content']}" for message in messages
        )
        return (
            "你是 MMW 流水线中的文本生成器。不要执行命令、修改文件或解释工具调用；"
            "仅根据以下对话返回最终答案，并严格保留用户要求的 artifact 标签和格式。\n\n"
            f"{transcript}"
        )

    @staticmethod
    def _codex_usage(output: str) -> tuple[int, int] | None:
        for line in reversed(output.splitlines()):
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            usage = event.get("usage") if event.get("type") == "turn.completed" else None
            if not isinstance(usage, dict):
                continue
            input_tokens = usage.get("input_tokens")
            output_tokens = usage.get("output_tokens")
            if (
                isinstance(input_tokens, int)
                and not isinstance(input_tokens, bool)
                and input_tokens >= 0
                and isinstance(output_tokens, int)
                and not isinstance(output_tokens, bool)
                and output_tokens >= 0
            ):
                return input_tokens, output_tokens
        return None

    def _chat_codex(self, messages: list[dict]) -> str:
        executable = shutil.which("codex.cmd" if sys.platform == "win32" else "codex")
        if not executable:
            raise RuntimeError("未安装 Codex CLI，请先安装并运行 codex login")
        with tempfile.TemporaryDirectory(prefix="mmw-codex-") as temp_name:
            output_path = Path(temp_name) / "response.txt"
            command = [
                executable,
                "exec",
                "--ephemeral",
                "--ignore-user-config",
                "--ignore-rules",
                "--sandbox",
                "read-only",
                "--skip-git-repo-check",
                "--cd",
                temp_name,
                "--json",
                "--output-last-message",
                str(output_path),
                "-",
            ]
            started_at = time.monotonic()
            try:
                completed = subprocess.run(
                    command,
                    input=self._codex_prompt(messages),
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    capture_output=True,
                    timeout=self.config.request_timeout,
                    check=False,
                )
                if completed.returncode:
                    if not codex_cli_status()["logged_in"]:
                        raise RuntimeError("Codex CLI 未登录，请先运行 codex login")
                    raise CodexCLIError(
                        f"Codex CLI 调用失败（退出码 {completed.returncode}）"
                    )
                if not output_path.is_file():
                    raise CodexCLIError("Codex CLI 未生成响应")
                response = output_path.read_text(encoding="utf-8").strip()
                if not response:
                    raise CodexCLIError("Codex CLI 返回空响应")
                if usage := self._codex_usage(getattr(completed, "stdout", "")):
                    self._track_usage(
                        SimpleNamespace(
                            prompt_tokens=usage[0],
                            completion_tokens=usage[1],
                        ),
                        messages,
                        response,
                        time.monotonic() - started_at,
                    )
                return response
            except subprocess.TimeoutExpired as exc:
                raise CodexCLIError("Codex CLI 调用超时") from exc

    def chat(
        self,
        messages: list[dict],
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> str:
        """同步聊天，返回完整响应文本。"""
        _guard_token_request()
        if self.config.backend == "codex":
            return self._chat_codex(messages)
        started_at = time.monotonic()
        resp = self.client.chat.completions.create(
            model=self.model,
            messages=messages,
            temperature=self.config.temperature if temperature is None else temperature,
            max_tokens=self.config.max_tokens if max_tokens is None else max_tokens,
        )
        content = resp.choices[0].message.content or ""
        if resp.choices[0].finish_reason == "length":
            _warn_truncated(self.model)
        self._track_usage(resp.usage, messages, content, time.monotonic() - started_at)
        return content

    def chat_stream(
        self,
        messages: list[dict],
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> Iterable[str]:
        """流式聊天，返回 StreamResult 供调用方迭代并获取完整文本。"""
        _guard_token_request()
        if self.config.backend == "codex":
            return iter((self._chat_codex(messages),))
        stream = self.client.chat.completions.create(
            model=self.model,
            messages=messages,
            temperature=self.config.temperature if temperature is None else temperature,
            max_tokens=self.config.max_tokens if max_tokens is None else max_tokens,
            stream=True,
            stream_options={"include_usage": True},
        )
        return StreamResult(stream, self, messages)

    def _track_usage(
        self,
        usage,
        messages: list[dict],
        response: str,
        duration_seconds: float = 0.0,
    ) -> None:
        """记录 token 用量，可选写入日志文件。"""
        if not usage:
            return
        input_tokens = getattr(usage, "prompt_tokens", 0) or 0
        output_tokens = getattr(usage, "completion_tokens", 0) or 0
        self.total_input_tokens += input_tokens
        self.total_output_tokens += output_tokens

        if self.log_dir:
            self.log_dir.mkdir(parents=True, exist_ok=True)
            ts = datetime.now().strftime("%Y-%m-%d_%H-%M-%S-%f")
            log_entry = {
                "timestamp": ts,
                "model": self.model,
                "role": self.log_role,
                "duration_seconds": round(max(0.0, duration_seconds), 3),
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "messages_count": len(messages),
                "response_length": len(response),
            }
            log_file = self.log_dir / f"{ts}_{self.model.replace('/', '_')}.json"
            log_file.write_text(json.dumps(log_entry, ensure_ascii=False, indent=2), encoding="utf-8")
        if observer := _token_usage_observer.get():
            observer(input_tokens, output_tokens)

    def get_usage_summary(self) -> dict:
        """返回累计 token 用量。"""
        return {
            "model": self.model,
            "total_input_tokens": self.total_input_tokens,
            "total_output_tokens": self.total_output_tokens,
            "total_tokens": self.total_input_tokens + self.total_output_tokens,
        }
