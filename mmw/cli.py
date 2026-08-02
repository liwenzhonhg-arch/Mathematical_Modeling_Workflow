"""mmw CLI 入口：Typer 命令行工具。"""

from __future__ import annotations

from pathlib import Path
import hashlib
import json
import time
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

AGENT_ROLES = (
    "analyst", "eda", "researcher", "modeler",
    "verifier", "coder", "writer", "figure_polisher", "typesetter", "reviewer",
)


def _masked_key(key: str) -> str:
    return f"****{key[-4:]}" if len(key) > 4 else "****"


def _probe_request(config) -> None:
    from mmw.llm import LLMClient

    client = LLMClient(config)
    client.chat([{"role": "user", "content": "ping"}], temperature=0, max_tokens=1)


def _probe_llm_config(config) -> tuple[bool, str]:
    """最小请求验证配置；只重试瞬时错误，不回传可能含密钥的异常正文。"""
    from mmw.agents.base import RETRYABLE_ERRORS

    for attempt in range(1, 4):
        try:
            _probe_request(config)
            return True, "OK"
        except RETRYABLE_ERRORS as exc:
            if attempt < 3:
                time.sleep(attempt)
                continue
            detail = type(exc).__name__
        except RuntimeError as exc:
            detail = str(exc) if config.backend == "codex" else type(exc).__name__
        except Exception as exc:
            status = getattr(exc, "status_code", None)
            detail = f"HTTP {status}" if status else type(exc).__name__
        return False, detail
    return False, "UnknownError"


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


def _run_stage(stage: StageID, ws: Path, mgr: CheckpointManager) -> bool | None:
    """调度阶段执行。"""
    before = mgr.get_latest_version(stage)
    result = None
    if stage == StageID.ANALYZE:
        from mmw.pipeline.stage_analyze import run_analyze
        result = run_analyze(ws, mgr)
    elif stage == StageID.EDA:
        from mmw.pipeline.stage_eda import run_eda
        result = run_eda(ws, mgr)
    elif stage == StageID.RESEARCH:
        from mmw.pipeline.stage_research import run_research
        result = run_research(ws, mgr)
    elif stage == StageID.MODEL:
        from mmw.pipeline.stage_model import run_model
        result = run_model(ws, mgr)
    elif stage == StageID.CODE:
        from mmw.pipeline.stage_code import run_code
        result = run_code(ws, mgr)
    elif stage == StageID.SOLVE:
        from mmw.pipeline.stage_solve import run_solve
        result = run_solve(ws, mgr)
    elif stage == StageID.PAPER:
        from mmw.pipeline.stage_paper import run_paper
        result = run_paper(ws, mgr)
    elif stage == StageID.REVIEW:
        from mmw.pipeline.stage_review import run_review
        result = run_review(ws, mgr)
    else:
        print_error(f"阶段 '{stage.value}' 未实现")
        return False
    if result is False or mgr.get_latest_version(stage) <= before:
        return False
    if stage == StageID.REVIEW:
        from mmw.benchmark import run_final_certification

        review_version = mgr.get_latest_version(StageID.REVIEW)
        cases_root = Path(__file__).resolve().parent.parent / "test_cases"
        report = run_final_certification(mgr, cases_root, review_version)
        console.print(
            f"[bold]最终可信等级：{report['certification']['level']}[/bold] "
            f"({report['certification']['meaning']})"
        )
        if not report["overall_passed"]:
            print_error("最终 benchmark 未通过")
            return False
    if stage in {StageID.CODE, StageID.SOLVE}:
        return not bool(PipelineStateMachine(mgr).quality_error(stage, mgr.get_latest_version(stage)))
    return True


# ── init ─────────────────────────────────────────────────


@app.command(name="check-config")
def check_config():
    """在正式运行前验证全部 Agent 的最终 LLM 配置。"""
    settings = get_settings()
    grouped: dict[tuple[str, str, str, str], dict] = {}

    for role in AGENT_ROLES:
        config = settings.get_llm_config(role)
        if config.backend == "codex":
            print_info(f"{role}: backend=codex, model=Codex 默认模型, max_tokens={config.max_tokens}")
        else:
            print_info(
                f"{role}: backend=openai, base_url={config.base_url}, model={config.model}, "
                f"max_tokens={config.max_tokens}, key={_masked_key(config.api_key) if config.api_key else 'MISSING'}"
            )
        identity = (config.backend, config.base_url, config.api_key, config.model)
        grouped.setdefault(identity, {"config": config, "roles": []})["roles"].append(role)

    failed = False
    for item in grouped.values():
        roles = ", ".join(item["roles"])
        config = item["config"]
        if config.backend == "openai" and not config.api_key:
            print_error(f"配置失败 ({roles}): API Key 缺失")
            failed = True
            continue
        ok, detail = _probe_llm_config(config)
        if ok:
            print_success(f"配置可用 ({roles})")
        else:
            print_error(f"配置失败 ({roles}): {detail}")
            failed = True

    if failed:
        raise typer.Exit(1)
    print_success("全部 Agent 配置检查通过")


@app.command()
def init(
    name: str = typer.Argument(help="竞赛工作空间名称，如 2025_cumcm_A"),
    problem: str = typer.Option("A", help="题目编号"),
    year: int = typer.Option(2025, help="年份"),
    title: str = typer.Option("", help="正式论文题目"),
    team_number: str = typer.Option("", help="参赛队号"),
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
    config = CompetitionConfig(
        name=name, year=year, problem=problem, title=title, team_number=team_number
    )
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

    if _run_stage(target, mgr.workspace, mgr) is False:
        raise typer.Exit(1)


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


@app.command()
def audit(
    workspace: Optional[str] = typer.Option(None, "--workspace", "-w", help="工作空间名称"),
):
    """纯本地审计论文数值出处，不向 LLM 发送论文内容。"""
    mgr, _ = _get_mgr(workspace)
    from mmw.pipeline.stage_review import build_numeric_audit

    try:
        report, audit_md = build_numeric_audit(mgr.workspace, mgr)
    except ValueError as exc:
        print_error(str(exc))
        raise typer.Exit(1) from exc
    console.print(audit_md)
    if report.unmatched_high:
        raise typer.Exit(1)


@app.command()
def benchmark(
    case: str = typer.Option(..., "--case", help="test_cases 下的案例目录名"),
    workspace: str = typer.Option(..., "--workspace", "-w", help="工作空间名称"),
    stage: str = typer.Option("solve", "--stage", help="评估 code 或 solve"),
    version: Optional[int] = typer.Option(None, "--version", "-v", help="版本号（默认激活版本）"),
):
    """使用不进入 Agent 上下文的真题 Oracle 独立评估结果。"""
    from mmw.benchmark import (
        BenchmarkInputError,
        evaluate_benchmark,
        render_benchmark_markdown,
        write_benchmark_report,
    )

    if Path(case).name != case or "/" in case or "\\" in case:
        print_error("--case 必须是 test_cases 下的单个目录名")
        raise typer.Exit(2)
    try:
        stage_id = StageID(stage)
    except ValueError as exc:
        print_error("--stage 只支持 code 或 solve")
        raise typer.Exit(2) from exc
    if stage_id not in {StageID.CODE, StageID.SOLVE}:
        print_error("--stage 只支持 code 或 solve")
        raise typer.Exit(2)

    ws = _get_workspace(workspace)
    cases_root = Path(__file__).resolve().parent.parent / "test_cases"
    case_dir = (cases_root / case).resolve()
    if not case_dir.is_relative_to(cases_root.resolve()):
        print_error("--case 必须位于 test_cases 下")
        raise typer.Exit(2)
    try:
        report = evaluate_benchmark(
            case_dir,
            CheckpointManager(ws),
            stage_id,
            version,
        )
    except BenchmarkInputError as exc:
        print_error(str(exc))
        raise typer.Exit(2) from exc

    json_path, md_path = write_benchmark_report(ws, report)
    console.print(render_benchmark_markdown(report))
    print_info(f"报告: {json_path} / {md_path}")
    if not report["overall_passed"]:
        raise typer.Exit(1)
    print_success("benchmark 通过")


@app.command("benchmark-suite")
def benchmark_suite(
    suite: str = typer.Option("core-v1", "--suite", help="benchmark_suite.json 中的套件名"),
    workspace_map: Optional[list[str]] = typer.Option(
        None, "--workspace-map", help="案例=工作区路径，可重复指定",
    ),
    output: Path = typer.Option(Path("output"), "--output", help="汇总报告目录"),
):
    """顺序运行多个独立 benchmark，并输出最低可信等级。"""
    from mmw.benchmark import (
        BenchmarkInputError,
        evaluate_benchmark_suite,
        render_benchmark_suite_markdown,
        write_benchmark_suite_report,
    )

    mapping: dict[str, Path] = {}
    for item in workspace_map or []:
        case, separator, raw_path = item.partition("=")
        if not separator or not case.strip() or not raw_path.strip():
            print_error("--workspace-map 格式必须为 案例=工作区路径")
            raise typer.Exit(2)
        if Path(case).name != case or "/" in case or "\\" in case:
            print_error("--workspace-map 的案例名必须是单个目录名")
            raise typer.Exit(2)
        candidate = Path(raw_path).expanduser()
        mapping[case] = (
            candidate.resolve() if candidate.is_dir()
            else _get_workspace(raw_path)
        )
    cases_root = Path(__file__).resolve().parent.parent / "test_cases"
    try:
        report = evaluate_benchmark_suite(
            cases_root / "benchmark_suite.json",
            suite,
            cases_root,
            mapping,
        )
    except BenchmarkInputError as error:
        print_error(str(error))
        raise typer.Exit(2) from error
    json_path, md_path = write_benchmark_suite_report(output.resolve(), report)
    console.print(render_benchmark_suite_markdown(report))
    print_info(f"报告: {json_path} / {md_path}")
    if not report["overall_passed"]:
        raise typer.Exit(1)
    print_success("benchmark suite 通过")


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
    if not run_model_branch(mgr.workspace, mgr):
        raise typer.Exit(1)


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
    if not run_compare_model(mgr.workspace, mgr, v1, v2):
        raise typer.Exit(1)


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


# ── paper polish / compile ───────────────────────────────


@app.command("polish-figures")
def polish_figures_command(
    workspace: Optional[str] = typer.Option(None, "--workspace", "-w", help="工作空间名称"),
):
    """重制当前图表并生成新的 solve 检查点。"""
    from mmw.pipeline.stage_solve import rerun_figure_polish

    mgr, _ = _get_mgr(workspace)
    try:
        version_dir = rerun_figure_polish(mgr.workspace, mgr)
    except ValueError as error:
        print_error(str(error))
        raise typer.Exit(1) from error
    print_success(f"图表重制完成：{version_dir}")


@app.command()
def typeset(
    workspace: Optional[str] = typer.Option(None, "--workspace", "-w", help="工作空间名称"),
):
    """自动整理当前论文并生成新的 paper 检查点。"""
    from mmw.pipeline.stage_paper import rerun_typesetter

    mgr, _ = _get_mgr(workspace)
    try:
        version_dir = rerun_typesetter(mgr.workspace, mgr)
    except ValueError as error:
        print_error(str(error))
        raise typer.Exit(1) from error
    print_success(f"自动排版完成：{version_dir}")


def _solve_figure_manifest(mgr: CheckpointManager) -> dict | None:
    raw = mgr.load_artifacts(StageID.SOLVE).get("figure_manifest.json", "")
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) and isinstance(data.get("figures"), list) else None


@app.command("layout-check")
def layout_check(
    workspace: Optional[str] = typer.Option(None, "--workspace", "-w", help="工作空间名称"),
):
    """检查现有 paper.pdf 的版式、日志和图表质量。"""
    from mmw.utils.file_io import read_yaml
    from mmw.utils.layout_quality import inspect_layout

    mgr, _ = _get_mgr(workspace)
    paths = mgr.paths
    config = read_yaml(paths.config) if paths.config.is_file() else {}
    paper_version = mgr.get_active_version(StageID.PAPER) or mgr.get_latest_version(StageID.PAPER)
    report = inspect_layout(
        paths.output / "paper.pdf",
        paths.output / "latex_build" / f"paper_v{paper_version}" / "main.log",
        max_pages=int(config.get("max_pages", 20)),
        paper_version=paper_version,
        manifest=_solve_figure_manifest(mgr),
        figures_dir=paths.figures,
        output_dir=paths.output,
        allow_test_placeholders=bool(config.get("allow_test_placeholders", False)),
    )
    if report["passed"]:
        print_success("论文视觉质量检查通过")
        return
    print_error("；".join(report["failures"]))
    raise typer.Exit(1)


@app.command()
def compile(
    workspace: Optional[str] = typer.Option(None, "--workspace", "-w", help="工作空间名称"),
):
    """编译 LaTeX 论文为 PDF。"""
    from mmw.latex.compiler import (
        assemble_main_tex, compile_latex, find_unsafe_tex, prepare_compile_dir,
    )

    mgr, _ = _get_mgr(workspace)
    ws = mgr.workspace

    paper_version = mgr.get_active_version(StageID.PAPER)
    if paper_version == 0:
        print_error("请先完成论文写作阶段")
        raise typer.Exit(1)

    if not mgr.is_approved(StageID.PAPER, paper_version) or not mgr.is_approved(StageID.REVIEW):
        print_error("paper/review 尚未审批，不能编译正式提交 PDF")
        raise typer.Exit(1)
    paper_dir = mgr._version_dir(StageID.PAPER, paper_version)
    unsafe_tex = find_unsafe_tex(paper_dir)
    if unsafe_tex:
        print_error(f"论文包含不安全的 LaTeX 文件读取命令: {', '.join(unsafe_tex)}")
        raise typer.Exit(1)
    compile_dir = prepare_compile_dir(ws, paper_dir, f"paper_v{paper_version}")

    config_path = mgr.paths.config
    title = ""
    team_number = ""
    problem = ""
    max_pages = 20
    if config_path.exists():
        from mmw.utils.file_io import read_yaml
        cfg = read_yaml(config_path)
        title = str(cfg.get("title", "")).strip()
        team_number = str(cfg.get("team_number", "")).strip()
        problem = str(cfg.get("problem", "")).strip()
        max_pages = int(cfg.get("max_pages", 20))
    if not title or not team_number or not problem:
        print_error("config.yaml 必须填写 title、team_number 和 problem 后才能编译")
        raise typer.Exit(1)

    main_content = assemble_main_tex(
        paper_dir, title=title, team_number=team_number, problem=problem, workspace=ws
    )
    (compile_dir / "main.tex").write_text(main_content, encoding="utf-8")

    print_info(f"编译目录: {compile_dir}")
    success, msg = compile_latex(compile_dir, max_pages=max_pages)

    if success:
        import shutil
        from mmw.utils.layout_quality import inspect_layout

        pdf_path = compile_dir / "main.pdf"
        output_pdf = ws / "output" / "paper.pdf"
        shutil.copy2(pdf_path, output_pdf)
        layout_report = inspect_layout(
            output_pdf,
            compile_dir / "main.log",
            max_pages=max_pages,
            paper_version=paper_version,
            manifest=_solve_figure_manifest(mgr),
            figures_dir=mgr.paths.figures,
            output_dir=mgr.paths.output,
            allow_test_placeholders=bool(cfg.get("allow_test_placeholders", False)),
        )
        versions = {
            stage.value: mgr.get_active_version(stage)
            for stage in (StageID.CODE, StageID.SOLVE, StageID.PAPER, StageID.REVIEW)
        }
        manifest = {
            "versions": versions,
            "pdf_sha256": hashlib.sha256(output_pdf.read_bytes()).hexdigest(),
        }
        (ws / "output" / "paper_manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        if not layout_report["passed"]:
            print_error("PDF 已生成，但视觉质量门禁未通过：" + "；".join(layout_report["failures"]))
            raise typer.Exit(1)
        print_success(f"PDF 已生成: {output_pdf}")
    else:
        print_error(msg)
        raise typer.Exit(1)


# ── export ───────────────────────────────────────────────


@app.command(name="export")
def export_submission(
    workspace: Optional[str] = typer.Option(None, "--workspace", "-w", help="工作空间名称"),
):
    """打包提交文件（PDF + 代码 + 支撑材料）。"""
    import zipfile

    mgr, sm = _get_mgr(workspace)
    ws = mgr.workspace
    output_dir = ws / "output"

    for stage_id in (StageID.CODE, StageID.SOLVE, StageID.PAPER, StageID.REVIEW):
        if not mgr.is_approved(stage_id):
            print_error(f"{stage_id.value} 阶段尚未审批，不能导出提交包")
            raise typer.Exit(1)
        quality_error = sm.quality_error(stage_id)
        if quality_error:
            print_error(f"{stage_id.value} 质量门禁未通过: {quality_error}")
            raise typer.Exit(1)

    pdf_path = output_dir / "paper.pdf"
    if not pdf_path.exists():
        print_error("未找到 paper.pdf，请先运行 mmw compile")
        raise typer.Exit(1)
    manifest_path = output_dir / "paper_manifest.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        print_error("缺少合法 paper_manifest.json，请重新运行 mmw compile")
        raise typer.Exit(1)
    active_versions = {
        stage.value: mgr.get_active_version(stage)
        for stage in (StageID.CODE, StageID.SOLVE, StageID.PAPER, StageID.REVIEW)
    }
    if manifest.get("versions") != active_versions or manifest.get("pdf_sha256") != hashlib.sha256(pdf_path.read_bytes()).hexdigest():
        print_error("paper.pdf 与当前激活版本不一致，请重新运行 mmw compile")
        raise typer.Exit(1)
    try:
        layout_quality = json.loads((output_dir / "layout_quality.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        print_error("缺少合法 layout_quality.json，请重新运行 mmw compile")
        raise typer.Exit(1)
    if (
        not layout_quality.get("passed")
        or layout_quality.get("paper_version") != mgr.get_active_version(StageID.PAPER)
        or layout_quality.get("pdf_sha256") != manifest.get("pdf_sha256")
    ):
        print_error("论文视觉质量报告未通过或与当前 PDF 不一致")
        raise typer.Exit(1)

    from mmw.pipeline.stage_code import load_deliverables

    deliverable_names = {d["file"] for d in load_deliverables(mgr)}
    missing = [
        name
        for name in sorted(deliverable_names)
        if not mgr.paths.deliverable(name).is_file()
        or mgr.paths.deliverable(name).stat().st_size == 0
    ]
    if missing:
        print_error(f"题目要求的交付文件缺失或为空，已取消导出: {', '.join(missing)}")
        raise typer.Exit(1)

    zip_path = output_dir / "submission.zip"
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.write(pdf_path, "paper.pdf")

        code_arts = mgr.load_artifacts(StageID.CODE)
        if "solution.py" in code_arts:
            zf.writestr("code/solution.py", code_arts["solution.py"])
        if code_arts.get("identifiability.json"):
            zf.writestr(
                "verification/identifiability.json",
                code_arts["identifiability.json"],
            )

        figures_dir = mgr.paths.figures
        solve_arts = mgr.load_artifacts(StageID.SOLVE)
        for name in ("results.json", "sensitivity.json"):
            if solve_arts.get(name):
                zf.writestr(f"data/{name}", solve_arts[name])
        benchmark_path = output_dir / "benchmark.json"
        if benchmark_path.is_file():
            zf.write(benchmark_path, "verification/benchmark.json")
        zf.writestr("verification/layout_quality.json", json.dumps(
            layout_quality, ensure_ascii=False, indent=2
        ))
        numeric_audit = mgr.load_artifacts(StageID.REVIEW).get("numeric_audit.md")
        if numeric_audit:
            zf.writestr("verification/numeric_audit.md", numeric_audit)
        method_evidence = {
            StageID.MODEL: ("method_contract.json",),
            StageID.CODE: ("method_contract.json",),
            StageID.SOLVE: (
                "method_contract.json", "method_runtime.json", "method_validation.json",
            ),
            StageID.PAPER: ("method_contract.json", "method_traceability.json"),
            StageID.REVIEW: ("method_consistency.json",),
        }
        for stage, names in method_evidence.items():
            artifacts = mgr.load_artifacts(stage)
            for name in names:
                if artifacts.get(name):
                    zf.writestr(f"verification/method/{stage.value}_{name}", artifacts[name])
        try:
            figure_names = json.loads(solve_arts.get("figures_list.json", "[]"))
        except json.JSONDecodeError:
            figure_names = []
        for name in figure_names:
            fig = figures_dir / Path(str(name)).name
            if fig.is_file():
                zf.write(fig, f"figures/{fig.name}")
        try:
            figure_manifest = json.loads(solve_arts.get("figure_manifest.json", "{}"))
        except json.JSONDecodeError:
            figure_manifest = {}
        for item in figure_manifest.get("figures", []):
            relative = Path(str(item.get("data_file", "")).replace("\\", "/"))
            if (
                len(relative.parts) != 2
                or relative.parts[0] != "figure_data"
                or relative.suffix.lower() != ".csv"
            ):
                continue
            data_file = mgr.paths.result_data / relative
            if data_file.is_file():
                zf.write(data_file, f"figures/data/{data_file.name}")
        for name in ("figure_manifest.json", "renderer.json", "figure_quality_report.json"):
            if solve_arts.get(name):
                zf.writestr(f"figures/{name}", solve_arts[name])

        # 题目硬性交付文件（analyze 清单 + 兜底匹配 result*.xlsx），solution.py 生成在 workspace 根
        for name in sorted(deliverable_names):
            fpath = mgr.paths.deliverable(name)
            if fpath.exists():
                zf.write(fpath, name)

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


@app.command()
def gui(
    port: int = typer.Option(8765, help="本机监听端口"),
    no_browser: bool = typer.Option(False, "--no-browser", help="不自动打开浏览器"),
):
    """启动仅监听 127.0.0.1 的工作流审查 GUI。"""
    from mmw.gui.server import serve_gui

    serve_gui(port=port, open_browser=not no_browser)


def main():
    app()


if __name__ == "__main__":
    main()
