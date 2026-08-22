"""从受控 CSV/manifest 可复现地重制论文图表。"""

from __future__ import annotations

import hashlib
import importlib.util
from functools import lru_cache
import json
from pathlib import Path
from typing import Any

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from cycler import cycler

from mmw.utils.figure_quality import inspect_figure, load_paper_style


_PALETTE_SCRIPT = Path(__file__).resolve().parents[2] / "skills" / "scientific-chart-palette" / "scripts" / "select_palette.py"
_PALETTE_CATALOG = _PALETTE_SCRIPT.parent.parent / "references" / "palettes.json"


def _safe_data_path(root: Path, relative: str) -> Path:
    path = (root / relative).resolve()
    if not relative or not path.is_relative_to(root.resolve()) or path.suffix.casefold() != ".csv":
        raise ValueError(f"非法图表数据路径：{relative}")
    if not path.is_file():
        raise ValueError(f"图表数据不存在：{relative}")
    return path


def _series(item: dict[str, Any], frame: pd.DataFrame) -> list[str]:
    raw = item.get("y")
    columns = [raw] if isinstance(raw, str) else raw
    if not isinstance(columns, list) or not columns or any(not isinstance(name, str) for name in columns):
        raise ValueError(f"{item['file']} 缺少 y 列")
    missing = [name for name in columns if name not in frame.columns]
    if missing:
        raise ValueError(f"{item['file']} 缺少数据列：{', '.join(missing)}")
    return columns


@lru_cache(maxsize=1)
def _palette_module() -> Any:
    spec = importlib.util.spec_from_file_location("mmw_scientific_chart_palette", _PALETTE_SCRIPT)
    if spec is None or spec.loader is None:
        raise ImportError(f"无法加载配色 Skill：{_PALETTE_SCRIPT}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def select_palette_for_item(item: dict[str, Any], style: dict[str, Any] | None = None) -> dict[str, Any]:
    """为当前图表选择本地配色；Skill 缺失时回退到论文样式。"""
    style = style or load_paper_style()
    raw_series = item.get("y")
    series_count = len(raw_series) if isinstance(raw_series, list) else 1
    try:
        module = _palette_module()
        catalog = module.load_catalog(_PALETTE_CATALOG)
        selected = module.select_palette(
            catalog,
            chart_type=str(item.get("kind", "")),
            series_count=series_count,
            output_mode=str(item.get("output_mode", "print")),
            roles=item.get("roles") if isinstance(item.get("roles"), list) else None,
            scale_semantics=item.get("scale_semantics"),
            midpoint=item.get("midpoint"),
        )
        selected["catalog_sha256"] = hashlib.sha256(_PALETTE_CATALOG.read_bytes()).hexdigest()
        selected["palette_roles"] = item.get("roles", [])
        return selected
    except (OSError, ImportError, ValueError, TypeError, json.JSONDecodeError) as error:
        return {
            "palette_id": "paper-style-fallback-v1",
            "colors": list(style["figure"]["palette"]),
            "role_map": {},
            "secondary_encodings": [],
            "backend_status": {"matplotlib": "supported", "matlab": "supported", "origin": "validate-before-use"},
            "warnings": [f"配色 Skill 不可用，回退 paper_style：{type(error).__name__}: {error}"],
            "catalog_sha256": None,
            "palette_roles": [],
        }


def _apply_style(style: dict[str, Any], colors: list[str] | None = None) -> None:
    plt.rcParams.update({
        "font.sans-serif": ["Microsoft YaHei", "SimHei", "DejaVu Sans"],
        "axes.unicode_minus": False,
        "figure.figsize": (8, 5),
        "savefig.dpi": 300,
        "savefig.bbox": "tight",
        "savefig.pad_inches": 0.08,
        "axes.titlesize": 14,
        "axes.labelsize": 12,
        "xtick.labelsize": 10,
        "ytick.labelsize": 10,
        "legend.fontsize": 10,
        "lines.linewidth": 1.8,
        "lines.markersize": 5,
        "axes.linewidth": 0.8,
        "axes.grid": True,
        "grid.linestyle": "--",
        "grid.linewidth": 0.5,
        "grid.alpha": 0.3,
        "axes.spines.top": False,
        "axes.spines.right": False,
        "axes.prop_cycle": cycler(color=colors or style["figure"]["palette"]),
        "legend.frameon": False,
    })


def render_matplotlib_figure(
    item: dict[str, Any],
    data_root: Path,
    figures_dir: Path,
    style: dict[str, Any] | None = None,
) -> dict[str, Any]:
    style = style or load_paper_style()
    kind = item.get("kind")
    if kind not in style["figure"]["allowed_types"]:
        raise ValueError(f"不支持的图表类型：{kind}")
    data_path = _safe_data_path(data_root, str(item.get("data_file", "")))
    try:
        frame = pd.read_csv(data_path)
    except pd.errors.EmptyDataError as error:
        raise ValueError(f"{item['file']} 的 CSV 没有表头或数据") from error
    if frame.empty:
        raise ValueError(f"{item['file']} 的 CSV 为空")
    palette = select_palette_for_item(item, style)
    _apply_style(style, palette["colors"])
    fig, ax = plt.subplots(constrained_layout=True)

    if kind == "heatmap":
        required = [item.get(key) for key in ("x", "y", "value")]
        if any(not isinstance(name, str) or name not in frame.columns for name in required):
            raise ValueError(f"{item['file']} 的 heatmap 列配置非法")
        table = frame.pivot(index=required[1], columns=required[0], values=required[2])
        from matplotlib.colors import LinearSegmentedColormap

        cmap = LinearSegmentedColormap.from_list(palette["palette_id"], palette["colors"])
        image = ax.imshow(table.to_numpy(dtype=float), cmap=cmap, aspect="auto")
        ax.set_xticks(range(len(table.columns)), table.columns, rotation=45, ha="right")
        ax.set_yticks(range(len(table.index)), table.index)
        fig.colorbar(image, ax=ax, shrink=0.85)
        ax.grid(False)
    else:
        x = item.get("x")
        if not isinstance(x, str) or x not in frame.columns:
            raise ValueError(f"{item['file']} 缺少 x 列")
        ys = _series(item, frame)
        labels = item.get("series_labels")
        if not isinstance(labels, list) or len(labels) != len(ys):
            labels = ys
        group_column = None
        if kind == "bar":
            positions = np.arange(len(frame))
            width = 0.8 / len(ys)
            for index, (name, series_label) in enumerate(zip(ys, labels, strict=True)):
                ax.bar(
                    positions + (index - (len(ys) - 1) / 2) * width,
                    frame[name],
                    width,
                    label=series_label,
                )
            ax.set_xticks(positions, frame[x].astype(str))
        else:
            group_column = next(
                (name for name in ("series", "vehicle", "group") if name in frame.columns),
                None,
            )
            for name, series_label in zip(ys, labels, strict=True):
                groups = frame.groupby(group_column, sort=False) if group_column else [(None, frame)]
                for group_name, group in groups:
                    order_column = next(
                        (column for column in ("order", "sequence") if column in group.columns),
                        None,
                    )
                    if order_column:
                        group = group.sort_values(order_column)
                    label = (
                        f"车辆 {group_name}" if group_column == "vehicle"
                        else f"{group_column}={group_name}" if group_column
                        else series_label
                    )
                    is_route = group_column == "vehicle" and order_column is not None
                    if kind == "line" or is_route:
                        line = ax.plot(group[x], group[name], marker="o", label=label)[0]
                        if is_route:
                            points = list(zip(group[x], group[name]))
                            for start, end in zip(points, points[1:]):
                                ax.annotate(
                                    "",
                                    xy=end,
                                    xytext=start,
                                    arrowprops={
                                        "arrowstyle": "->",
                                        "color": line.get_color(),
                                        "lw": 1.2,
                                        "shrinkA": 4,
                                        "shrinkB": 4,
                                    },
                                )
                    else:
                        ax.scatter(group[x], group[name], label=label, alpha=0.85)
                    if len(ys) == 1 and "node" in group.columns:
                        for _, row in group.iterrows():
                            node = row["node"]
                            node_label = (
                                str(int(node))
                                if isinstance(node, (int, float, np.number)) and float(node).is_integer()
                                else str(node)
                            )
                            ax.annotate(
                                node_label,
                                (row[x], row[name]),
                                xytext=(4, 4),
                                textcoords="offset points",
                                fontsize=9,
                            )
        if len(ys) > 1 or group_column:
            ax.legend()

    ax.set_title(str(item.get("title", "")).strip())
    ax.set_xlabel(str(item.get("x_label", item.get("x", ""))).strip())
    ax.set_ylabel(str(item.get("y_label", "")).strip())
    figures_dir.mkdir(parents=True, exist_ok=True)
    target = figures_dir / item["file"]
    fig.savefig(target)
    plt.close(fig)
    quality = inspect_figure(target, style)
    return {
        **quality,
        "kind": kind,
        "renderer": "matplotlib",
        "data_sha256": hashlib.sha256(data_path.read_bytes()).hexdigest(),
        "palette_id": palette["palette_id"],
        "palette_colors": palette["colors"],
        "palette_roles": palette["role_map"],
        "secondary_encodings": palette["secondary_encodings"],
        "palette_warnings": palette["warnings"],
        "palette_backend_status": palette["backend_status"],
        "palette_catalog_sha256": palette["catalog_sha256"],
    }


def render_matplotlib_manifest(
    manifest: dict[str, Any],
    data_root: Path,
    figures_dir: Path,
) -> dict[str, Any]:
    allowed = set(load_paper_style()["figure"]["allowed_types"])
    reports = []
    for item in manifest["figures"]:
        if item.get("kind") not in allowed:
            report = inspect_figure(figures_dir / item["file"])
            report["warnings"].append(f"不支持 {item.get('kind')}，保留原图")
            reports.append({**report, "kind": item.get("kind"), "renderer": "original"})
        else:
            reports.append(render_matplotlib_figure(item, data_root, figures_dir))
    return {
        "schema_version": 1,
        "renderer": "matplotlib",
        "passed": all(item["passed"] for item in reports),
        "figures": reports,
    }
