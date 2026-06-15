"""阶段 4：数学建模 + Verifier 双重验证。"""

from __future__ import annotations

from pathlib import Path

from mmw.agents.modeler import ModelerAgent
from mmw.agents.verifier import VerifierAgent
from mmw.config import get_settings
from mmw.llm import LLMClient
from mmw.models import MetaData, StageID
from mmw.utils.checkpoint import CheckpointManager
from mmw.utils.display import print_error, print_info, print_success


def run_model(workspace: Path, mgr: CheckpointManager) -> None:
    analyze_arts = mgr.load_artifacts(StageID.ANALYZE)
    research_arts = mgr.load_artifacts(StageID.RESEARCH)
    eda_arts = mgr.load_artifacts(StageID.EDA)

    if not analyze_arts or not research_arts:
        print_error("请先完成并审批前置阶段")
        return

    analysis = analyze_arts.get("analysis.md", "")
    assumptions = analyze_arts.get("assumptions.md", "")
    methods = research_arts.get("methods.md", "")
    approach = research_arts.get("approach.md", "")
    data_summary = eda_arts.get("data_summary.md", "")

    settings = get_settings()

    # 建模阶段
    llm_config = settings.get_llm_config("modeler")
    if not llm_config.api_key:
        print_error("未配置 LLM API Key")
        return
    llm = LLMClient(llm_config, log_dir=workspace / "logs")

    modeler = ModelerAgent(llm)
    print_info("正在建立数学模型...")
    model_artifacts = modeler.build_model(
        analysis=analysis, methods=methods, approach=approach,
        assumptions=assumptions, data_summary=data_summary,
    )

    # 验证阶段
    print_info("正在验证模型...")
    verify_config = settings.get_llm_config("verifier")
    verify_llm = LLMClient(verify_config, log_dir=workspace / "logs")

    verifier = VerifierAgent(verify_llm)
    problem_summary = analysis[:1500]
    model_text = model_artifacts.get("model.md", "")
    equations_text = model_artifacts.get("equations.json", "")

    verify_artifacts = verifier.verify(
        problem_summary=problem_summary,
        assumptions=assumptions,
        model=model_text,
        equations=equations_text,
    )

    # 合并产出
    all_artifacts = {**model_artifacts, **verify_artifacts}

    total_input = llm.total_input_tokens + verify_llm.total_input_tokens
    total_output = llm.total_output_tokens + verify_llm.total_output_tokens
    meta = MetaData(
        stage=StageID.MODEL.value, version=0,
        model_used=f"{llm.model}+{verify_llm.model}",
        tokens_input=total_input,
        tokens_output=total_output,
    )
    vdir = mgr.save(StageID.MODEL, all_artifacts, meta)
    print_success(f"建模完成（含验证），产出保存到: {vdir}")

    verify_report = verify_artifacts.get("verify_report.md", "")
    if "问题" in verify_report or "修改" in verify_report:
        print_info("Verifier 发现了一些问题，请仔细审查 verify_report.md")


def run_model_branch(workspace: Path, mgr: CheckpointManager) -> None:
    """branch：生成与激活方案显著不同的备选建模方案，产出新版本。

    跳过 Verifier（备选方案的取舍由 compare 报告 + 人工完成，
    选中后如需验证可 rework model）。
    """
    analyze_arts = mgr.load_artifacts(StageID.ANALYZE)
    research_arts = mgr.load_artifacts(StageID.RESEARCH)
    eda_arts = mgr.load_artifacts(StageID.EDA)

    existing_version = mgr.get_active_version(StageID.MODEL)
    if existing_version == 0:
        print_error("model 阶段尚无版本，请先运行 mmw run model")
        return
    existing_model = mgr.load_artifacts(StageID.MODEL, existing_version).get("model.md", "")
    if not existing_model:
        print_error(f"model v{existing_version} 中未找到 model.md")
        return

    settings = get_settings()
    llm_config = settings.get_llm_config("modeler")
    if not llm_config.api_key:
        print_error("未配置 LLM API Key")
        return
    llm = LLMClient(llm_config, log_dir=workspace / "logs")

    modeler = ModelerAgent(llm)
    print_info(f"基于 model v{existing_version} 生成备选建模方案...")
    artifacts = modeler.build_alternative_model(
        analysis=analyze_arts.get("analysis.md", ""),
        methods=research_arts.get("methods.md", ""),
        approach=research_arts.get("approach.md", ""),
        assumptions=analyze_arts.get("assumptions.md", ""),
        data_summary=eda_arts.get("data_summary.md", ""),
        existing_model=existing_model,
        existing_version=existing_version,
    )

    meta = MetaData(
        stage=StageID.MODEL.value, version=0,
        model_used=llm.model,
        tokens_input=llm.total_input_tokens,
        tokens_output=llm.total_output_tokens,
    )
    vdir = mgr.save(StageID.MODEL, artifacts, meta)
    new_version = mgr.get_latest_version(StageID.MODEL)
    print_success(f"备选方案已生成: {vdir}")
    print_info(f"对比两个方案: mmw compare model {existing_version} {new_version}")
    print_info(f"选定方案后审批激活: mmw approve model --version <N>")


def run_compare_model(workspace: Path, mgr: CheckpointManager, v1: int, v2: int) -> None:
    """用 LLM 对比 model 阶段的两个版本，报告写入 output/（不进版本树）。"""
    from mmw.agents.base import BaseAgent

    if v1 == v2:
        print_error("两个版本号相同，无需对比")
        return
    arts1 = mgr.load_artifacts(StageID.MODEL, v1)
    arts2 = mgr.load_artifacts(StageID.MODEL, v2)
    if not arts1:
        print_error(f"model v{v1} 不存在")
        return
    if not arts2:
        print_error(f"model v{v2} 不存在")
        return

    settings = get_settings()
    llm_config = settings.get_llm_config("verifier")
    if not llm_config.api_key:
        print_error("未配置 LLM API Key")
        return
    llm = LLMClient(llm_config, log_dir=workspace / "logs")

    agent = BaseAgent(llm)
    agent.role = "compare"
    prompt = agent.render_prompt(
        "compare_model.j2",
        v1=v1, v2=v2,
        model_a=arts1.get("model.md", ""),
        model_b=arts2.get("model.md", ""),
    )
    print_info(f"正在对比 model v{v1} 与 v{v2}...")
    report = agent.run_stream(prompt)

    out_path = workspace / "output" / f"compare_model_v{v1}_v{v2}.md"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(report, encoding="utf-8")
    print_success(f"对比报告已生成: {out_path}")
    print_info("选定方案后审批激活: mmw approve model --version <N>")
