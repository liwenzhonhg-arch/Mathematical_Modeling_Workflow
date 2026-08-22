from pathlib import Path

from mmw.utils.competition_profile import validate_competition_profile


def test_competition_profile_is_optional():
    assert validate_competition_profile({}, Path(".")) == ({}, [])


def test_enabled_profile_requires_declaration_and_metadata(tmp_path):
    profile, issues = validate_competition_profile(
        {"team_number": "", "problem": "A", "competition_profile": {"enabled": True}},
        tmp_path,
    )
    assert profile == {}
    assert any("team_number" in issue for issue in issues)
    assert any("AI" in issue for issue in issues)


def test_enabled_profile_accepts_inline_declaration_and_safe_names(tmp_path):
    profile, issues = validate_competition_profile(
        {
            "team_number": "T01",
            "problem": "A",
            "competition_profile": {
                "enabled": True,
                "ai_declaration": "本项目使用 AI 辅助，结果经人工复核。",
                "pdf_name": "T01_A.pdf",
                "zip_name": "T01_A.zip",
            },
        },
        tmp_path,
    )
    assert not issues
    assert profile["pdf_name"] == "T01_A.pdf"
