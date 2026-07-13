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
    numeric = df.select_dtypes(include="number")
    numeric_stats = "无数值列"
    if not numeric.empty:
        stats = numeric.agg(["min", "max", "mean", "median", "std"]).T
        numeric_stats = stats.round(6).to_string()
    trend_note = _trend_note(df)
    return (
        f"#### {label}：{df.shape[0]} 行 × {df.shape[1]} 列\n"
        f"列名: {list(df.columns)}\n"
        f"缺失值计数: {missing_str}\n"
        f"数值列统计（由 pandas 计算）:\n{numeric_stats}\n"
        f"时序异常检测提示: {trend_note}\n"
        f"前 3 行:\n{df.head(3).to_string()}\n"
    )


def _trend_note(df) -> str:
    """识别强趋势时序，避免直接在原始状态值上做全局 IQR。"""
    time_columns = [
        column for column in df.columns
        if any(token in str(column).casefold() for token in ("time", "时间", "秒"))
    ]
    if not time_columns:
        return "未识别到时间列"
    time_column = time_columns[0]
    numeric = df.select_dtypes(include="number")
    if time_column not in numeric.columns:
        return "时间列不是数值类型"
    for column in numeric.columns:
        if column == time_column:
            continue
        correlation = numeric[time_column].corr(numeric[column], method="spearman")
        if correlation == correlation and abs(correlation) >= 0.8:
            return (
                f"{column} 与 {time_column} 存在强趋势（Spearman={correlation:.3f}）；"
                "应对一阶差分/变化率/残差做异常检测，禁止用原始值全局 IQR 删除过渡段"
            )
    return "未发现 Spearman 绝对值不低于 0.8 的强趋势数值列"


def _file_digest(f: Path) -> str | None:
    """用 pandas 真实读取数据文件，生成结构摘要（防止 LLM 编造数据结构）。"""
    try:
        import pandas as pd
    except ImportError:
        return None
    try:
        if f.suffix.lower() in (".xlsx", ".xls"):
            xl = pd.ExcelFile(f)
            merged_by_sheet: dict[str, int] = {}
            if f.suffix.lower() == ".xlsx":
                from openpyxl import load_workbook

                book = load_workbook(f, read_only=False, data_only=True)
                merged_by_sheet = {
                    sheet.title: len(sheet.merged_cells.ranges)
                    for sheet in book.worksheets
                }
                book.close()
            parts = [f"共 {len(xl.sheet_names)} 个表单: {xl.sheet_names}"]
            for sheet in xl.sheet_names:
                merged_count = merged_by_sheet.get(sheet, 0)
                if merged_count:
                    parts.append(
                        f"表单 '{sheet}' 检测到 {merged_count} 个合并单元格；"
                        "pandas 会把非首行读为空值，分组标识列必须先前向填充"
                    )
                parts.append(_df_digest(xl.parse(sheet), f"表单 '{sheet}'"))
            return "\n".join(parts)
        if f.suffix.lower() in (".csv", ".tsv", ".txt"):
            sep = "\t" if f.suffix.lower() == ".tsv" else ","
            df, encoding = _read_delimited(f, sep=sep, nrows=2000)
            note = "（仅读前 2000 行做摘要）" if len(df) == 2000 else ""
            return f"检测编码: {encoding}\n" + _df_digest(df, f"数据表{note}")
    except Exception as exc:
        return f"[pandas 解析失败: {exc}]"
    return None


def _read_delimited(f: Path, sep: str, nrows: int | None = None):
    """按常见中英文编码读取分隔文本，返回 (DataFrame, encoding)。"""
    import pandas as pd

    last_error: UnicodeError | None = None
    for encoding in ("utf-8-sig", "utf-8", "gb18030", "gbk"):
        try:
            return pd.read_csv(f, sep=sep, nrows=nrows, encoding=encoding), encoding
        except UnicodeError as exc:
            last_error = exc
    raise last_error or UnicodeError(f"无法识别文件编码: {f.name}")


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
        print_error("未生成 eda_code.py，EDA 阶段失败且不保存检查点")
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
    try:
        script_path.unlink(missing_ok=True)
    except PermissionError as exc:
        print_error(f"EDA 临时脚本清理失败，已保留 eda_code.py: {exc}")

    figures = sorted(
        fig.name for fig in (workspace / "figures").glob("eda_*.png")
    )

    if success:
        print_info("基于真实执行输出撰写数据报告...")
        artifacts = agent.write_summary(exec_output, figures)
    else:
        print_error("EDA 代码多轮修复仍失败，EDA 阶段失败且不保存检查点")
        return

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
