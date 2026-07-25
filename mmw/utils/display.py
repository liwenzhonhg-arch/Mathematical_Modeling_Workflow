"""Rich 终端显示工具。"""

from __future__ import annotations

import io
import sys

from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.table import Table

from mmw.models import CheckpointStatus, StageID

if sys.platform == "win32" and hasattr(sys.stdout, "buffer"):
    _stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    console = Console(file=_stdout, force_terminal=True)
else:
    console = Console()

STATUS_ICONS = {
    "pending": "[dim][ ] 待运行[/dim]",
    "completed": "[yellow][~] 待审批[/yellow]",
    "approved": "[green][v] 已审批[/green]",
}


def show_pipeline_status(status_list: list[dict]) -> None:
    """以表格展示流水线各阶段状态。"""
    table = Table(title="流水线状态", show_lines=True)
    table.add_column("#", justify="center", width=3)
    table.add_column("阶段", width=10)
    table.add_column("名称", width=10)
    table.add_column("版本", justify="center", width=14)
    table.add_column("状态", width=14)
    table.add_column("上游变更", justify="center", width=8)

    for entry in status_list:
        version_str = f"v{entry['version']}" if entry["version"] > 0 else "-"
        active = entry.get("active_version", 0)
        if active and active != entry["version"]:
            version_str += f" (激活:v{active})"
        status_str = STATUS_ICONS.get(entry["status"], entry["status"])
        upstream_str = "[red]! 是[/red]" if entry["upstream_changed"] else "[dim]-[/dim]"
        table.add_row(
            str(entry["index"]),
            entry["stage"],
            entry["label"],
            version_str,
            status_str,
            upstream_str,
        )
    console.print(table)


def show_artifacts(artifacts: dict[str, str], stage_label: str) -> None:
    """展示阶段产出内容。"""
    for name, content in artifacts.items():
        if name.endswith(".md"):
            console.print(Panel(Markdown(content), title=f"{stage_label} / {name}"))
        else:
            console.print(Panel(content, title=f"{stage_label} / {name}"))


def show_warnings(warnings: list[str]) -> None:
    """展示警告信息。"""
    for w in warnings:
        console.print(f"[yellow]! {w}[/yellow]")


def print_success(msg: str) -> None:
    console.print(f"[green][OK] {msg}[/green]")


def print_error(msg: str) -> None:
    console.print(f"[red][ERR] {msg}[/red]")


def print_warning(msg: str) -> None:
    console.print(f"[yellow][WARN] {msg}[/yellow]")


def print_info(msg: str) -> None:
    console.print(f"[blue][i] {msg}[/blue]")
