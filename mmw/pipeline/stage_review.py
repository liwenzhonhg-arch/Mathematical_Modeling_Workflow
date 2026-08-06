"""阶段 8：评审润色。"""

from __future__ import annotations

import json
from pathlib import Path

from mmw.agents.reviewer import ReviewerAgent
from mmw.config import get_settings
from mmw.llm import LLMClient
from mmw.models import MetaData, StageID
from mmw.project import ProjectPaths
from mmw.utils.checkpoint import CheckpointManager
from mmw.utils.display import print_error, print_info, print_success
from mmw.utils.method_contract import build_review_consistency
from mmw.utils.numeric_audit import audit_paper, render_audit_md


def build_numeric_audit(workspace: Path, mgr: CheckpointManager):
    """纯本地构建论文数值审计，不调用 LLM、不保存检查点。"""
    sections = {
        name: content
        for name, content in mgr.load_artifacts(StageID.PAPER).items()
        if name.endswith(".tex")
    }
    if not sections:
        raise ValueError("paper 阶段没有可审计的 .tex 章节")
    solve_arts = mgr.load_artifacts(StageID.SOLVE)
    model_arts = mgr.load_artifacts(StageID.MODEL)
    problem_path = ProjectPaths(workspace).problem
    problem_text = problem_path.read_text(encoding="utf-8") if problem_path.exists() else ""
    report = audit_paper(
        sections,
        results_json=solve_arts.get("results.json", "[]"),
        sensitivity_json=solve_arts.get("sensitivity.json", "{}"),
        params_json=model_arts.get("params.json", "[]"),
        method_contract_json=solve_arts.get("method_contract.json", "{}"),
        method_runtime_json=solve_arts.get("method_runtime.json", "{}"),
        raw_output=(solve_arts.get("run_log.txt", "") + "\n"
                    + solve_arts.get("interpretation.md", "") + "\n"
                    + solve_arts.get("method_contract.json", "") + "\n"
                    + solve_arts.get("method_runtime.json", "") + "\n"
                    + problem_text),
    )
    return report, render_audit_md(report)


def _add_numeric_audit_check(artifacts: dict[str, str], unmatched_count: int) -> None:
    """把程序审计结论写入结构化 checklist；格式无效时留给审批门禁拒绝。"""
    try:
        checklist = json.loads(artifacts.get("checklist.json", ""))
    except json.JSONDecodeError:
        return
    if not isinstance(checklist, dict) or not isinstance(checklist.get("items"), list):
        return
    checklist["items"].append({
        "check": "程序化数值审计无高置信缺出处数字",
        "status": "fail" if unmatched_count else "pass",
        "note": f"高置信缺出处数值 {unmatched_count} 个",
    })
    artifacts["checklist.json"] = json.dumps(checklist, ensure_ascii=False, indent=2)


def _add_method_check(artifacts: dict[str, str], report: dict) -> None:
    try:
        checklist = json.loads(artifacts.get("checklist.json", ""))
    except json.JSONDecodeError:
        return
    if not isinstance(checklist, dict) or not isinstance(checklist.get("items"), list):
        return
    checklist["items"].append({
        "check": "模型、代码、求解与论文方法契约一致",
        "status": "pass" if report["passed"] else "fail",
        "note": "；".join(report["failures"]) or "方法契约与当前版本绑定",
    })
    artifacts["checklist.json"] = json.dumps(checklist, ensure_ascii=False, indent=2)


def _review_manifest(paper_arts: dict[str, str], solve_arts: dict[str, str]) -> str:
    """列出当前论文与导出阶段会携带的真实文件，避免 Reviewer 误报缺件。"""
    entries = set(paper_arts)
    if paper_arts.get("solution.py"):
        entries.add("code/solution.py (export path)")
    if solve_arts.get("results.json"):
        entries.add("output/data/results.json")
    if solve_arts.get("sensitivity.json"):
        entries.add("output/data/sensitivity.json")
    try:
        data_tables = json.loads(solve_arts.get("data_tables.json", "{}"))
    except json.JSONDecodeError:
        data_tables = {}
    entries.update(
        f"output/data/{Path(name).name}"
        for name in data_tables
        if isinstance(name, str) and Path(name).name == name
    )
    try:
        figures = json.loads(solve_arts.get("figures_list.json", "[]"))
    except json.JSONDecodeError:
        figures = []
    entries.update(
        f"output/figures/{Path(str(name)).name}"
        for name in figures
        if isinstance(name, str) and Path(name).name
    )
    return "\n".join(sorted(entries))


def run_review(workspace: Path, mgr: CheckpointManager) -> None:
    paper_arts = mgr.load_artifacts(StageID.PAPER)
    if not paper_arts:
        print_error("请先完成并审批论文写作阶段")
        return

    # 收集论文章节与参考文献，避免 Reviewer 因看不到现有文件而误报缺失。
    sections: dict[str, str] = {}
    for name, content in paper_arts.items():
        if name.endswith(".tex") or name == "references.bib":
            sections[name] = content
    solve_arts = mgr.load_artifacts(StageID.SOLVE)
    sections["artifact_manifest.txt"] = _review_manifest(paper_arts, solve_arts)
    if solve_arts.get("method_contract.json"):
        sections["method_contract.json"] = solve_arts["method_contract.json"]
        sections["method_validation.json"] = solve_arts.get("method_validation.json", "")
        sections["method_traceability.json"] = paper_arts.get(
            "method_traceability.json", ""
        )
    latest_review = mgr.get_latest_version(StageID.REVIEW)
    human_reason = mgr.latest_rework_reason(StageID.REVIEW, latest_review)
    if human_reason:
        sections["human_rework_feedback.txt"] = human_reason

    if not sections:
        print_error("论文阶段未生成 .tex 文件")
        return

    # 程序化数值审计：论文数值必须能在求解产出中找到出处
    print_info("正在审计论文数值出处...")
    paths = ProjectPaths(workspace)
    report, audit_md = build_numeric_audit(workspace, mgr)
    if report.unmatched_high:
        print_error(f"发现 {len(report.unmatched_high)} 个高置信缺出处数值，详见 numeric_audit.md")

    settings = get_settings()
    llm_config = settings.get_llm_config("reviewer")
    if getattr(llm_config, "backend", "openai") == "openai" and not llm_config.api_key:
        print_error("未配置 LLM API Key")
        return
    llm = LLMClient(llm_config, log_dir=paths.logs)

    agent = ReviewerAgent(llm)
    print_info("正在评审论文...")
    artifacts = agent.review(sections, numeric_audit=audit_md)
    artifacts["numeric_audit.md"] = audit_md
    _add_numeric_audit_check(artifacts, len(report.unmatched_high))
    if solve_arts.get("method_contract.json"):
        method_report = build_review_consistency(
            solve_arts["method_contract.json"],
            paper_arts.get("method_contract.json", ""),
            paper_arts.get("method_traceability.json", ""),
            paper_arts.get("sections/model_solution.tex", ""),
        )
        artifacts["method_consistency.json"] = json.dumps(
            method_report, ensure_ascii=False, indent=2,
        )
        _add_method_check(artifacts, method_report)

    meta = MetaData(
        stage=StageID.REVIEW.value, version=0,
        model_used=llm.model,
        tokens_input=llm.total_input_tokens,
        tokens_output=llm.total_output_tokens,
    )
    vdir = mgr.save(StageID.REVIEW, artifacts, meta)
    print_success(f"评审完成，产出保存到: {vdir}")
    print_info("请查看 review.md 和 checklist.json")
