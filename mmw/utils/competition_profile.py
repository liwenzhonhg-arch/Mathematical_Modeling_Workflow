"""可选竞赛合规 profile；默认关闭，不影响普通建模项目。"""

from __future__ import annotations

from pathlib import Path
from typing import Any


def validate_competition_profile(
    config: dict[str, Any],
    workspace: Path,
) -> tuple[dict[str, str], list[str]]:
    profile = config.get("competition_profile")
    if profile in (None, False, {}):
        return {}, []
    if not isinstance(profile, dict) or profile.get("enabled") is not True:
        return {}, []
    issues: list[str] = []
    for field in ("team_number", "problem"):
        if not str(config.get(field, "")).strip():
            issues.append(f"competition_profile 启用时必须填写 config.{field}")
    declaration = str(profile.get("ai_declaration", "")).strip()
    declaration_file = str(profile.get("ai_declaration_file", "")).strip()
    if declaration_file:
        path = (workspace / declaration_file).resolve()
        if path.parent != workspace.resolve() or not path.is_file():
            issues.append("ai_declaration_file 必须是工作区根目录下的现有文件")
        else:
            try:
                declaration = path.read_text(encoding="utf-8").strip()
            except (OSError, UnicodeError):
                issues.append("ai_declaration_file 必须是可读取的 UTF-8 文本")
    if not declaration:
        issues.append("competition_profile 启用时必须提供 AI 使用声明")
    names = {
        "pdf_name": str(profile.get("pdf_name", "paper.pdf")).strip(),
        "zip_name": str(profile.get("zip_name", "submission.zip")).strip(),
    }
    for key, value in names.items():
        if not value or Path(value).name != value or Path(value).suffix.casefold() not in (
            {".pdf"} if key == "pdf_name" else {".zip"}
        ):
            issues.append(f"competition_profile.{key} 必须是安全文件名")
    if issues:
        return {}, issues
    return {**names, "ai_declaration": declaration}, []
