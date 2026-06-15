"""阶段 7：论文写作（分节 LaTeX 生成 + 摘要专项打分迭代）。"""

from __future__ import annotations

import json
from pathlib import Path

from mmw.agents.abstract_critic import AbstractCriticAgent
from mmw.agents.writer import WriterAgent
from mmw.config import get_settings
from mmw.llm import LLMClient
from mmw.models import MetaData, StageID
from mmw.utils.checkpoint import CheckpointManager
from mmw.utils.display import print_error, print_info, print_success

ABSTRACT_SCORE_THRESHOLD = 85
ABSTRACT_MAX_ROUNDS = 4


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

    for round_no in range(1, max_rounds + 1):
        print_info(f"摘要评审第 {round_no}/{max_rounds} 轮...")
        score_data = critic.score(abstract, results_json)
        score = score_data.get("score", -1)
        iterations.append({
            "round": round_no,
            "score": score,
            "issues": score_data.get("issues", []),
            "abstract": abstract,
        })
        # 修订可能让摘要变差，始终保留历史最高分版本
        if score > best_score:
            best_score = score
            best_abstract = abstract
            best_score_data = score_data

        if score < 0:
            print_error("摘要评分解析失败，跳过迭代（不阻塞流程）")
            break
        print_info(f"摘要得分: {score}")
        if score >= threshold:
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
        abstract = writer.revise_abstract(
            abstract,
            json.dumps(score_data, ensure_ascii=False, indent=2),
            results_json,
        )

    artifacts["sections/abstract.tex"] = best_abstract
    artifacts["abstract_score.json"] = json.dumps(best_score_data, ensure_ascii=False, indent=2)
    artifacts["abstract_iterations.json"] = json.dumps(iterations, ensure_ascii=False, indent=2)
    return artifacts


def run_paper(workspace: Path, mgr: CheckpointManager) -> None:
    analyze_arts = mgr.load_artifacts(StageID.ANALYZE)
    eda_arts = mgr.load_artifacts(StageID.EDA)
    model_arts = mgr.load_artifacts(StageID.MODEL)
    solve_arts = mgr.load_artifacts(StageID.SOLVE)

    if not analyze_arts or not model_arts:
        print_error("请先完成并审批前置阶段（至少到建模）")
        return

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
    if not llm_config.api_key:
        print_error("未配置 LLM API Key")
        return
    llm = LLMClient(llm_config, log_dir=workspace / "logs")

    agent = WriterAgent(llm)
    print_info("正在撰写论文...")
    artifacts = agent.write_paper(
        analysis=analysis,
        assumptions=assumptions,
        model=model_text,
        results=results,
        figures=figures,
        results_json=solve_arts.get("results.json", "[]"),
        sensitivity_json=solve_arts.get("sensitivity.json", "{}"),
        eda_summary=eda_arts.get("data_summary.md", ""),
    )

    # 关键章节守卫：缺核心章节则中止，不产出残缺检查点
    required = ("sections/abstract.tex", "sections/model_solution.tex")
    missing = [name for name in required if not artifacts.get(name)]
    if missing:
        print_error(f"论文生成缺少关键章节: {', '.join(missing)}，已中止（不保存检查点），请重跑 paper 阶段")
        return

    # 摘要专项打分迭代（critic 用 reviewer 的 LLM 配置，未配置时回退默认）
    critic_llm = LLMClient(settings.get_llm_config("reviewer"), log_dir=workspace / "logs")
    critic = AbstractCriticAgent(critic_llm)
    artifacts = _refine_abstract(
        agent, critic, artifacts,
        results_json=solve_arts.get("results.json", "[]"),
    )

    meta = MetaData(
        stage=StageID.PAPER.value, version=0,
        model_used=llm.model,
        tokens_input=llm.total_input_tokens,
        tokens_output=llm.total_output_tokens,
    )
    vdir = mgr.save(StageID.PAPER, artifacts, meta)
    print_success(f"论文写作完成，产出保存到: {vdir}")
    print_info("请审查各 sections/*.tex 文件后审批")
