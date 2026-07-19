"""阶段 5：代码实现（含错误反思循环）。"""

from __future__ import annotations

import json
import sys
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

from mmw.agents.coder import CoderAgent
from mmw.config import get_settings
from mmw.llm import LLMClient
from mmw.models import MetaData, StageID
from mmw.project import ProjectPaths
from mmw.utils.checkpoint import CheckpointManager
from mmw.utils.display import print_error, print_info, print_success


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


def _runtime_summary() -> str:
    packages = ("numpy", "pandas", "scipy", "scikit-learn")
    lines = [f"Python {sys.version.split()[0]}"]
    for package in packages:
        try:
            package_version = version(package)
        except PackageNotFoundError:
            package_version = "未安装"
        lines.append(f"{package} {package_version}")
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
    return f"paper v{version} 摘要评审确认缺少上游求解数据：\n{score}"


def run_code(workspace: Path, mgr: CheckpointManager) -> None:
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
    if not llm_config.api_key:
        print_error("未配置 LLM API Key")
        return
    llm = LLMClient(llm_config, log_dir=paths.logs)

    # 真实数据文件清单（防止 coder 猜文件名失败后用模拟数据兜底）
    data_files = [paths.relative(path) for path in paths.data_files()]

    deliverables = load_deliverables(mgr)

    previous_code = ""
    revision_feedback = ""
    latest_code = mgr.get_latest_version(StageID.CODE)
    if latest_code:
        from mmw.pipeline.state_machine import PipelineStateMachine

        gate_error = PipelineStateMachine(mgr).quality_error(StageID.CODE, latest_code)
        if not gate_error:
            gate_error = _solve_feedback(mgr)
        if not gate_error:
            gate_error = _paper_feedback(mgr)
        if not gate_error:
            gate_error = _review_feedback(mgr)
        if gate_error:
            previous = mgr.load_artifacts(StageID.CODE, latest_code)
            previous_code = previous.get("solution.py", "")
            run_log = previous.get("run_log.txt", "")
            revision_feedback = f"{gate_error}\n\n上一版运行日志：\n{run_log[-8000:]}"

    agent = CoderAgent(llm)
    print_info("正在生成代码并尝试运行...")
    artifacts, exec_result = agent.implement_with_retry(
        model=model_text,
        params=params_text,
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
    )

    if not _has_solution_py(artifacts):
        print_error(
            "代码阶段未产出 solution.py，已拒绝保存 completed 检查点。"
            "请 rework code 或检查 Coder 输出 artifact 格式"
        )
        return

    if exec_result and exec_result.success:
        artifacts["run_log.txt"] = f"STDOUT:\n{exec_result.stdout}\n\nSTDERR:\n{exec_result.stderr}"
    elif exec_result:
        artifacts["run_log.txt"] = f"[执行失败]\n{exec_result.error_summary}\n\nSTDERR:\n{exec_result.stderr}"

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
    print_success(f"代码实现完成，产出保存到: {vdir}")

    if exec_result and not exec_result.success:
        print_info("代码运行未成功，请手动检查和修改 solution.py")
