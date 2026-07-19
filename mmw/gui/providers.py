"""LLM 供应商配置的保存、脱敏与原子切换。"""

from __future__ import annotations

import base64
import json
import os
import re
import tempfile
from pathlib import Path
from typing import Any
from uuid import uuid4

from mmw.config import reset_settings


AGENT_ROLES = (
    "analyst",
    "eda",
    "researcher",
    "modeler",
    "verifier",
    "coder",
    "writer",
    "reviewer",
)
_ENV_LINE = re.compile(
    r"^(?P<prefix>\s*(?:export\s+)?)(?P<key>[A-Za-z_][A-Za-z0-9_]*)(?P<gap>\s*=\s*).*$"
)


def mask_key(api_key: str) -> str:
    """只保留足够辨认供应商密钥的首尾字符。"""
    if not api_key:
        return "未配置"
    if len(api_key) <= 8:
        return "•" * len(api_key)
    return f"{api_key[:4]}••••••••{api_key[-4:]}"


def _encode_profiles(profiles: list[dict[str, Any]]) -> str:
    raw = json.dumps(profiles, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii")


def _decode_profiles(value: str) -> list[dict[str, Any]]:
    if not value:
        return []
    try:
        data = json.loads(base64.urlsafe_b64decode(value.encode("ascii")).decode("utf-8"))
    except (ValueError, UnicodeDecodeError, json.JSONDecodeError):
        return []
    return data if isinstance(data, list) else []


def _read_env_value(env_path: Path, key: str) -> str:
    """仅读取指定非敏感配置项，不把整个 .env 暴露到调用方。"""
    if not env_path.is_file():
        return ""
    target = key.casefold()
    for line in env_path.read_text(encoding="utf-8").splitlines():
        match = _ENV_LINE.match(line)
        if not match or match.group("key").casefold() != target:
            continue
        value = line[match.end("gap") :].strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        return value
    return ""


def load_profiles(env_path: Path) -> tuple[list[dict[str, Any]], str]:
    """从 `.env` 中的单个 Base64 字段加载供应商资料。"""
    profiles = _decode_profiles(_read_env_value(env_path, "MMW_PROVIDER_PROFILES_B64"))
    active_id = _read_env_value(env_path, "MMW_ACTIVE_PROVIDER")
    return profiles, active_id


def public_profiles(env_path: Path) -> dict[str, Any]:
    profiles, active_id = load_profiles(env_path)
    public = []
    for profile in profiles:
        item = {key: value for key, value in profile.items() if key != "api_key"}
        item["masked_key"] = mask_key(str(profile.get("api_key", "")))
        item["has_api_key"] = bool(profile.get("api_key"))
        public.append(item)
    return {"profiles": public, "active_id": active_id}


def _dotenv_quote(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace('"', '\\"').replace("\r", "\\r").replace("\n", "\\n")
    return f'"{escaped}"'


def atomic_update_env(env_path: Path, updates: dict[str, str]) -> None:
    """保留注释和未知字段，在同目录写临时文件后用 os.replace 原子替换。"""
    env_path = env_path.resolve()
    env_path.parent.mkdir(parents=True, exist_ok=True)
    original = env_path.read_text(encoding="utf-8") if env_path.exists() else ""
    newline = "\r\n" if "\r\n" in original else "\n"
    lines = original.splitlines()
    remaining = {key.casefold(): (key, value) for key, value in updates.items()}
    output: list[str] = []

    for line in lines:
        match = _ENV_LINE.match(line)
        if not match:
            output.append(line)
            continue
        normalized = match.group("key").casefold()
        replacement = remaining.pop(normalized, None)
        if replacement is None:
            output.append(line)
            continue
        _, value = replacement
        output.append(
            f"{match.group('prefix')}{match.group('key')}{match.group('gap')}{_dotenv_quote(value)}"
        )

    if output and output[-1]:
        output.append("")
    output.extend(f"{key}={_dotenv_quote(value)}" for key, value in remaining.values())
    content = newline.join(output)
    if content and not content.endswith(newline):
        content += newline

    fd, temp_name = tempfile.mkstemp(prefix=f".{env_path.name}.", suffix=".tmp", dir=env_path.parent)
    temp_path = Path(temp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, env_path)
    finally:
        if temp_path.exists():
            temp_path.unlink()


def save_profile(env_path: Path, payload: dict[str, Any]) -> dict[str, Any]:
    """新增或更新一个供应商；留空的 API Key 在编辑时沿用旧值。"""
    profiles, active_id = load_profiles(env_path)
    profile_id = str(payload.get("id") or uuid4().hex[:12])
    existing = next((item for item in profiles if item.get("id") == profile_id), None)

    name = str(payload.get("name", "")).strip()
    base_url = str(payload.get("base_url", "")).strip().rstrip("/")
    default_model = str(payload.get("default_model", "")).strip()
    reasoning_model = str(payload.get("reasoning_model", "")).strip() or default_model
    api_key = str(payload.get("api_key", "")).strip()
    if not api_key and existing:
        api_key = str(existing.get("api_key", ""))
    if not name or not base_url or not default_model or not api_key:
        raise ValueError("名称、API Base URL、默认模型和 API Key 均不能为空")
    if not base_url.startswith(("http://", "https://")):
        raise ValueError("API Base URL 必须以 http:// 或 https:// 开头")

    models = payload.get("models")
    if not isinstance(models, list):
        models = []
    clean_models = list(
        dict.fromkeys(
            model.strip()
            for model in [str(item) for item in models] + [default_model, reasoning_model]
            if model.strip()
        )
    )
    role_models = payload.get("role_models")
    if not isinstance(role_models, dict):
        role_models = {}
    role_models = {
        role: str(role_models.get(role) or (reasoning_model if role in {"modeler", "verifier"} else default_model))
        for role in AGENT_ROLES
    }

    profile = {
        "id": profile_id,
        "name": name,
        "base_url": base_url,
        "protocol": "openai_chat",
        "api_key": api_key,
        "default_model": default_model,
        "reasoning_model": reasoning_model,
        "models": clean_models,
        "role_models": role_models,
    }
    if existing:
        profiles[profiles.index(existing)] = profile
    else:
        profiles.append(profile)

    atomic_update_env(
        env_path,
        {
            "MMW_PROVIDER_PROFILES_B64": _encode_profiles(profiles),
            "MMW_ACTIVE_PROVIDER": active_id,
        },
    )
    reset_settings()
    return {**{key: value for key, value in profile.items() if key != "api_key"}, "masked_key": mask_key(api_key)}


def activate_profile(env_path: Path, profile_id: str) -> dict[str, Any]:
    """把一个供应商的连接和八个角色路由作为同一次原子更新激活。"""
    profiles, _ = load_profiles(env_path)
    profile = next((item for item in profiles if item.get("id") == profile_id), None)
    if profile is None:
        raise ValueError("供应商不存在")

    api_key = str(profile.get("api_key", ""))
    base_url = str(profile.get("base_url", ""))
    default_model = str(profile.get("default_model", ""))
    reasoning_model = str(profile.get("reasoning_model") or default_model)
    role_models = profile.get("role_models")
    if not isinstance(role_models, dict):
        role_models = {}
    updates = {
        "LLM_API_KEY": api_key,
        "LLM_BASE_URL": base_url,
        "LLM_MODEL": default_model,
        "MMW_ACTIVE_PROVIDER": profile_id,
    }
    for role in AGENT_ROLES:
        updates[f"{role.upper()}_API_KEY"] = api_key
        updates[f"{role.upper()}_BASE_URL"] = base_url
        updates[f"{role.upper()}_MODEL"] = str(
            role_models.get(role) or (reasoning_model if role in {"modeler", "verifier"} else default_model)
        )

    atomic_update_env(env_path, updates)
    reset_settings()
    return {
        "id": profile_id,
        "name": profile.get("name", ""),
        "base_url": base_url,
        "default_model": default_model,
        "masked_key": mask_key(api_key),
    }


def get_profile_secret(env_path: Path, profile_id: str) -> dict[str, Any]:
    """仅供后端连接测试使用，返回值不得直接序列化给浏览器。"""
    profiles, _ = load_profiles(env_path)
    profile = next((item for item in profiles if item.get("id") == profile_id), None)
    if profile is None:
        raise ValueError("供应商不存在")
    return profile
