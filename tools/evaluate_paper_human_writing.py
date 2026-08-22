#!/usr/bin/env python3
"""Deterministic gate for a supplied source/baseline/candidate A/B set.

This tool does not generate rewrites or replace blind human review.  It only
checks protected content, runs the prose auditor, and records hashes/results.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
AUDITOR_PATH = ROOT / "skills" / "mmw-paper-human-writing" / "scripts" / "audit_latex_prose.py"


def _load_auditor() -> Any:
    spec = importlib.util.spec_from_file_location("mmw_human_writing_auditor", AUDITOR_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"无法加载审计器：{AUDITOR_PATH}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _files(path: Path) -> dict[str, Path]:
    if path.is_file():
        return {path.name: path}
    return {
        file.relative_to(path).as_posix(): file
        for file in sorted(path.rglob("*.tex"))
        if file.is_file()
    }


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _load_json(path: Path | None) -> dict[str, object] | None:
    if path is None:
        return None
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("expectations JSON 必须是对象")
    return value


def _audit_set(auditor: Any, files: dict[str, Path], expectations: dict[str, object] | None) -> dict[str, object]:
    reports: dict[str, object] = {}
    for name, path in files.items():
        text = path.read_text(encoding="utf-8")
        report = auditor.audit_text(
            text,
            expectations if Path(name).name == "abstract.tex" else None,
        )
        reports[name] = report
    return reports


def evaluate(source: Path, baseline: Path, candidate: Path, output: Path, expectations_path: Path | None) -> dict[str, object]:
    auditor = _load_auditor()
    source_files, baseline_files, candidate_files = (
        _files(source),
        _files(baseline),
        _files(candidate),
    )
    file_sets = {label: set(files) for label, files in (
        ("source", source_files),
        ("baseline", baseline_files),
        ("candidate", candidate_files),
    )}
    if len({frozenset(values) for values in file_sets.values()}) != 1:
        raise ValueError(f"三组文本文件集合不一致：{file_sets}")
    common = sorted(file_sets["source"])
    if not common:
        raise ValueError("source、baseline、candidate 没有共同的 .tex 文件")

    expectations = _load_json(expectations_path)
    comparisons: dict[str, object] = {}
    for name in common:
        source_text = source_files[name].read_text(encoding="utf-8")
        comparisons[name] = {
            "baseline": auditor.compare_texts(
                source_text, baseline_files[name].read_text(encoding="utf-8")
            ),
            "candidate": auditor.compare_texts(
                source_text, candidate_files[name].read_text(encoding="utf-8")
            ),
        }

    baseline_reports = _audit_set(auditor, baseline_files, expectations)
    candidate_reports = _audit_set(auditor, candidate_files, expectations)
    protected_pass = all(
        pair["baseline"]["passed"] and pair["candidate"]["passed"]
        for pair in comparisons.values()
    )
    candidate_coverage = (
        candidate_reports.get("abstract.tex", {}).get("abstract_coverage")
        if isinstance(candidate_reports.get("abstract.tex"), dict)
        else None
    )
    report: dict[str, object] = {
        "status": "ready_for_blind_review" if protected_pass else "deterministic_fail",
        "files": common,
        "protected_content_pass": protected_pass,
        "comparisons": comparisons,
        "baseline_audit": baseline_reports,
        "candidate_audit": candidate_reports,
        "candidate_abstract_coverage": candidate_coverage,
        "human_review": "pending",
        "end_to_end": "pending",
    }

    output.mkdir(parents=True, exist_ok=True)
    hashes = {
        label: {name: _sha256(files[name]) for name in common}
        for label, files in (
            ("source", source_files),
            ("baseline", baseline_files),
            ("candidate", candidate_files),
        )
    }
    (output / "source_hashes.json").write_text(
        json.dumps(hashes, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (output / "deterministic.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="运行论文自然表达 Skill 的确定性 A/B 门禁")
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--baseline", required=True, type=Path)
    parser.add_argument("--candidate", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--expectations", type=Path)
    args = parser.parse_args(argv)
    try:
        report = evaluate(
            args.source,
            args.baseline,
            args.candidate,
            args.output,
            args.expectations,
        )
    except (OSError, UnicodeError, ValueError, RuntimeError) as error:
        print(f"评测失败：{error}", file=sys.stderr)
        return 2
    print(json.dumps({"status": report["status"], "files": report["files"]}, ensure_ascii=False))
    return 0 if report["protected_content_pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
