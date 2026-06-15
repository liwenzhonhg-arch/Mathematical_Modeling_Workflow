"""mmw CLI 入口：Typer 命令行工具。"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import typer
from rich.console import Console

from mmw.config import get_settings
from mmw.models import (
    STAGE_META,
    STAGE_ORDER,
    CompetitionConfig,
    StageID,
    StageResult,
)
from mmw.pipeline.state_machine import PipelineStateMachine
from mmw.utils.checkpoint import CheckpointManager
from mmw.utils.display import (
    print_error,
    print_info,
    print_success,
    show_artifacts,
    show_pipeline_status,
    show_warnings,
)
from mmw.utils.file_io import write_text, write_yaml

app = typer.Typer(name="mmw", help="数学建模竞赛工作流工具", no_args_is_help=True)
console = Console()


def _get_workspace(name: str | None = None) -> Path:
    """获取竞赛工作空间路径。自动查找当前活跃工作空间。"""
    settings = get_settings()
    ws_root = settings.workspace_dir

    if name:
        return ws_root / name

    # 尝试找到唯一的工作空间
    if ws_root.exists():
        workspaces = [
            d for d in ws_root.iterdir()
            if d.is_dir() and (d / "config.yaml").exists()
        ]
        if len(workspaces) == 1:
            return workspaces[0]
        if len(workspaces) > 1:
            names = ", ".join(d.name for d in workspaces)
            print_error(f"存在多个工作空间: {names}，请用 --workspace 指定")
            raise typer.Exit(1)

    print_error("未找到工作空间，请先运行 mmw init <name>")
    raise typer.Exit(1)


def _get_mgr(workspace: str | None = None) -> tuple[CheckpointManager, PipelineStateMachine]:
    ws = _get_workspace(workspace)
    mgr = CheckpointManager(ws)
    sm = PipelineStateMachine(mgr)
    return mgr, sm


def _run_stage(stage: StageID, ws: Path, mgr: CheckpointManager) -> None:
    """调度阶段执行。"""
    if stage == StageID.ANALYZE:
        from mmw.pipeline.stage_analyze import run_analyze
        run_analyze(ws, mgr)
    elif stage == StageID.EDA:
        from mmw.pipeline.stage_eda import run_eda
        run_eda(ws, mgr)
    elif stage == StageID.RESEARCH:
        from mmw.pipeline.stage_research import run_research
        run_research(ws, mgr)
    elif stage == StageID.MODEL:
        from mmw.pipeline.stage_model import run_model
        run_model(ws, mgr)
    elif stage == StageID.CODE:
        from mmw.pipeline.stage_code import run_code
        run_code(ws, mgr)
    elif stage == StageID.SOLVE:
        from mmw.pipeline.stage_solve import run_solve
        run_solve(ws, mgr)
    elif stage == StageID.PAPER:
        from mmw.pipeline.stage_paper import run_paper
        run_paper(ws, mgr)
    elif stage == StageID.REVIEW:
        from mmw.pipeline.stage_review import run_review
        run_review(ws, mgr)
    else:
        print_error(f"阶段 '{stage.value}' 未实现")


# ── init ─────────────────────────────────────────────────


@app.command()
def init(
    name: str = typer.Argument(help="竞赛工作空间名称，如 2025_cumcm_A"),
    problem: str = typer.Option("A", help="题目编号"),
    year: int = typer.Option(2025, help="年份"),
):
    """初始化新的竞赛工作空间。"""
    settings = get_settings()
    ws = settings.workspace_dir / name

    if ws.exists():
        print_error(f"工作空间 '{name}' 已存在")
        raise typer.Exit(1)

    # 创建目录结构
    (ws / "data" / "raw").mkdir(parents=True)
    (ws / "data" / "processed").mkdir(parents=True)
    (ws / "references").mkdir(parents=True)
    (ws / "checkpoints").mkdir(parents=True)
    (ws / "output").mkdir(parents=True)
    (ws / "logs").mkdir(parents=True)

    # 写入配置
    config = CompetitionConfig(name=name, year=year, problem=problem)
    write_yaml(ws / "config.yaml", config.model_dump())

    # 创建空的 problem.md
    write_text(ws / "problem.md", "<!-- 在此粘贴竞赛题目原文 -->\n\n")

    print_success(f"工作空间已创建: {ws}")
    print_info(f"请将题目粘贴到: {ws / 'problem.md'}")
    print_info(f"请将数据文件放入: {ws / 'data' / 'raw'}")


# ── status ───────────────────────────────────────────────


@app.command()
def status(
    workspace: Optional[str] = typer.Option(None, "--workspace", "-w", help="工作空间名称"),
):
    """显示流水线状态。"""
    mgr, sm = _get_mgr(workspace)

    pipeline_status = mgr.get_pipeline_status()
    show_pipeline_status(pipeline_status)

    warnings = sm.get_warnings()
    if warnings:
        console.print()
        show_warnings(warnings)


# ── run ──────────────────────────────────────────────────


@app.command()
def run(
    stage: str = typer.Argument("next", help="阶段名称或 'next'"),
    workspace: Optional[str] = typer.Option(None, "--workspace", "-w", help="工作空间名称"),
):
    """运行指定阶段（或下一个待运行阶段）。"""
    mgr, sm = _get_mgr(workspace)

    if stage == "next":
        target = sm.get_next_runnable()
        if target is None:
            print_info("所有阶段已完成或无可运行阶段")
            return
    else:
        try:
            target = StageID(stage)
        except ValueError:
            print_error(f"未知阶段: {stage}，可选: {', '.join(s.value for s in StageID)}")
            raise typer.Exit(1)

    can, reason = sm.can_run(target)
    if not can:
        print_error(reason)
        raise typer.Exit(1)

    meta = STAGE_META[target]
    print_info(f"运行阶段 {meta['index']}: {meta['label']} ({target.value})")

    _run_stage(target, mgr.workspace, mgr)


# ── show ─────────────────────────────────────────────────


@app.command()
def show(
    stage: str = typer.Argument(help="阶段名称"),
    version: Optional[int] = typer.Option(None, "--version", "-v", help="版本号"),
    workspace: Optional[str] = typer.Option(None, "--workspace", "-w", help="工作空间名称"),
):
    """查看阶段产出。"""
    mgr, _ = _get_mgr(workspace)

    try:
        stage_id = StageID(stage)
    except ValueError:
        print_error(f"未知阶段: {stage}")
        raise typer.Exit(1)

    artifacts = mgr.load_artifacts(stage_id, version)
    if not artifacts:
        v_str = f"v{version}" if version else "最新版"
        print_error(f"阶段 '{stage}' ({v_str}) 无产出")
        raise typer.Exit(1)

    label = STAGE_META[stage_id]["label"]
    v = version or mgr.get_latest_version(stage_id)
    show_artifacts(artifacts, f"{label} (v{v})")


# ── approve ──────────────────────────────────────────────


@app.command()
def approve(
    stage: str = typer.Argument(help="阶段名称"),
    version: Optional[int] = typer.Option(None, "--version", "-v", help="审批/激活的版本号（默认最新版）"),
    workspace: Optional[str] = typer.Option(None, "--workspace", "-w", help="工作空间名称"),
):
    """审批阶段（或切换激活版本），允许流水线继续。"""
    mgr, sm = _get_mgr(workspace)

    try:
        stage_id = StageID(stage)
    except ValueError:
        print_error(f"未知阶段: {stage}")
        raise typer.Exit(1)

    # 指定的历史版本若已 approved，则只切换激活版本（branch 多方案场景）
    if version is not None:
        target_status = mgr.load_status(stage_id, version)
        if target_status is None:
            print_error(f"阶段 '{stage}' 的 v{version} 不存在")
            raise typer.Exit(1)
        if mgr.is_approved(stage_id, version):
            mgr.set_active_version(stage_id, version)
            print_success(f"阶段 '{stage}' 已切换激活版本为 v{version}")
            return

    can, reason = sm.can_approve(stage_id, version)
    if not can:
        print_error(reason)
        raise typer.Exit(1)

    mgr.approve(stage_id, version=version)
    v = version or mgr.get_latest_version(stage_id)
    print_success(f"阶段 '{stage}' v{v} 已审批通过并激活")

    from mmw.models import next_stage
    ns = next_stage(stage_id)
    if ns:
        print_info(f"运行下一阶段: mmw run {ns.value}")


# ── branch / compare ─────────────────────────────────────


@app.command()
def branch(
    stage: str = typer.Argument("model", help="阶段名称（目前仅支持 model）"),
    workspace: Optional[str] = typer.Option(None, "--workspace", "-w", help="工作空间名称"),
):
    """生成与当前方案显著不同的备选建模方案（产出新版本，不影响激活版本）。"""
    if stage != StageID.MODEL.value:
        print_error("branch 目前仅支持 model 阶段")
        raise typer.Exit(1)

    mgr, _ = _get_mgr(workspace)
    from mmw.pipeline.stage_model import run_model_branch
    run_model_branch(mgr.workspace, mgr)


@app.command()
def compare(
    stage: str = typer.Argument(help="阶段名称（目前仅支持 model）"),
    v1: int = typer.Argument(help="版本1"),
    v2: int = typer.Argument(help="版本2"),
    workspace: Optional[str] = typer.Option(None, "--workspace", "-w", help="工作空间名称"),
):
    """用 LLM 对比同阶段两个版本（建模合理性/求解难度/创新性），报告写入 output/。"""
    if stage != StageID.MODEL.value:
        print_error("compare 目前仅支持 model 阶段")
        raise typer.Exit(1)

    mgr, _ = _get_mgr(workspace)
    from mmw.pipeline.stage_model import run_compare_model
    run_compare_model(mgr.workspace, mgr, v1, v2)


@app.command()
def ack(
    stage: str = typer.Argument(help="阶段名称"),
    workspace: Optional[str] = typer.Option(None, "--workspace", "-w", help="工作空间名称"),
):
    """确认上游变更对本阶段无影响，清除「上游已变更」警告（无需重跑）。"""
    mgr, _ = _get_mgr(workspace)

    try:
        stage_id = StageID(stage)
    except ValueError:
        print_error(f"未知阶段: {stage}")
        raise typer.Exit(1)

    if mgr.ack_upstream(stage_id):
        print_success(f"阶段 '{stage}' 已确认上游变更，警告已清除")
    else:
        print_error(f"阶段 '{stage}' 尚无检查点，无可确认的变更")
        raise typer.Exit(1)


# ── rework ───────────────────────────────────────────────


@app.command()
def rework(
    target: str = typer.Argument(help="需要重做的目标阶段"),
    workspace: Optional[str] = typer.Option(None, "--workspace", "-w", help="工作空间名称"),
):
    """回退到指定阶段重做。"""
    mgr, sm = _get_mgr(workspace)

    try:
        target_stage = StageID(target)
    except ValueError:
        print_error(f"未知阶段: {target}")
        raise typer.Exit(1)

    affected = sm.apply_rework(target_stage)
    print_success(f"已标记阶段 '{target}' 需要重做")
    if len(affected) > 1:
        print_info(f"受影响的下游阶段: {', '.join(affected[1:])}")
    print_info(f"运行: mmw run {target}")


# ── diff ─────────────────────────────────────────────────


@app.command()
def diff(
    stage: str = typer.Argument(help="阶段名称"),
    v1: int = typer.Argument(help="版本1"),
    v2: int = typer.Argument(help="版本2"),
    workspace: Optional[str] = typer.Option(None, "--workspace", "-w", help="工作空间名称"),
):
    """对比同一阶段的两个版本。"""
    mgr, _ = _get_mgr(workspace)

    try:
        stage_id = StageID(stage)
    except ValueError:
        print_error(f"未知阶段: {stage}")
        raise typer.Exit(1)

    arts1 = mgr.load_artifacts(stage_id, v1)
    arts2 = mgr.load_artifacts(stage_id, v2)

    if not arts1:
        print_error(f"版本 v{v1} 不存在")
        raise typer.Exit(1)
    if not arts2:
        print_error(f"版本 v{v2} 不存在")
        raise typer.Exit(1)

    all_keys = sorted(set(arts1.keys()) | set(arts2.keys()))
    for key in all_keys:
        c1 = arts1.get(key, "")
        c2 = arts2.get(key, "")
        if c1 == c2:
            console.print(f"[dim]{key}: 无变化[/dim]")
        else:
            console.print(f"\n[bold]{key}[/bold]:")
            console.print(f"[red]--- v{v1}[/red]")
            console.print(f"[green]+++ v{v2}[/green]")
            # 简单逐行对比
            lines1 = c1.splitlines()
            lines2 = c2.splitlines()
            max_lines = max(len(lines1), len(lines2))
            for i in range(max_lines):
                l1 = lines1[i] if i < len(lines1) else ""
                l2 = lines2[i] if i < len(lines2) else ""
                if l1 != l2:
                    if l1:
                        console.print(f"[red]- {l1}[/red]")
                    if l2:
                        console.print(f"[green]+ {l2}[/green]")


# ── compile ──────────────────────────────────────────────


@app.command()
def compile(
    workspace: Optional[str] = typer.Option(None, "--workspace", "-w", help="工作空间名称"),
):
    """编译 LaTeX 论文为 PDF。"""
    from mmw.latex.compiler import assemble_main_tex, compile_latex, prepare_compile_dir

    mgr, _ = _get_mgr(workspace)
    ws = mgr.workspace

    paper_version = mgr.get_latest_version(StageID.PAPER)
    if paper_version == 0:
        print_error("请先完成论文写作阶段")
        raise typer.Exit(1)

    paper_dir = mgr._version_dir(StageID.PAPER, paper_version)
    compile_dir = prepare_compile_dir(ws, paper_dir)

    config_path = ws / "config.yaml"
    title = "题目"
    if config_path.exists():
        from mmw.utils.file_io import read_yaml
        cfg = read_yaml(config_path)
        title = cfg.get("name", "题目")

    main_content = assemble_main_tex(paper_dir, title=title, workspace=ws)
    (compile_dir / "main.tex").write_text(main_content, encoding="utf-8")

    print_info(f"编译目录: {compile_dir}")
    success, msg = compile_latex(compile_dir)

    if success:
        import shutil
        pdf_path = compile_dir / "main.pdf"
        output_pdf = ws / "output" / "paper.pdf"
        shutil.copy2(pdf_path, output_pdf)
        print_success(f"PDF 已生成: {output_pdf}")
    else:
        print_error(msg)


# ── export ───────────────────────────────────────────────


@app.command(name="export")
def export_submission(
    workspace: Optional[str] = typer.Option(None, "--workspace", "-w", help="工作空间名称"),
):
    """打包提交文件（PDF + 代码 + 支撑材料）。"""
    import zipfile

    mgr, _ = _get_mgr(workspace)
    ws = mgr.workspace
    output_dir = ws / "output"

    pdf_path = output_dir / "paper.pdf"
    if not pdf_path.exists():
        print_error("未找到 paper.pdf，请先运行 mmw compile")
        raise typer.Exit(1)

    zip_path = output_dir / "submission.zip"
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.write(pdf_path, "paper.pdf")

        code_arts = mgr.load_artifacts(StageID.CODE)
        if "solution.py" in code_arts:
            zf.writestr("code/solution.py", code_arts["solution.py"])

        figures_dir = ws / "figures"
        if figures_dir.exists():
            for fig in figures_dir.glob("*.png"):
                zf.write(fig, f"figures/{fig.name}")

        # 题目硬性交付文件（analyze 清单 + 兜底匹配 result*.xlsx），solution.py 生成在 workspace 根
        from mmw.pipeline.stage_code import load_deliverables

        deliverable_names = {d["file"] for d in load_deliverables(mgr)}
        deliverable_names.update(f.name for f in ws.glob("result*.xlsx"))
        missing = []
        for name in sorted(deliverable_names):
            fpath = ws / name
            if fpath.exists():
                zf.write(fpath, name)
            else:
                missing.append(name)

    if missing:
        print_error(f"题目要求的交付文件缺失，未打包: {', '.join(missing)}")
    print_success(f"提交包已生成: {zip_path}")


# ── log ──────────────────────────────────────────────────


@app.command()
def log(
    workspace: Optional[str] = typer.Option(None, "--workspace", "-w", help="工作空间名称"),
):
    """查看 LLM 调用历史和费用。"""
    ws = _get_workspace(workspace)
    log_dir = ws / "logs"

    if not log_dir.exists() or not any(log_dir.iterdir()):
        print_info("暂无 LLM 调用记录")
        return

    from mmw.utils.file_io import read_json

    total_input = 0
    total_output = 0
    entries = []
    for f in sorted(log_dir.glob("*.json")):
        entry = read_json(f)
        entries.append(entry)
        total_input += entry.get("input_tokens", 0)
        total_output += entry.get("output_tokens", 0)

    from rich.table import Table
    table = Table(title="LLM 调用记录")
    table.add_column("时间", width=20)
    table.add_column("模型", width=20)
    table.add_column("输入 tokens", justify="right", width=12)
    table.add_column("输出 tokens", justify="right", width=12)

    for e in entries[-20:]:  # 最近 20 条
        table.add_row(
            e.get("timestamp", ""),
            e.get("model", ""),
            str(e.get("input_tokens", 0)),
            str(e.get("output_tokens", 0)),
        )
    console.print(table)
    console.print(f"\n累计: 输入 {total_input:,} tokens / 输出 {total_output:,} tokens / 共 {total_input + total_output:,} tokens")
    if len(entries) > 20:
        console.print(f"[dim]（仅显示最近 20 条，共 {len(entries)} 条）[/dim]")


def main():
    app()


if __name__ == "__main__":
    main()
