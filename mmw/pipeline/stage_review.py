"""阶段 8：评审润色。"""

from __future__ import annotations

import json
from pathlib import Path

from mmw.agents.reviewer import ReviewerAgent
from mmw.config import get_settings
from mmw.llm import LLMClient
from mmw.models import MetaData, StageID
from mmw.utils.checkpoint import CheckpointManager
from mmw.utils.display import print_error, print_info, print_success
from mmw.utils.numeric_audit import audit_paper, render_audit_md


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
    sections["artifact_manifest.txt"] = "\n".join(sorted(paper_arts))

    if not sections:
        print_error("论文阶段未生成 .tex 文件")
        return

    # 程序化数值审计：论文数值必须能在求解产出中找到出处
    print_info("正在审计论文数值出处...")
    solve_arts = mgr.load_artifacts(StageID.SOLVE)
    model_arts = mgr.load_artifacts(StageID.MODEL)
    problem_path = workspace / "problem.md"
    problem_text = problem_path.read_text(encoding="utf-8") if problem_path.exists() else ""
    report = audit_paper(
        sections,
        results_json=solve_arts.get("results.json", "[]"),
        sensitivity_json=solve_arts.get("sensitivity.json", "{}"),
        params_json=model_arts.get("params.json", "[]"),
        raw_output=(solve_arts.get("run_log.txt", "") + "\n"
                    + solve_arts.get("interpretation.md", "") + "\n" + problem_text),
    )
    audit_md = render_audit_md(report)
    if report.unmatched_high:
        print_error(f"发现 {len(report.unmatched_high)} 个高置信缺出处数值，详见 numeric_audit.md")

    settings = get_settings()
    llm_config = settings.get_llm_config("reviewer")
    if not llm_config.api_key:
        print_error("未配置 LLM API Key")
        return
    llm = LLMClient(llm_config, log_dir=workspace / "logs")

    agent = ReviewerAgent(llm)
    print_info("正在评审论文...")
    artifacts = agent.review(sections, numeric_audit=audit_md)
    artifacts["numeric_audit.md"] = audit_md
    _add_numeric_audit_check(artifacts, len(report.unmatched_high))

    meta = MetaData(
        stage=StageID.REVIEW.value, version=0,
        model_used=llm.model,
        tokens_input=llm.total_input_tokens,
        tokens_output=llm.total_output_tokens,
    )
    vdir = mgr.save(StageID.REVIEW, artifacts, meta)
    print_success(f"评审完成，产出保存到: {vdir}")
    print_info("请查看 review.md 和 checklist.json")
