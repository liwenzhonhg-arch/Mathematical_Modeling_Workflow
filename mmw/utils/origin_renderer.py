"""Origin 2024 可选绘图后端；不可用时逐图回退 Matplotlib。"""

from __future__ import annotations

import hashlib
import importlib
import platform
from pathlib import Path
from typing import Any

import pandas as pd

from mmw.utils.figure_quality import inspect_figure, load_paper_style
from mmw.utils.figure_renderer import (
    _safe_data_path,
    _series,
    render_matplotlib_figure,
    render_matplotlib_manifest,
    select_palette_for_item,
)

_ORIGIN_CLSID = "{2F234A01-A4EB-4EAB-A130-A13C97953F0B}"


def _origin_executable() -> str | None:
    if platform.system() != "Windows":
        return None
    try:
        import winreg

        key = rf"CLSID\{_ORIGIN_CLSID}\LocalServer32"
        with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, key) as handle:
            value = str(winreg.QueryValue(handle, None)).strip().strip('"')
        return value if Path(value).is_file() else None
    except OSError:
        return None


def origin_status() -> dict[str, Any]:
    executable = _origin_executable()
    try:
        module = importlib.import_module("originpro")
    except ImportError:
        module = None
    return {
        "available": bool(executable and module),
        "executable": executable,
        "originpro_version": getattr(module, "__version__", None),
        "reason": None if executable and module else (
            "未发现 Origin 2024 Automation Server" if not executable else
            "未安装可选依赖 originpro"
        ),
    }


def _safe_label(value: Any) -> str:
    # LabTalk label 命令消费这些字符串；去掉命令分隔符，避免标题成为脚本。
    return str(value or "").translate(str.maketrans("", "", "{};\r\n")).strip()[:160]


def _render_origin_figure(
    op: Any,
    item: dict[str, Any],
    data_root: Path,
    figures_dir: Path,
    style: dict[str, Any],
) -> dict[str, Any]:
    if item.get("kind") == "heatmap":
        result = render_matplotlib_figure(item, data_root, figures_dir, style)
        return {**result, "fallback_reason": "Origin 首版不处理热力图"}

    data_path = _safe_data_path(data_root, str(item.get("data_file", "")))
    frame = pd.read_csv(data_path)
    if frame.empty:
        raise ValueError(f"{item['file']} 的 CSV 为空")
    x = item.get("x")
    if not isinstance(x, str) or x not in frame.columns:
        raise ValueError(f"{item['file']} 缺少 x 列")
    ys = _series(item, frame)

    sheet = op.new_sheet("w")
    sheet.from_df(frame[[x, *ys]])
    graph = op.new_graph(template={"line": "line", "scatter": "scatter", "bar": "column"}[item["kind"]])
    layer = graph[0]
    plot_type = {"line": "l", "scatter": "s", "bar": "c"}[item["kind"]]
    palette_info = select_palette_for_item(item, style)
    palette = palette_info["colors"]
    for index, name in enumerate(ys, start=1):
        plot = layer.add_plot(sheet, coly=index, colx=0, type=plot_type)
        plot.color = palette[(index - 1) % len(palette)]
        if item["kind"] == "line":
            plot.set_cmd("-w 4")
        elif item["kind"] == "scatter":
            plot.symbol_size = 7
    if len(ys) > 1:
        layer.group()
    else:
        legend = layer.label("Legend")
        if legend:
            legend.remove()
    layer.axis("x").title = _safe_label(item.get("x_label", x))
    layer.axis("y").title = _safe_label(item.get("y_label", ""))
    layer.rescale()

    figures_dir.mkdir(parents=True, exist_ok=True)
    target = figures_dir / item["file"]
    exported = graph.save_fig(str(target), type="png", width=1800)
    if not exported or not target.is_file():
        raise RuntimeError(f"Origin 导出失败：{item['file']}")
    quality = inspect_figure(target, style)
    return {
        **quality,
        "kind": item["kind"],
        "renderer": "origin",
        "data_sha256": hashlib.sha256(data_path.read_bytes()).hexdigest(),
        "palette_id": palette_info["palette_id"],
        "palette_colors": palette_info["colors"],
        "palette_roles": palette_info["role_map"],
        "secondary_encodings": palette_info["secondary_encodings"],
        "palette_warnings": palette_info["warnings"],
        "palette_backend_status": palette_info["backend_status"],
        "palette_catalog_sha256": palette_info["catalog_sha256"],
    }


def render_origin_manifest(
    manifest: dict[str, Any],
    data_root: Path,
    figures_dir: Path,
) -> dict[str, Any]:
    status = origin_status()
    if not status["available"]:
        reports = render_matplotlib_manifest(manifest, data_root, figures_dir)["figures"]
        reports = [{**item, "status": "degraded", "fallback_reason": status["reason"]} for item in reports]
        return {
            "schema_version": 1,
            "requested_renderer": "origin",
            "renderer": "matplotlib",
            "passed": all(item["passed"] for item in reports),
            "origin": status,
            "coverage": {"requested": len(reports), "rendered": 0, "degraded": len(reports), "unsupported": 0},
            "figures": reports,
        }

    op = importlib.import_module("originpro")
    reports: list[dict[str, Any]] = []
    allowed = set(load_paper_style()["figure"]["allowed_types"])
    try:
        op.set_show(False)
        for item in manifest["figures"]:
            if item.get("kind") not in allowed:
                report = inspect_figure(figures_dir / item["file"])
                report["warnings"].append(f"不支持 {item.get('kind')}，保留原图")
                reports.append({**report, "kind": item.get("kind"), "renderer": "original"})
                continue
            try:
                reports.append(_render_origin_figure(op, item, data_root, figures_dir, load_paper_style()))
            except Exception as error:
                reports.append({
                    **render_matplotlib_figure(item, data_root, figures_dir),
                    "fallback_reason": f"{type(error).__name__}: {error}",
                })
    finally:
        op.exit()
    actual = "origin" if any(item["renderer"] == "origin" for item in reports) else "matplotlib"
    degraded = sum(1 for item in reports if item.get("fallback_reason") or item.get("status") == "degraded")
    unsupported = sum(1 for item in reports if item.get("status") == "unsupported")
    return {
        "schema_version": 1,
        "requested_renderer": "origin",
        "renderer": actual,
        "passed": all(item["passed"] for item in reports),
        "origin": status,
        "coverage": {
            "requested": len(reports),
            "rendered": max(0, len(reports) - degraded - unsupported),
            "degraded": degraded,
            "unsupported": unsupported,
        },
        "figures": reports,
    }
