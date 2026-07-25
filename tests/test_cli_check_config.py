"""check-config：去重探测、失败退出和密钥脱敏。"""

import pytest
import typer

import mmw.cli as cli
from mmw.config import Settings


def _settings() -> Settings:
    return Settings(
        _env_file=None,
        llm_api_key="default-secret-1234",
        coder_api_key="broken-secret-5678",
    )


def test_check_config_groups_requests_and_hides_keys(monkeypatch):
    calls = []
    messages = []
    monkeypatch.setattr(cli, "get_settings", _settings)
    monkeypatch.setattr(cli, "print_info", messages.append)
    monkeypatch.setattr(cli, "print_success", messages.append)

    def probe(config):
        calls.append(config.api_key)
        return True, "OK"

    monkeypatch.setattr(cli, "_probe_llm_config", probe)

    cli.check_config()

    output = "\n".join(messages)
    assert len(calls) == 2
    assert "default-secret-1234" not in output
    assert "broken-secret-5678" not in output
    assert "****1234" in output and "****5678" in output


def test_check_config_returns_one_when_any_group_fails(monkeypatch):
    monkeypatch.setattr(cli, "get_settings", _settings)
    monkeypatch.setattr(
        cli,
        "_probe_llm_config",
        lambda config: (False, "HTTP 401") if config.api_key.endswith("5678") else (True, "OK"),
    )

    with pytest.raises(typer.Exit) as exc:
        cli.check_config()

    assert exc.value.exit_code == 1


def test_probe_retries_transient_error_only(monkeypatch):
    calls = {"count": 0}

    def request(config):
        calls["count"] += 1
        if calls["count"] == 1:
            raise ConnectionError("temporary")

    monkeypatch.setattr(cli, "_probe_request", request)
    monkeypatch.setattr(cli.time, "sleep", lambda seconds: None)

    assert cli._probe_llm_config(object()) == (True, "OK")
    assert calls["count"] == 2


def test_probe_does_not_retry_permanent_error(monkeypatch):
    calls = {"count": 0}

    def request(config):
        calls["count"] += 1
        raise ValueError("permanent")

    monkeypatch.setattr(cli, "_probe_request", request)

    assert cli._probe_llm_config(object()) == (False, "ValueError")
    assert calls["count"] == 1
