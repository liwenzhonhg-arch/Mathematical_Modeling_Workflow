"""Typesetter Agent：只允许在不改变事实契约的前提下整理 LaTeX。"""

from __future__ import annotations

import collections
import json
import re

from mmw.agents.base import BaseAgent
from mmw.utils.figure_quality import load_paper_style

_NUMBER_RE = re.compile(r"(?<![A-Za-z])[-+]?(?:\d+\.\d+|\d+)(?:[eE][-+]?\d+)?")
_COMMAND_RE = re.compile(r"\\(?:cite|label|ref|eqref)\{([^{}]+)\}")
_FIGURE_RE = re.compile(r"\\includegraphics(?:\[[^\]]*])?\{([^{}]+)\}")
_BIB_KEY_RE = re.compile(r"@\w+\s*\{\s*([^,\s]+)")


def _protected_contract(name: str, content: str) -> dict[str, object]:
    commands: dict[str, set[str]] = {"cite": set(), "label": set(), "ref": set(), "eqref": set()}
    for match in _COMMAND_RE.finditer(content):
        command = match.group(0).split("{", 1)[0].lstrip("\\")
        commands[command].update(part.strip() for part in match.group(1).split(","))
    return {
        "numbers": collections.Counter(_NUMBER_RE.findall(content)),
        "commands": commands,
        "figures": set(_FIGURE_RE.findall(content)),
        "bib_keys": set(_BIB_KEY_RE.findall(content)) if name == "references.bib" else set(),
    }


def validate_typeset_revision(before: dict[str, str], after: dict[str, str]) -> list[str]:
    violations: list[str] = []
    allowed = {
        name for name in before
        if name == "references.bib" or (name.startswith("sections/") and name.endswith(".tex"))
    }
    unexpected = sorted(set(after) - allowed)
    if unexpected:
        violations.append("输出包含非法文件：" + ", ".join(unexpected))
    merged = {**before, **after}
    for name in sorted(allowed):
        if _protected_contract(name, before[name]) != _protected_contract(name, merged[name]):
            violations.append(f"{name} 的数值、引用、标签、图表或文献键发生变化")
    return violations


def normalize_tex_artifacts(artifacts: dict[str, str]) -> tuple[dict[str, str], list[str]]:
    normalized = dict(artifacts)
    changes: list[str] = []
    for name, content in artifacts.items():
        if not name.endswith(".tex"):
            continue
        cleaned = re.sub(r"[ \t]+\n", "\n", content)
        cleaned = re.sub(r"\n{4,}", "\n\n\n", cleaned).strip() + "\n"
        if cleaned != content:
            normalized[name] = cleaned
            changes.append(name)
    return normalized, changes


class TypesetterAgent(BaseAgent):
    role = "typesetter"
    system_prompt_template = "system/typesetter.j2"

    def typeset(
        self,
        artifacts: dict[str, str],
        layout_feedback: dict | None = None,
    ) -> tuple[dict[str, str], dict[str, object]]:
        normalized, deterministic = normalize_tex_artifacts(artifacts)
        editable = {
            name: content for name, content in normalized.items()
            if name == "references.bib" or (name.startswith("sections/") and name.endswith(".tex"))
        }
        prompt = self.render_prompt(
            "typesetter.j2",
            artifacts=json.dumps(editable, ensure_ascii=False, indent=2),
            feedback=json.dumps(layout_feedback or {}, ensure_ascii=False, indent=2),
        )
        revision: dict[str, str] = {}
        violations: list[str] = []
        rounds = 0
        for rounds in range(1, 3):
            response = self.run_stream(
                prompt,
                system_kwargs={"paper_style": load_paper_style()},
            )
            revision = self.parse_artifacts(response)
            violations = validate_typeset_revision(editable, revision)
            if not violations:
                break
            prompt = (
                "上一轮排版输出未通过不可变契约：\n- "
                + "\n- ".join(violations)
                + "\n请只重新输出需要修改的原文件；不得改变任何受保护内容。"
            )
        if violations:
            return normalized, {
                "schema_version": 1,
                "accepted": False,
                "rounds": rounds,
                "deterministic_changes": deterministic,
                "violations": violations,
            }
        result = dict(normalized)
        result.update(revision)
        return result, {
            "schema_version": 1,
            "accepted": True,
            "rounds": rounds,
            "deterministic_changes": deterministic,
            "violations": [],
        }
