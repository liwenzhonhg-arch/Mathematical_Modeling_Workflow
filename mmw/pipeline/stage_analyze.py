"""阶段 1：问题分析。"""

from __future__ import annotations

from pathlib import Path

from mmw.agents.analyst import AnalystAgent
from mmw.config import get_settings
from mmw.llm import LLMClient
from mmw.models import MetaData, StageID
from mmw.project import ProjectPaths
from mmw.utils.checkpoint import CheckpointManager
from mmw.utils.display import print_info, print_success


def _scan_data_files(workspace: Path) -> list[dict]:
    """扫描项目输入清单或旧式 data/raw，返回数据文件信息。"""
    paths = ProjectPaths(workspace)
    files = []
    for f in paths.data_files():
        if f.is_file() and not f.name.startswith("."):
            info: dict = {
                "name": paths.relative(f),
                "size": _format_size(f.stat().st_size),
                "preview": None,
            }
            if f.suffix in (".csv", ".txt", ".tsv"):
                try:
                    lines = f.read_text(encoding="utf-8", errors="replace").splitlines()[:5]
                    info["preview"] = "\n".join(lines)
                except Exception:
                    pass
            files.append(info)
    return files


def _format_size(size: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024:
            return f"{size:.0f} {unit}"
        size /= 1024
    return f"{size:.1f} TB"


def run_analyze(workspace: Path, mgr: CheckpointManager) -> None:
    """执行问题分析阶段。"""
    paths = ProjectPaths(workspace)
    problem_path = paths.problem
    if not problem_path.exists():
        print_info(f"请先将题目粘贴到: {problem_path}")
        return

    problem_text = problem_path.read_text(encoding="utf-8").strip()
    if not problem_text or problem_text.startswith("<!--"):
        print_info(f"题目文件为空，请先编辑: {problem_path}")
        return

    data_files = _scan_data_files(workspace)
    if data_files:
        print_info(f"检测到 {len(data_files)} 个数据文件")

    settings = get_settings()
    llm_config = settings.get_llm_config("analyst")
    if not llm_config.api_key:
        from mmw.utils.display import print_error
        print_error("未配置 LLM API Key，请复制 .env.example 为 .env 并填入 API Key")
        return
    llm = LLMClient(llm_config, log_dir=paths.logs)

    agent = AnalystAgent(llm)

    print_info("正在分析题目...")
    artifacts = agent.analyze(problem_text, data_files)

    meta = MetaData(
        stage=StageID.ANALYZE.value,
        version=0,
        model_used=llm.model,
        tokens_input=llm.total_input_tokens,
        tokens_output=llm.total_output_tokens,
    )
    vdir = mgr.save(StageID.ANALYZE, artifacts, meta)

    print_success(f"分析完成，产出保存到: {vdir}")
    print_info("查看产出: mmw show analyze")
    print_info("审批通过: mmw approve analyze")
