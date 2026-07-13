"""阶段 4：数学建模 + Verifier 双重验证。"""

from __future__ import annotations

import json
from pathlib import Path

from mmw.agents.modeler import ModelerAgent
from mmw.agents.verifier import VerifierAgent
from mmw.config import get_settings
from mmw.llm import LLMClient
from mmw.models import MetaData, StageID
from mmw.utils.checkpoint import CheckpointManager
from mmw.utils.display import print_error, print_info, print_success

MAX_MODEL_REVISIONS = 2


def _code_feedback(mgr: CheckpointManager) -> str:
    """把最新 code 的机器门禁失败证据交回 model，避免跨阶段失忆。"""
    version = mgr.get_latest_version(StageID.CODE)
    if not version:
        return ""
    meta = mgr.load_meta(StageID.CODE, version)
    if meta is None or meta.upstream_versions.get(StageID.MODEL.value) != mgr.get_latest_version(StageID.MODEL):
        return ""
    from mmw.pipeline.state_machine import PipelineStateMachine

    error = PipelineStateMachine(mgr).quality_error(StageID.CODE, version)
    if not error:
        return ""
    run_log = mgr.load_artifacts(StageID.CODE, version).get("run_log.txt", "")
    return f"{error}\n\ncode v{version} 运行证据：\n{run_log[-8000:]}"


def _verify_model(
    workspace: Path,
    settings,
    analysis: str,
    assumptions: str,
    model_artifacts: dict[str, str],
) -> tuple[dict[str, str], LLMClient]:
    verify_config = settings.get_llm_config("verifier")
    verify_llm = LLMClient(verify_config, log_dir=workspace / "logs")
    verifier = VerifierAgent(verify_llm)
    artifacts = verifier.verify(
        problem_summary=analysis[:1500],
        assumptions=assumptions,
        model=model_artifacts.get("model.md", ""),
        equations=model_artifacts.get("equations.json", ""),
    )
    return artifacts, verify_llm


def _verify_severity(artifacts: dict[str, str]) -> str:
    try:
        status = json.loads(artifacts.get("verify_status.json", ""))
    except json.JSONDecodeError:
        return "invalid"
    severity = status.get("severity") if isinstance(status, dict) else None
    return severity if severity in {"pass", "warning", "block"} else "invalid"


def _run_verified_versions(
    workspace: Path,
    mgr: CheckpointManager,
    settings,
    modeler: ModelerAgent,
    model_llm: LLMClient,
    analysis: str,
    assumptions: str,
    model_artifacts: dict[str, str],
    max_revisions: int = MAX_MODEL_REVISIONS,
    history: list[dict] | None = None,
) -> tuple[Path, dict[str, str]]:
    history = list(history or [])
    verify_artifacts: dict[str, str] = {}
    vdir = workspace

    for round_no in range(max_revisions + 1):
        print_info(f"正在验证模型（第 {round_no + 1} 次）...")
        verify_artifacts, verify_llm = _verify_model(
            workspace, settings, analysis, assumptions, model_artifacts
        )
        severity = _verify_severity(verify_artifacts)
        try:
            status_data = json.loads(verify_artifacts.get("verify_status.json", "{}"))
        except json.JSONDecodeError:
            status_data = {}
        history.append({
            "round": round_no + 1,
            "severity": severity,
            "issues": status_data.get("issues", []) if isinstance(status_data, dict) else [],
            "tokens_input": model_llm.total_input_tokens + verify_llm.total_input_tokens,
            "tokens_output": model_llm.total_output_tokens + verify_llm.total_output_tokens,
        })
        artifacts = {
            **model_artifacts,
            **verify_artifacts,
            "revision_history.json": json.dumps(history, ensure_ascii=False, indent=2),
        }
        meta = MetaData(
            stage=StageID.MODEL.value,
            version=0,
            model_used=f"{model_llm.model}+{verify_llm.model}",
            tokens_input=model_llm.total_input_tokens + verify_llm.total_input_tokens,
            tokens_output=model_llm.total_output_tokens + verify_llm.total_output_tokens,
        )
        vdir = mgr.save(StageID.MODEL, artifacts, meta)

        if severity != "block" or round_no == max_revisions:
            break
        print_info(f"Verifier 判定 block，正在进行第 {round_no + 1}/{max_revisions} 轮定向修订...")
        revised = modeler.revise_model(
            model_artifacts,
            verify_artifacts.get("verify_status.json", "{}"),
            verify_artifacts.get("verify_report.md", ""),
        )
        model_artifacts = {**model_artifacts, **revised}

    return vdir, verify_artifacts


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
    latest_version = mgr.get_latest_version(StageID.MODEL)
    latest_artifacts = mgr.load_artifacts(StageID.MODEL, latest_version)
    code_feedback = _code_feedback(mgr)
    if latest_version and _verify_severity(latest_artifacts) == "block":
        print_info(f"检测到 model v{latest_version} 的 Verifier block，先进行定向修订...")
        model_artifacts = {
            **latest_artifacts,
            **modeler.revise_model(
                latest_artifacts,
                latest_artifacts.get("verify_status.json", "{}"),
                latest_artifacts.get("verify_report.md", ""),
            ),
        }
        try:
            prior_status = json.loads(latest_artifacts.get("verify_status.json", "{}"))
        except json.JSONDecodeError:
            prior_status = {}
        initial_history = [{
            "round": 0,
            "source_version": latest_version,
            "severity": "block",
            "issues": prior_status.get("issues", []) if isinstance(prior_status, dict) else [],
        }]
        remaining_revisions = MAX_MODEL_REVISIONS - 1
    elif latest_version and code_feedback:
        print_info(f"检测到 code 的质量门禁失败，基于 model v{latest_version} 定向修订...")
        feedback_status = json.dumps({
            "severity": "block",
            "issues": [{"category": "运行证据", "summary": code_feedback[:1000]}],
        }, ensure_ascii=False)
        model_artifacts = {
            **latest_artifacts,
            **modeler.revise_model(latest_artifacts, feedback_status, code_feedback),
        }
        initial_history = [{
            "round": 0,
            "source_version": latest_version,
            "severity": "block",
            "issues": [{"category": "运行证据", "summary": code_feedback[:1000]}],
        }]
        remaining_revisions = MAX_MODEL_REVISIONS - 1
    else:
        print_info("正在建立数学模型...")
        model_artifacts = modeler.build_model(
            analysis=analysis, methods=methods, approach=approach,
            assumptions=assumptions, data_summary=data_summary,
        )
        initial_history = []
        remaining_revisions = MAX_MODEL_REVISIONS

    vdir, verify_artifacts = _run_verified_versions(
        workspace, mgr, settings, modeler, llm,
        analysis, assumptions, model_artifacts,
        max_revisions=remaining_revisions,
        history=initial_history,
    )
    print_success(f"建模完成（含验证），产出保存到: {vdir}")

    verify_report = verify_artifacts.get("verify_report.md", "")
    if "问题" in verify_report or "修改" in verify_report:
        print_info("Verifier 发现了一些问题，请仔细审查 verify_report.md")


def run_model_branch(workspace: Path, mgr: CheckpointManager) -> None:
    """branch：生成并独立验证与当前激活方案显著不同的备选方案。"""
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
    model_artifacts = modeler.build_alternative_model(
        analysis=analyze_arts.get("analysis.md", ""),
        methods=research_arts.get("methods.md", ""),
        approach=research_arts.get("approach.md", ""),
        assumptions=analyze_arts.get("assumptions.md", ""),
        data_summary=eda_arts.get("data_summary.md", ""),
        existing_model=existing_model,
        existing_version=existing_version,
    )
    vdir, _ = _run_verified_versions(
        workspace,
        mgr,
        settings,
        modeler,
        llm,
        analyze_arts.get("analysis.md", ""),
        analyze_arts.get("assumptions.md", ""),
        model_artifacts,
    )
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
