"""全局配置，基于 Pydantic Settings + .env 文件。"""

from __future__ import annotations

from pathlib import Path
from typing import Literal, Optional

from pydantic import BaseModel
from pydantic_settings import BaseSettings, SettingsConfigDict


class LLMConfig(BaseModel):
    """单个 LLM 连接配置。"""

    api_key: str
    base_url: str = "https://api.deepseek.com/v1"
    model: str = "deepseek-v4-pro"
    temperature: float = 0.7
    max_tokens: int = 4096
    request_timeout: float = 900
    backend: Literal["openai", "codex"] = "openai"
    supports_images: bool = False


class Settings(BaseSettings):
    """从 .env 读取的全局设置。"""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    # 默认 LLM
    llm_api_key: str = ""
    llm_base_url: str = "https://api.deepseek.com/v1"
    llm_model: str = "deepseek-v4-pro"
    llm_max_tokens: int = 4096  # 推理模型（思考占输出额度）需调大
    llm_timeout_seconds: float = 900
    llm_backend: Literal["openai", "codex"] = "openai"
    codex_model: str = "gpt-5.6-sol"
    llm_supports_images: bool = False
    mmw_provider_profiles_b64: str = ""
    mmw_active_provider: str = ""
    research_web_enabled: bool = False
    # 正式数值程序默认不设墙钟上限；仅用户显式配置正数时启用保护性超时。
    mmw_max_runtime_seconds: Optional[float] = None

    # per-agent 覆盖（可选）
    analyst_api_key: Optional[str] = None
    analyst_base_url: Optional[str] = None
    analyst_model: Optional[str] = None
    analyst_max_tokens: Optional[int] = None
    analyst_supports_images: Optional[bool] = None

    eda_api_key: Optional[str] = None
    eda_base_url: Optional[str] = None
    eda_model: Optional[str] = None
    eda_max_tokens: Optional[int] = None

    researcher_api_key: Optional[str] = None
    researcher_base_url: Optional[str] = None
    researcher_model: Optional[str] = None
    researcher_max_tokens: Optional[int] = None

    modeler_api_key: Optional[str] = None
    modeler_base_url: Optional[str] = None
    modeler_model: Optional[str] = None
    modeler_max_tokens: Optional[int] = None

    verifier_api_key: Optional[str] = None
    verifier_base_url: Optional[str] = None
    verifier_model: Optional[str] = None
    verifier_max_tokens: Optional[int] = None

    coder_api_key: Optional[str] = None
    coder_base_url: Optional[str] = None
    coder_model: Optional[str] = None
    coder_max_tokens: Optional[int] = None

    writer_api_key: Optional[str] = None
    writer_base_url: Optional[str] = None
    writer_model: Optional[str] = None
    writer_max_tokens: Optional[int] = None

    reviewer_api_key: Optional[str] = None
    reviewer_base_url: Optional[str] = None
    reviewer_model: Optional[str] = None
    reviewer_max_tokens: Optional[int] = None

    # 工作空间
    workspace_dir: Path = Path("workspace")

    def get_llm_config(self, agent_role: str | None = None) -> LLMConfig:
        """获取 LLM 配置，支持 per-agent 覆盖。"""
        if self.llm_backend == "codex":
            max_tokens = (
                getattr(self, f"{agent_role}_max_tokens", None) if agent_role else None
            ) or self.llm_max_tokens
            return LLMConfig(
                api_key="",
                base_url="",
                model=self.codex_model,
                max_tokens=max_tokens,
                request_timeout=self.llm_timeout_seconds,
                backend="codex",
                supports_images=False,
            )
        if agent_role:
            key = getattr(self, f"{agent_role}_api_key", None) or self.llm_api_key
            url = getattr(self, f"{agent_role}_base_url", None) or self.llm_base_url
            model = getattr(self, f"{agent_role}_model", None) or self.llm_model
            max_tokens = getattr(self, f"{agent_role}_max_tokens", None) or self.llm_max_tokens
        else:
            key = self.llm_api_key
            url = self.llm_base_url
            model = self.llm_model
            max_tokens = self.llm_max_tokens
        return LLMConfig(
            api_key=key,
            base_url=url,
            model=model,
            max_tokens=max_tokens,
            request_timeout=self.llm_timeout_seconds,
            backend=self.llm_backend,
            supports_images=(
                self.analyst_supports_images
                if agent_role == "analyst" and self.analyst_supports_images is not None
                else self.llm_supports_images
            ),
        )


_settings: Settings | None = None


def get_settings() -> Settings:
    """单例获取全局设置。"""
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings


def reset_settings() -> None:
    """重置单例（测试用）。"""
    global _settings
    _settings = None
