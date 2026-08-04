"""流水线完成后的隐藏 Oracle 评估。"""

from __future__ import annotations

import hashlib
import json
import math
import re
from datetime import datetime
from pathlib import Path

from mmw.models import CheckpointStatus, StageID
from mmw.pipeline.state_machine import PipelineStateMachine, _result_schema_error
from mmw.project import ProjectPaths
from mmw.utils.checkpoint import CheckpointManager
from mmw.utils.file_io import read_yaml
from mmw.utils.reference_contract import (
    contract_result_groups,
    load_reference_contract,
    reference_result_failures,
)

CERTIFICATION_RANK = {"unverified": 0, "scenario-feasible": 1, "verified": 2}


class BenchmarkInputError(ValueError):
    """benchmark 的案例、工作区或参数无效。"""


def evaluate_benchmark(
    case_dir: Path | None,
    mgr: CheckpointManager,
    stage: StageID,
    version: int | None = None,
    *,
    require_contract: bool = True,
    review_version: int = 0,
) -> dict:
    if stage not in {StageID.CODE, StageID.SOLVE}:
        raise BenchmarkInputError("benchmark 只支持 code 或 solve 阶段")
    if case_dir is not None and not case_dir.is_dir():
        raise BenchmarkInputError(f"案例目录不存在: {case_dir}")
    try:
        contract = load_reference_contract(case_dir) if case_dir is not None else None
    except ValueError as exc:
        raise BenchmarkInputError(str(exc)) from exc
    if contract is None and require_contract:
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
    oracle_failures = reference_result_failures(contract, results) if contract else []
    if results is None and contract:
        oracle_failures = [{"name": "", "actual": None, "category": "invalid_results_json"}]

    expected_names = {
        candidate
        for _, items in (contract_result_groups(contract) if contract else [])
        for item in items
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
    repeatability_failures = _repeatability_failures(contract, mgr, results)
    table_failures = _table_failures(contract, mgr.workspace) if contract else []
    passed = (
        not generic_failures
        and not oracle_failures
        and not table_failures
        and not repeatability_failures
    )
    level = "verified" if passed and contract else "scenario-feasible" if passed else "unverified"
    review_artifacts = mgr.load_artifacts(StageID.REVIEW, review_version) if review_version else {}
    return {
        "schema_version": 1,
        "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "case": case_dir.name if case_dir else None,
        "workspace": mgr.workspace.name,
        "stage": stage.value,
        "version": selected,
        "review_version": review_version,
        "bindings": {
            "solve_results_sha256": hashlib.sha256(
                artifacts.get(result_name, "").encode("utf-8")
            ).hexdigest(),
            "review_checklist_sha256": hashlib.sha256(
                review_artifacts.get("checklist.json", "").encode("utf-8")
            ).hexdigest(),
        },
        "generic_gate": {"passed": not generic_failures, "failures": generic_failures},
        "oracle": {
            "available": contract is not None,
            "passed": not oracle_failures and not table_failures if contract else None,
            "contract_sha256": (
                hashlib.sha256(
                    (case_dir / "reference_expected.json").read_bytes()
                ).hexdigest()
                if contract and case_dir else None
            ),
            "actual_results": actual_results,
            "failures": oracle_failures,
        },
        "tables": {
            "required": bool(contract and contract.get("tables")),
            "passed": not table_failures,
            "failures": table_failures,
        },
        "repeatability": {
            "required": bool(contract and contract.get("repeatability")),
            "passed": not repeatability_failures,
            "failures": repeatability_failures,
        },
        "certification": {
            "level": level,
            "meaning": {
                "verified": "通过独立隐藏参考契约",
                "scenario-feasible": "通过通用约束、可执行性和灵敏度门禁，但没有现实 Oracle",
                "unverified": "至少一项自动门禁失败",
            }[level],
        },
        "overall_passed": passed,
    }


def render_benchmark_markdown(report: dict) -> str:
    verdict = "PASS" if report["overall_passed"] else "FAIL"
    lines = [
        "# Benchmark Report",
        "",
        f"- Case: `{report['case'] or 'none'}`",
        f"- Workspace: `{report['workspace']}`",
        f"- Target: `{report['stage']} v{report['version']}`",
        f"- Generic gate: `{'PASS' if report['generic_gate']['passed'] else 'FAIL'}`",
        f"- Oracle: `{_oracle_verdict(report['oracle'])}`",
        f"- Tables: `{'PASS' if report.get('tables', {}).get('passed', True) else 'FAIL'}`",
        f"- Repeatability: `{'PASS' if report['repeatability']['passed'] else 'FAIL'}`",
        f"- Certification: **{report['certification']['level']}**",
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
    if report.get("tables", {}).get("failures"):
        lines += ["", "## Table failures"]
        lines += [
            f"- `{item['name']}`: {item['category']}"
            for item in report["tables"]["failures"]
        ]
    if report["repeatability"]["failures"]:
        lines += ["", "## Repeatability failures"]
        lines += [
            f"- `{item['name']}`: code={item['code_value']}; solve={item['solve_value']}"
            for item in report["repeatability"]["failures"]
        ]
    return "\n".join(lines) + "\n"


def _oracle_verdict(oracle: dict) -> str:
    if not oracle.get("available"):
        return "NOT AVAILABLE"
    return "PASS" if oracle.get("passed") else "FAIL"


def _repeatability_failures(contract: dict | None, mgr: CheckpointManager, solve_results) -> list[dict]:
    config = contract.get("repeatability") if contract else None
    if not config:
        return []
    code_artifacts = mgr.load_artifacts(StageID.CODE)
    try:
        code_results = json.loads(code_artifacts.get("results_preview.json", ""))
    except json.JSONDecodeError:
        code_results = None
    if not isinstance(code_results, list) or not isinstance(solve_results, list):
        return [{"name": "results", "code_value": None, "solve_value": None}]
    code_values = {
        item.get("name"): item.get("value") for item in code_results if isinstance(item, dict)
    }
    solve_values = {
        item.get("name"): item.get("value") for item in solve_results if isinstance(item, dict)
    }
    abs_tol = config.get("absolute_tolerance", 0)
    rel_tol = config.get("relative_tolerance", 0)
    failures = []
    aliases = {
        item["name"]: [item["name"], *item.get("aliases", [])]
        for _, items in contract_result_groups(contract)
        for item in items
    }
    for name in config["results"]:
        candidates = aliases.get(name, [name])
        before = next((code_values[item] for item in candidates if item in code_values), None)
        after = next((solve_values[item] for item in candidates if item in solve_values), None)
        valid = all(
            isinstance(value, (int, float))
            and not isinstance(value, bool)
            and math.isfinite(value)
            for value in (before, after)
        )
        if not valid or not math.isclose(before, after, rel_tol=rel_tol, abs_tol=abs_tol):
            failures.append({"name": name, "code_value": before, "solve_value": after})
    return failures


def _table_failures(contract: dict, workspace: Path) -> list[dict]:
    tables = contract.get("tables", [])
    if not tables:
        return []
    import pandas as pd

    paths = ProjectPaths(workspace)
    roots = list(dict.fromkeys((paths.result_data, paths.output / "data", paths.output, paths.root)))
    failures = []
    for expected in tables:
        name = expected["name"]
        candidates = [
            root / filename
            for filename in expected["files"]
            for root in roots
            if (root / filename).is_file()
            and (root / filename).resolve().is_relative_to(root.resolve())
        ]
        if not candidates:
            failures.append({"name": name, "category": "missing_file"})
            continue
        passed = False
        best_categories: list[str] | None = None
        for path in candidates:
            try:
                frames = (
                    pd.read_excel(path, sheet_name=None)
                    if path.suffix.casefold() == ".xlsx"
                    else {"": pd.read_csv(path)}
                )
            except (OSError, ValueError):
                continue
            for frame in frames.values():
                columns = {
                    re.sub(r"[\W_]+", "", str(column).casefold()): column
                    for column in frame.columns
                }
                height_column = next(
                    (
                        columns[key]
                        for column in expected["height_columns"]
                        if (key := re.sub(r"[\W_]+", "", column.casefold())) in columns
                    ),
                    None,
                )
                value_column = next(
                    (
                        columns[key]
                        for column in expected["value_columns"]
                        if (key := re.sub(r"[\W_]+", "", column.casefold())) in columns
                    ),
                    None,
                )
                if height_column is None or value_column is None:
                    continue
                pair = frame[[height_column, value_column]].apply(
                    pd.to_numeric, errors="coerce",
                ).dropna().sort_values(height_column)
                if pair.empty:
                    continue
                heights = pair[height_column].astype(float).tolist()
                values = pair[value_column].astype(float).tolist()
                if not all(math.isfinite(value) for value in heights + values):
                    continue
                raw_max = max(heights)
                scale = 1.0 if raw_max <= 5 else 100.0 if raw_max <= 500 else 1000.0
                heights = [value / scale for value in heights]
                step = expected["step"]
                count = round((expected["height_max"] - expected["height_min"]) / step) + 1
                indices = {
                    round((height - expected["height_min"]) / step)
                    for height in heights
                    if expected["height_min"] - step / 4 <= height <= expected["height_max"] + step / 4
                    and abs(
                        height - (
                            expected["height_min"]
                            + round((height - expected["height_min"]) / step) * step
                        )
                    ) <= step / 4
                }
                categories = []
                if len(indices) / count < expected["min_coverage"]:
                    categories.append("insufficient_coverage")
                if len(indices) != len(heights):
                    categories.append("duplicate_or_off_grid_height")
                if any(after < before - 1e-6 for before, after in zip(values, values[1:])):
                    categories.append("not_monotonic")
                for sample in expected["samples"]:
                    nearest = min(range(len(heights)), key=lambda index: abs(heights[index] - sample["height"]))
                    if (
                        abs(heights[nearest] - sample["height"]) > step / 4
                        or not sample["min"] <= values[nearest] <= sample["max"]
                    ):
                        categories.append("sample_out_of_range")
                        break
                if not categories:
                    passed = True
                    break
                categories = list(dict.fromkeys(categories))
                if best_categories is None or len(categories) < len(best_categories):
                    best_categories = categories
            if passed:
                break
        if passed:
            continue
        if best_categories is not None:
            failures.extend({"name": name, "category": item} for item in best_categories)
        else:
            failures.append({"name": name, "category": "unreadable_or_missing_columns"})
    return failures


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


def discover_reference_case(workspace: Path, cases_root: Path) -> Path | None:
    """按显式 benchmark_case 或唯一的年份题号前缀匹配隐藏案例。"""
    config_path = ProjectPaths(workspace).config
    config = read_yaml(config_path) if config_path.is_file() else {}
    if not isinstance(config, dict):
        config = {}
    explicit = str(config.get("benchmark_case", "")).strip()
    if explicit:
        if Path(explicit).name != explicit or "/" in explicit or "\\" in explicit:
            raise BenchmarkInputError("config.yaml 的 benchmark_case 必须是单个案例目录名")
        root = cases_root.resolve()
        candidate = (cases_root / explicit).resolve()
        if not candidate.is_relative_to(root) or not candidate.is_dir():
            raise BenchmarkInputError(f"benchmark_case 不存在: {explicit}")
        return candidate

    year = config.get("year")
    problem = str(config.get("problem", "")).strip().upper()
    if not isinstance(year, int) or not problem:
        return None
    matches = [
        path for path in cases_root.glob(f"{year}{problem}_*")
        if path.is_dir() and (path / "reference_expected.json").is_file()
    ]
    return matches[0] if len(matches) == 1 else None


def run_final_certification(
    mgr: CheckpointManager,
    cases_root: Path,
    review_version: int,
) -> dict:
    """review 后执行最终独立认证；无 Oracle 时只给 scenario-feasible。"""
    case_dir = discover_reference_case(mgr.workspace, cases_root)
    report = evaluate_benchmark(
        case_dir,
        mgr,
        StageID.SOLVE,
        require_contract=False,
        review_version=review_version,
    )
    write_benchmark_report(mgr.workspace, report)
    return report


def final_certification_error(
    workspace: Path,
    solve_version: int,
    review_version: int,
) -> str:
    """校验最终认证报告与当前激活链一致，避免旧报告放行新结果。"""
    path = ProjectPaths(workspace).output / "benchmark.json"
    if not path.is_file():
        return "review 缺少自动生成的最终 benchmark 报告"
    try:
        report = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return "最终 benchmark 报告格式非法"
    if report.get("version") != solve_version or report.get("review_version") != review_version:
        return "最终 benchmark 报告与当前 solve/review 版本不一致"
    solve_artifacts = CheckpointManager(workspace).load_artifacts(StageID.SOLVE, solve_version)
    review_artifacts = CheckpointManager(workspace).load_artifacts(StageID.REVIEW, review_version)
    expected_bindings = {
        "solve_results_sha256": hashlib.sha256(
            solve_artifacts.get("results.json", "").encode("utf-8")
        ).hexdigest(),
        "review_checklist_sha256": hashlib.sha256(
            review_artifacts.get("checklist.json", "").encode("utf-8")
        ).hexdigest(),
    }
    if report.get("bindings") != expected_bindings:
        return "最终 benchmark 报告与当前产物内容不一致"
    if not report.get("overall_passed"):
        return "最终 benchmark 未通过"
    if report.get("certification", {}).get("level") not in {"verified", "scenario-feasible"}:
        return "最终 benchmark 缺少有效可信等级"
    return ""


def load_benchmark_suite(path: Path, suite: str) -> list[dict]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise BenchmarkInputError("benchmark_suite.json 不存在或格式非法") from error
    suites = data.get("suites") if isinstance(data, dict) else None
    entries = suites.get(suite) if isinstance(suites, dict) else None
    if (
        not isinstance(data, dict)
        or data.get("schema_version") != 1
        or not isinstance(entries, list)
        or not entries
    ):
        raise BenchmarkInputError(f"基准集不存在或为空: {suite}")
    normalized = []
    for item in entries:
        if not isinstance(item, dict):
            raise BenchmarkInputError("基准集条目必须是对象")
        case = str(item.get("case", "")).strip()
        required = str(item.get("required_level", "")).strip()
        if (
            not case
            or Path(case).name != case
            or "/" in case
            or "\\" in case
        ):
            raise BenchmarkInputError("基准集案例名必须是单个安全目录名")
        if required not in CERTIFICATION_RANK:
            raise BenchmarkInputError(f"{case} 的 required_level 非法")
        normalized.append({"case": case, "required_level": required})
    return normalized


def evaluate_benchmark_suite(
    suite_path: Path,
    suite: str,
    cases_root: Path,
    workspaces: dict[str, Path],
) -> dict:
    entries = load_benchmark_suite(suite_path, suite)
    results = []
    for entry in entries:
        case_name = entry["case"]
        required = entry["required_level"]
        case_dir = (cases_root / case_name).resolve()
        root = cases_root.resolve()
        workspace = workspaces.get(case_name)
        if not case_dir.is_relative_to(root) or not case_dir.is_dir():
            results.append({
                **entry, "passed": False, "level": "unverified",
                "error": "案例目录不存在", "report": None,
            })
            continue
        if workspace is None or not Path(workspace).is_dir():
            results.append({
                **entry, "passed": False, "level": "unverified",
                "error": "未提供可用工作区", "report": None,
            })
            continue
        try:
            mgr = CheckpointManager(Path(workspace))
            review_version = mgr.get_active_version(StageID.REVIEW)
            report = evaluate_benchmark(
                case_dir if (case_dir / "reference_expected.json").is_file() else None,
                mgr,
                StageID.SOLVE,
                require_contract=required == "verified",
                review_version=review_version,
            )
            level = report["certification"]["level"]
            solve_version = mgr.get_active_version(StageID.SOLVE)
            pipeline_error = (
                final_certification_error(Path(workspace), solve_version, review_version)
                if review_version and mgr.is_approved(StageID.REVIEW, review_version)
                else "review 尚未审批"
            )
            passed = (
                report["overall_passed"]
                and CERTIFICATION_RANK[level] >= CERTIFICATION_RANK[required]
                and not pipeline_error
            )
            results.append({
                **entry, "passed": passed, "level": level,
                "error": (
                    ""
                    if passed
                    else pipeline_error or f"要求 {required}，实际 {level}"
                ),
                "report": report,
            })
        except (BenchmarkInputError, OSError, ValueError) as error:
            results.append({
                **entry, "passed": False, "level": "unverified",
                "error": str(error), "report": None,
            })
    levels = [item["level"] for item in results]
    overall_level = min(levels, key=CERTIFICATION_RANK.get)
    return {
        "schema_version": 1,
        "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "suite": suite,
        "overall_passed": all(item["passed"] for item in results),
        "certification": {"level": overall_level},
        "cases": results,
    }


def render_benchmark_suite_markdown(report: dict) -> str:
    lines = [
        f"# Benchmark Suite: {report['suite']}",
        "",
        f"- Overall: **{'PASS' if report['overall_passed'] else 'FAIL'}**",
        f"- Certification: **{report['certification']['level']}**",
        "",
        "| Case | Required | Actual | Result |",
        "|---|---|---|---|",
    ]
    for item in report["cases"]:
        verdict = "PASS" if item["passed"] else f"FAIL: {item['error']}"
        lines.append(
            f"| `{item['case']}` | `{item['required_level']}` | "
            f"`{item['level']}` | {verdict} |"
        )
    return "\n".join(lines) + "\n"


def write_benchmark_suite_report(output: Path, report: dict) -> tuple[Path, Path]:
    output.mkdir(parents=True, exist_ok=True)
    stem = f"benchmark-suite-{report['suite']}"
    json_path = output / f"{stem}.json"
    md_path = output / f"{stem}.md"
    json_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False),
        encoding="utf-8",
    )
    md_path.write_text(render_benchmark_suite_markdown(report), encoding="utf-8")
    return json_path, md_path
