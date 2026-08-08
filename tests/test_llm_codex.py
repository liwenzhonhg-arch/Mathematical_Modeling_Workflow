"""本机 Codex 后端：命令边界、结果读取和临时文件清理。"""

import json
import sys
from pathlib import Path

from mmw.config import LLMConfig
from mmw.llm import CodexCLIError, LLMClient, codex_cli_status


def test_codex_backend_uses_read_only_ephemeral_command(monkeypatch):
    calls = []
    executable = "codex.cmd" if sys.platform == "win32" else "codex"
    monkeypatch.setattr("mmw.llm.shutil.which", lambda _: executable)

    def fake_run(command, **kwargs):
        calls.append((command, kwargs))
        Path(command[command.index("--output-last-message") + 1]).write_text(
            "<artifact name=\"analysis.md\">ok</artifact>", encoding="utf-8"
        )
        return type("Completed", (), {
            "returncode": 0,
            "stdout": json.dumps({
                "type": "turn.completed",
                "usage": {
                    "input_tokens": 123,
                    "cached_input_tokens": 100,
                    "output_tokens": 45,
                },
            }),
        })()

    monkeypatch.setattr("mmw.llm.subprocess.run", fake_run)
    client = LLMClient(LLMConfig(api_key="", backend="codex", model="gpt-5.6-sol"))
    result = client.chat([{"role": "user", "content": "生成结果"}])

    command, kwargs = calls[0]
    assert command[:3] == [executable, "exec", "--ephemeral"]
    assert command[command.index("--model") + 1] == "gpt-5.6-sol"
    assert "--ignore-user-config" in command
    assert "--ignore-rules" in command
    assert "--json" in command
    assert command[command.index("--sandbox") + 1] == "read-only"
    assert "--skip-git-repo-check" in command
    assert kwargs["input"].endswith("[user]\n生成结果")
    assert result == '<artifact name="analysis.md">ok</artifact>'
    assert client.get_usage_summary()["total_tokens"] == 168
    assert not Path(command[command.index("--output-last-message") + 1]).exists()


def test_token_log_records_role_and_duration(tmp_path):
    client = LLMClient(LLMConfig(api_key="", backend="codex"), log_dir=tmp_path)
    client.log_role = "modeler"

    client._track_usage(
        type("Usage", (), {"prompt_tokens": 3, "completion_tokens": 2})(),
        [{"role": "user", "content": "x"}],
        "ok",
        1.2345,
    )

    entry = json.loads(next(tmp_path.glob("*.json")).read_text(encoding="utf-8"))
    assert entry["role"] == "modeler"
    assert entry["duration_seconds"] == 1.234


def test_codex_usage_ignores_missing_or_invalid_events():
    assert LLMClient._codex_usage("not-json") is None
    assert LLMClient._codex_usage(json.dumps({
        "type": "turn.completed",
        "usage": {"input_tokens": -1, "output_tokens": 2},
    })) is None


def test_codex_backend_reports_missing_cli(monkeypatch):
    monkeypatch.setattr("mmw.llm.shutil.which", lambda _: None)
    client = LLMClient(LLMConfig(api_key="", backend="codex"))

    try:
        client.chat([{"role": "user", "content": "ping"}])
    except RuntimeError as exc:
        assert str(exc) == "未安装 Codex CLI，请先安装并运行 codex login"
    else:
        raise AssertionError("缺少 Codex CLI 时未明确失败")


def test_codex_backend_reports_missing_login(monkeypatch):
    executable = "codex.cmd" if sys.platform == "win32" else "codex"
    monkeypatch.setattr("mmw.llm.shutil.which", lambda _: executable)

    def fake_run(command, **kwargs):
        return type("Completed", (), {"returncode": 1})()

    monkeypatch.setattr("mmw.llm.subprocess.run", fake_run)
    client = LLMClient(LLMConfig(api_key="", backend="codex"))

    try:
        client.chat([{"role": "user", "content": "ping"}])
    except RuntimeError as exc:
        assert str(exc) == "Codex CLI 未登录，请先运行 codex login"
    else:
        raise AssertionError("Codex CLI 未登录时未明确失败")


def test_logged_in_codex_nonzero_exit_is_retryable(monkeypatch):
    executable = "codex.cmd" if sys.platform == "win32" else "codex"
    monkeypatch.setattr("mmw.llm.shutil.which", lambda _: executable)
    monkeypatch.setattr(
        "mmw.llm.subprocess.run",
        lambda *args, **kwargs: type("Completed", (), {"returncode": 7})(),
    )
    monkeypatch.setattr(
        "mmw.llm.codex_cli_status",
        lambda: {"installed": True, "logged_in": True, "message": "ok"},
    )

    client = LLMClient(LLMConfig(api_key="", backend="codex"))
    try:
        client.chat([{"role": "user", "content": "ping"}])
    except CodexCLIError as exc:
        assert "退出码 7" in str(exc)
    else:
        raise AssertionError("已登录 Codex 的临时退出未标记为可重试")


def test_codex_missing_or_empty_response_is_retryable(monkeypatch):
    executable = "codex.cmd" if sys.platform == "win32" else "codex"
    monkeypatch.setattr("mmw.llm.shutil.which", lambda _: executable)

    for content, expected in ((None, "未生成响应"), ("", "空响应")):
        def fake_run(command, **kwargs):
            if content is not None:
                Path(command[command.index("--output-last-message") + 1]).write_text(
                    content, encoding="utf-8",
                )
            return type("Completed", (), {"returncode": 0, "stdout": "", "stderr": ""})()

        monkeypatch.setattr("mmw.llm.subprocess.run", fake_run)
        client = LLMClient(LLMConfig(api_key="", backend="codex"))
        try:
            client.chat([{"role": "user", "content": "ping"}])
        except CodexCLIError as exc:
            assert expected in str(exc)
        else:
            raise AssertionError("缺失或空响应未标记为可重试")


def test_codex_status_does_not_return_cli_output(monkeypatch):
    monkeypatch.setattr("mmw.llm.shutil.which", lambda _: "codex.cmd")
    monkeypatch.setattr(
        "mmw.llm.subprocess.run",
        lambda *args, **kwargs: type(
            "Completed",
            (),
            {"returncode": 0, "stdout": "account@example.test", "stderr": "session-secret"},
        )(),
    )

    status = codex_cli_status()

    assert status == {
        "installed": True,
        "logged_in": True,
        "message": "Codex CLI 已登录",
    }
