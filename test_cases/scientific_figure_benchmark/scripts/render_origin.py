"""用本机 Origin 自动化渲染当前可稳定表达的基准图。"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys
from typing import Any

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from mmw.utils.origin_renderer import origin_status


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
COM_FIGURES = ("01_time_series", "02_scatter_fit", "04_grouped_comparison", "07_pareto")


def _hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _safe_label(value: str) -> str:
    return value.translate(str.maketrans("", "", "{};\r\n"))[:160]


def _export(graph: Any, figure_id: str) -> str:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    target = OUTPUT_DIR / f"{figure_id}.png"
    exported = graph.save_fig(str(target), type="png", width=1800)
    if not exported or not target.is_file():
        raise RuntimeError(f"Origin 导出失败：{figure_id}")
    return target.relative_to(ROOT).as_posix()


def _put_column(origin: Any, book: str, column: int, values: Any) -> None:
    """Write one worksheet column through Origin's COM bridge."""

    rows = [[value.item() if hasattr(value, "item") else value] for value in values]
    if not origin.PutWorksheet(book, rows, 0, column):
        raise RuntimeError(f"Origin 写入工作表失败：{book} col={column}")


def _execute(origin: Any, command: str, context: str) -> None:
    if not origin.Execute(command):
        raise RuntimeError(f"Origin LabTalk 命令失败（{context}）：{command}")


def _com_export(origin: Any, figure_id: str) -> str:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    target = OUTPUT_DIR / f"{figure_id}.png"
    command = (
        f'expGraph type:=png filename:="{target.stem}" '
        f'path:="{OUTPUT_DIR.as_posix()}" overwrite:=replace '
        "tr1.unit:=2 tr1.width:=1800 tr2.PNG.dotsperinch:=300;"
    )
    _execute(origin, command, f"export {figure_id}")
    if not target.is_file() or target.stat().st_size == 0:
        raise RuntimeError(f"Origin 导出文件不存在：{target}")
    return target.relative_to(ROOT).as_posix()


def _com_labels(origin: Any, x_label: str, y_label: str) -> None:
    _execute(origin, f'label -xb "{_safe_label(x_label)}";', "x label")
    _execute(origin, f'label -yl "{_safe_label(y_label)}";', "y label")
    _execute(origin, "layer -a;", "rescale")


def _com_long_names(origin: Any, book: str, names: list[str]) -> None:
    assignments = " ".join(
        f'wks.col{index}.lname$="{_safe_label(name)}";'
        for index, name in enumerate(names, start=1)
    )
    _execute(origin, f"win -a {book}; {assignments}", "column long names")


def _com_plot_styles(
    origin: Any,
    graph_name: str,
    styles: list[tuple[str, float | None]],
) -> list[str]:
    failures: list[str] = []
    for index, (role, width) in enumerate(styles, start=1):
        color_command = f"win -a {graph_name}; layer.plot{index}.color=color({COLORS[role]});"
        if not origin.Execute(color_command):
            failures.append(f"plot{index}.color")
        if width is not None:
            width_command = f"win -a {graph_name}; layer.plot{index}.line.width={width};"
            if not origin.Execute(width_command):
                failures.append(f"plot{index}.line.width")
    return failures


def _render_direct_com(origin: Any, figure_id: str) -> dict[str, object]:
    """Render the stable Origin subset without requiring external-originpro."""

    source = DATA_DIR / f"{figure_id}.csv"
    frame = pd.read_csv(source)
    book = origin.CreatePage(2, f"B{figure_id[:2]}", "origin")
    graph_name = f"G{figure_id[:2]}"
    style_failures: list[str] = []
    if not book:
        raise RuntimeError(f"Origin 无法创建工作簿：{figure_id}")

    if figure_id == "01_time_series":
        columns = ["day", "observed", "forecast", "lower_95", "upper_95"]
        for index, name in enumerate(columns):
            _put_column(origin, book, index, frame[name].to_numpy())
        _com_long_names(origin, book, ["Time", "Observed", "Forecast", "95% Lower", "95% Upper"])
        _execute(
            origin,
            f"win -a {book}; plotxy iy:=(1,2:5) plot:=200 ogl:=<new name:={graph_name}>;",
            figure_id,
        )
        origin.Execute(f"win -a {graph_name}; layer -gu;")
        style_failures.extend(_com_plot_styles(
            origin,
            graph_name,
            [("text", 2.0), ("primary", 3.0), ("primary", 1.2), ("primary", 1.2)],
        ))
        origin.Execute(f"win -a {graph_name}; legend -r;")
        _com_labels(origin, "时间（天）", "需求量（单位/天）")
        result: dict[str, object] = {
            "id": figure_id,
            "status": "degraded",
            "reason": "Origin COM 首轮以四条曲线表达区间，尚未实现半透明带",
        }
    elif figure_id == "02_scatter_fit":
        columns = ["x", "observed", "fitted", "lower_95", "upper_95"]
        for index, name in enumerate(columns):
            _put_column(origin, book, index, frame[name].to_numpy())
        _com_long_names(origin, book, ["X", "Observed", "Fitted", "95% Lower", "95% Upper"])
        _execute(
            origin,
            f"win -a {book}; plotxy iy:=(1,2) plot:=201 ogl:=<new name:={graph_name}>;",
            f"{figure_id} scatter",
        )
        _execute(
            origin,
            f"win -a {book}; plotxy iy:=(1,3:5) plot:=200 ogl:=[{graph_name}]1; win -a {graph_name}; legend -r;",
            f"{figure_id} lines",
        )
        style_failures.extend(_com_plot_styles(
            origin,
            graph_name,
            [("accent", 3.0), ("primary", 1.2), ("primary", 1.2)],
        ))
        _com_labels(origin, "解释变量 x（单位）", "响应变量 y（单位）")
        result = {
            "id": figure_id,
            "status": "degraded",
            "reason": "Origin COM 混合图层仅保留拟合线与区间线，观测散点未稳定叠加",
        }
    elif figure_id == "04_grouped_comparison":
        columns = ["scenario", "baseline", "method_a", "method_b"]
        for index, name in enumerate(columns):
            _put_column(origin, book, index, frame[name].to_numpy())
        _com_long_names(origin, book, ["Scenario", "Baseline", "Method A", "Method B"])
        _execute(
            origin,
            f"win -a {book}; plotxy iy:=(1,2:4) plot:=203 ogl:=<new name:={graph_name}>;",
            figure_id,
        )
        origin.Execute(f"win -a {graph_name}; layer -gu;")
        style_failures.extend(_com_plot_styles(
            origin,
            graph_name,
            [("neutral", None), ("primary", None), ("accent", None)],
        ))
        origin.Execute(f"win -a {graph_name}; legend -r;")
        _com_labels(origin, "场景", "综合得分（分）")
        result = {"id": figure_id, "status": "rendered"}
    elif figure_id == "07_pareto":
        dominated = frame.loc[:, ["cost", "emissions"]]
        front = frame.loc[frame.is_pareto == 1, ["cost", "emissions"]].sort_values("cost")
        for index, values in enumerate(
            (
                dominated.cost.to_numpy(),
                dominated.emissions.to_numpy(),
                front.cost.to_numpy(),
                front.emissions.to_numpy(),
            )
        ):
            _put_column(origin, book, index, values)
        _com_long_names(origin, book, ["Candidate Cost", "Candidate Emissions", "Pareto Cost", "Pareto Emissions"])
        _execute(
            origin,
            f"win -a {book}; plotxy iy:=(1,2) plot:=201 ogl:=<new name:={graph_name}>;",
            f"{figure_id} candidates",
        )
        _execute(
            origin,
            f"win -a {book}; plotxy iy:=(3,4) plot:=202 ogl:=[{graph_name}]1; win -a {graph_name}; legend -r;",
            f"{figure_id} front",
        )
        style_failures.extend(_com_plot_styles(origin, graph_name, [("primary", 3.0)]))
        _com_labels(origin, "成本（万元）", "排放量（tCO2）")
        result = {
            "id": figure_id,
            "status": "degraded",
            "reason": "Origin COM 混合图层仅稳定保留有限候选前沿，支配候选背景未稳定叠加",
        }
    else:
        raise ValueError(f"未声明的 Origin COM 图型：{figure_id}")

    if style_failures:
        prior_reason = str(result.get("reason", "")).rstrip("；")
        style_reason = "Origin 部分样式属性未接受：" + ", ".join(style_failures)
        result["status"] = "degraded"
        result["reason"] = f"{prior_reason}；{style_reason}" if prior_reason else style_reason
    result["data_sha256"] = _hash(source)
    result["png"] = _com_export(origin, figure_id)
    return result


def _line_graph(op: Any) -> dict[str, object]:
    figure_id = "01_time_series"
    source = DATA_DIR / f"{figure_id}.csv"
    frame = pd.read_csv(source)
    sheet = op.new_sheet("w")
    sheet.from_df(frame[["day", "observed", "forecast", "lower_95", "upper_95"]])
    graph = op.new_graph(template="line")
    layer = graph[0]
    labels = ["观测值", "预测值", "95% 下界", "95% 上界"]
    for index, label in enumerate(labels, start=1):
        plot = layer.add_plot(sheet, coly=index, colx=0, type="l")
        plot.color = [COLORS["text"], COLORS["primary"], COLORS["primary"], COLORS["primary"]][index - 1]
        plot.set_cmd("-w 4" if index <= 2 else "-w 2")
    layer.group()
    layer.axis("x").title = _safe_label("时间（天）")
    layer.axis("y").title = _safe_label("需求量（单位/天）")
    layer.rescale()
    return {
        "id": figure_id,
        "status": "degraded",
        "reason": "Origin 首轮以四条曲线表达区间，尚未实现半透明带",
        "data_sha256": _hash(source),
        "png": _export(graph, figure_id),
    }


def _scatter_fit(op: Any) -> dict[str, object]:
    figure_id = "02_scatter_fit"
    source = DATA_DIR / f"{figure_id}.csv"
    frame = pd.read_csv(source)
    sheet = op.new_sheet("w")
    sheet.from_df(frame[["x", "observed", "fitted", "lower_95", "upper_95"]])
    graph = op.new_graph(template="scatter")
    layer = graph[0]
    points = layer.add_plot(sheet, coly=1, colx=0, type="s")
    points.color = COLORS["neutral_dark"]
    points.symbol_size = 7
    for index, color in ((2, COLORS["accent"]), (3, COLORS["primary"]), (4, COLORS["primary"])):
        line = layer.add_plot(sheet, coly=index, colx=0, type="l")
        line.color = color
        line.set_cmd("-w 4" if index == 2 else "-w 2")
    layer.axis("x").title = _safe_label("解释变量 x（单位）")
    layer.axis("y").title = _safe_label("响应变量 y（单位）")
    layer.rescale()
    return {
        "id": figure_id,
        "status": "rendered",
        "data_sha256": _hash(source),
        "png": _export(graph, figure_id),
    }


def _grouped_bar(op: Any) -> dict[str, object]:
    figure_id = "04_grouped_comparison"
    source = DATA_DIR / f"{figure_id}.csv"
    frame = pd.read_csv(source)
    sheet = op.new_sheet("w")
    sheet.from_df(frame[["scenario", "baseline", "method_a", "method_b"]])
    graph = op.new_graph(template="column")
    layer = graph[0]
    for index in range(1, 4):
        plot = layer.add_plot(sheet, coly=index, colx=0, type="c")
        plot.color = [COLORS["neutral"], COLORS["primary"], COLORS["accent"]][index - 1]
    layer.group()
    layer.axis("x").title = _safe_label("场景")
    layer.axis("y").title = _safe_label("综合得分（分）")
    layer.rescale()
    return {
        "id": figure_id,
        "status": "rendered",
        "data_sha256": _hash(source),
        "png": _export(graph, figure_id),
    }


def _pareto(op: Any) -> dict[str, object]:
    figure_id = "07_pareto"
    source = DATA_DIR / f"{figure_id}.csv"
    frame = pd.read_csv(source)
    dominated = frame.loc[frame.is_pareto == 0, ["cost", "emissions"]]
    front = frame.loc[frame.is_pareto == 1, ["cost", "emissions"]].sort_values("cost")
    dominated_sheet = op.new_sheet("w")
    dominated_sheet.from_df(dominated)
    front_sheet = op.new_sheet("w")
    front_sheet.from_df(front)
    graph = op.new_graph(template="scatter")
    layer = graph[0]
    background = layer.add_plot(dominated_sheet, coly=1, colx=0, type="s")
    background.color = COLORS["neutral"]
    background.symbol_size = 6
    curve = layer.add_plot(front_sheet, coly=1, colx=0, type="l")
    curve.color = COLORS["primary"]
    curve.set_cmd("-w 4")
    layer.axis("x").title = _safe_label("成本（万元）")
    layer.axis("y").title = _safe_label("排放量（tCO2）")
    layer.rescale()
    return {
        "id": figure_id,
        "status": "rendered",
        "data_sha256": _hash(source),
        "png": _export(graph, figure_id),
    }


def main() -> None:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    status = origin_status()
    safe_status = {key: value for key, value in status.items() if key != "executable"}
    originpro_available = bool(safe_status.pop("available", False))
    originpro_reason = safe_status.pop("reason", None)
    executable_detected = bool(status.get("executable"))
    safe_status.update({
        "originpro_available": originpro_available,
        "originpro_reason": originpro_reason,
        "executable_detected": executable_detected,
        "automation_available": originpro_available or executable_detected,
        "automation_mode": "com_labtalk" if executable_detected else "originpro" if originpro_available else None,
    })
    reports: list[dict[str, object]] = []
    if status.get("executable"):
        try:
            import win32com.client

            origin = win32com.client.Dispatch("Origin.ApplicationSI")
            try:
                origin.Visible = 0
                origin.NewProject()
                for figure_id in COM_FIGURES:
                    try:
                        reports.append(_render_direct_com(origin, figure_id))
                    except Exception as error:
                        reports.append({
                            "id": figure_id,
                            "status": "failed",
                            "reason": f"COM/LabTalk: {type(error).__name__}: {error}",
                        })
            finally:
                origin.Exit()
        except Exception as error:
            reports.clear()
            for figure_id in COM_FIGURES:
                reports.append({
                    "id": figure_id,
                    "status": "failed",
                    "reason": f"COM/LabTalk startup: {type(error).__name__}: {error}",
                })
    elif status["available"]:
        import originpro as op

        try:
            op.set_show(False)
            for figure_id, renderer in (
                ("01_time_series", _line_graph),
                ("02_scatter_fit", _scatter_fit),
                ("04_grouped_comparison", _grouped_bar),
                ("07_pareto", _pareto),
            ):
                try:
                    reports.append(renderer(op))
                except Exception as error:
                    reports.append({
                        "id": figure_id,
                        "status": "failed",
                        "reason": f"{type(error).__name__}: {error}",
                    })
        finally:
            op.exit()
    else:
        for figure_id in COM_FIGURES:
            reports.append({"id": figure_id, "status": "failed", "reason": status["reason"]})
    for figure_id, reason in UNSUPPORTED.items():
        reports.append({"id": figure_id, "status": "unsupported", "reason": reason})
    reports.sort(key=lambda item: str(item["id"]))
    payload = {
        "schema_version": 1,
        "backend": "origin",
        "palette_id": STYLE["palette_id"],
        "origin": safe_status,
        "passed": not any(item["status"] == "failed" for item in reports),
        "figures": reports,
    }
    (REPORT_DIR / "origin_renderer.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    if not payload["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
