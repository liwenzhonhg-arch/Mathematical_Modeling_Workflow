"""阶段 5：代码实现（含错误反思循环）。"""

from __future__ import annotations

import json
from pathlib import Path

from mmw.agents.coder import CoderAgent
from mmw.config import get_settings
from mmw.llm import LLMClient
from mmw.models import MetaData, StageID
from mmw.utils.checkpoint import CheckpointManager
from mmw.utils.display import print_error, print_info, print_success


def load_deliverables(mgr: CheckpointManager) -> list[dict]:
    """从 analyze 检查点的 sub_problems.json 读取题目硬性交付文件清单。"""
    analyze_arts = mgr.load_artifacts(StageID.ANALYZE)
    try:
        data = json.loads(analyze_arts.get("sub_problems.json", "{}"))
        deliverables = data.get("deliverables", [])
    except json.JSONDecodeError:
        return []
    return [d for d in deliverables if isinstance(d, dict) and d.get("file")]


def run_code(workspace: Path, mgr: CheckpointManager) -> None:
    model_arts = mgr.load_artifacts(StageID.MODEL)
    if not model_arts:
        print_error("请先完成并审批建模阶段")
        return

    eda_arts = mgr.load_artifacts(StageID.EDA)

    model_text = model_arts.get("model.md", "")
    params_text = model_arts.get("params.json", "")
    data_summary = eda_arts.get("data_summary.md", "")
    verify_notes = model_arts.get("verify_report.md", "")

    settings = get_settings()
    llm_config = settings.get_llm_config("coder")
    if not llm_config.api_key:
        print_error("未配置 LLM API Key")
        return
    llm = LLMClient(llm_config, log_dir=workspace / "logs")

    # 真实数据文件清单（防止 coder 猜文件名失败后用模拟数据兜底）
    raw_dir = workspace / "data" / "raw"
    data_files = sorted(
        f.name for f in raw_dir.iterdir() if f.is_file() and not f.name.startswith(".")
    ) if raw_dir.exists() else []

    deliverables = load_deliverables(mgr)

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
    )

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
    print_success(f"代码实现完成，产出保存到: {vdir}")

    if exec_result and not exec_result.success:
        print_info("代码运行未成功，请手动检查和修改 solution.py")
