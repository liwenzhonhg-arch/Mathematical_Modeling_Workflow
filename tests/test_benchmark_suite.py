import json

import pytest

from mmw.benchmark import (
    BenchmarkInputError,
    evaluate_benchmark_suite,
    load_benchmark_suite,
    render_benchmark_suite_markdown,
)


def _write_suite(path, entries):
    path.write_text(json.dumps({
        "schema_version": 1,
        "suites": {"core-v1": entries},
    }, ensure_ascii=False), encoding="utf-8")


def test_suite_rejects_unsafe_case_name(tmp_path):
    path = tmp_path / "benchmark_suite.json"
    _write_suite(path, [{"case": "../secret", "required_level": "verified"}])
    with pytest.raises(BenchmarkInputError, match="安全目录名"):
        load_benchmark_suite(path, "core-v1")


def test_suite_continues_after_case_failure(tmp_path, monkeypatch):
    cases = tmp_path / "cases"
    cases.mkdir()
    workspaces = {}
    entries = []
    for name in ("case-a", "case-b"):
        (cases / name).mkdir()
        workspace = tmp_path / f"workspace-{name}"
        workspace.mkdir()
        workspaces[name] = workspace
        entries.append({"case": name, "required_level": "scenario-feasible"})
    suite_path = cases / "benchmark_suite.json"
    _write_suite(suite_path, entries)

    def fake_evaluate(case_dir, mgr, stage, **kwargs):
        passed = mgr.workspace.name.endswith("case-b")
        return {
            "overall_passed": passed,
            "certification": {
                "level": "scenario-feasible" if passed else "unverified",
            },
        }

    monkeypatch.setattr("mmw.benchmark.evaluate_benchmark", fake_evaluate)
    monkeypatch.setattr("mmw.benchmark.final_certification_error", lambda *args: "")
    monkeypatch.setattr(
        "mmw.utils.checkpoint.CheckpointManager.is_approved",
        lambda *args, **kwargs: True,
    )
    monkeypatch.setattr(
        "mmw.utils.checkpoint.CheckpointManager.get_active_version",
        lambda *args, **kwargs: 1,
    )
    report = evaluate_benchmark_suite(
        suite_path, "core-v1", cases, workspaces,
    )
    assert [item["passed"] for item in report["cases"]] == [False, True]
    assert not report["overall_passed"]
    assert report["certification"]["level"] == "unverified"
    assert "case-b" in render_benchmark_suite_markdown(report)


def test_suite_enforces_required_certification(tmp_path, monkeypatch):
    cases = tmp_path / "cases"
    case = cases / "case-a"
    case.mkdir(parents=True)
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    suite_path = cases / "benchmark_suite.json"
    _write_suite(suite_path, [{"case": "case-a", "required_level": "verified"}])
    monkeypatch.setattr("mmw.benchmark.evaluate_benchmark", lambda *args, **kwargs: {
        "overall_passed": True,
        "certification": {"level": "scenario-feasible"},
    })
    monkeypatch.setattr("mmw.benchmark.final_certification_error", lambda *args: "")
    monkeypatch.setattr(
        "mmw.utils.checkpoint.CheckpointManager.is_approved",
        lambda *args, **kwargs: True,
    )
    monkeypatch.setattr(
        "mmw.utils.checkpoint.CheckpointManager.get_active_version",
        lambda *args, **kwargs: 1,
    )
    report = evaluate_benchmark_suite(
        suite_path, "core-v1", cases, {"case-a": workspace},
    )
    assert not report["overall_passed"]
    assert report["cases"][0]["error"] == "要求 verified，实际 scenario-feasible"


def test_suite_requires_current_review_binding(tmp_path, monkeypatch):
    cases = tmp_path / "cases"
    case = cases / "case-a"
    case.mkdir(parents=True)
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    suite_path = cases / "benchmark_suite.json"
    _write_suite(suite_path, [{"case": "case-a", "required_level": "scenario-feasible"}])
    monkeypatch.setattr("mmw.benchmark.evaluate_benchmark", lambda *args, **kwargs: {
        "overall_passed": True,
        "certification": {"level": "scenario-feasible"},
    })
    monkeypatch.setattr(
        "mmw.utils.checkpoint.CheckpointManager.get_active_version",
        lambda *args, **kwargs: 1,
    )
    monkeypatch.setattr(
        "mmw.utils.checkpoint.CheckpointManager.is_approved",
        lambda *args, **kwargs: True,
    )
    monkeypatch.setattr(
        "mmw.benchmark.final_certification_error",
        lambda *args: "最终 benchmark 报告与当前版本不一致",
    )

    report = evaluate_benchmark_suite(
        suite_path, "core-v1", cases, {"case-a": workspace},
    )

    assert not report["overall_passed"]
    assert "当前版本" in report["cases"][0]["error"]
