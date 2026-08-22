"""独立验证标准数据、后端报告和图片技术质量。"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys
from typing import Any

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from mmw.utils.figure_quality import png_info


ROOT = Path(__file__).resolve().parent.parent
REPORT_DIR = ROOT / "reports"
MANIFEST = json.loads((ROOT / "manifest.json").read_text(encoding="utf-8"))
STYLE = json.loads((ROOT / "style_contract.json").read_text(encoding="utf-8"))


def _hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _assert(condition: bool, message: str, failures: list[str]) -> None:
    if not condition:
        failures.append(message)


def _validate_data() -> dict[str, Any]:
    failures: list[str] = []
    warnings: list[str] = []
    generation_path = REPORT_DIR / "data_generation.json"
    _assert(generation_path.is_file(), "缺少 data_generation.json", failures)
    generated = json.loads(generation_path.read_text(encoding="utf-8")) if generation_path.is_file() else {"files": []}
    recorded = {item["file"]: item for item in generated.get("files", [])}
    hashes: dict[str, str] = {}
    for item in MANIFEST["figures"]:
        path = ROOT / item["data_file"]
        _assert(path.is_file(), f"缺少数据：{item['data_file']}", failures)
        if not path.is_file():
            continue
        digest = _hash(path)
        hashes[item["id"]] = digest
        entry = recorded.get(item["data_file"])
        _assert(bool(entry), f"生成报告未记录：{item['data_file']}", failures)
        if entry:
            _assert(entry["sha256"] == digest, f"数据哈希不一致：{item['data_file']}", failures)

    time_series = pd.read_csv(ROOT / "data/01_time_series.csv")
    _assert(bool((time_series.lower_95 <= time_series.forecast).all()), "时间序列下界高于预测值", failures)
    _assert(bool((time_series.forecast <= time_series.upper_95).all()), "时间序列上界低于预测值", failures)

    scatter = pd.read_csv(ROOT / "data/02_scatter_fit.csv")
    _assert(bool((scatter.lower_95 <= scatter.fitted).all()), "拟合置信下界非法", failures)
    _assert(bool((scatter.fitted <= scatter.upper_95).all()), "拟合置信上界非法", failures)

    distribution = pd.read_csv(ROOT / "data/03_distribution.csv")
    counts = distribution.groupby("group").size()
    _assert(len(counts) == 3 and bool((counts >= 30).all()), "分布图组数或样本量不足", failures)

    comparison = pd.read_csv(ROOT / "data/04_grouped_comparison.csv")
    _assert(bool((comparison[["baseline", "method_a", "method_b"]] >= 0).all().all()), "分组比较含负值", failures)

    heatmap = pd.read_csv(ROOT / "data/05_heatmap.csv")
    _assert(heatmap.delta_score.min() < 0 < heatmap.delta_score.max(), "发散热力图未跨越零", failures)

    sensitivity = pd.read_csv(ROOT / "data/06_sensitivity.csv")
    _assert(bool((sensitivity.low_effect < 0).all()), "敏感性低扰动不是全负", failures)
    _assert(bool((sensitivity.high_effect > 0).all()), "敏感性高扰动不是全正", failures)

    pareto = pd.read_csv(ROOT / "data/07_pareto.csv")
    recomputed = np.ones(len(pareto), dtype=bool)
    for index in range(len(pareto)):
        dominates = (
            (pareto.cost <= pareto.cost.iloc[index])
            & (pareto.emissions <= pareto.emissions.iloc[index])
            & ((pareto.cost < pareto.cost.iloc[index]) | (pareto.emissions < pareto.emissions.iloc[index]))
        )
        if dominates.any():
            recomputed[index] = False
    _assert(np.array_equal(recomputed.astype(int), pareto.is_pareto.to_numpy()), "Pareto 标记独立复算失败", failures)

    gantt = pd.read_csv(ROOT / "data/08_gantt.csv")
    _assert(bool(np.allclose(gantt.start + gantt.duration, gantt.end)), "甘特图 end != start + duration", failures)
    for resource, group in gantt.sort_values("start").groupby("resource"):
        previous_end = -np.inf
        for row in group.itertuples(index=False):
            _assert(row.start >= previous_end, f"资源 {resource} 存在任务重叠", failures)
            previous_end = row.end
    return {"passed": not failures, "failures": failures, "warnings": warnings, "hashes": hashes}


def _validate_backend(name: str, require_vector: bool) -> dict[str, Any]:
    failures: list[str] = []
    warnings: list[str] = []
    report_path = REPORT_DIR / f"{name}_renderer.json"
    _assert(report_path.is_file(), f"缺少 {name}_renderer.json", failures)
    renderer = json.loads(report_path.read_text(encoding="utf-8")) if report_path.is_file() else {"figures": []}
    _assert(
        renderer.get("palette_id") == STYLE["palette_id"],
        f"{name} 未绑定现役配色合同 {STYLE['palette_id']}",
        failures,
    )
    by_id = {item["id"]: item for item in renderer.get("figures", [])}
    outputs: list[dict[str, Any]] = []
    for spec in MANIFEST["figures"]:
        figure_id = spec["id"]
        item = by_id.get(figure_id)
        _assert(item is not None, f"{name} 报告缺少 {figure_id}", failures)
        if item is None:
            continue
        expected_unsupported = name == "origin" and spec["origin_support"] == "unsupported"
        if expected_unsupported:
            _assert(item.get("status") == "unsupported", f"Origin {figure_id} 应明确 unsupported", failures)
            continue
        _assert(item.get("status") in {"rendered", "degraded"}, f"{name} {figure_id} 未成功：{item.get('reason')}", failures)
        source = ROOT / spec["data_file"]
        _assert(
            item.get("data_sha256") == _hash(source),
            f"{name} {figure_id} 未绑定当前输入哈希",
            failures,
        )
        if item.get("status") == "degraded":
            warnings.append(f"{name} {figure_id}：{item.get('reason')}")
        png = ROOT / str(item.get("png", ""))
        _assert(png.is_file(), f"缺少图片：{png}", failures)
        if not png.is_file():
            continue
        try:
            info = png_info(png)
        except (OSError, ValueError) as error:
            failures.append(f"无效 PNG {png.name}: {error}")
            continue
        _assert(int(info["width"]) >= 1200, f"{png.name} 宽度不足：{info['width']}", failures)
        _assert(int(info["height"]) >= 700, f"{png.name} 高度不足：{info['height']}", failures)
        dpi_values = [value for value in (info["dpi_x"], info["dpi_y"]) if value is not None]
        if dpi_values:
            _assert(min(dpi_values) >= 290, f"{png.name} DPI 过低：{min(dpi_values):.1f}", failures)
        else:
            warnings.append(f"{png.name} 未记录 DPI")
        entry: dict[str, Any] = {"id": figure_id, "png": png.relative_to(ROOT).as_posix(), "sha256": _hash(png), **info}
        if require_vector:
            pdf = ROOT / str(item.get("pdf", ""))
            _assert(pdf.is_file(), f"缺少矢量 PDF：{pdf}", failures)
            if pdf.is_file():
                _assert(pdf.read_bytes().startswith(b"%PDF"), f"无效 PDF：{pdf.name}", failures)
                entry["pdf"] = pdf.relative_to(ROOT).as_posix()
                entry["pdf_sha256"] = _hash(pdf)
        outputs.append(entry)
    return {"passed": not failures, "failures": failures, "warnings": warnings, "outputs": outputs}


def main() -> None:
    data = _validate_data()
    matplotlib_report = _validate_backend("matplotlib", require_vector=True)
    matlab_report = _validate_backend("matlab", require_vector=True)
    origin_report = _validate_backend("origin", require_vector=False)
    payload = {
        "schema_version": 1,
        "passed": all(item["passed"] for item in (data, matplotlib_report, matlab_report, origin_report)),
        "data": data,
        "backends": {
            "matplotlib": matplotlib_report,
            "matlab": matlab_report,
            "origin": origin_report,
        },
        "manual_review_required": [
            "最终论文栏宽下的中文和图例可读性",
            "灰度打印下的系列区分",
            "色觉缺陷模拟",
            "Origin 降级时间序列是否可接受",
            "不同后端的视觉层次和留白",
        ],
    }
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    (REPORT_DIR / "validation.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    if not payload["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
