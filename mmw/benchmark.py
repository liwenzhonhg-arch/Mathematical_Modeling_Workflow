"""流水线完成后的隐藏 Oracle 评估。"""

from __future__ import annotations

import json
import math
from datetime import datetime
from pathlib import Path

from mmw.models import CheckpointStatus, StageID
from mmw.pipeline.state_machine import PipelineStateMachine, _result_schema_error
from mmw.project import ProjectPaths
from mmw.utils.checkpoint import CheckpointManager
from mmw.utils.reference_contract import (
    load_reference_contract,
    reference_result_failures,
)


class BenchmarkInputError(ValueError):
    """benchmark 的案例、工作区或参数无效。"""


def evaluate_benchmark(
    case_dir: Path,
    mgr: CheckpointManager,
    stage: StageID,
    version: int | None = None,
) -> dict:
    if stage not in {StageID.CODE, StageID.SOLVE}:
        raise BenchmarkInputError("benchmark 只支持 code 或 solve 阶段")
    if not case_dir.is_dir():
        raise BenchmarkInputError(f"案例目录不存在: {case_dir}")
    try:
        contract = load_reference_contract(case_dir)
    except ValueError as exc:
        raise BenchmarkInputError(str(exc)) from exc
    if contract is None:
        raise BenchmarkInputError("案例缺少 reference_expected.json")

    selected = version if version is not None else mgr.get_active_version(stage)
    if selected <= 0:
        raise BenchmarkInputError(f"阶段 '{stage.value}' 尚未运行")
    status = mgr.load_status(stage, selected)
    artifacts = mgr.load_artifacts(stage, selected)
    if status is None or not artifacts:
        raise BenchmarkInputError(f"阶段 '{stage.value}' v{selected} 不存在或没有产物")

    generic_failures = []
    if status.status not in {CheckpointStatus.COMPLETED, CheckpointStatus.APPROVED}:
        generic_failures.append(f"阶段状态为 {status.status.value}")
    quality_error = PipelineStateMachine(mgr).quality_error(stage, selected)
    if quality_error:
        generic_failures.append(quality_error)
    if status.upstream_changed or mgr.check_upstream_changed(stage, selected):
        generic_failures.append("上游版本已变化")

    result_name = "results_preview.json" if stage == StageID.CODE else "results.json"
    try:
        results = json.loads(artifacts.get(result_name, ""))
    except json.JSONDecodeError:
        results = None
    if stage == StageID.CODE:
        if not isinstance(results, list) or not results:
            generic_failures.append(f"{result_name} 必须是非空列表")
        elif schema_error := _result_schema_error(results):
            generic_failures.append(schema_error)
    oracle_failures = reference_result_failures(contract, results)
    if results is None:
        oracle_failures = [{"name": "", "actual": None, "category": "invalid_results_json"}]

    expected_names = {
        candidate
        for item in contract["results"]
        for candidate in [item["name"], *item.get("aliases", [])]
    }
    actual_results = [
        {
            "name": item["name"],
            "value": (
                item.get("value")
                if isinstance(item.get("value"), (int, float))
                and not isinstance(item.get("value"), bool)
                and math.isfinite(item["value"])
                else None
            ),
        }
        for item in results or []
        if isinstance(item, dict) and item.get("name") in expected_names
    ]
    passed = not generic_failures and not oracle_failures
    return {
        "schema_version": 1,
        "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "case": case_dir.name,
        "workspace": mgr.workspace.name,
        "stage": stage.value,
        "version": selected,
        "generic_gate": {"passed": not generic_failures, "failures": generic_failures},
        "oracle": {
            "passed": not oracle_failures,
            "actual_results": actual_results,
            "failures": oracle_failures,
        },
        "overall_passed": passed,
    }


def render_benchmark_markdown(report: dict) -> str:
    verdict = "PASS" if report["overall_passed"] else "FAIL"
    lines = [
        "# Benchmark Report",
        "",
        f"- Case: `{report['case']}`",
        f"- Workspace: `{report['workspace']}`",
        f"- Target: `{report['stage']} v{report['version']}`",
        f"- Generic gate: `{'PASS' if report['generic_gate']['passed'] else 'FAIL'}`",
        f"- Oracle: `{'PASS' if report['oracle']['passed'] else 'FAIL'}`",
        f"- Overall: **{verdict}**",
    ]
    if report["generic_gate"]["failures"]:
        lines += ["", "## Generic gate failures"]
        lines += [f"- {failure}" for failure in report["generic_gate"]["failures"]]
    if report["oracle"]["failures"]:
        lines += ["", "## Oracle failures"]
        lines += [
            f"- `{item['name'] or 'results.json'}`: {item['category']}; actual={item['actual']}"
            for item in report["oracle"]["failures"]
        ]
    return "\n".join(lines) + "\n"


def write_benchmark_report(workspace: Path, report: dict) -> tuple[Path, Path]:
    output = ProjectPaths(workspace).output
    output.mkdir(parents=True, exist_ok=True)
    json_path = output / "benchmark.json"
    md_path = output / "benchmark.md"
    json_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False),
        encoding="utf-8",
    )
    md_path.write_text(render_benchmark_markdown(report), encoding="utf-8")
    return json_path, md_path
