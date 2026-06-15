"""阶段 2：数据探索（EDA）。

流程：pandas 真实读取数据结构 → Agent 生成 eda_code.py → 沙箱执行
（失败最多修复 2 轮）→ Agent 基于真实执行输出撰写报告。
"""

from __future__ import annotations

from pathlib import Path

from mmw.agents.eda import EDAAgent
from mmw.config import get_settings
from mmw.llm import LLMClient
from mmw.models import MetaData, StageID
from mmw.utils.checkpoint import CheckpointManager
from mmw.utils.display import print_error, print_info, print_success
from mmw.utils.executor import run_python_script

MAX_FIX_ROUNDS = 2


def _df_digest(df, label: str) -> str:
    """单个 DataFrame 的结构摘要。"""
    missing = df.isna().sum()
    missing_str = ", ".join(f"{c}: {n}" for c, n in missing.items() if n > 0) or "无"
    return (
        f"#### {label}：{df.shape[0]} 行 × {df.shape[1]} 列\n"
        f"列名: {list(df.columns)}\n"
        f"缺失值计数: {missing_str}\n"
        f"前 3 行:\n{df.head(3).to_string()}\n"
    )


def _file_digest(f: Path) -> str | None:
    """用 pandas 真实读取数据文件，生成结构摘要（防止 LLM 编造数据结构）。"""
    try:
        import pandas as pd
    except ImportError:
        return None
    try:
        if f.suffix.lower() in (".xlsx", ".xls"):
            xl = pd.ExcelFile(f)
            parts = [f"共 {len(xl.sheet_names)} 个表单: {xl.sheet_names}"]
            for sheet in xl.sheet_names:
                parts.append(_df_digest(xl.parse(sheet), f"表单 '{sheet}'"))
            return "\n".join(parts)
        if f.suffix.lower() in (".csv", ".tsv", ".txt"):
            sep = "\t" if f.suffix.lower() == ".tsv" else ","
            df = pd.read_csv(f, sep=sep, nrows=2000)
            note = "（仅读前 2000 行做摘要）" if len(df) == 2000 else ""
            return _df_digest(df, f"数据表{note}")
    except Exception as exc:
        return f"[pandas 解析失败: {exc}]"
    return None


def _scan_data_files(workspace: Path) -> list[dict]:
    raw_dir = workspace / "data" / "raw"
    if not raw_dir.exists():
        return []
    files = []
    for f in sorted(raw_dir.iterdir()):
        if f.is_file() and not f.name.startswith("."):
            files.append({
                "name": f.name,
                "size": _fmt(f.stat().st_size),
                "preview": _file_digest(f),
            })
    return files


def _fmt(size: int) -> str:
    for u in ("B", "KB", "MB", "GB"):
        if size < 1024:
            return f"{size:.0f} {u}"
        size /= 1024
    return f"{size:.1f} TB"


def run_eda(workspace: Path, mgr: CheckpointManager) -> None:
    data_files = _scan_data_files(workspace)
    if not data_files:
        print_info("data/raw/ 下无数据文件，跳过 EDA 阶段")
        artifacts = {"data_summary.md": "# 数据探索\n\n本题未附带数据文件，无需 EDA。\n"}
        meta = MetaData(stage=StageID.EDA.value, version=0)
        mgr.save(StageID.EDA, artifacts, meta)
        print_info("已创建空 EDA 检查点")
        return

    upstream = mgr.load_artifacts(StageID.ANALYZE)
    problem_summary = upstream.get("analysis.md", "")[:2000]

    settings = get_settings()
    llm_config = settings.get_llm_config("eda")
    if not llm_config.api_key:
        print_error("未配置 LLM API Key")
        return
    llm = LLMClient(llm_config, log_dir=workspace / "logs")

    agent = EDAAgent(llm)
    print_info(f"正在为 {len(data_files)} 个数据文件生成 EDA 代码...")
    code = agent.generate_code(problem_summary, data_files)
    if not code:
        print_error("未生成 eda_code.py，降级为仅保存结构摘要")
        digest = "\n\n".join(f["preview"] or f["name"] for f in data_files)
        artifacts = {"data_summary.md": f"# 数据探索（结构摘要）\n\n{digest}\n"}
        meta = MetaData(stage=StageID.EDA.value, version=0, model_used=llm.model)
        mgr.save(StageID.EDA, artifacts, meta)
        return

    # 执行 EDA 代码，失败时让 Agent 修复（最多 MAX_FIX_ROUNDS 轮）
    (workspace / "figures").mkdir(exist_ok=True)
    script_path = workspace / "eda_code.py"
    exec_output = ""
    success = False
    result = None
    for round_no in range(MAX_FIX_ROUNDS + 1):
        script_path.write_text(code, encoding="utf-8")
        print_info(f"执行 EDA 代码（第 {round_no + 1} 次）...")
        result = run_python_script(script_path, workspace, timeout=300)
        if result.success:
            success = True
            exec_output = result.stdout
            print_success("EDA 代码执行成功")
            break
        print_error(f"执行失败: {result.error_summary}")
        if round_no == MAX_FIX_ROUNDS:
            break
        fixed = agent.fix_code(f"{result.error_summary}\n\n{result.stderr[-2000:]}")
        if fixed:
            code = fixed
    script_path.unlink(missing_ok=True)

    figures = sorted(
        fig.name for fig in (workspace / "figures").glob("eda_*.png")
    )

    if success:
        print_info("基于真实执行输出撰写数据报告...")
        artifacts = agent.write_summary(exec_output, figures)
    else:
        print_error("EDA 代码多轮修复仍失败，报告降级为结构摘要 + 错误信息")
        digest = "\n\n".join(f["preview"] or f["name"] for f in data_files)
        error_summary = result.error_summary if result is not None else "未执行"
        artifacts = {
            "data_summary.md": (
                f"# 数据探索（结构摘要，代码执行失败）\n\n{digest}\n\n"
                f"## 执行错误\n\n```\n{error_summary}\n```\n"
            )
        }

    artifacts["eda_code.py"] = code
    if exec_output:
        artifacts["eda_output.txt"] = exec_output

    meta = MetaData(
        stage=StageID.EDA.value, version=0,
        model_used=llm.model,
        tokens_input=llm.total_input_tokens,
        tokens_output=llm.total_output_tokens,
    )
    vdir = mgr.save(StageID.EDA, artifacts, meta)
    print_success(f"EDA 完成，产出保存到: {vdir}")
    if figures:
        print_info(f"生成图表 {len(figures)} 张: {', '.join(figures[:5])}")
