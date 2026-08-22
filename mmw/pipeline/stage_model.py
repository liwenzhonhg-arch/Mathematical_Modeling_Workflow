"""阶段 4：数学建模 + Verifier 双重验证。"""

from __future__ import annotations

import json
import hashlib
import re
from pathlib import Path

from mmw.agents.modeler import ModelerAgent
from mmw.agents.verifier import VerifierAgent
from mmw.config import get_settings
from mmw.llm import LLMClient
from mmw.models import MetaData, StageID
from mmw.project import ProjectPaths
from mmw.utils.checkpoint import CheckpointManager
from mmw.utils.display import print_error, print_info, print_success
from mmw.utils.method_contract import build_model_contract
from mmw.utils.model_handoff import build_model_handoff, model_structure_issues

MAX_MODEL_REVISIONS = 2


def _code_feedback(mgr: CheckpointManager) -> str:
    """把最新 code 的机器门禁失败证据交回 model，避免跨阶段失忆。"""
    latest_model = mgr.get_latest_version(StageID.MODEL)
    active_model = mgr.get_active_version(StageID.MODEL)
    version = 0
    for target_model in dict.fromkeys((latest_model, active_model)):
        for candidate in range(mgr.get_latest_version(StageID.CODE), 0, -1):
            meta = mgr.load_meta(StageID.CODE, candidate)
            if (
                meta is not None
                and meta.upstream_versions.get(StageID.MODEL.value) == target_model
            ):
                version = candidate
                break
        if version:
            break
    if not version:
        return ""
    from mmw.pipeline.state_machine import PipelineStateMachine

    error = PipelineStateMachine(mgr).quality_error(StageID.CODE, version)
    if not error:
        return ""
    artifacts = mgr.load_artifacts(StageID.CODE, version)
    run_log = artifacts.get("run_log.txt", "")
    attempt_history = artifacts.get("attempt_history.json", "")
    try:
        contract = json.loads(artifacts.get("method_contract.json", ""))
    except json.JSONDecodeError:
        contract = {}
    contract_summary = {}
    if isinstance(contract, dict):
        formulation = contract.get("formulation")
        implementation = contract.get("implementation")
        if isinstance(formulation, dict):
            contract_summary["model_family"] = formulation.get("model_family", "")
        if isinstance(implementation, dict):
            contract_summary["deviations"] = implementation.get("deviations", [])
    runtime_raw = artifacts.get("method_runtime.json", "")
    if not runtime_raw and artifacts.get("results_preview.json"):
        paths = ProjectPaths(mgr.workspace)
        results_path = paths.result_data / "results.json"
        runtime_path = paths.result_data / "method_runtime.json"
        if results_path.is_file() and runtime_path.is_file():
            try:
                if (
                    results_path.read_text(encoding="utf-8")
                    == artifacts["results_preview.json"]
                ):
                    runtime_raw = runtime_path.read_text(encoding="utf-8")
            except OSError:
                runtime_raw = ""
    try:
        runtime = json.loads(runtime_raw)
    except json.JSONDecodeError:
        runtime = {}
    runtime_summary = {}
    if isinstance(runtime, dict):
        for key in (
            "constraints_not_fully_implemented",
            "strict_continuous_slope_certificate",
            "formal_optimization_call_count",
            "formal_optimization_call_limit",
            "limitations",
        ):
            if key in runtime:
                runtime_summary[key] = runtime[key]
    return (
        f"{error}\n\ncode v{version} 最终运行证据：\n{run_log[-8000:]}"
        f"\n\n全部候选执行摘要：\n{attempt_history[-12000:]}"
        f"\n\ncode 方法契约摘要：\n"
        f"{json.dumps(contract_summary, ensure_ascii=False)[-6000:]}"
        f"\n\ncode 运行契约摘要：\n"
        f"{json.dumps(runtime_summary, ensure_ascii=False)[-4000:]}"
    )


def _review_feedback(mgr: CheckpointManager) -> str:
    """只把 Reviewer 明确归因到 model 的失败反馈给 Modeler。"""
    version = mgr.get_latest_version(StageID.REVIEW)
    if not version:
        return ""
    meta = mgr.load_meta(StageID.REVIEW, version)
    if meta is None or meta.upstream_versions.get(StageID.MODEL.value) != mgr.get_latest_version(StageID.MODEL):
        return ""
    artifacts = mgr.load_artifacts(StageID.REVIEW, version)
    from mmw.agents.reviewer import get_review_rework_stage

    if get_review_rework_stage(artifacts) != StageID.MODEL.value:
        return ""
    return (
        f"review v{version} 要求回退 model：\n"
        f"{artifacts.get('review.md', '')[-10000:]}\n"
        f"{artifacts.get('checklist.json', '')}"
    )


def _verify_model(
    workspace: Path,
    settings,
    problem_text: str,
    assumptions: str,
    model_artifacts: dict[str, str],
    research_evidence: str = "",
) -> tuple[dict[str, str], LLMClient]:
    verify_config = settings.get_llm_config("verifier")
    verify_llm = LLMClient(verify_config, log_dir=ProjectPaths(workspace).logs)
    verifier = VerifierAgent(verify_llm)
    artifacts = verifier.verify(
        problem_summary=problem_text[:16000],
        assumptions=assumptions,
        model=model_artifacts.get("model.md", ""),
        equations=model_artifacts.get("equations.json", ""),
        research_evidence=research_evidence,
    )
    return artifacts, verify_llm


def _model_evidence_issues(
    model_artifacts: dict[str, str],
    research_evidence: str,
    research_methods: str = "",
    downstream_evidence: str = "",
) -> list[str]:
    """确定性拒绝模型阶段的伪检索和伪运行结论。"""
    model = model_artifacts.get("model.md", "")
    substantive = model.split("Verifier 修复核对表", 1)[0]
    issues: list[str] = []
    claims_executed_fit = any(
        (
            re.search(r"(?:标定|辨识|拟合)(?:后)?(?:得到|获得)", line)
            and re.search(r"(?:RMSE|NRMSE|R\^?2|R²|K_)", line, re.IGNORECASE)
            and re.search(r"(?:=|≈|<|>)\s*\d", line)
        )
        or (
            re.search(r"(?:RMSE|R\^?2|R²)\s*(?:=|≈|<)\s*\d", line, re.IGNORECASE)
            and re.search(r"(?:模型)?(?:通过验证|吻合良好)", line)
            and "若" not in line
        )
        for line in substantive.splitlines()
    )
    if claims_executed_fit:
        issues.append("model 阶段尚未执行代码，却声称已得到拟合参数或误差指标")
    try:
        evidence = json.loads(research_evidence) if research_evidence else {}
    except json.JSONDecodeError:
        evidence = {}
    unresolved = evidence.get("unresolved_searches", []) if isinstance(evidence, dict) else []
    if (
        unresolved
        and re.search(
            r"(?:查阅|文献(?:显示|表明|给出)|研究(?:显示|表明))"
            r"[^\n]{0,40}(?:典型|范围|参数)",
            substantive,
        )
    ):
        issues.append("research 仍将该资料列为 unresolved，模型却把它写成了已取得证据")
    if (
        unresolved
        and re.search(
            r"(?:典型对流系数|FR-?4[^\n]{0,30}导热系数)"
            r"[^\n]{0,50}(?:\d+(?:\.\d+)?)",
            substantive,
            re.IGNORECASE,
        )
    ):
        issues.append("模型填写了 research 阶段尚未取得的材料或换热参数数值")
    unsupported_bi_selection = any(
        "若" not in line
        and re.search(
            r"Bi[^\n]{0,100}<\s*0\.1[^\n]{0,100}(?:采用|选择|满足)集总",
            line,
            re.IGNORECASE,
        )
        for line in substantive.splitlines()
    )
    if (
        unresolved
        and any(any(token in str(item) for token in ("热物理", "换热系数", "导热系数")) for item in unresolved)
        and unsupported_bi_selection
    ):
        issues.append("Bi 依赖的材料/换热证据仍未解决，不能据此选择集总模型")
    research_requires_pde = (
        "主要方法" in research_methods
        and "一维非稳态导热" in research_methods
    )
    pde_retired = bool(
        re.search(
            r"(?:PDE|一维[^\n]{0,20}导热)[^\n]{0,80}(?:否决|淘汰|拒绝|不可辨识)"
            r"|(?:否决|淘汰|拒绝|不可辨识)[^\n]{0,80}(?:PDE|一维[^\n]{0,20}导热)",
            downstream_evidence,
            re.IGNORECASE,
        )
    )
    equations = model_artifacts.get("equations.json", "")
    active_pde = any(
        token in equations
        for token in ("simulate_moving_slab", r"\partial T", '"PDE"', "PDE-Robin")
    )
    if pde_retired and active_pde:
        issues.append("下游运行证据已淘汰 PDE，现役结构化合同不得重新引入")
    elif research_requires_pde and not pde_retired:
        has_pde_blueprint = all(
            token in substantive
            for token in ("Robin", "x(t)", r"\partial T")
        )
        treats_pde_as_fallback = bool(
            re.search(r"一维非稳态导热[^\n]{0,40}(?:升级|备用|触发条件)", substantive)
            or re.search(r"一维(?:瞬态|非稳态)?导热[^\n]{0,40}备用", substantive)
            or re.search(r"PDE[^\n]{0,40}备用", substantive, re.IGNORECASE)
            or re.search(r"(?:否则|失败时|未通过)[^\n]{0,60}(?:一维|PDE)", substantive)
        )
        if not has_pde_blueprint:
            issues.append(
                "research 已把一维非稳态导热列为主要结构，model 却未给出"
                "移动坐标、PDE 与 Robin 边界的可实现蓝图"
            )
        elif treats_pde_as_fallback:
            issues.append(
                "research 已把一维非稳态导热列为主要结构，model 却仍把它降级为"
                "集总模型失败后的备用路径"
            )
    return issues


def _apply_evidence_gate(
    verify_artifacts: dict[str, str],
    issues: list[str],
) -> dict[str, str]:
    if not issues:
        return verify_artifacts
    try:
        status = json.loads(verify_artifacts.get("verify_status.json", "{}"))
    except json.JSONDecodeError:
        status = {}
    existing = status.get("issues", []) if isinstance(status, dict) else []
    status = {
        "severity": "block",
        "issues": [
            *existing,
            *({"category": "证据", "summary": issue} for issue in issues),
        ],
    }
    report = verify_artifacts.get("verify_report.md", "")
    prefix = "# 确定性证据门禁\n\n" + "\n".join(f"- [问题] {issue}" for issue in issues)
    return {
        **verify_artifacts,
        "verify_status.json": json.dumps(status, ensure_ascii=False, indent=2),
        "verify_report.md": f"{prefix}\n\n{report}",
    }


def _verify_severity(artifacts: dict[str, str]) -> str:
    try:
        status = json.loads(artifacts.get("verify_status.json", ""))
    except json.JSONDecodeError:
        return "invalid"
    severity = status.get("severity") if isinstance(status, dict) else None
    return severity if severity in {"pass", "warning", "block"} else "invalid"


def _revision_integrity_issues(
    previous: dict[str, str],
    revised: dict[str, str],
) -> list[str]:
    """Reject lossy model revisions before they replace the complete source."""
    required = {"model.md", "equations.json", "params.json"}
    missing = sorted(required - revised.keys())
    issues = [f"定向修订缺少完整 artifact：{', '.join(missing)}"] if missing else []
    model = revised.get("model.md", "")
    if re.search(
        r"(?:保持|沿用|复用|其余)[^。\n]{0,40}(?:原|不变)|原(?:式|模型|若干项)",
        model,
    ):
        issues.append("定向修订使用了引用旧版的省略语，model.md 必须自包含")
    heading_pattern = r"(?im)^##\s+(?:子问题\s*)?q?(\d+)\b"
    previous_ids = set(re.findall(heading_pattern, previous.get("model.md", "")))
    revised_ids = set(re.findall(heading_pattern, model))
    missing_ids = sorted(previous_ids - revised_ids, key=int)
    if missing_ids:
        issues.append(
            "定向修订遗漏原模型子问题："
            + "、".join(f"子问题 {item}" for item in missing_ids)
        )
    structure_issues = model_structure_issues(
        model,
        revised.get("equations.json", "{}"),
    )
    issues.extend(
        issue for issue in structure_issues
        if "历史版本" in issue or "章节重复" in issue
    )
    return issues


def _prepare_model_artifacts(
    artifacts: dict[str, str],
    assumptions_contract: str,
    *,
    enforce_structure: bool,
) -> tuple[dict[str, str], list[str]]:
    """生成可读交接件，并给新合同建立确定性结构门禁。"""
    prepared = {
        name: content
        for name, content in artifacts.items()
        if name not in {"model_handoff.md", "model_quality_report.json"}
    }
    equations = prepared.get("equations.json", "")
    prepared["model_handoff.md"] = build_model_handoff(
        equations,
        prepared.get("params.json", "{}"),
        assumptions_contract,
    )
    issues = model_structure_issues(
        prepared.get("model.md", ""),
        equations,
        assumptions_contract,
    )
    try:
        equations_data = json.loads(equations)
    except (json.JSONDecodeError, TypeError):
        equations_data = None
    if isinstance(equations_data, dict) and equations_data.get("schema_version") != 2:
        issues.append("equations.json 仍为旧合同，缺少 schema_version=2 的结构化逻辑链")
    blocking = issues if enforce_structure else [
        issue for issue in issues
        if "历史版本" in issue or "章节重复" in issue
    ]
    prepared["model_quality_report.json"] = json.dumps({
        "schema_version": 1,
        "status": "fail" if blocking else ("warning" if issues else "pass"),
        "enforced": enforce_structure,
        "issues": issues,
    }, ensure_ascii=False, indent=2)
    return prepared, blocking


def _exhausted_block_revisions(artifacts: dict[str, str]) -> bool:
    """连续定向修订仍 block 时从头重建，避免在错误结构上无限打补丁。"""
    try:
        history = json.loads(artifacts.get("revision_history.json", "[]"))
    except json.JSONDecodeError:
        return False
    return (
        isinstance(history, list)
        and len(history) >= MAX_MODEL_REVISIONS + 1
        and all(
            isinstance(item, dict) and item.get("severity") == "block"
            for item in history[-(MAX_MODEL_REVISIONS + 1):]
        )
    )


def _run_verified_versions(
    workspace: Path,
    mgr: CheckpointManager,
    settings,
    modeler: ModelerAgent,
    model_llm: LLMClient,
    analysis: str,
    assumptions: str,
    model_artifacts: dict[str, str],
    problem_text: str = "",
    research_evidence: str = "",
    research_methods: str = "",
    downstream_evidence: str = "",
    max_revisions: int = MAX_MODEL_REVISIONS,
    history: list[dict] | None = None,
    assumptions_contract: str = "{}",
) -> tuple[Path, dict[str, str]]:
    history = list(history or [])
    verify_artifacts: dict[str, str] = {}
    vdir = workspace

    for round_no in range(max_revisions + 1):
        candidate_artifacts = {
            name: content
            for name, content in model_artifacts.items()
            if name not in {
                "verify_report.md",
                "verify_status.json",
                "revision_history.json",
                "model_handoff.md",
                "model_quality_report.json",
            }
        }
        enforce_structure = bool(
            assumptions_contract.strip()
            and assumptions_contract.strip() != "{}"
        )
        candidate_artifacts, structure_issues = _prepare_model_artifacts(
            candidate_artifacts,
            assumptions_contract,
            enforce_structure=enforce_structure,
        )
        candidate_artifacts["method_contract.json"] = json.dumps(
            build_model_contract(candidate_artifacts.get("equations.json", "")),
            ensure_ascii=False,
            indent=2,
        )
        contract = json.loads(candidate_artifacts["method_contract.json"])
        contract.setdefault("bindings", {})["model_artifacts_sha256"] = {
            name: hashlib.sha256(candidate_artifacts.get(name, "").encode("utf-8")).hexdigest()
            for name in ("model.md", "equations.json", "params.json")
        }
        candidate_artifacts["method_contract.json"] = json.dumps(
            contract, ensure_ascii=False, indent=2,
        )
        evidence_issues = _model_evidence_issues(
            candidate_artifacts,
            research_evidence,
            research_methods,
            downstream_evidence,
        )
        if evidence_issues:
            print_info(f"模型触发确定性证据门禁（第 {round_no + 1} 次），跳过 Verifier 调用")
            verify_artifacts = _apply_evidence_gate({}, evidence_issues)
            verify_llm = None
            review_source = "deterministic-gate"
        else:
            print_info(f"正在验证模型（第 {round_no + 1} 次）...")
            verify_artifacts, verify_llm = _verify_model(
                workspace,
                settings,
                problem_text,
                assumptions,
                candidate_artifacts,
                research_evidence,
            )
            review_source = "llm-verifier"
        verify_artifacts = _apply_evidence_gate(verify_artifacts, structure_issues)
        severity = _verify_severity(verify_artifacts)
        try:
            status_data = json.loads(verify_artifacts.get("verify_status.json", "{}"))
        except json.JSONDecodeError:
            status_data = {}
        verifier_input = verify_llm.total_input_tokens if verify_llm else 0
        verifier_output = verify_llm.total_output_tokens if verify_llm else 0
        history.append({
            "round": round_no + 1,
            "severity": severity,
            "issues": status_data.get("issues", []) if isinstance(status_data, dict) else [],
            "review_source": review_source,
            "tokens_input": model_llm.total_input_tokens + verifier_input,
            "tokens_output": model_llm.total_output_tokens + verifier_output,
        })
        artifacts = {
            **candidate_artifacts,
            **verify_artifacts,
            "revision_history.json": json.dumps(history, ensure_ascii=False, indent=2),
        }
        model_used = model_llm.model
        if verify_llm:
            model_used += f"+{verify_llm.model}"
        meta = MetaData(
            stage=StageID.MODEL.value,
            version=0,
            model_used=model_used,
            tokens_input=model_llm.total_input_tokens + verifier_input,
            tokens_output=model_llm.total_output_tokens + verifier_output,
        )
        vdir = mgr.save(StageID.MODEL, artifacts, meta)

        if severity != "block" or round_no == max_revisions:
            break
        print_info(f"Verifier 判定 block，正在进行第 {round_no + 1}/{max_revisions} 轮定向修订...")
        modeler.reset_context()
        revised = modeler.revise_model(
            candidate_artifacts,
            verify_artifacts.get("verify_status.json", "{}"),
            verify_artifacts.get("verify_report.md", ""),
            problem_text=problem_text,
            research_evidence=research_evidence,
        )
        integrity_issues = _revision_integrity_issues(candidate_artifacts, revised)
        if integrity_issues:
            print_info("定向修订不完整，保留原模型并补充一次自包含修订...")
            try:
                integrity_status = json.loads(
                    verify_artifacts.get("verify_status.json", "{}")
                )
            except json.JSONDecodeError:
                integrity_status = {}
            if not isinstance(integrity_status, dict):
                integrity_status = {}
            integrity_status["severity"] = "block"
            integrity_status["issues"] = [
                *(integrity_status.get("issues") or []),
                *(
                    {"category": "完整性", "summary": issue}
                    for issue in integrity_issues
                ),
            ]
            modeler.reset_context()
            revised = modeler.revise_model(
                candidate_artifacts,
                json.dumps(integrity_status, ensure_ascii=False),
                verify_artifacts.get("verify_report.md", "")
                + "\n\n定向修订完整性门禁：\n- "
                + "\n- ".join(integrity_issues),
                problem_text=problem_text,
                research_evidence=research_evidence,
            )
            retry_issues = _revision_integrity_issues(candidate_artifacts, revised)
            if retry_issues:
                raise RuntimeError("；".join(retry_issues))
        model_artifacts = {**candidate_artifacts, **revised}

    return vdir, verify_artifacts


def run_model(workspace: Path, mgr: CheckpointManager) -> bool:
    analyze_arts = mgr.load_artifacts(StageID.ANALYZE)
    research_arts = mgr.load_artifacts(StageID.RESEARCH)
    eda_arts = mgr.load_artifacts(StageID.EDA)

    if not analyze_arts or not research_arts:
        print_error("请先完成并审批前置阶段")
        return False

    analysis = analyze_arts.get("analysis.md", "")
    assumptions = analyze_arts.get("assumptions.md", "")
    assumptions_contract = analyze_arts.get("assumptions.json", "{}")
    methods = research_arts.get("methods.md", "")
    approach = research_arts.get("approach.md", "")
    research_evidence = research_arts.get("research_evidence.json", "")
    method_candidates = research_arts.get("method_candidates.json", "")
    data_summary = eda_arts.get("data_summary.md", "")
    problem_path = ProjectPaths(workspace).problem
    problem_text = problem_path.read_text(encoding="utf-8") if problem_path.is_file() else analysis

    settings = get_settings()

    # 建模阶段
    llm_config = settings.get_llm_config("modeler")
    if getattr(llm_config, "backend", "openai") == "openai" and not llm_config.api_key:
        print_error("未配置 LLM API Key")
        return False
    llm = LLMClient(llm_config, log_dir=ProjectPaths(workspace).logs)

    modeler = ModelerAgent(llm)
    latest_version = mgr.get_latest_version(StageID.MODEL)
    latest_artifacts = mgr.load_artifacts(StageID.MODEL, latest_version)
    latest_severity = _verify_severity(latest_artifacts)
    code_feedback = _code_feedback(mgr)
    human_feedback = mgr.latest_rework_reason(StageID.MODEL, latest_version)
    downstream_feedback = (
        human_feedback
        or _review_feedback(mgr)
        or code_feedback
    )
    downstream_evidence = "\n".join(
        dict.fromkeys(item for item in (downstream_feedback, code_feedback) if item)
    )
    if latest_version and downstream_feedback and latest_severity != "block":
        print_info(f"检测到下游质量反馈，基于 model v{latest_version} 定向修订...")
        feedback_status = json.dumps({
            "severity": "block",
            "issues": [{"category": "下游反馈", "summary": downstream_feedback[:1000]}],
        }, ensure_ascii=False)
        model_artifacts = {
            **latest_artifacts,
            **modeler.revise_model(
                latest_artifacts,
                feedback_status,
                downstream_feedback,
                problem_text=problem_text,
                research_evidence=research_evidence,
            ),
        }
        initial_history = [{
            "round": 0,
            "source_version": latest_version,
            "severity": "block",
            "issues": [{"category": "下游反馈", "summary": downstream_feedback[:1000]}],
        }]
        remaining_revisions = MAX_MODEL_REVISIONS - 1
    elif (
        latest_version
        and latest_severity == "block"
        and human_feedback
        and _exhausted_block_revisions(latest_artifacts)
    ):
        print_info(
            f"检测到 model v{latest_version} 的新人工重做理由，"
            "重置一次定向修订预算..."
        )
        combined_report = (
            latest_artifacts.get("verify_report.md", "")
            + "\n\n新人工重做要求：\n"
            + human_feedback
        )
        model_artifacts = {
            **latest_artifacts,
            **modeler.revise_model(
                latest_artifacts,
                latest_artifacts.get("verify_status.json", "{}"),
                combined_report,
                problem_text=problem_text,
                research_evidence=research_evidence,
            ),
        }
        try:
            prior_status = json.loads(latest_artifacts.get("verify_status.json", "{}"))
        except json.JSONDecodeError:
            prior_status = {}
        initial_history = [{
            "round": 0,
            "source_version": latest_version,
            "severity": latest_severity,
            "issues": prior_status.get("issues", []) if isinstance(prior_status, dict) else [],
        }]
        remaining_revisions = MAX_MODEL_REVISIONS - 1
    elif latest_version and (
        latest_severity == "block"
        or (latest_severity == "warning" and not mgr.is_approved(StageID.MODEL, latest_version))
    ) and not _exhausted_block_revisions(latest_artifacts):
        print_info(
            f"检测到未通过最终确认的 model v{latest_version}（Verifier={latest_severity}），"
            "先进行定向修订..."
        )
        model_artifacts = {
            **latest_artifacts,
            **modeler.revise_model(
                latest_artifacts,
                latest_artifacts.get("verify_status.json", "{}"),
                latest_artifacts.get("verify_report.md", ""),
                problem_text=problem_text,
                research_evidence=research_evidence,
            ),
        }
        try:
            prior_status = json.loads(latest_artifacts.get("verify_status.json", "{}"))
        except json.JSONDecodeError:
            prior_status = {}
        initial_history = [{
            "round": 0,
            "source_version": latest_version,
            "severity": latest_severity,
            "issues": prior_status.get("issues", []) if isinstance(prior_status, dict) else [],
        }]
        remaining_revisions = MAX_MODEL_REVISIONS - 1
    else:
        print_info("正在建立数学模型...")
        model_artifacts = modeler.build_model(
            analysis=analysis, methods=methods, approach=approach,
            assumptions=assumptions, data_summary=data_summary,
            problem_text=problem_text,
            research_evidence=research_evidence,
            method_candidates=method_candidates,
            assumptions_contract=assumptions_contract,
        )
        initial_history = []
        remaining_revisions = MAX_MODEL_REVISIONS

    vdir, verify_artifacts = _run_verified_versions(
        workspace, mgr, settings, modeler, llm,
        analysis, assumptions, model_artifacts,
        problem_text=problem_text,
        research_evidence=research_evidence,
        research_methods=methods,
        downstream_evidence=downstream_evidence,
        max_revisions=remaining_revisions,
        history=initial_history,
        assumptions_contract=assumptions_contract,
    )
    severity = _verify_severity(verify_artifacts)
    if severity not in {"pass", "warning"}:
        print_error(f"建模产物已保存到 {vdir}，但 Verifier={severity}，本阶段未通过")
        return False
    print_success(f"建模完成（含验证），产出保存到: {vdir}")

    verify_report = verify_artifacts.get("verify_report.md", "")
    if "问题" in verify_report or "修改" in verify_report:
        print_info("Verifier 发现了一些问题，请仔细审查 verify_report.md")
    return True


def run_model_branch(workspace: Path, mgr: CheckpointManager) -> bool:
    """branch：生成并独立验证与当前激活方案显著不同的备选方案。"""
    analyze_arts = mgr.load_artifacts(StageID.ANALYZE)
    research_arts = mgr.load_artifacts(StageID.RESEARCH)
    eda_arts = mgr.load_artifacts(StageID.EDA)

    existing_version = mgr.get_active_version(StageID.MODEL)
    if existing_version == 0:
        print_error("model 阶段尚无版本，请先运行 mmw run model")
        return False
    existing_model = mgr.load_artifacts(StageID.MODEL, existing_version).get("model.md", "")
    if not existing_model:
        print_error(f"model v{existing_version} 中未找到 model.md")
        return False

    settings = get_settings()
    llm_config = settings.get_llm_config("modeler")
    if getattr(llm_config, "backend", "openai") == "openai" and not llm_config.api_key:
        print_error("未配置 LLM API Key")
        return False
    llm = LLMClient(llm_config, log_dir=ProjectPaths(workspace).logs)

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
        assumptions_contract=analyze_arts.get("assumptions.json", "{}"),
    )
    vdir, verify_artifacts = _run_verified_versions(
        workspace,
        mgr,
        settings,
        modeler,
        llm,
        analyze_arts.get("analysis.md", ""),
        analyze_arts.get("assumptions.md", ""),
        model_artifacts,
        assumptions_contract=analyze_arts.get("assumptions.json", "{}"),
    )
    new_version = mgr.get_latest_version(StageID.MODEL)
    severity = _verify_severity(verify_artifacts)
    if severity not in {"pass", "warning"}:
        print_error(
            f"备选方案已保存为 model v{new_version}，但 Verifier={severity}，"
            "不能进入方案对比或审批"
        )
        return False
    print_success(f"备选方案已生成: {vdir}")
    print_info(f"对比两个方案: mmw compare model {existing_version} {new_version}")
    print_info(f"选定方案后审批激活: mmw approve model --version <N>")
    return True


def run_compare_model(workspace: Path, mgr: CheckpointManager, v1: int, v2: int) -> bool:
    """用 LLM 对比 model 阶段的两个版本，报告写入 output/（不进版本树）。"""
    from mmw.agents.base import BaseAgent

    if v1 == v2:
        print_error("两个版本号相同，无需对比")
        return False
    arts1 = mgr.load_artifacts(StageID.MODEL, v1)
    arts2 = mgr.load_artifacts(StageID.MODEL, v2)
    if not arts1:
        print_error(f"model v{v1} 不存在")
        return False
    if not arts2:
        print_error(f"model v{v2} 不存在")
        return False
    out_path = ProjectPaths(workspace).output / f"compare_model_v{v1}_v{v2}.md"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    severities = {v1: _verify_severity(arts1), v2: _verify_severity(arts2)}
    ineligible = [
        f"v{version}={severity}"
        for version, severity in severities.items()
        if severity not in {"pass", "warning"}
    ]
    if ineligible:
        report = (
            "# 建模方案对比中止\n\n"
            "以下版本未通过 Verifier，不能作为候选主方案："
            + "、".join(ineligible)
            + "。\n\n请先修订模型并取得 pass 或 warning，再运行 compare。\n"
        )
        out_path.write_text(report, encoding="utf-8")
        print_error(report.splitlines()[2])
        return False

    settings = get_settings()
    llm_config = settings.get_llm_config("verifier")
    if getattr(llm_config, "backend", "openai") == "openai" and not llm_config.api_key:
        print_error("未配置 LLM API Key")
        return False
    llm = LLMClient(llm_config, log_dir=ProjectPaths(workspace).logs)

    agent = BaseAgent(llm)
    agent.role = "compare"
    prompt = agent.render_prompt(
        "compare_model.j2",
        v1=v1, v2=v2,
        model_a=arts1.get("model.md", ""),
        model_b=arts2.get("model.md", ""),
        verify_a=arts1.get("verify_report.md", ""),
        verify_b=arts2.get("verify_report.md", ""),
    )
    print_info(f"正在对比 model v{v1} 与 v{v2}...")
    report = agent.run_stream(prompt)

    out_path.write_text(report, encoding="utf-8")
    print_success(f"对比报告已生成: {out_path}")
    print_info("选定方案后审批激活: mmw approve model --version <N>")
    return True
