import json

from typer.testing import CliRunner

import mmw.cli as cli
from mmw.benchmark import (
    evaluate_benchmark,
    render_benchmark_markdown,
    write_benchmark_report,
)
from mmw.models import MetaData, StageID
from mmw.utils.checkpoint import CheckpointManager


CONTRACT = {
    "schema_version": 1,
    "results": [{"name": "q2_最大允许速度", "min": 76.0, "max": 80.0}],
}


def _case(tmp_path):
    case_dir = tmp_path / "test_cases" / "2020A_炉温曲线"
    case_dir.mkdir(parents=True)
    (case_dir / "reference_expected.json").write_text(
        json.dumps(CONTRACT, ensure_ascii=False), encoding="utf-8"
    )
    return case_dir


def _solve(mgr, value=77.06):
    artifacts = {
        "run_log.txt": "STDOUT:\n求解完成",
        "results.json": json.dumps([{
            "name": "q2_最大允许速度", "value": value, "unit": "cm/min", "desc": "结果",
        }], ensure_ascii=False),
        "sensitivity.json": json.dumps({
            "baseline": {"objective": 100.0},
            "experiments": [
                {"param": "alpha", "delta_pct": -10, "objective": 90.0, "change_pct": -10.0},
                {"param": "beta", "delta_pct": 10, "objective": 110.0, "change_pct": 10.0},
            ],
        }),
        "figures_list.json": "[]",
        "deliverables_manifest.json": "{}",
    }
    mgr.save(StageID.SOLVE, artifacts, MetaData(stage="solve", version=0))


def test_benchmark_passes_without_exposing_expected_range(tmp_path):
    case_dir = _case(tmp_path)
    workspace = tmp_path / "workspace" / "run"
    mgr = CheckpointManager(workspace)
    _solve(mgr)

    report = evaluate_benchmark(case_dir, mgr, StageID.SOLVE, 1)
    markdown = render_benchmark_markdown(report)

    assert report["overall_passed"] is True
    assert "76.0" not in markdown
    assert "80.0" not in markdown


def test_benchmark_reports_oracle_failure_without_range(tmp_path):
    case_dir = _case(tmp_path)
    mgr = CheckpointManager(tmp_path / "workspace" / "run")
    _solve(mgr, value=99.29)

    report = evaluate_benchmark(case_dir, mgr, StageID.SOLVE, 1)

    assert report["overall_passed"] is False
    assert report["oracle"]["failures"] == [{
        "name": "q2_最大允许速度", "actual": 99.29, "category": "out_of_range",
    }]
    assert "min" not in json.dumps(report, ensure_ascii=False)
    assert "max" not in json.dumps(report, ensure_ascii=False)


def test_benchmark_handles_non_finite_result_without_invalid_report_json(tmp_path):
    case_dir = _case(tmp_path)
    workspace = tmp_path / "workspace" / "run"
    mgr = CheckpointManager(workspace)
    _solve(mgr, value=float("nan"))

    report = evaluate_benchmark(case_dir, mgr, StageID.SOLVE, 1)
    json_path, _ = write_benchmark_report(workspace, report)

    assert report["overall_passed"] is False
    assert report["oracle"]["failures"][0]["category"] == "missing_or_invalid"
    assert "NaN" not in json_path.read_text(encoding="utf-8")


def test_benchmark_rejects_stale_upstream(tmp_path):
    case_dir = _case(tmp_path)
    mgr = CheckpointManager(tmp_path / "workspace" / "run")
    mgr.save(StageID.ANALYZE, {"sub_problems.json": "{}"}, MetaData(stage="analyze", version=0))
    mgr.approve(StageID.ANALYZE)
    _solve(mgr)
    mgr.save(StageID.ANALYZE, {"sub_problems.json": '{"changed": true}'}, MetaData(stage="analyze", version=0))
    mgr.approve(StageID.ANALYZE, version=2)

    report = evaluate_benchmark(case_dir, mgr, StageID.SOLVE, 1)

    assert report["overall_passed"] is False
    assert "上游版本已变化" in report["generic_gate"]["failures"]


def test_code_benchmark_rejects_invalid_results_preview_schema(tmp_path):
    case_dir = _case(tmp_path)
    mgr = CheckpointManager(tmp_path / "workspace" / "run")
    mgr.save(StageID.CODE, {
        "solution.py": "print('ok')",
        "run_log.txt": "STDOUT:\nok",
        "results_preview.json": json.dumps([{
            "name": "q2_最大允许速度", "value": 77.0,
        }], ensure_ascii=False),
    }, MetaData(stage="code", version=0))

    report = evaluate_benchmark(case_dir, mgr, StageID.CODE, 1)

    assert report["overall_passed"] is False
    assert "缺少字符串 unit/desc" in report["generic_gate"]["failures"][0]


def test_benchmark_cli_writes_reports_and_uses_exit_codes(tmp_path, monkeypatch):
    case_dir = _case(tmp_path)
    workspace = tmp_path / "workspace" / "run"
    mgr = CheckpointManager(workspace)
    _solve(mgr)
    fake_module = tmp_path / "mmw" / "cli.py"
    fake_module.parent.mkdir()
    monkeypatch.setattr(cli, "__file__", str(fake_module))
    monkeypatch.setattr(cli, "_get_workspace", lambda name: workspace)

    result = CliRunner().invoke(cli.app, [
        "benchmark", "--case", case_dir.name, "--workspace", "run", "--stage", "solve",
    ])

    assert result.exit_code == 0, result.output
    assert (workspace / "output" / "benchmark.json").is_file()
    invalid = CliRunner().invoke(cli.app, [
        "benchmark", "--case", "../bad", "--workspace", "run",
    ])
    assert invalid.exit_code == 2

    _solve(CheckpointManager(workspace), value=99.29)
    failed = CliRunner().invoke(cli.app, [
        "benchmark", "--case", case_dir.name, "--workspace", "run", "--stage", "solve", "--version", "2",
    ])
    assert failed.exit_code == 1
