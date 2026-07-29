"""阶段 5：代码实现（含错误反思循环）。"""

from __future__ import annotations

import json
import sys
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

from mmw.agents.coder import (
    CoderAgent,
    model_rework_requested,
    requires_moving_heat_helper,
)
from mmw.config import get_settings
from mmw.llm import LLMClient
from mmw.models import MetaData, StageID
from mmw.project import ProjectPaths
from mmw.utils.checkpoint import CheckpointManager
from mmw.utils.display import print_error, print_info, print_success
from mmw.utils.method_contract import finalize_code_contract


def load_deliverables(mgr: CheckpointManager, report_ignored: bool = True) -> list[dict]:
    """读取有题面原文佐证的硬交付文件清单。"""
    analyze_arts = mgr.load_artifacts(StageID.ANALYZE)
    try:
        data = json.loads(analyze_arts.get("sub_problems.json", "{}"))
        deliverables = data.get("deliverables", [])
    except json.JSONDecodeError:
        return []

    problem_path = ProjectPaths(mgr.workspace).problem
    problem_text = (
        problem_path.read_text(encoding="utf-8").casefold()
        if problem_path.exists()
        else ""
    )
    confirmed: list[dict] = []
    ignored: list[str] = []
    for item in deliverables:
        if not isinstance(item, dict) or not item.get("file"):
            continue
        name = str(item["file"]).strip()
        safe_name = Path(name).name == name and "/" not in name and "\\" not in name
        if safe_name and name.casefold() in problem_text:
            confirmed.append({**item, "file": name})
        else:
            ignored.append(name)
    if ignored and report_ignored:
        print_info(f"忽略题面未确认的交付文件: {', '.join(ignored)}")
    return confirmed


def _has_solution_py(artifacts: dict[str, str]) -> bool:
    """代码阶段必须产出非空 solution.py，否则不能进入 completed 检查点。"""
    return bool(artifacts.get("solution.py", "").strip())


def _file_signature(path: Path) -> tuple[int, int] | None:
    if not path.is_file():
        return None
    stat = path.stat()
    return stat.st_mtime_ns, stat.st_size


def _candidate_quality_error(
    result,
    results_path: Path,
    results_before: tuple[int, int] | None,
    *,
    require_identifiability: bool = False,
    identifiability_path: Path | None = None,
    identifiability_before: tuple[int, int] | None = None,
    sub_problems: list[dict] | None = None,
    model_contract: str = "",
) -> str:
    """在 Coder 宣告成功前校验可行性标记和本轮结构化结果。"""
    from mmw.pipeline.state_machine import (
        _invalid_run_marker,
        _missing_subproblem_results,
        _result_schema_error,
    )

    marker = _invalid_run_marker(f"{result.stdout}\n{result.stderr}")
    if marker:
        return marker
    if _file_signature(results_path) == results_before:
        return "本轮执行未生成或更新 results.json"
    try:
        results = json.loads(results_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return "results.json 不存在或不是合法 JSON"
    if not isinstance(results, list) or not results:
        return "results.json 必须是非空列表"
    if schema_error := _result_schema_error(results):
        return schema_error
    if model_contract:
        from mmw.utils.method_contract import validate_result_contract

        if failures := validate_result_contract(model_contract, results):
            return "结果违反模型硬约束: " + "；".join(failures)
    if missing := _missing_subproblem_results(
        results, sub_problems or [], allow_model_only=True,
    ):
        return "results.json 缺少子问题结果: " + ", ".join(missing)
    if require_identifiability:
        if (
            identifiability_path is None
            or _file_signature(identifiability_path) == identifiability_before
        ):
            return "本轮执行未生成或更新 identifiability.json"
        try:
            report_content = identifiability_path.read_text(encoding="utf-8")
        except OSError:
            return "identifiability.json 不存在或无法读取"
        if report_error := _identifiability_report_error(report_content):
            return report_error
        if identifiability_error := _identifiability_result_error(results):
            return identifiability_error
    failed_validation = [
        item["name"]
        for item in results
        if any(
            token in item["name"]
            for token in ("验证状态", "校准状态", "验证可用", "约束满足", "可行性")
        )
        and item["value"] == 0
        and not (
            "外部验证可用" in item["name"]
            and any(
                token in item["desc"]
                for token in ("不可用", "缺少独立", "无独立", "单工况")
            )
        )
        and "不可用" not in item["desc"]
    ]
    if failed_validation:
        return "结果明确标记验证/约束失败: " + ", ".join(failed_validation[:5])
    return ""


def _identifiability_result_error(results: list[dict]) -> str:
    diagnostics = [
        item for item in results
        if "参数可辨识性" in item["name"]
    ]
    if not diagnostics:
        return "一维瞬态导热标定缺少参数可辨识性结果"
    if any(item["value"] != 1 for item in diagnostics):
        return "多起点标定未通过参数可辨识性门禁"
    return ""


def _identifiability_report_error(content: str) -> str:
    from mmw.utils.moving_heat import assess_multistart_identifiability

    try:
        report = json.loads(content)
    except json.JSONDecodeError:
        return "identifiability.json 不存在或不是合法 JSON"
    if not isinstance(report, dict) or report.get("schema_version") != 1:
        return "identifiability.json schema_version 必须为 1"
    thresholds = report.get("thresholds")
    if not isinstance(thresholds, dict):
        return "identifiability.json 缺少 thresholds"
    try:
        expected = assess_multistart_identifiability(
            report.get("parameter_sets"),
            report.get("losses"),
            initial_parameter_sets=report.get("initial_parameter_sets"),
            relative_loss_tolerance=thresholds.get("relative_loss"),
            absolute_loss_tolerance=thresholds.get("absolute_loss"),
            parameter_spread_tolerance=thresholds.get("parameter_spread"),
            outcome_sets=report.get("outcome_sets"),
            outcome_spread_tolerance=thresholds.get("outcome_spread"),
        )
    except (TypeError, ValueError):
        return "identifiability.json 的原始多起点证据或阈值非法"
    checked_fields = (
        "identifiable",
        "starts",
        "near_optimal_count",
        "best_loss",
        "loss_limit",
        "parameter_relative_spans",
        "outcome_relative_spans",
        "thresholds",
        "failures",
    )
    if any(report.get(key) != expected[key] for key in checked_fields):
        return "identifiability.json 诊断与原始多起点证据不一致"
    if not expected["identifiable"]:
        return "多起点诊断明确判定参数不可辨识"
    return ""


def _recovery_path(mgr: CheckpointManager) -> Path:
    checkpoint_dir = getattr(mgr, "checkpoint_dir", ProjectPaths(mgr.workspace).checkpoints)
    return checkpoint_dir / "05_code" / "recovery.json"


def _active_model_version(mgr: CheckpointManager) -> int:
    getter = getattr(mgr, "get_active_version", None)
    return getter(StageID.MODEL) if getter else 0


def _save_recovery(mgr: CheckpointManager, code: str) -> None:
    path = _recovery_path(mgr)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({
        "model_version": _active_model_version(mgr),
        "solution.py": code,
    }, ensure_ascii=False), encoding="utf-8")


def _load_recovery(mgr: CheckpointManager) -> str:
    path = _recovery_path(mgr)
    if not path.is_file():
        return ""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return ""
    if (
        not isinstance(data, dict)
        or data.get("model_version") != _active_model_version(mgr)
        or not isinstance(data.get("solution.py"), str)
    ):
        return ""
    return data["solution.py"].strip()


def _load_newer_recovery(mgr: CheckpointManager, latest_code: int) -> str:
    code = _load_recovery(mgr)
    if not code:
        return ""
    checkpoint = (
        mgr.checkpoint_dir / "05_code" / f"v{latest_code}" / "solution.py"
    )
    recovery = _recovery_path(mgr)
    if (
        latest_code <= 0
        or not checkpoint.is_file()
        or recovery.stat().st_mtime_ns > checkpoint.stat().st_mtime_ns
    ):
        return code
    return ""


def _code_uses_active_model(mgr: CheckpointManager, version: int) -> bool:
    """仅复用由当前激活模型生成的代码，避免跨模型修补旧实现。"""
    meta = mgr.load_meta(StageID.CODE, version)
    return (
        meta is not None
        and meta.upstream_versions.get(StageID.MODEL.value)
        == mgr.get_active_version(StageID.MODEL)
    )


def _runtime_summary() -> str:
    packages = ("numpy", "pandas", "scipy", "scikit-learn")
    lines = [f"Python {sys.version.split()[0]}"]
    for package in packages:
        try:
            package_version = version(package)
        except PackageNotFoundError:
            package_version = "未安装"
        lines.append(f"{package} {package_version}")
    lines.extend([
        "",
        "受测运行时模块：",
        "from _mmw_moving_heat import (MovingSlabConfig, simulate_moving_slab, "
        "simulate_piecewise_first_order, assess_multistart_identifiability)",
        "MovingSlabConfig(thickness, grid_points, sample_dt, substeps, "
        "diffusivity, initial_temperature, scheme='explicit'|'implicit')",
        "simulate_moving_slab(sample_times, *, speed, air_position_knots, "
        "air_temperatures, transfer_position_knots, surface_transfer_rates, config)",
        "surface_transfer_rates 直接接收 Robin 系数 gamma=h/lambda，单位与 thickness "
        "的倒数一致；模块内部负责边界离散，不要换算成 1/time。",
        "speed * sample_times 必须与位置节点同单位；题面为 cm/min、采样时间为秒时，"
        "传入 speed/60（cm/s），不能把 70 cm/min 当成 70 cm/s。",
        "返回值仅为一维中心温度 ndarray，不返回 (times, temperatures) 元组；"
        "sample_times 必须严格等间隔且间隔等于 sample_dt，grid_points 必须为奇数。",
        "simulate_piecewise_first_order(sample_times, *, speed, "
        "air_position_knots, air_temperatures, response_position_knots, "
        "response_rates, initial_temperature) 是物理 PDE 参数不可辨识时的经验降阶"
        "路径；response_rates 单位为 1/time，只表示中心温度有效响应率，不是 "
        "Robin/材料参数。首个采样时刻可大于零，函数会从物理时刻零积分。",
        "assess_multistart_identifiability(parameter_sets, losses, *, "
        "initial_parameter_sets, "
        "relative_loss_tolerance=0.01, absolute_loss_tolerance=1e-9, "
        "parameter_spread_tolerance=0.25, outcome_sets=None, "
        "outcome_spread_tolerance=0.05) 返回可 JSON 序列化诊断。",
        "只有 scheme='explicit' 才检查 config.diffusion_number <= 0.5，"
        "不足时增加 substeps。薄层刚性问题应使用 scheme='implicit'、"
        "sample_dt=真实输出间隔、substeps=1；隐式格式不得被显式扩散数条件阻断，"
        "但仍须做网格或时间步收敛检查。",
        "移动热过程必须优先复用该模块，不要重新手写有限差分循环。",
        "至少 3 个不同初值标定并调用可辨识性诊断；失败时 raise，"
        "诊断函数的原始返回对象直接、无包装地写入结果目录 identifiability.json "
        "顶层，其他标定元数据另存；通过时 results.json "
        "必须写入名称含“参数可辨识性”、value=1 的状态项。",
    ])
    return "\n".join(lines)


def _review_feedback(mgr: CheckpointManager) -> str:
    """显式重跑 code 时复用最新 review 的失败证据。"""
    version = mgr.get_latest_version(StageID.REVIEW)
    if not version:
        return ""
    meta = mgr.load_meta(StageID.REVIEW, version)
    if meta is None or meta.upstream_versions.get(StageID.CODE.value) != mgr.get_latest_version(StageID.CODE):
        return ""
    from mmw.pipeline.state_machine import PipelineStateMachine

    error = PipelineStateMachine(mgr).quality_error(StageID.REVIEW, version)
    if not error:
        return ""
    artifacts = mgr.load_artifacts(StageID.REVIEW, version)
    from mmw.agents.reviewer import get_review_rework_stage

    if get_review_rework_stage(artifacts) != StageID.CODE.value:
        return ""
    details = artifacts.get("review.md", "") + "\n" + artifacts.get("numeric_audit.md", "")
    return f"{error}\n\nreview v{version} 反馈：\n{details[-12000:]}"


def _solve_feedback(mgr: CheckpointManager) -> str:
    """显式重跑 code 时优先复用由当前代码产生的 solve 门禁错误。"""
    version = mgr.get_latest_version(StageID.SOLVE)
    if not version:
        return ""
    meta = mgr.load_meta(StageID.SOLVE, version)
    if meta is None or meta.upstream_versions.get(StageID.CODE.value) != mgr.get_latest_version(StageID.CODE):
        return ""
    from mmw.pipeline.state_machine import PipelineStateMachine

    error = PipelineStateMachine(mgr).quality_error(StageID.SOLVE, version)
    if not error:
        return ""
    artifacts = mgr.load_artifacts(StageID.SOLVE, version)
    sensitivity = artifacts.get("sensitivity.json", "")
    results = artifacts.get("results.json", "")
    return (
        f"{error}\n\nsolve v{version} 产物摘录：\n"
        f"sensitivity.json:\n{sensitivity[-6000:]}\n\nresults.json:\n{results[-6000:]}"
    )


def _paper_feedback(mgr: CheckpointManager) -> str:
    """把摘要评审确认的上游数据缺口交回当前代码版本。"""
    version = mgr.get_latest_version(StageID.PAPER)
    if not version:
        return ""
    meta = mgr.load_meta(StageID.PAPER, version)
    if meta is None or meta.upstream_versions.get(StageID.CODE.value) != mgr.get_latest_version(StageID.CODE):
        return ""
    score = mgr.load_artifacts(StageID.PAPER, version).get("abstract_score.json", "")
    try:
        data = json.loads(score)
    except json.JSONDecodeError:
        return ""
    if not isinstance(data, dict) or data.get("needs_upstream_data") is not True:
        return ""
    return (
        f"paper v{version} 摘要评审确认缺少上游求解数据：\n{score}\n\n"
        "只能依据题面、已审批上游产物和真实文件补充结果；缺失输入必须明确标记不可用，"
        "不得新增题目、场景或参数，也不得把情景代理写成现场实证。"
    )


def run_code(workspace: Path, mgr: CheckpointManager) -> bool | None:
    paths = ProjectPaths(workspace)
    model_arts = mgr.load_artifacts(StageID.MODEL)
    if not model_arts:
        print_error("请先完成并审批建模阶段")
        return

    eda_arts = mgr.load_artifacts(StageID.EDA)

    model_text = model_arts.get("model.md", "")
    params_text = model_arts.get("params.json", "")
    data_summary = eda_arts.get("data_summary.md", "")
    eda_output = eda_arts.get("eda_output.txt", "")
    if eda_output:
        data_summary += "\n\n## EDA 程序真实输出（截取）\n\n" + eda_output[:8000]
    verify_notes = model_arts.get("verify_report.md", "")

    settings = get_settings()
    llm_config = settings.get_llm_config("coder")
    if getattr(llm_config, "backend", "openai") == "openai" and not llm_config.api_key:
        print_error("未配置 LLM API Key")
        return
    llm = LLMClient(llm_config, log_dir=paths.logs)

    # 真实数据文件清单（防止 coder 猜文件名失败后用模拟数据兜底）
    data_files = [paths.relative(path) for path in paths.data_files()]

    deliverables = load_deliverables(mgr)
    try:
        sub_problems = json.loads(
            mgr.load_artifacts(StageID.ANALYZE).get("sub_problems.json", "{}")
        ).get("sub_problems", [])
    except (json.JSONDecodeError, AttributeError):
        sub_problems = []

    previous_code = ""
    previous_contract = ""
    revision_feedback = ""
    latest_code = mgr.get_latest_version(StageID.CODE)
    recovered = _load_newer_recovery(mgr, latest_code)
    if recovered:
        previous_code = recovered
        print_info("检测到比最新检查点更新的代码候选，将先直接恢复执行")
    elif latest_code and _code_uses_active_model(mgr, latest_code):
        from mmw.pipeline.state_machine import PipelineStateMachine

        human_reason = mgr.latest_rework_reason(StageID.CODE, latest_code)
        human_feedback = f"重做要求：\n{human_reason}" if human_reason else ""
        gate_error = PipelineStateMachine(mgr).quality_error(StageID.CODE, latest_code)
        if not gate_error:
            gate_error = _solve_feedback(mgr)
        if not gate_error:
            gate_error = _paper_feedback(mgr)
        if not gate_error:
            gate_error = _review_feedback(mgr)
        feedback = "\n\n".join(item for item in (human_feedback, gate_error) if item)
        if feedback:
            previous = mgr.load_artifacts(StageID.CODE, latest_code)
            previous_code = previous.get("solution.py", "")
            previous_contract = previous.get("method_contract.json", "")
            run_log = previous.get("run_log.txt", "")
            attempt_history = previous.get("attempt_history.json", "")
            revision_feedback = (
                f"{feedback}\n\n上一版运行日志：\n{run_log[-8000:]}"
                f"\n\n全部候选执行摘要：\n{attempt_history[-12000:]}"
            )
    agent = CoderAgent(llm)
    print_info("正在生成代码并尝试运行...")
    results_path = paths.result_data / "results.json"
    results_before = _file_signature(results_path)
    identifiability_path = paths.result_data / "identifiability.json"
    identifiability_before = _file_signature(identifiability_path)
    artifacts, exec_result = agent.implement_with_retry(
        model=model_text,
        params=params_text,
        problem_text=paths.problem.read_text(encoding="utf-8") if paths.problem.is_file() else "",
        work_dir=workspace,
        data_summary=data_summary,
        verify_notes=verify_notes,
        data_files=data_files,
        deliverables=deliverables,
        runtime_summary=_runtime_summary(),
        previous_code=previous_code,
        revision_feedback=revision_feedback,
        figures_dir=paths.relative(paths.figures),
        results_dir=paths.relative(paths.result_data) if paths.modern else ".",
        method_contract=previous_contract or model_arts.get("method_contract.json", "{}"),
        on_candidate=lambda code: _save_recovery(mgr, code),
        output_validator=lambda result: _candidate_quality_error(
            result,
            results_path,
            results_before,
            require_identifiability=requires_moving_heat_helper(model_text),
            identifiability_path=identifiability_path,
            identifiability_before=identifiability_before,
            sub_problems=sub_problems,
            model_contract=model_arts.get("method_contract.json", ""),
        ),
    )

    if not _has_solution_py(artifacts):
        print_error(
            "代码阶段未产出 solution.py，已拒绝保存 completed 检查点。"
            "请 rework code 或检查 Coder 输出 artifact 格式"
        )
        return

    if exec_result and exec_result.success:
        artifacts["run_log.txt"] = f"STDOUT:\n{exec_result.stdout}\n\nSTDERR:\n{exec_result.stderr}"
        if _file_signature(results_path) != results_before:
            artifacts["results_preview.json"] = results_path.read_text(encoding="utf-8")
        if _file_signature(identifiability_path) != identifiability_before:
            artifacts["identifiability.json"] = identifiability_path.read_text(
                encoding="utf-8",
            )
    elif exec_result:
        artifacts["run_log.txt"] = (
            f"[执行失败]\n{exec_result.error_summary}\n\n"
            f"STDOUT:\n{exec_result.stdout}\n\nSTDERR:\n{exec_result.stderr}"
        )
        if model_rework_requested(exec_result.error_summary):
            artifacts["rework_request.json"] = json.dumps({
                "schema_version": 1,
                "target": StageID.MODEL.value,
                "reason": "当前模型契约内候选结构无法同时通过拟合质量与参数可辨识性门禁",
            }, ensure_ascii=False, indent=2)

    if model_arts.get("method_contract.json"):
        try:
            method_contract = finalize_code_contract(
                model_arts["method_contract.json"],
                artifacts.get("method_contract.json", "") or previous_contract,
                solution=artifacts["solution.py"],
                model_version=mgr.get_active_version(StageID.MODEL),
                code_version=mgr.get_next_version(StageID.CODE),
            )
        except ValueError as error:
            print_error(str(error))
            return
        artifacts["method_contract.json"] = json.dumps(
            method_contract, ensure_ascii=False, indent=2,
        )

    meta = MetaData(
        stage=StageID.CODE.value, version=0,
        model_used=llm.model,
        tokens_input=llm.total_input_tokens,
        tokens_output=llm.total_output_tokens,
    )
    vdir = mgr.save(StageID.CODE, artifacts, meta)
    if paths.modern:
        code_output = paths.output / "code" / "solution.py"
        code_output.parent.mkdir(parents=True, exist_ok=True)
        code_output.write_text(artifacts["solution.py"], encoding="utf-8")

    if exec_result and not exec_result.success:
        print_info(f"失败候选已保存到检查点，供下一轮诊断: {vdir}")
        print_info("代码运行未成功，请手动检查和修改 solution.py")
    else:
        print_success(f"代码实现完成，产出保存到: {vdir}")
