"""配置测试：全局默认与 per-agent 覆盖。"""

from mmw.config import Settings


def _settings(**kwargs) -> Settings:
    # _env_file=None 隔离项目根目录的真实 .env
    return Settings(_env_file=None, **kwargs)


def test_default_llm_config():
    s = _settings(llm_api_key="key-1", llm_model="deepseek-chat")
    cfg = s.get_llm_config()
    assert cfg.api_key == "key-1"
    assert cfg.model == "deepseek-chat"
    assert cfg.request_timeout == 900


def test_agent_override_model_only():
    s = _settings(llm_api_key="key-1", llm_model="deepseek-chat", modeler_model="deepseek-reasoner")
    cfg = s.get_llm_config("modeler")
    # model 被覆盖，key 回落到全局默认
    assert cfg.model == "deepseek-reasoner"
    assert cfg.api_key == "key-1"


def test_agent_without_override_uses_default():
    s = _settings(llm_api_key="key-1", llm_model="deepseek-chat")
    cfg = s.get_llm_config("writer")
    assert cfg.model == "deepseek-chat"
    assert cfg.api_key == "key-1"


def test_agent_full_override():
    s = _settings(
        llm_api_key="key-1",
        verifier_api_key="key-2",
        verifier_base_url="https://api.other.com/v1",
        verifier_model="other-model",
    )
    cfg = s.get_llm_config("verifier")
    assert cfg.api_key == "key-2"
    assert cfg.base_url == "https://api.other.com/v1"
    assert cfg.model == "other-model"


def test_codex_backend_does_not_require_api_key():
    cfg = _settings(
        llm_backend="codex",
        codex_model="gpt-5.6-sol",
        llm_api_key="api-key-must-not-be-used",
        writer_model="api-model-must-not-be-used",
    ).get_llm_config("writer")
    assert cfg.backend == "codex"
    assert cfg.api_key == ""
    assert cfg.base_url == ""
    assert cfg.model == "gpt-5.6-sol"


def test_image_support_must_be_explicit_and_codex_never_claims_it():
    api = _settings(
        llm_api_key="key-1",
        llm_supports_images=False,
        analyst_supports_images=True,
    ).get_llm_config("analyst")
    codex = _settings(
        llm_backend="codex",
        llm_supports_images=True,
        analyst_supports_images=True,
    ).get_llm_config("analyst")

    assert api.supports_images is True
    assert codex.supports_images is False
