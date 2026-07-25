"""阶段 3：方法调研。"""

from __future__ import annotations

import json
import re
from importlib.resources import files
from pathlib import Path

from mmw.agents.researcher import ResearcherAgent
from mmw.config import get_settings
from mmw.llm import LLMClient
from mmw.models import MetaData, StageID
from mmw.project import ProjectPaths
from mmw.utils.checkpoint import CheckpointManager
from mmw.utils.display import print_error, print_info, print_success


def _load_references(workspace: Path) -> list[str]:
    """读取 references/ 下可安全解码的文本资料。"""
    ref_dir = workspace / "references"
    if not ref_dir.exists():
        return []
    references: list[str] = []
    for path in sorted(ref_dir.iterdir()):
        if not path.is_file():
            continue
        if path.suffix.casefold() in {".md", ".txt", ".tex", ".csv"}:
            content = path.read_text(encoding="utf-8", errors="replace")[:20000]
            references.append(f"{path.name}\n{content}")
        else:
            references.append(f"{path.name}（当前仅记录文件名，未解析二进制内容）")
    return references


def _load_knowledge(knowledge_dir: Path, query: str = "") -> str:
    """按题面关键词读取 HMML 中最相关的方法正文。"""
    hmml_path = knowledge_dir / "hmml.json"
    if not hmml_path.exists():
        return ""
    try:
        data = json.loads(hmml_path.read_text(encoding="utf-8"))
        if isinstance(data, dict) and "domains" in data:
            candidates: list[tuple[int, str, str]] = []
            folded = query.casefold()
            for domain in data["domains"]:
                for method in domain.get("methods", []):
                    terms = [method.get("name", ""), *method.get("keywords", [])]
                    score = sum(1 for term in terms if term and str(term).casefold() in folded)
                    candidates.append((score, domain.get("id", ""), method.get("id", "")))
            selected = [item for item in sorted(candidates, reverse=True) if item[0] > 0][:5]
            if not selected:
                return "可用方法域：\n" + "\n".join(
                    f"- {domain['name']}: {domain.get('description', '')}"
                    for domain in data["domains"]
                )
            parts: list[str] = []
            for _, domain_id, method_id in selected:
                path = knowledge_dir / "domains" / domain_id / f"{method_id}.md"
                if path.exists():
                    parts.append(path.read_text(encoding="utf-8")[:8000])
            return "\n\n".join(parts)
    except Exception:
        pass
    return ""


def _build_evidence(
    references: list[str],
    knowledge_context: str,
    approach: str,
) -> str:
    """记录本阶段实际拥有的证据，避免把待搜索占位符当成已调研资料。"""
    unresolved = re.findall(r"\[需要搜索:\s*([^\]]+)\]", approach)
    reference_names = [reference.splitlines()[0] for reference in references]
    return json.dumps({
        "local_references": reference_names,
        "hmml_index_loaded": bool(knowledge_context),
        "external_search_performed": False,
        "unresolved_searches": unresolved,
    }, ensure_ascii=False, indent=2)


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
    knowledge_dir = Path(str(files("knowledge")))
    knowledge_context = _load_knowledge(knowledge_dir, analysis)

    if references:
        print_info(f"检测到 {len(references)} 个参考资料文件")

    settings = get_settings()
    llm_config = settings.get_llm_config("researcher")
    if getattr(llm_config, "backend", "openai") == "openai" and not llm_config.api_key:
        print_error("未配置 LLM API Key")
        return
    llm = LLMClient(llm_config, log_dir=ProjectPaths(workspace).logs)

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
    artifacts["research_evidence.json"] = _build_evidence(
        references,
        knowledge_context,
        artifacts.get("approach.md", ""),
    )

    meta = MetaData(
        stage=StageID.RESEARCH.value, version=0,
        model_used=llm.model,
        tokens_input=llm.total_input_tokens,
        tokens_output=llm.total_output_tokens,
    )
    vdir = mgr.save(StageID.RESEARCH, artifacts, meta)
    print_success(f"方法调研完成，产出保存到: {vdir}")
