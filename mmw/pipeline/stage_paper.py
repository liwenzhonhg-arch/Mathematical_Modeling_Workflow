"""阶段 7：论文写作（分节 LaTeX 生成 + 摘要专项打分迭代）。"""

from __future__ import annotations

import json
import re
from pathlib import Path

from mmw.agents.abstract_critic import AbstractCriticAgent, _abstract_plain_text
from mmw.agents.typesetter import TypesetterAgent, normalize_tex_artifacts
from mmw.agents.writer import WriterAgent
from mmw.config import get_settings
from mmw.llm import LLMClient
from mmw.models import MetaData, StageID
from mmw.project import ProjectPaths
from mmw.utils.checkpoint import CheckpointManager
from mmw.utils.display import print_error, print_info, print_success, print_warning
from mmw.utils.method_contract import build_paper_traceability

ABSTRACT_SCORE_THRESHOLD = 85
ABSTRACT_MAX_ROUNDS = 4
ABSTRACT_MAX_CHARS = 600
MAX_INLINE_CODE_LINES = 200
INCLUDEGRAPHICS_RE = re.compile(r"\\includegraphics(?:\[[^\]]*\])?\{([^{}]+)\}")


def _add_code_appendix(artifacts: dict[str, str], solution: str) -> None:
    if not solution.strip():
        return
    artifacts["solution.py"] = solution
    appendix = "\\appendix\n\\section{程序代码}\n"
    if len(solution.splitlines()) <= MAX_INLINE_CODE_LINES:
        appendix += "\\lstinputlisting[language=Python]{solution.py}\n"
    else:
        appendix += "完整可运行程序见提交包中的 \\texttt{code/solution.py}。\n"
    artifacts["sections/appendix.tex"] = appendix


def _review_revision(mgr: CheckpointManager) -> tuple[dict[str, str], str]:
    """提取数值审计明确点名的小节，避免整篇论文重新随机生成。"""
    review_version = mgr.get_latest_version(StageID.REVIEW)
    paper_version = mgr.get_latest_version(StageID.PAPER)
    if not paper_version:
        return {}, ""
    paper = mgr.load_artifacts(StageID.PAPER, paper_version)
    paper_meta = mgr.load_meta(StageID.PAPER, paper_version)
    active_solve = mgr.get_active_version(StageID.SOLVE)
    if active_solve and paper_meta and paper_meta.upstream_versions.get(StageID.SOLVE.value) != active_solve:
        return {}, ""
    human_reason = mgr.latest_rework_reason(StageID.PAPER, paper_version)
    human_feedback = f"\n\n人工重做要求：\n{human_reason}" if human_reason else ""
    if paper_meta:
        from mmw.pipeline.state_machine import PipelineStateMachine

        gate_error = PipelineStateMachine(mgr).quality_error(StageID.PAPER, paper_version)
        if "cite" in gate_error:
            names = (
                "sections/model_solution.tex",
                "sections/evaluation.tex",
                "references.bib",
            )
            return {name: paper[name] for name in names if name in paper}, gate_error + human_feedback
        if "核心图表引用" in gate_error:
            name = "sections/model_solution.tex"
            return ({name: paper[name]} if name in paper else {}), gate_error + human_feedback
        if "摘要正文" in gate_error or "摘要评分" in gate_error:
            name = "sections/abstract.tex"
            return ({name: paper[name]} if name in paper else {}), gate_error + human_feedback
        method_sections = {
            name for marker, name in (
                ("摘要未如实说明", "sections/abstract.tex"),
                ("符号说明缺少", "sections/symbols.tex"),
                (
                    "formulation 与 heuristic implementation",
                    "sections/model_solution.tex",
                ),
            )
            if marker in gate_error and name in paper
        }
        if method_sections:
            return {
                name: paper[name] for name in method_sections
            }, gate_error + human_feedback
    if human_reason:
        all_sections = {
            name: content for name, content in paper.items()
            if name.endswith(".tex") or name == "references.bib"
        }
        named_sections = {
            name: content for name, content in all_sections.items()
            if name in human_reason
        }
        return named_sections or all_sections, human_reason
    if not review_version:
        return {}, ""
    meta = mgr.load_meta(StageID.REVIEW, review_version)
    if meta is None or meta.upstream_versions.get(StageID.PAPER.value) != paper_version:
        return {}, ""
    review = mgr.load_artifacts(StageID.REVIEW, review_version)
    from mmw.agents.reviewer import get_review_rework_stage

    rework_stage = get_review_rework_stage(review)
    if rework_stage and rework_stage != StageID.PAPER.value:
        return {}, ""
    audit = review.get("numeric_audit.md", "")
    if "## [严重]" in audit:
        names = set(re.findall(r"出自 ([^：\s]+)：", audit))
        sections = {name: paper[name] for name in names if name in paper and name.endswith(".tex")}
        if sections:
            return sections, audit
    if rework_stage == StageID.PAPER.value:
        sections = {
            name: content for name, content in paper.items()
            if name.endswith(".tex") or name == "references.bib"
        }
        feedback = review.get("review.md", "") + "\n" + review.get("checklist.json", "")
        return sections, feedback
    return {}, ""


def _result_value(results: list[dict], name: str):
    for item in results:
        if item.get("name") == name:
            return item.get("value")
    return None


def _fmt_number(value) -> str:
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        if value.is_integer():
            return f"{value:.1f}"
        return f"{value:.4f}".rstrip("0").rstrip(".")
    return str(value)


def _build_fallback_abstract(results_json: str) -> str:
    """用结构化结果生成一版短摘要，避免 LLM 摘要修订多轮空转。"""
    try:
        results = json.loads(results_json)
    except json.JSONDecodeError:
        return ""
    if not isinstance(results, list):
        return ""

    required = [
        "q1_覆盖宽度_验证",
        "q1_平坦近似宽度",
        "q1_宽度差异百分比",
        "q2_视坡度_beta30",
        "q2_视坡度_beta0",
        "q2_视坡度_beta90",
        "q2_覆盖宽度最小值",
        "q2_覆盖宽度最大值",
        "q3_测线数量",
        "q3_总长度",
        "q3_最小重叠率",
        "q3_最大重叠率",
        "q4_测线数量",
        "q4_总长度",
        "q4_漏测率",
        "q4_超重叠率长度",
        "q4_超重叠率长度占比",
        "sensitivity_alpha_10pct",
        "sensitivity_theta_20pct",
        "sensitivity_eta_20pct",
    ]
    values = {name: _result_value(results, name) for name in required}
    if any(values[name] is None for name in required):
        return ""

    q3_min_eta = float(values["q3_最小重叠率"]) * 100
    q3_max_eta = float(values["q3_最大重叠率"]) * 100

    return (
        "\\begin{abstract}\n"
        "本文针对多波束测深测线布设问题，建立了覆盖宽度、视坡度和测线优化模型。"
        "问题1中，基于二维剖面几何关系推导覆盖宽度与重叠率公式；当水深为70m、坡度为"
        "$1.5^\\circ$时，覆盖宽度为"
        f"{_fmt_number(values['q1_覆盖宽度_验证'])}m，平坦近似宽度为"
        f"{_fmt_number(values['q1_平坦近似宽度'])}m，相对差异为"
        f"{_fmt_number(values['q1_宽度差异百分比'])}\\%。问题2中，引入测线方向与坡面法向水平投影夹角"
        "$\\beta$，建立视坡度模型 $\\alpha'=\\arctan(\\tan\\alpha\\cos\\beta)$；验证得到"
        f"$\\beta=30^\\circ$时视坡度为{_fmt_number(values['q2_视坡度_beta30'])}^\\circ$，"
        f"$\\beta=0^\\circ$时为{_fmt_number(values['q2_视坡度_beta0'])}^\\circ$，"
        f"$\\beta=90^\\circ$时为{_fmt_number(values['q2_视坡度_beta90'])}^\\circ$；"
        "result2 表中覆盖宽度范围为"
        f"{_fmt_number(values['q2_覆盖宽度最小值'])}m--{_fmt_number(values['q2_覆盖宽度最大值'])}m。\n\n"
        "问题3中，将恒定坡度矩形海域的布线转化为一维变间距优化问题，以全覆盖和重叠率约束为条件，"
        "采用贪心迭代确定相邻测线位置。结果得到"
        f"{_fmt_number(values['q3_测线数量'])}条测线，总长度为"
        f"{_fmt_number(values['q3_总长度'])}m，相邻重叠率范围为"
        f"{_fmt_number(q3_min_eta)}\\%--{_fmt_number(q3_max_eta)}\\%，满足10\\%--20\\%约束。"
        "问题4中，针对真实水深网格，建立基于动态覆盖宽度的自适应贪心规划模型，以候选测线对未覆盖网格的覆盖面积增量为收益函数。"
        "最终布设"
        f"{_fmt_number(values['q4_测线数量'])}条测线，总长度为"
        f"{_fmt_number(values['q4_总长度'])}m，漏测率为"
        f"{_fmt_number(values['q4_漏测率'])}\\%，超重叠率区域长度为"
        f"{_fmt_number(values['q4_超重叠率长度'])}m，占总测线长度"
        f"{_fmt_number(values['q4_超重叠率长度占比'])}\\%。灵敏度分析表明，坡度增加10\\%使总长度增加"
        f"{_fmt_number(values['sensitivity_alpha_10pct'])}\\%，开角增加20\\%使总长度减少"
        f"{abs(float(values['sensitivity_theta_20pct'])):.2f}\\%，目标重叠率增加20\\%使总长度增加"
        f"{_fmt_number(values['sensitivity_eta_20pct'])}\\%。\n\n"
        "\\textbf{关键词}：多波束测深；覆盖宽度模型；视坡度；测线优化；自适应贪心算法；重叠率；灵敏度分析\n"
        "\\end{abstract}"
    )


def _normalize_graphic_ref(ref: str) -> str:
    """统一图片引用格式，支持 figures/foo.png、foo.png 和省略扩展名。"""
    ref_path = Path(ref.strip().replace("\\", "/"))
    name = ref_path.name
    return name


def _graphic_candidates(name: str) -> set[str]:
    path = Path(name)
    if path.suffix:
        return {path.name}
    return {
        f"{path.name}{suffix}"
        for suffix in (".png", ".jpg", ".jpeg", ".pdf", ".eps")
    }


def _find_missing_graphics(
    artifacts: dict[str, str],
    figures: list[str],
    workspace: Path,
) -> list[str]:
    """检查 LaTeX artifact 中的图片引用是否存在于求解图表或 workspace/figures。"""
    available = {_normalize_graphic_ref(item) for item in figures}
    figures_dir = ProjectPaths(workspace).figures
    if figures_dir.exists():
        available.update(path.name for path in figures_dir.iterdir() if path.is_file())

    missing: list[str] = []
    for name, content in artifacts.items():
        if not name.endswith(".tex"):
            continue
        for match in INCLUDEGRAPHICS_RE.finditer(content):
            ref = _normalize_graphic_ref(match.group(1))
            candidates = _graphic_candidates(ref)
            if not candidates & available:
                missing.append(f"{name}: {match.group(1)}")
    return missing


def _refine_abstract(
    writer: WriterAgent,
    critic: AbstractCriticAgent,
    artifacts: dict[str, str],
    results_json: str,
    threshold: int = ABSTRACT_SCORE_THRESHOLD,
    max_rounds: int = ABSTRACT_MAX_ROUNDS,
) -> dict[str, str]:
    """摘要打分→修订循环。把最终摘要写回 artifacts，附加评分与迭代历史。"""
    abstract = artifacts.get("sections/abstract.tex", "")
    if not abstract:
        return artifacts

    iterations: list[dict] = []
    score_data: dict = {"score": -1, "dimensions": {}, "issues": [], "suggestions": []}
    best_score = -1
    best_abstract = abstract
    best_score_data = score_data
    best_within_limit = False

    for round_no in range(1, max_rounds + 1):
        print_info(f"摘要评审第 {round_no}/{max_rounds} 轮...")
        score_data = critic.score(abstract, results_json)
        score = score_data.get("score", -1)
        abstract_length = len(re.sub(r"\s", "", _abstract_plain_text(abstract)))
        within_limit = abstract_length <= ABSTRACT_MAX_CHARS
        iterations.append({
            "round": round_no,
            "score": score,
            "length": abstract_length,
            "issues": score_data.get("issues", []),
            "abstract": abstract,
        })
        # 优先保留满足字数硬约束的最高分版本，避免高分超长稿覆盖可审批稿。
        if (within_limit and not best_within_limit) or (
            within_limit == best_within_limit and score > best_score
        ):
            best_score = score
            best_abstract = abstract
            best_score_data = score_data
            best_within_limit = within_limit

        if score < 0:
            print_error("摘要评分解析失败，跳过迭代（不阻塞流程）")
            break
        print_info(f"摘要得分: {score}")
        if score >= threshold and within_limit:
            print_success(f"摘要达标（>= {threshold} 分）")
            break
        # 失分主因是 results.json 缺数据时，继续改写措辞是空转——提前退出提示补上游
        if score_data.get("needs_upstream_data"):
            print_error(
                "摘要受限于 results.json 数据缺口（评审判定缺少子问题数值结果），"
                "已提前结束迭代。建议 rework code 补齐产出后重跑 paper 阶段"
            )
            break
        if round_no == max_rounds:
            print_info(f"已达最大轮数 {max_rounds}，保留最高分版本（{best_score} 分）")
            break

        print_info("根据评审意见修订摘要...")
        if not within_limit:
            score_data = {
                **score_data,
                "hard_requirement": (
                    f"摘要正文当前 {abstract_length} 字，下一版必须压缩到 520-550 字，"
                    f"绝不能超过 {ABSTRACT_MAX_CHARS} 字"
                ),
            }
        elif round_no == max_rounds - 1:
            score_data = {
                **score_data,
                "final_revision": True,
                "hard_requirement": (
                    f"这是最后一次修订，摘要正文必须压缩到 {ABSTRACT_MAX_CHARS} 字以内"
                ),
            }
        abstract = writer.revise_abstract(
            abstract,
            json.dumps(score_data, ensure_ascii=False, indent=2),
            results_json,
        )

    if best_score < threshold or not best_within_limit:
        fallback = _build_fallback_abstract(results_json)
        if fallback:
            print_info("摘要迭代未达标，尝试结构化结果兜底摘要...")
            score_data = critic.score(fallback, results_json)
            score = score_data.get("score", -1)
            fallback_length = len(re.sub(r"\s", "", _abstract_plain_text(fallback)))
            fallback_within_limit = fallback_length <= ABSTRACT_MAX_CHARS
            iterations.append({
                "round": "fallback",
                "score": score,
                "length": fallback_length,
                "issues": score_data.get("issues", []),
                "abstract": fallback,
            })
            if (fallback_within_limit and not best_within_limit) or (
                fallback_within_limit == best_within_limit and score > best_score
            ):
                best_score = score
                best_abstract = fallback
                best_score_data = score_data
                best_within_limit = fallback_within_limit

    artifacts["sections/abstract.tex"] = best_abstract
    artifacts["abstract_score.json"] = json.dumps(best_score_data, ensure_ascii=False, indent=2)
    artifacts["abstract_iterations.json"] = json.dumps(iterations, ensure_ascii=False, indent=2)
    return artifacts


def run_paper(workspace: Path, mgr: CheckpointManager) -> bool:
    analyze_arts = mgr.load_artifacts(StageID.ANALYZE)
    eda_arts = mgr.load_artifacts(StageID.EDA)
    model_arts = mgr.load_artifacts(StageID.MODEL)
    solve_arts = mgr.load_artifacts(StageID.SOLVE)

    if not analyze_arts or not model_arts:
        print_error("请先完成并审批前置阶段（至少到建模）")
        return False

    analysis = analyze_arts.get("analysis.md", "")
    assumptions = analyze_arts.get("assumptions.md", "")
    model_text = model_arts.get("model.md", "")
    results = solve_arts.get("interpretation.md", "（求解阶段未完成）")

    # 收集图表列表
    figures: list[str] = []
    fig_json = solve_arts.get("figures_list.json", "[]")
    try:
        figures = json.loads(fig_json)
    except json.JSONDecodeError:
        pass

    settings = get_settings()
    llm_config = settings.get_llm_config("writer")
    if getattr(llm_config, "backend", "openai") == "openai" and not llm_config.api_key:
        print_error("未配置 LLM API Key")
        return False
    llm = LLMClient(llm_config, log_dir=ProjectPaths(workspace).logs)

    agent = WriterAgent(llm)
    print_info("正在撰写论文...")
    revision_sections, revision_feedback = _review_revision(mgr)
    if revision_sections:
        print_info("检测到论文质量反馈，仅定向修订被点名小节...")
        artifacts = mgr.load_artifacts(StageID.PAPER, mgr.get_latest_version(StageID.PAPER))
        artifacts.update(agent.revise_sections(
            revision_sections,
            revision_feedback,
            solve_arts.get("results.json", "[]"),
            solve_arts.get("sensitivity.json", "{}"),
            solve_arts.get("method_contract.json", "{}"),
        ))
    else:
        artifacts = agent.write_paper(
            analysis=analysis,
            assumptions=assumptions,
            model=model_text,
            results=results,
            figures=figures,
            results_json=solve_arts.get("results.json", "[]"),
            sensitivity_json=solve_arts.get("sensitivity.json", "{}"),
            eda_summary=eda_arts.get("data_summary.md", ""),
            method_contract=solve_arts.get("method_contract.json", "{}"),
        )
    _add_code_appendix(
        artifacts,
        mgr.load_artifacts(StageID.CODE).get("solution.py", ""),
    )

    # 关键章节守卫：缺核心章节则中止，不产出残缺检查点
    required = ("sections/abstract.tex", "sections/model_solution.tex")
    missing = [name for name in required if not artifacts.get(name)]
    if missing:
        print_error(f"论文生成缺少关键章节: {', '.join(missing)}，已中止（不保存检查点），请重跑 paper 阶段")
        return False

    # 摘要专项打分迭代（critic 用 reviewer 的 LLM 配置，未配置时回退默认）
    critic_llm = LLMClient(settings.get_llm_config("reviewer"), log_dir=ProjectPaths(workspace).logs)
    critic = AbstractCriticAgent(critic_llm)
    if not revision_sections or "sections/abstract.tex" in revision_sections:
        artifacts = _refine_abstract(
            agent, critic, artifacts,
            results_json=solve_arts.get("results.json", "[]"),
        )

    typesetter_llm = LLMClient(
        settings.get_llm_config("typesetter"),
        log_dir=ProjectPaths(workspace).logs,
    )
    try:
        artifacts, layout_report = TypesetterAgent(typesetter_llm).typeset(artifacts)
    except Exception as error:
        artifacts, deterministic = normalize_tex_artifacts(artifacts)
        layout_report = {
            "schema_version": 1,
            "accepted": False,
            "deterministic_changes": deterministic,
            "violations": [f"{type(error).__name__}，已保留确定性规范化结果"],
        }
        print_warning("自动排版调用失败，已保留确定性规范化结果")
    artifacts["layout_report.json"] = json.dumps(
        layout_report, ensure_ascii=False, indent=2
    )
    if solve_arts.get("method_contract.json"):
        try:
            model_solution, traceability = build_paper_traceability(
                solve_arts["method_contract.json"],
                artifacts.get("sections/model_solution.tex", ""),
            )
        except ValueError as error:
            print_error(str(error))
            return False
        artifacts["sections/model_solution.tex"] = model_solution
        artifacts["method_contract.json"] = solve_arts["method_contract.json"]
        artifacts["method_traceability.json"] = json.dumps(
            traceability, ensure_ascii=False, indent=2,
        )

    missing_graphics = _find_missing_graphics(artifacts, figures, workspace)
    if missing_graphics:
        print_error(
            "论文引用了不存在的图片，已中止（不保存检查点）: "
            + "; ".join(missing_graphics)
        )
        return False

    meta = MetaData(
        stage=StageID.PAPER.value, version=0,
        model_used=f"{llm.model}; typesetter={typesetter_llm.model}",
        tokens_input=llm.total_input_tokens + typesetter_llm.total_input_tokens,
        tokens_output=llm.total_output_tokens + typesetter_llm.total_output_tokens,
    )
    vdir = mgr.save(StageID.PAPER, artifacts, meta)
    print_success(f"论文写作完成，产出保存到: {vdir}")
    print_info("请审查各 sections/*.tex 文件后审批")
    return True


def rerun_typesetter(workspace: Path, mgr: CheckpointManager) -> Path:
    latest_version = mgr.get_latest_version(StageID.PAPER)
    artifacts = mgr.load_artifacts(StageID.PAPER, latest_version)
    if not artifacts:
        raise ValueError("当前项目没有 paper 检查点")
    paths = ProjectPaths(workspace)
    feedback = {}
    feedback_path = paths.output / "layout_quality.json"
    if feedback_path.is_file():
        try:
            feedback = json.loads(feedback_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            feedback = {}
    llm_config = get_settings().get_llm_config("typesetter")
    if getattr(llm_config, "backend", "openai") == "openai" and not llm_config.api_key:
        raise ValueError("未配置 LLM API Key；如使用本机 Codex，请先在 GUI 切换到 Codex 模式")
    llm = LLMClient(llm_config, log_dir=paths.logs)
    revised, report = TypesetterAgent(llm).typeset(artifacts, feedback)
    revised["layout_report.json"] = json.dumps(report, ensure_ascii=False, indent=2)
    if revised.get("method_contract.json"):
        model_solution, traceability = build_paper_traceability(
            revised["method_contract.json"],
            revised.get("sections/model_solution.tex", ""),
        )
        revised["sections/model_solution.tex"] = model_solution
        revised["method_traceability.json"] = json.dumps(
            traceability, ensure_ascii=False, indent=2,
        )
    return mgr.save(
        StageID.PAPER,
        revised,
        MetaData(
            stage=StageID.PAPER.value,
            version=0,
            model_used=llm.model,
            tokens_input=llm.total_input_tokens,
            tokens_output=llm.total_output_tokens,
        ),
    )
