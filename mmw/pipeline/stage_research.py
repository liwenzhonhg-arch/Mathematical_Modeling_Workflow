"""阶段 3：方法调研。"""

from __future__ import annotations

import json
from pathlib import Path

from mmw.agents.researcher import ResearcherAgent
from mmw.config import get_settings
from mmw.llm import LLMClient
from mmw.models import MetaData, StageID
from mmw.utils.checkpoint import CheckpointManager
from mmw.utils.display import print_error, print_info, print_success


def _load_references(workspace: Path) -> list[str]:
    """读取 references/ 下用户手动放入的参考资料文件名。"""
    ref_dir = workspace / "references"
    if not ref_dir.exists():
        return []
    return [f.name for f in sorted(ref_dir.iterdir()) if f.is_file()]


def _load_knowledge(knowledge_dir: Path) -> str:
    """简单加载知识库摘要（如果存在）。"""
    hmml_path = knowledge_dir / "hmml.json"
    if not hmml_path.exists():
        return ""
    try:
        data = json.loads(hmml_path.read_text(encoding="utf-8"))
        # 提取顶层域名作为概要
        if isinstance(data, dict) and "domains" in data:
            domains = data["domains"]
            lines = [f"- {d['name']}: {d.get('description', '')}" for d in domains]
            return "可用方法域：\n" + "\n".join(lines)
    except Exception:
        pass
    return ""


def run_research(workspace: Path, mgr: CheckpointManager) -> None:
    analyze_arts = mgr.load_artifacts(StageID.ANALYZE)
    if not analyze_arts:
        print_error("请先完成并审批分析阶段")
        return

    analysis = analyze_arts.get("analysis.md", "")
    assumptions = analyze_arts.get("assumptions.md", "")

    sub_problems_raw = analyze_arts.get("sub_problems.json", "[]")
    try:
        sp_data = json.loads(sub_problems_raw)
        sub_problems = sp_data.get("sub_problems", []) if isinstance(sp_data, dict) else []
    except json.JSONDecodeError:
        sub_problems = []

    eda_arts = mgr.load_artifacts(StageID.EDA)
    data_summary = eda_arts.get("data_summary.md", "")

    references = _load_references(workspace)
    knowledge_dir = Path("knowledge")
    knowledge_context = _load_knowledge(knowledge_dir)

    if references:
        print_info(f"检测到 {len(references)} 个参考资料文件")

    settings = get_settings()
    llm_config = settings.get_llm_config("researcher")
    if not llm_config.api_key:
        print_error("未配置 LLM API Key")
        return
    llm = LLMClient(llm_config, log_dir=workspace / "logs")

    agent = ResearcherAgent(llm)
    print_info("正在调研建模方法...")
    artifacts = agent.research(
        analysis=analysis,
        sub_problems=sub_problems,
        assumptions=assumptions,
        data_summary=data_summary,
        knowledge_context=knowledge_context,
        references=references,
    )

    meta = MetaData(
        stage=StageID.RESEARCH.value, version=0,
        model_used=llm.model,
        tokens_input=llm.total_input_tokens,
        tokens_output=llm.total_output_tokens,
    )
    vdir = mgr.save(StageID.RESEARCH, artifacts, meta)
    print_success(f"方法调研完成，产出保存到: {vdir}")
