"""在 Origin 内置 Python 中运行；由 COM 调用，不依赖外部 OriginExt。"""

from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path
from typing import Any

import originpro as op


ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
OUTPUT_DIR = ROOT / "outputs" / "origin"
REPORT_DIR = ROOT / "reports"
STYLE = json.loads((ROOT / "style_contract.json").read_text(encoding="utf-8"))
COLORS: dict[str, str] = STYLE["colors"]
PALETTE = [COLORS["primary"], COLORS["accent"], COLORS["teal"], COLORS["purple"]]
UNSUPPORTED = {
    "03_distribution": "Origin 首轮不自动构造雨云图",
    "05_heatmap": "现有 Origin 后端未实现语义化发散热力图",
    "06_sensitivity": "现有 Origin 后端未实现水平 Tornado 图",
    "08_gantt": "现有 Origin 后端未实现甘特图",
}


def _hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _safe_label(value: str) -> str:
    return value.translate(str.maketrans("", "", "{};\r\n"))[:160]


def _read_columns(path: Path, columns: list[str]) -> dict[str, list[Any]]:
    output: dict[str, list[Any]] = {name: [] for name in columns}
    with path.open("r", encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            for name in columns:
                raw = row[name]
                try:
                    value: Any = float(raw)
                except ValueError:
                    value = raw
                output[name].append(value)
    return output


def _sheet(columns: dict[str, list[Any]], labels: dict[str, str] | None = None) -> Any:
    sheet = op.new_sheet("w")
    for index, (name, values) in enumerate(columns.items()):
        sheet.from_list(index, values, lname=(labels or {}).get(name, name))
    return sheet


def _export(graph: Any, figure_id: str) -> str:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    target = OUTPUT_DIR / f"{figure_id}.png"
    exported = graph.save_fig(str(target), type="png", width=1800)
    if not exported or not target.is_file():
        raise RuntimeError(f"Origin 导出失败：{figure_id}")
    return target.relative_to(ROOT).as_posix()


def _time_series() -> dict[str, Any]:
    figure_id = "01_time_series"
    source = DATA_DIR / f"{figure_id}.csv"
    columns = _read_columns(source, ["day", "observed", "forecast", "lower_95", "upper_95"])
    sheet = _sheet(columns, {
        "day": "时间（天）", "observed": "观测值", "forecast": "预测值",
        "lower_95": "95% 下界", "upper_95": "95% 上界",
    })
    graph = op.new_graph(template="line")
    layer = graph[0]
    for index in range(1, 5):
        plot = layer.add_plot(sheet, coly=index, colx=0, type="l")
        plot.color = [COLORS["text"], COLORS["primary"], COLORS["primary"], COLORS["primary"]][index - 1]
        plot.set_cmd("-w 4" if index <= 2 else "-w 2")
    layer.group()
    layer.axis("x").title = _safe_label("时间（天）")
    layer.axis("y").title = _safe_label("需求量（单位/天）")
    layer.rescale()
    return {
        "id": figure_id, "status": "degraded",
        "reason": "Origin 首轮以四条曲线表达区间，尚未实现半透明带",
        "data_sha256": _hash(source), "png": _export(graph, figure_id),
    }


def _scatter_fit() -> dict[str, Any]:
    figure_id = "02_scatter_fit"
    source = DATA_DIR / f"{figure_id}.csv"
    columns = _read_columns(source, ["x", "observed", "fitted", "lower_95", "upper_95"])
    sheet = _sheet(columns, {
        "x": "解释变量 x", "observed": "观测值", "fitted": "线性拟合",
        "lower_95": "95% 下界", "upper_95": "95% 上界",
    })
    graph = op.new_graph(template="scatter")
    layer = graph[0]
    points = layer.add_plot(sheet, coly=1, colx=0, type="s")
    points.color = COLORS["neutral_dark"]; points.symbol_size = 7
    for index, color in ((2, COLORS["accent"]), (3, COLORS["primary"]), (4, COLORS["primary"])):
        line = layer.add_plot(sheet, coly=index, colx=0, type="l")
        line.color = color; line.set_cmd("-w 4" if index == 2 else "-w 2")
    layer.axis("x").title = _safe_label("解释变量 x（单位）")
    layer.axis("y").title = _safe_label("响应变量 y（单位）")
    layer.rescale()
    return {"id": figure_id, "status": "rendered", "data_sha256": _hash(source), "png": _export(graph, figure_id)}


def _grouped_bar() -> dict[str, Any]:
    figure_id = "04_grouped_comparison"
    source = DATA_DIR / f"{figure_id}.csv"
    columns = _read_columns(source, ["scenario", "baseline", "method_a", "method_b"])
    sheet = _sheet(columns, {
        "scenario": "场景", "baseline": "基准", "method_a": "方法 A", "method_b": "方法 B",
    })
    graph = op.new_graph(template="column")
    layer = graph[0]
    for index in range(1, 4):
        plot = layer.add_plot(sheet, coly=index, colx=0, type="c")
        plot.color = [COLORS["neutral"], COLORS["primary"], COLORS["accent"]][index - 1]
    layer.group()
    layer.axis("x").title = _safe_label("场景")
    layer.axis("y").title = _safe_label("综合得分（分）")
    layer.rescale()
    return {"id": figure_id, "status": "rendered", "data_sha256": _hash(source), "png": _export(graph, figure_id)}


def _pareto() -> dict[str, Any]:
    figure_id = "07_pareto"
    source = DATA_DIR / f"{figure_id}.csv"
    columns = _read_columns(source, ["cost", "emissions", "is_pareto"])
    dominated_cost: list[float] = []
    dominated_emissions: list[float] = []
    front_pairs: list[tuple[float, float]] = []
    for cost, emissions, flag in zip(columns["cost"], columns["emissions"], columns["is_pareto"]):
        if int(flag) == 1:
            front_pairs.append((float(cost), float(emissions)))
        else:
            dominated_cost.append(float(cost)); dominated_emissions.append(float(emissions))
    front_pairs.sort()
    dominated_sheet = _sheet({"cost": dominated_cost, "emissions": dominated_emissions})
    front_sheet = _sheet({
        "cost": [item[0] for item in front_pairs],
        "emissions": [item[1] for item in front_pairs],
    })
    graph = op.new_graph(template="scatter")
    layer = graph[0]
    background = layer.add_plot(dominated_sheet, coly=1, colx=0, type="s")
    background.color = COLORS["neutral"]; background.symbol_size = 6
    curve = layer.add_plot(front_sheet, coly=1, colx=0, type="l")
    curve.color = COLORS["primary"]; curve.set_cmd("-w 4")
    layer.axis("x").title = _safe_label("成本（万元）")
    layer.axis("y").title = _safe_label("排放量（tCO2）")
    layer.rescale()
    return {"id": figure_id, "status": "rendered", "data_sha256": _hash(source), "png": _export(graph, figure_id)}


def main() -> None:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    reports: list[dict[str, Any]] = []
    for figure_id, renderer in (
        ("01_time_series", _time_series),
        ("02_scatter_fit", _scatter_fit),
        ("04_grouped_comparison", _grouped_bar),
        ("07_pareto", _pareto),
    ):
        try:
            reports.append(renderer())
        except Exception as error:
            reports.append({"id": figure_id, "status": "failed", "reason": f"{type(error).__name__}: {error}"})
    for figure_id, reason in UNSUPPORTED.items():
        reports.append({"id": figure_id, "status": "unsupported", "reason": reason})
    reports.sort(key=lambda item: item["id"])
    payload = {
        "schema_version": 1,
        "backend": "origin",
        "palette_id": STYLE["palette_id"],
        "bridge": "embedded_python_via_com",
        "originpro_version": getattr(op, "__version__", None),
        "passed": not any(item["status"] == "failed" for item in reports),
        "figures": reports,
    }
    (REPORT_DIR / "origin_renderer.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    if not payload["passed"]:
        raise RuntimeError("一个或多个 Origin 图生成失败")


if __name__ == "__main__":
    main()
