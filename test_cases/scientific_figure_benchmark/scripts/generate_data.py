"""生成科研绘图基准的确定性 CSV，不读取任何真实比赛数据。"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
REPORT_DIR = ROOT / "reports"
SEED = 20260811


def _write(name: str, frame: pd.DataFrame) -> dict[str, object]:
    path = DATA_DIR / name
    frame.to_csv(path, index=False, encoding="utf-8", float_format="%.8f")
    return {
        "file": path.relative_to(ROOT).as_posix(),
        "rows": len(frame),
        "columns": list(frame.columns),
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
    }


def _pareto_mask(cost: np.ndarray, emissions: np.ndarray) -> np.ndarray:
    mask = np.ones(len(cost), dtype=bool)
    for index in range(len(cost)):
        dominates = (
            (cost <= cost[index])
            & (emissions <= emissions[index])
            & ((cost < cost[index]) | (emissions < emissions[index]))
        )
        if dominates.any():
            mask[index] = False
    return mask


def main() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(SEED)
    records: list[dict[str, object]] = []

    day = np.arange(1, 61)
    trend = 118 + 0.52 * day
    seasonal = 12 * np.sin(2 * np.pi * day / 14)
    forecast = trend + seasonal
    observed = forecast + rng.normal(0, 5.5, size=day.size)
    interval = 9 + 0.06 * day
    records.append(_write("01_time_series.csv", pd.DataFrame({
        "day": day,
        "observed": observed,
        "forecast": forecast,
        "lower_95": forecast - interval,
        "upper_95": forecast + interval,
    })))

    x = np.linspace(0.5, 10.0, 72)
    observed_y = 4.5 + 2.35 * x + rng.normal(0, 2.6, size=x.size)
    slope, intercept = np.polyfit(x, observed_y, 1)
    fitted = intercept + slope * x
    residual = observed_y - fitted
    residual_std = np.sqrt(np.sum(residual**2) / (len(x) - 2))
    leverage = 1 / len(x) + (x - x.mean()) ** 2 / np.sum((x - x.mean()) ** 2)
    confidence = 1.96 * residual_std * np.sqrt(leverage)
    records.append(_write("02_scatter_fit.csv", pd.DataFrame({
        "x": x,
        "observed": observed_y,
        "fitted": fitted,
        "lower_95": fitted - confidence,
        "upper_95": fitted + confidence,
    })))

    distribution_frames = []
    for label, mean, std, count in (
        ("基准方案", 68.0, 7.0, 42),
        ("方案 A", 75.0, 5.0, 42),
        ("方案 B", 79.0, 8.0, 42),
    ):
        values = rng.normal(mean, std, count)
        distribution_frames.append(pd.DataFrame({"group": label, "value": values}))
    records.append(_write("03_distribution.csv", pd.concat(distribution_frames, ignore_index=True)))

    records.append(_write("04_grouped_comparison.csv", pd.DataFrame({
        "scenario": ["低负荷", "常规", "高负荷", "极端"],
        "baseline": [72.0, 69.0, 61.0, 48.0],
        "method_a": [76.0, 78.0, 73.0, 63.0],
        "method_b": [74.0, 81.0, 79.0, 71.0],
    })))

    alpha_values = np.round(np.linspace(0.6, 1.4, 9), 1)
    beta_values = np.round(np.linspace(0.7, 1.3, 7), 1)
    heatmap_rows = []
    for beta in beta_values:
        for alpha in alpha_values:
            delta = 16 * (alpha - 1.0) - 12 * (beta - 1.0) + 18 * (alpha - 1.0) * (beta - 1.0)
            heatmap_rows.append({"alpha": alpha, "beta": beta, "delta_score": delta})
    records.append(_write("05_heatmap.csv", pd.DataFrame(heatmap_rows)))

    sensitivity = pd.DataFrame({
        "parameter": ["需求增长率", "能源价格", "设备效率", "排放因子", "维护成本", "折现率"],
        "low_effect": [-12.5, -9.2, -6.4, -5.1, -3.8, -2.6],
        "high_effect": [15.1, 11.7, 7.2, 6.8, 4.4, 3.0],
    })
    sensitivity["span"] = sensitivity["high_effect"] - sensitivity["low_effect"]
    sensitivity = sensitivity.sort_values("span", ascending=True).drop(columns="span")
    records.append(_write("06_sensitivity.csv", sensitivity))

    front_cost = np.linspace(82, 148, 18)
    front_emissions = 235 - 1.15 * (front_cost - 82) + 7 * np.exp(-(front_cost - 82) / 22)
    dominated_cost = rng.uniform(92, 155, 38)
    baseline_emissions = 235 - 1.15 * (dominated_cost - 82) + 7 * np.exp(-(dominated_cost - 82) / 22)
    dominated_emissions = baseline_emissions + rng.uniform(8, 42, dominated_cost.size)
    cost = np.concatenate([front_cost, dominated_cost])
    emissions = np.concatenate([front_emissions, dominated_emissions])
    pareto = _pareto_mask(cost, emissions)
    pareto_frame = pd.DataFrame({
        "solution_id": [f"S{index:03d}" for index in range(1, len(cost) + 1)],
        "cost": cost,
        "emissions": emissions,
        "is_pareto": pareto.astype(int),
    }).sort_values(["is_pareto", "cost"], ascending=[False, True])
    records.append(_write("07_pareto.csv", pareto_frame))

    gantt = pd.DataFrame([
        ("T01", "设备 A", 0.0, 3.5, "准备"),
        ("T02", "设备 A", 4.0, 5.0, "加工"),
        ("T03", "设备 A", 10.0, 3.0, "加工"),
        ("T04", "设备 B", 1.0, 4.0, "加工"),
        ("T05", "设备 B", 6.0, 2.5, "检测"),
        ("T06", "设备 B", 9.5, 4.0, "加工"),
        ("T07", "设备 C", 0.5, 2.0, "准备"),
        ("T08", "设备 C", 3.0, 4.5, "检测"),
        ("T09", "设备 C", 8.0, 3.5, "收尾"),
        ("T10", "设备 D", 2.0, 3.0, "加工"),
        ("T11", "设备 D", 5.5, 4.0, "加工"),
        ("T12", "设备 D", 10.0, 2.0, "收尾"),
    ], columns=["task_id", "resource", "start", "duration", "category"])
    gantt["end"] = gantt["start"] + gantt["duration"]
    records.append(_write("08_gantt.csv", gantt))

    payload = {"schema_version": 1, "seed": SEED, "files": records}
    (REPORT_DIR / "data_generation.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
