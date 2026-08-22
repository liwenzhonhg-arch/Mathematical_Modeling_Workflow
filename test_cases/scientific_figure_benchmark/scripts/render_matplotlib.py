"""使用 Matplotlib 渲染八类科研绘图基准。"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.colors import LinearSegmentedColormap, TwoSlopeNorm
import numpy as np
import pandas as pd
from scipy.stats import gaussian_kde


ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
OUTPUT_DIR = ROOT / "outputs" / "matplotlib"
REPORT_DIR = ROOT / "reports"
STYLE = json.loads((ROOT / "style_contract.json").read_text(encoding="utf-8"))
COLORS: dict[str, str] = STYLE["colors"]


def _style() -> None:
    plt.rcParams.update({
        "font.sans-serif": ["Microsoft YaHei", "SimHei", "DejaVu Sans"],
        "axes.unicode_minus": False,
        "figure.figsize": (7.2, 4.6),
        "figure.dpi": 120,
        "savefig.dpi": 300,
        "savefig.bbox": "tight",
        "savefig.pad_inches": 0.06,
        "pdf.fonttype": 42,
        "ps.fonttype": 42,
        "axes.titlesize": 13,
        "axes.labelsize": 11,
        "xtick.labelsize": 9,
        "ytick.labelsize": 9,
        "legend.fontsize": 9,
        "lines.linewidth": 1.8,
        "axes.linewidth": 0.8,
        "axes.spines.top": False,
        "axes.spines.right": False,
        "legend.frameon": False,
        "axes.edgecolor": COLORS["text"],
        "axes.labelcolor": COLORS["text"],
        "axes.titlecolor": COLORS["text"],
        "xtick.color": COLORS["text"],
        "ytick.color": COLORS["text"],
        "text.color": COLORS["text"],
    })


def _finish_axes(ax: plt.Axes, grid_axis: str | None = "y") -> None:
    ax.set_axisbelow(True)
    if grid_axis:
        ax.grid(axis=grid_axis, color=COLORS["grid"], linewidth=0.65, alpha=0.85)


def _save(fig: plt.Figure, figure_id: str, source: Path) -> dict[str, object]:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    png = OUTPUT_DIR / f"{figure_id}.png"
    pdf = OUTPUT_DIR / f"{figure_id}.pdf"
    fig.savefig(png, facecolor="white")
    fig.savefig(pdf, facecolor="white")
    plt.close(fig)
    return {
        "id": figure_id,
        "status": "rendered",
        "data_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "png": png.relative_to(ROOT).as_posix(),
        "pdf": pdf.relative_to(ROOT).as_posix(),
    }


def render_time_series() -> dict[str, object]:
    source = DATA_DIR / "01_time_series.csv"
    frame = pd.read_csv(source)
    fig, ax = plt.subplots(layout="constrained")
    ax.fill_between(frame.day, frame.lower_95, frame.upper_95, color=COLORS["primary"], alpha=0.13, linewidth=0, label="95% 预测区间")
    ax.plot(frame.day, frame.observed, color=COLORS["text"], marker="o", markersize=2.6, markevery=3, linewidth=1.35, label="观测值")
    ax.plot(frame.day, frame.forecast, color=COLORS["primary"], linestyle="--", linewidth=2.1, label="预测值")
    ax.set(title="需求预测与 95% 预测区间", xlabel="时间（天）", ylabel="需求量（单位/天）")
    ax.legend(ncols=3, loc="upper left")
    ax.margins(x=0)
    _finish_axes(ax)
    return _save(fig, "01_time_series", source)


def render_scatter_fit() -> dict[str, object]:
    source = DATA_DIR / "02_scatter_fit.csv"
    frame = pd.read_csv(source)
    fig, ax = plt.subplots(layout="constrained")
    ax.fill_between(frame.x, frame.lower_95, frame.upper_95, color=COLORS["primary"], alpha=0.12, linewidth=0, label="95% 均值置信带")
    ax.scatter(frame.x, frame.observed, s=24, facecolors=COLORS["paper"], edgecolors=COLORS["neutral_dark"], linewidths=0.85, label="观测值")
    ax.plot(frame.x, frame.fitted, color=COLORS["accent"], linewidth=2.1, label="线性拟合")
    ax.set(title="变量关系与线性拟合", xlabel="解释变量 x（单位）", ylabel="响应变量 y（单位）")
    ax.legend(loc="upper left")
    _finish_axes(ax)
    return _save(fig, "02_scatter_fit", source)


def render_distribution() -> dict[str, object]:
    source = DATA_DIR / "03_distribution.csv"
    frame = pd.read_csv(source)
    groups = list(dict.fromkeys(frame.group))
    fig, ax = plt.subplots(layout="constrained")
    jitter_rng = np.random.default_rng(20260811)
    distribution_colors = [COLORS["primary"], COLORS["accent"], COLORS["teal"]]
    for index, (group, color) in enumerate(zip(groups, distribution_colors, strict=False)):
        values = frame.loc[frame.group == group, "value"].to_numpy()
        y_grid = np.linspace(values.min() - 3, values.max() + 3, 180)
        density = gaussian_kde(values)(y_grid)
        density = density / density.max() * 0.34
        ax.fill_betweenx(y_grid, index, index + density, color=color, alpha=0.22, linewidth=0)
        jitter = jitter_rng.uniform(-0.28, -0.06, len(values))
        ax.scatter(index + jitter, values, s=15, color=color, alpha=0.50, edgecolors="none")
        q1, median, q3 = np.quantile(values, [0.25, 0.5, 0.75])
        ax.plot([index, index], [q1, q3], color=COLORS["text"], linewidth=4.5, solid_capstyle="butt")
        ax.scatter([index], [median], s=32, facecolor=COLORS["paper"], edgecolor=COLORS["text"], zorder=5)
    ax.set_xticks(range(len(groups)), groups)
    ax.set(title="三种方案的结果分布", xlabel="方案", ylabel="指标值（分）")
    ax.set_xlim(-0.55, len(groups) - 0.45)
    _finish_axes(ax)
    return _save(fig, "03_distribution", source)


def render_grouped_comparison() -> dict[str, object]:
    source = DATA_DIR / "04_grouped_comparison.csv"
    frame = pd.read_csv(source)
    fig, ax = plt.subplots(layout="constrained")
    positions = np.arange(len(frame))
    width = 0.24
    series = [
        ("baseline", "基准", COLORS["neutral"], ""),
        ("method_a", "方法 A", COLORS["primary"], "/"),
        ("method_b", "方法 B", COLORS["accent"], "."),
    ]
    for index, (column, label, color, hatch) in enumerate(series):
        ax.bar(
            positions + (index - 1) * width,
            frame[column],
            width,
            color=color,
            label=label,
            hatch=hatch,
            edgecolor=COLORS["paper"],
            linewidth=0.7,
            zorder=3,
        )
    ax.set_xticks(positions, frame.scenario)
    ax.set_ylim(bottom=0)
    ax.set(title="不同场景下的方案得分", xlabel="场景", ylabel="综合得分（分）")
    ax.legend(ncols=3, loc="upper right")
    _finish_axes(ax)
    return _save(fig, "04_grouped_comparison", source)


def render_heatmap() -> dict[str, object]:
    source = DATA_DIR / "05_heatmap.csv"
    frame = pd.read_csv(source)
    table = frame.pivot(index="beta", columns="alpha", values="delta_score")
    values = table.to_numpy()
    limit = float(np.abs(values).max())
    fig, ax = plt.subplots(layout="constrained")
    cmap = LinearSegmentedColormap.from_list(
        "muted_diverging",
        [COLORS["heat_low"], COLORS["heat_mid"], COLORS["heat_high"]],
    )
    image = ax.imshow(values, cmap=cmap, norm=TwoSlopeNorm(vmin=-limit, vcenter=0, vmax=limit), aspect="auto", origin="lower")
    ax.set_xticks(range(len(table.columns)), [f"{value:.1f}" for value in table.columns])
    ax.set_yticks(range(len(table.index)), [f"{value:.1f}" for value in table.index])
    ax.set(title="参数组合相对基准的目标变化", xlabel="参数 α", ylabel="参数 β")
    colorbar = fig.colorbar(image, ax=ax, shrink=0.88)
    colorbar.set_label("目标变化（%）")
    colorbar.outline.set_edgecolor(COLORS["grid"])
    _finish_axes(ax, None)
    return _save(fig, "05_heatmap", source)


def render_sensitivity() -> dict[str, object]:
    source = DATA_DIR / "06_sensitivity.csv"
    frame = pd.read_csv(source)
    fig, ax = plt.subplots(layout="constrained")
    positions = np.arange(len(frame))
    ax.barh(positions, frame.low_effect, color=COLORS["primary"], label="参数降低", zorder=3)
    ax.barh(positions, frame.high_effect, color=COLORS["accent"], label="参数升高", zorder=3)
    ax.axvline(0, color=COLORS["text"], linewidth=0.85, zorder=4)
    ax.set_yticks(positions, frame.parameter)
    ax.set(title="参数敏感性 Tornado 图", xlabel="目标相对变化（%）", ylabel="参数")
    ax.legend(ncols=2, loc="lower right")
    _finish_axes(ax, "x")
    return _save(fig, "06_sensitivity", source)


def render_pareto() -> dict[str, object]:
    source = DATA_DIR / "07_pareto.csv"
    frame = pd.read_csv(source)
    front = frame.loc[frame.is_pareto == 1].sort_values("cost")
    dominated = frame.loc[frame.is_pareto == 0]
    fig, ax = plt.subplots(layout="constrained")
    ax.scatter(dominated.cost, dominated.emissions, s=24, color=COLORS["neutral"], alpha=0.58, edgecolors="none", label="被支配候选")
    ax.plot(front.cost, front.emissions, color=COLORS["primary"], marker="o", markersize=4.3, markerfacecolor=COLORS["paper"], markeredgewidth=1.1, label="当前有限候选前沿")
    ax.set(title="成本与排放的有限候选权衡", xlabel="成本（万元）", ylabel=r"排放量（tCO$_2$）")
    ax.legend(loc="upper right")
    _finish_axes(ax, "both")
    return _save(fig, "07_pareto", source)


def render_gantt() -> dict[str, object]:
    source = DATA_DIR / "08_gantt.csv"
    frame = pd.read_csv(source)
    resources = list(dict.fromkeys(frame.resource))
    categories = list(dict.fromkeys(frame.category))
    gantt_colors = [COLORS["primary"], COLORS["teal"], COLORS["accent"], COLORS["purple"]]
    color_map = dict(zip(categories, gantt_colors, strict=False))
    fig, ax = plt.subplots(layout="constrained")
    for row in frame.itertuples(index=False):
        y = resources.index(row.resource)
        ax.barh(y, row.duration, left=row.start, height=0.58, color=color_map[row.category], edgecolor=COLORS["paper"], linewidth=0.8, zorder=3)
        ax.text(row.start + row.duration / 2, y, row.task_id, ha="center", va="center", fontsize=8, color="white", weight="bold")
    handles = [plt.Rectangle((0, 0), 1, 1, color=color_map[name]) for name in categories]
    ax.legend(handles, categories, ncols=len(categories), loc="upper center")
    ax.set_yticks(range(len(resources)), resources)
    ax.invert_yaxis()
    ax.set_xlim(left=0)
    ax.set(title="多资源任务调度甘特图", xlabel="时间（小时）", ylabel="资源")
    _finish_axes(ax, "x")
    return _save(fig, "08_gantt", source)


def main() -> None:
    _style()
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    results = [
        render_time_series(),
        render_scatter_fit(),
        render_distribution(),
        render_grouped_comparison(),
        render_heatmap(),
        render_sensitivity(),
        render_pareto(),
        render_gantt(),
    ]
    payload = {
        "schema_version": 1,
        "backend": "matplotlib",
        "palette_id": STYLE["palette_id"],
        "figures": results,
    }
    (REPORT_DIR / "matplotlib_renderer.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
