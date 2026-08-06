import sys
sys.stdout.reconfigure(encoding="utf-8")

import json
import time
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.optimize import least_squares

from _mmw_moving_heat import (
    MovingSlabConfig,
    simulate_effective_slab,
    assess_multistart_identifiability,
)

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from cycler import cycler

plt.rcParams.update({
    # 中文与符号
    "font.sans-serif": ["SimHei", "Microsoft YaHei"],
    "axes.unicode_minus": False,
    # 尺寸与导出
    "figure.figsize": (8, 5),        # 单图标准;并排双图用 (10, 4)
    "savefig.dpi": 300,
    "savefig.bbox": "tight",
    "savefig.pad_inches": 0.05,
    # 字号层级（标题 > 轴标签 > 刻度/图例）
    "axes.titlesize": 14,
    "axes.labelsize": 12,
    "xtick.labelsize": 10,
    "ytick.labelsize": 10,
    "legend.fontsize": 10,
    # 线条与标记
    "lines.linewidth": 1.8,
    "lines.markersize": 5,
    "axes.linewidth": 0.8,
    # 网格与边框
    "axes.grid": True,
    "grid.linestyle": "--",
    "grid.linewidth": 0.5,
    "grid.alpha": 0.35,
    "axes.spines.top": False,
    "axes.spines.right": False,
    # 统一配色循环（色盲友好，打印灰度可分辨）
    "axes.prop_cycle": cycler(color=[
        "#4C72B0", "#DD8452", "#55A868", "#C44E52",
        "#8172B3", "#937860", "#DA8BC3", "#8C8C8C"]),
    # 图例
    "legend.frameon": False,
})

# ============================================================
# 参数定义
# ============================================================

DATA_FILE = Path("data/raw/附件.xlsx")
RESULT_DIR = Path(".")
FIGURE_DIR = Path("figures")
FIGURE_DATA_DIR = RESULT_DIR / "figure_data"

L_F = 25.0
L_Z = 30.5
L_G = 5.0
L_TOTAL = 435.5
T_INITIAL = 25.0
DZETA = 1.0 / 6.0

GRID_STEPS = (0.1, 0.05, 0.025)
CALIBRATION_STEP = 0.025

THETA_LOWER = np.array([1e-4] * 7, dtype=float)
THETA_UPPER = np.array([0.1388888889] + [1.0] * 6, dtype=float)
LOG_LOWER = np.log(THETA_LOWER)
LOG_UPPER = np.log(THETA_UPPER)

CALIBRATION_STARTS = np.array([
    [0.25, 0.25, 0.25, 0.25, 0.25, 0.25, 0.25],
    [0.50, 0.50, 0.50, 0.50, 0.50, 0.50, 0.50],
    [0.75, 0.75, 0.75, 0.75, 0.75, 0.75, 0.75],
    [0.40, 0.30, 0.45, 0.55, 0.60, 0.70, 0.35],
], dtype=float)

PARAMETER_NAMES = [
    "a_eff", "k_bg", "k_15", "k_6", "k_7", "k_89", "k_cool"
]

Q3_LOWER = np.array([165.0, 185.0, 225.0, 245.0, 65.0])
Q3_UPPER = np.array([185.0, 205.0, 245.0, 265.0, 100.0])
PATTERN_ALPHA = 0.25

DIRECTIONS = []
for index in range(5):
    positive = np.zeros(5)
    positive[index] = 1.0
    DIRECTIONS.append(positive)

    negative = np.zeros(5)
    negative[index] = -1.0
    DIRECTIONS.append(negative)

HARD_CONSTRAINT_IDS = [
    "CON-Q1-1", "CON-Q1-2", "CON-Q1-3", "CON-Q1-4", "CON-Q1-5",
    "CON-Q2-1", "CON-Q2-2", "CON-Q2-3", "CON-Q2-4", "CON-Q2-5",
    "CON-Q3-1", "CON-Q3-2", "CON-Q3-3", "CON-Q3-4", "CON-Q3-5",
    "CON-Q3-6", "CON-Q4-1", "CON-Q4-2", "CON-Q4-3", "CON-Q4-4",
    "CON-Q4-5", "CON-Q4-6",
]

START_TIME = time.monotonic()
DEADLINES = {
    "calibration": START_TIME + 54.0,
    "q1": START_TIME + 72.0,
    "q2": START_TIME + 165.0,
    "q3": START_TIME + 225.0,
    "q4": START_TIME + 255.0,
    "compute": START_TIME + 270.0,
}

figure_manifest = {
    "schema_version": 1,
    "figures": [],
}


# ============================================================
# 通用辅助函数
# ============================================================

def require_finite(name, values):
    array = np.asarray(values, dtype=float)
    if not np.all(np.isfinite(array)):
        raise RuntimeError(f"{name}: 检测到非有限数值")
    return array


def write_json(path, value):
    with open(path, "w", encoding="utf-8") as file:
        json.dump(value, file, ensure_ascii=False, indent=2)


def check_deadline(stage, remaining_calls=0, recent_call_times=None):
    now = time.monotonic()
    hard_deadline = min(DEADLINES[stage], DEADLINES["compute"])

    estimate = 0.05
    if recent_call_times:
        finite_times = [
            float(item) for item in recent_call_times
            if np.isfinite(item) and item >= 0.0
        ]
        if finite_times:
            estimate = max(finite_times) * 1.25 + 0.05

    required = estimate * max(1, remaining_calls)
    if now + required > hard_deadline:
        raise RuntimeError(
            f"{stage}_remaining_complete_work_budget_unavailable: "
            f"actual_remaining_time={hard_deadline - now:.6f}, "
            f"required_estimate={required:.6f}, "
            f"remaining_calls={remaining_calls}"
        )


def add_result(results, name, value, unit, desc):
    numeric = float(value)
    if not np.isfinite(numeric):
        raise RuntimeError(f"results.json非有限数值: {name}")
    results.append({
        "name": name,
        "value": numeric,
        "unit": unit,
        "desc": desc,
    })


def save_figure_data(file_name, data_frame):
    data_path = FIGURE_DATA_DIR / file_name
    clean = data_frame.copy()
    numeric_columns = clean.select_dtypes(include=[np.number]).columns
    if len(numeric_columns) > 0:
        require_finite(str(data_path), clean[numeric_columns].to_numpy())
    clean.to_csv(data_path, index=False, encoding="utf-8-sig")
    return f"figure_data/{file_name}"


def register_figure(
    file_name,
    kind,
    data_file,
    x,
    y,
    title,
    x_label,
    y_label,
    caption,
):
    figure_manifest["figures"].append({
        "file": file_name,
        "kind": kind,
        "data_file": data_file,
        "x": x,
        "y": y,
        "title": title,
        "x_label": x_label,
        "y_label": y_label,
        "caption": caption,
    })


def normalized_to_theta(xi):
    xi = np.asarray(xi, dtype=float)
    return np.exp(LOG_LOWER + xi * (LOG_UPPER - LOG_LOWER))


def theta_to_normalized(theta):
    theta = require_finite("theta", theta)
    return (np.log(theta) - LOG_LOWER) / (LOG_UPPER - LOG_LOWER)


def y_to_z(y):
    return (np.asarray(y, dtype=float) - Q3_LOWER) / (Q3_UPPER - Q3_LOWER)


def z_to_y(z):
    return Q3_LOWER + (Q3_UPPER - Q3_LOWER) * np.asarray(z, dtype=float)


def lex_key(values):
    output = []
    for value in values:
        if isinstance(value, (list, tuple, np.ndarray)):
            output.extend(float(item) for item in np.asarray(value).ravel())
        else:
            output.append(float(value))
    require_finite("候选比较键", output)
    return tuple(output)


# ============================================================
# 数据加载与EDA
# ============================================================

def load_data():
    if not DATA_FILE.exists():
        parent = DATA_FILE.parent
        print(f"数据文件不存在: {DATA_FILE}")
        if parent.exists():
            print(f"父目录内容: {[item.name for item in parent.iterdir()]}")
        else:
            print(f"父目录不存在: {parent}")
        raise FileNotFoundError(DATA_FILE)

    workbook = pd.ExcelFile(DATA_FILE)
    if "Sheet1" not in workbook.sheet_names:
        preview = pd.read_excel(DATA_FILE, sheet_name=0, header=None, nrows=8)
        print(preview.to_string(index=False))
        raise RuntimeError("工作表Sheet1不存在")

    raw = pd.read_excel(DATA_FILE, sheet_name="Sheet1")
    expected = ["时间(s)", "温度(ºC)"]
    if list(raw.columns) != expected:
        preview = pd.read_excel(
            DATA_FILE,
            sheet_name="Sheet1",
            header=None,
            nrows=8,
        )
        print(preview.to_string(index=False))
        raise RuntimeError(f"表头不符合预期: {list(raw.columns)}")

    original_rows = len(raw)
    missing_cells = int(raw.isna().sum().sum())
    duplicate_rows = int(raw.duplicated().sum())

    data = raw.copy()
    for column in expected:
        data[column] = pd.to_numeric(data[column], errors="coerce")

    invalid_rows = int(data[expected].isna().any(axis=1).sum())
    data = (
        data.dropna(subset=expected)
        .sort_values("时间(s)")
        .reset_index(drop=True)
    )

    duplicate_times = int(data["时间(s)"].duplicated().sum())
    if invalid_rows > 0 or duplicate_times > 0:
        raise RuntimeError(
            "CON-Q1-1失败: "
            f"invalid_rows={invalid_rows}, duplicate_times={duplicate_times}, "
            "required=0"
        )

    times = data["时间(s)"].to_numpy(dtype=float)
    temperatures = data["温度(ºC)"].to_numpy(dtype=float)
    require_finite("观测时间", times)
    require_finite("观测温度", temperatures)

    if len(times) < 3 or np.any(np.diff(times) <= 0):
        raise RuntimeError(
            f"CON-Q1-1失败: valid_rows={len(times)}, "
            "required_rows>=3且时间严格递增"
        )

    rates = np.diff(temperatures) / np.diff(times)
    differences = np.diff(temperatures)

    q1_diff, q3_diff = np.quantile(differences, [0.25, 0.75])
    iqr_diff = q3_diff - q1_diff
    diff_low = q1_diff - 1.5 * iqr_diff
    diff_high = q3_diff + 1.5 * iqr_diff

    q1_rate, q3_rate = np.quantile(rates, [0.25, 0.75])
    iqr_rate = q3_rate - q1_rate
    rate_low = q1_rate - 1.5 * iqr_rate
    rate_high = q3_rate + 1.5 * iqr_rate

    anomaly_mask = (
        (differences < diff_low)
        | (differences > diff_high)
        | (rates < rate_low)
        | (rates > rate_high)
    )
    anomaly_count = int(np.count_nonzero(anomaly_mask))

    if np.std(times) > 0 and np.std(temperatures) > 0:
        pearson = float(np.corrcoef(times, temperatures)[0, 1])
    else:
        pearson = 0.0

    eda = {
        "original_rows": original_rows,
        "valid_rows": len(data),
        "missing_cells": missing_cells,
        "missing_rate": missing_cells / max(1, raw.size),
        "duplicate_rows": duplicate_rows,
        "temperature_mean": float(np.mean(temperatures)),
        "temperature_peak": float(np.max(temperatures)),
        "temperature_peak_time": float(times[np.argmax(temperatures)]),
        "max_rise_rate": float(np.max(rates)),
        "max_fall_rate": float(np.min(rates)),
        "pearson_time_temperature": pearson,
        "anomaly_count": anomaly_count,
        "anomaly_rate": anomaly_count / max(1, len(differences)),
        "difference_lower": float(diff_low),
        "difference_upper": float(diff_high),
        "rate_lower": float(rate_low),
        "rate_upper": float(rate_high),
    }
    return data, eda


# ============================================================
# 环境温度、交换率与有效平板仿真
# ============================================================

def zone_geometry():
    starts = np.array([
        L_F + index * (L_Z + L_G) for index in range(11)
    ])
    ends = starts + L_Z
    midpoints = 0.5 * (starts + ends)
    gap_midpoints = ends + L_G / 2.0
    return starts, ends, midpoints, gap_midpoints


def full_zone_temperatures(settings):
    t15, t6, t7, t89 = [float(item) for item in settings]
    return np.array(
        [t15] * 5 + [t6, t7, t89, t89, 25.0, 25.0],
        dtype=float,
    )


def air_profile(settings):
    zones = full_zone_temperatures(settings)
    starts, ends, _, _ = zone_geometry()

    positions = [0.0, starts[0]]
    values = [25.0, zones[0]]

    for index in range(9):
        if positions[-1] < ends[index]:
            positions.append(float(ends[index]))
            values.append(float(zones[index]))
        if index < 8:
            positions.append(float(starts[index + 1]))
            values.append(float(zones[index + 1]))

    cooling_end = 377.5
    if not (ends[8] < cooling_end <= L_TOTAL):
        raise RuntimeError(
            "CON-Q1-2失败: "
            f"cooling_start={ends[8]:.6f}, cooling_end={cooling_end:.6f}, "
            f"path_end={L_TOTAL:.6f}"
        )

    positions.extend([cooling_end, L_TOTAL])
    values.extend([25.0, 25.0])

    positions = require_finite("环境温度位置节点", positions)
    values = require_finite("环境温度节点", values)

    if np.any(np.diff(positions) <= 0):
        raise RuntimeError(
            "CON-Q1-2失败: 环境温度位置节点必须严格递增"
        )
    return positions, values


def exchange_profile(theta):
    starts, ends, _, gap_midpoints = zone_geometry()
    k_bg, k15, k6, k7, k89, kcool = theta[1:]

    breaks = np.array([
        0.0,
        starts[0],
        gap_midpoints[4],
        gap_midpoints[5],
        gap_midpoints[6],
        gap_midpoints[8],
        ends[10],
        L_TOTAL,
    ], dtype=float)

    rates = np.array([
        k_bg, k15, k6, k7, k89, kcool, k_bg
    ], dtype=float)

    if len(breaks) != len(rates) + 1:
        raise RuntimeError("CON-Q1-2失败: 交换率区间数量不匹配")
    if breaks[0] != 0.0 or breaks[-1] != L_TOTAL:
        raise RuntimeError("CON-Q1-2失败: 交换率未覆盖完整路径")
    if np.any(np.diff(breaks) <= 0):
        raise RuntimeError("CON-Q1-2失败: 交换率边界不递增")
    return breaks, rates


def simulation_times(speed, sample_dt):
    final_time = 60.0 * L_TOTAL / float(speed)
    count = int(np.ceil(final_time / sample_dt))
    times = np.arange(count + 1, dtype=float) * sample_dt
    return times, final_time


def simulate_curve(speed, settings, theta, sample_dt):
    theta = require_finite("有效参数", theta)
    if np.any(theta <= 0):
        raise RuntimeError("CON-Q1-3失败: 有效参数必须为正")

    times, final_time = simulation_times(speed, sample_dt)
    air_knots, air_temperatures = air_profile(settings)
    exchange_breaks, exchange_rates = exchange_profile(theta)

    # simulate_effective_slab当前仅支持explicit。根据(M8)为每个外层
    # 时间步选择最少的等长内部子步，使内部步同时满足:
    # 2*r <= 1和r + beta <= 1。
    # MovingSlabConfig中的diffusivity直接取a_eff，模块会结合
    # thickness=1和grid_points=7得到Delta_zeta=1/6。
    diffusion_rate = float(theta[0] / (DZETA * DZETA))
    maximum_exchange_rate = float(np.max(exchange_rates))
    required_by_diffusion = 2.0 * diffusion_rate * float(sample_dt)
    required_by_combined = (
        diffusion_rate + maximum_exchange_rate
    ) * float(sample_dt)
    substeps = max(
        1,
        int(np.ceil(max(
            required_by_diffusion,
            required_by_combined,
        ))),
    )

    config = MovingSlabConfig(
        thickness=1.0,
        grid_points=7,
        sample_dt=float(sample_dt),
        substeps=substeps,
        diffusivity=float(theta[0]),
        initial_temperature=T_INITIAL,
        scheme="explicit",
    )

    internal_dt = float(sample_dt) / substeps
    internal_r = diffusion_rate * internal_dt
    internal_beta_max = maximum_exchange_rate * internal_dt
    if 2.0 * internal_r > 1.0 + 1e-12:
        raise RuntimeError(
            "CON-Q1-3失败: "
            f"2r={2.0 * internal_r:.12f}, threshold<=1, "
            f"sample_dt={sample_dt:.12f}, substeps={substeps}"
        )
    if internal_r + internal_beta_max > 1.0 + 1e-12:
        raise RuntimeError(
            "CON-Q1-3失败: "
            f"r_plus_beta={internal_r + internal_beta_max:.12f}, "
            f"threshold<=1, sample_dt={sample_dt:.12f}, "
            f"substeps={substeps}"
        )

    temperatures = simulate_effective_slab(
        times,
        speed=float(speed) / 60.0,
        air_position_knots=air_knots,
        air_temperatures=air_temperatures,
        exchange_position_breaks=exchange_breaks,
        exchange_rates=exchange_rates,
        config=config,
    )
    temperatures = require_finite("中心温度曲线", temperatures)

    if temperatures.shape != times.shape:
        raise RuntimeError(
            f"中心温度返回长度错误: expected={len(times)}, "
            f"actual={len(temperatures)}"
        )

    mask = times <= final_time + 1e-12
    return times[mask], temperatures[mask], final_time


def interpolate_curve(times, temperatures, query_times):
    query_times = np.asarray(query_times, dtype=float)
    if np.min(query_times) < times[0] or np.max(query_times) > times[-1]:
        raise RuntimeError(
            "CON-Q1-1失败: 插值时刻超出仿真域, "
            f"query_min={np.min(query_times):.6f}, "
            f"query_max={np.max(query_times):.6f}, "
            f"domain=[{times[0]:.6f},{times[-1]:.6f}]"
        )
    values = np.interp(query_times, times, temperatures)
    return require_finite("插值温度", values)


# ============================================================
# 标定
# ============================================================

def calibration_residual(log_theta, obs_times, obs_temperatures):
    theta = np.exp(log_theta)
    times, temperatures, _ = simulate_curve(
        70.0,
        [175.0, 195.0, 235.0, 255.0],
        theta,
        CALIBRATION_STEP,
    )
    predicted = interpolate_curve(times, temperatures, obs_times)
    residual = predicted - obs_temperatures
    return require_finite("标定残差", residual)


def region_residuals(obs_times, residuals):
    speed = 70.0 / 60.0
    positions = speed * obs_times
    labels = {
        "炉前与温区1至5": (0.0, 200.0),
        "温区6": (200.0, 235.5),
        "温区7": (235.5, 271.0),
        "温区8至9": (271.0, 342.0),
        "冷却与炉后": (342.0, L_TOTAL),
    }

    output = {}
    for name, (left, right) in labels.items():
        mask = (positions >= left) & (positions <= right)
        count = int(np.count_nonzero(mask))
        if count >= 5:
            value = float(np.mean(residuals[mask]))
            if not np.isfinite(value):
                raise RuntimeError("分区平均残差非有限")
            output[name] = {"count": count, "mean_residual": value}
        else:
            output[name] = {
                "count": count,
                "available": 0,
                "reason": "样本数少于5",
            }
    return output


def calibrate(obs_times, obs_temperatures):
    successful = []
    call_times = []

    for start_index, start_xi in enumerate(CALIBRATION_STARTS):
        check_deadline(
            "calibration",
            remaining_calls=len(CALIBRATION_STARTS) - start_index,
            recent_call_times=call_times,
        )
        call_start = time.monotonic()
        initial_theta = normalized_to_theta(start_xi)

        try:
            fit = least_squares(
                calibration_residual,
                np.log(initial_theta),
                bounds=(LOG_LOWER, LOG_UPPER),
                args=(obs_times, obs_temperatures),
                max_nfev=350,
                method="trf",
            )
            residuals = calibration_residual(
                fit.x,
                obs_times,
                obs_temperatures,
            )
            loss = float(np.sum(residuals ** 2))
            theta = np.exp(fit.x)

            if fit.success and np.isfinite(loss) and np.all(np.isfinite(theta)):
                successful.append({
                    "start_index": start_index,
                    "initial_theta": initial_theta,
                    "theta": theta,
                    "loss": loss,
                    "nfev": int(fit.nfev),
                    "message": str(fit.message),
                })
        finally:
            call_times.append(time.monotonic() - call_start)

    if len(successful) < 3:
        raise RuntimeError(
            "MODEL_REWORK_REQUIRED: CON-Q1-4失败: "
            f"successful_starts={len(successful)}, threshold=3"
        )

    parameter_sets = [
        item["theta"].tolist() for item in successful
    ]
    losses = [float(item["loss"]) for item in successful]
    initial_parameter_sets = [
        item["initial_theta"].tolist() for item in successful
    ]

    diagnosis = assess_multistart_identifiability(
        parameter_sets,
        losses,
        initial_parameter_sets=initial_parameter_sets,
        relative_loss_tolerance=0.01,
        absolute_loss_tolerance=1e-9,
        parameter_spread_tolerance=0.25,
    )
    write_json(RESULT_DIR / "identifiability.json", diagnosis)

    identifiable = bool(diagnosis.get("identifiable", False))
    failures = diagnosis.get("failures", [])
    if not identifiable or failures:
        raise RuntimeError(
            "MODEL_REWORK_REQUIRED: CON-Q1-4失败: "
            f"identifiable={int(identifiable)}, "
            f"failure_count={len(failures)}, "
            "required_identifiable=1, required_failure_count=0"
        )

    best_loss = min(losses)
    if best_loss > 0:
        near = [
            item for item in successful
            if item["loss"] <= 1.01 * best_loss
        ]
    else:
        near = [item for item in successful if item["loss"] == 0]

    representative = min(
        near,
        key=lambda item: (
            item["loss"],
            *theta_to_normalized(item["theta"]).tolist(),
        ),
    )

    theta_ref = representative["theta"]
    xi_ref = theta_to_normalized(theta_ref)
    boundary_distance = float(np.min(np.minimum(xi_ref, 1.0 - xi_ref)))

    predicted = obs_temperatures + calibration_residual(
        np.log(theta_ref),
        obs_times,
        obs_temperatures,
    )
    residuals = predicted - obs_temperatures
    loss = float(np.sum(residuals ** 2))
    rmse = float(np.sqrt(loss / len(obs_times)))
    observed_range = float(np.max(obs_temperatures) - np.min(obs_temperatures))
    denominator = float(np.sum(
        (obs_temperatures - np.mean(obs_temperatures)) ** 2
    ))

    if observed_range <= 0 or denominator <= 0:
        raise RuntimeError(
            "MODEL_REWORK_REQUIRED: calibration_metric_unavailable: "
            f"temperature_range={observed_range:.6f}, "
            f"variance_denominator={denominator:.6f}, thresholds=positive"
        )

    nrmse = rmse / observed_range
    r2 = 1.0 - loss / denominator

    failures_text = []
    if boundary_distance <= 0.01:
        failures_text.append(
            f"C8_boundary_distance={boundary_distance:.8f}, threshold>0.01"
        )
    if r2 < 0.90:
        failures_text.append(f"C11_R2={r2:.8f}, threshold>=0.90")
    if nrmse > 0.10:
        failures_text.append(f"C11_NRMSE={nrmse:.8f}, threshold<=0.10")

    if failures_text:
        raise RuntimeError(
            "MODEL_REWORK_REQUIRED: CON-Q1-4失败: "
            + "; ".join(failures_text)
        )

    metadata = {
        "successful_starts": len(successful),
        "near_optimal_count": len(near),
        "representative_theta": {
            name: float(value)
            for name, value in zip(PARAMETER_NAMES, theta_ref)
        },
        "representative_loss": loss,
        "rmse": rmse,
        "nrmse": nrmse,
        "r2": r2,
        "boundary_distance": boundary_distance,
        "region_residuals": region_residuals(obs_times, residuals),
        "runs": [
            {
                "start_index": item["start_index"],
                "loss": item["loss"],
                "nfev": item["nfev"],
                "theta": item["theta"].tolist(),
            }
            for item in successful
        ],
    }
    write_json(RESULT_DIR / "calibration_metadata.json", metadata)

    return {
        "theta_ref": theta_ref,
        "near_thetas": [item["theta"] for item in near],
        "loss": loss,
        "rmse": rmse,
        "nrmse": nrmse,
        "r2": r2,
        "boundary_distance": boundary_distance,
        "region_residuals": metadata["region_residuals"],
        "diagnosis": diagnosis,
        "predicted": predicted,
    }


# ============================================================
# 制程指标、面积和对称性
# ============================================================

def crossing_time(times, values, threshold, peak_index, ascending):
    if ascending:
        indices = range(peak_index - 1, -1, -1)
        for index in indices:
            left = values[index]
            right = values[index + 1]
            if left < threshold <= right:
                return float(
                    times[index]
                    + (threshold - left)
                    * (times[index + 1] - times[index])
                    / (right - left)
                )
            if left == threshold:
                while index > 0 and values[index - 1] == threshold:
                    index -= 1
                return float(times[index])
    else:
        indices = range(peak_index, len(times) - 1)
        for index in indices:
            left = values[index]
            right = values[index + 1]
            if left >= threshold > right:
                return float(
                    times[index]
                    + (threshold - left)
                    * (times[index + 1] - times[index])
                    / (right - left)
                )
            if right == threshold:
                endpoint = index + 1
                while (
                    endpoint + 1 < len(times)
                    and values[endpoint + 1] == threshold
                ):
                    endpoint += 1
                return float(times[endpoint])

    raise ValueError(f"threshold_event_unavailable_{threshold:g}")


def integrate_interpolated(times, values, left, right):
    if right < left:
        raise ValueError("integration_interval_unavailable")

    inside = (times > left) & (times < right)
    integration_times = np.concatenate((
        [left],
        times[inside],
        [right],
    ))
    integration_values = np.interp(integration_times, times, values)
    area = float(np.trapezoid(integration_values, integration_times))
    if not np.isfinite(area):
        raise ValueError("integration_nonfinite")
    return area


def calculate_metrics(times, temperatures):
    times = require_finite("指标时间", times)
    temperatures = require_finite("指标温度", temperatures)

    differences = np.diff(temperatures) / np.diff(times)
    peak_value = float(np.max(temperatures))
    peak_candidates = np.flatnonzero(
        np.isclose(temperatures, peak_value, rtol=0.0, atol=1e-12)
    )
    peak_index = int(peak_candidates[0])
    peak_time = float(times[peak_index])

    t150 = crossing_time(times, temperatures, 150.0, peak_index, True)
    t190 = crossing_time(times, temperatures, 190.0, peak_index, True)
    t217_up = crossing_time(times, temperatures, 217.0, peak_index, True)
    t217_down = crossing_time(
        times, temperatures, 217.0, peak_index, False
    )

    time_150_190 = t190 - t150
    time_above_217 = t217_down - t217_up

    clipped_area = integrate_interpolated(
        times,
        temperatures - 217.0,
        t217_up,
        peak_time,
    )

    tau_left = peak_time - t217_up
    tau_right = t217_down - peak_time
    tau = min(tau_left, tau_right)
    delta_tau = abs(tau_left - tau_right)

    if tau <= 0 or peak_value <= 217:
        raise ValueError("symmetry_normalization_unavailable")

    sample_count = max(3, int(np.ceil(tau / 0.025)) + 1)
    offsets = np.linspace(0.0, tau, sample_count)
    left_values = np.interp(
        peak_time - offsets, times, temperatures
    )
    right_values = np.interp(
        peak_time + offsets, times, temperatures
    )
    symmetry_area = float(np.trapezoid(
        np.abs(left_values - right_values),
        offsets,
    ))
    symmetry_normalized = symmetry_area / (tau * (peak_value - 217.0))

    values = {
        "rise_slope": float(np.max(differences)),
        "fall_slope": float(np.min(differences)),
        "time_150_190": float(time_150_190),
        "time_above_217": float(time_above_217),
        "peak_temperature": peak_value,
        "peak_time": peak_time,
        "t217_up": float(t217_up),
        "t217_down": float(t217_down),
        "area": float(clipped_area),
        "symmetry_area": symmetry_area,
        "symmetry_normalized": float(symmetry_normalized),
        "delta_tau": float(delta_tau),
    }
    require_finite("制程指标", list(values.values()))
    return values


def process_violation(metrics):
    terms = [
        max(-metrics["rise_slope"], 0.0) / 3.0,
        max(metrics["rise_slope"] - 3.0, 0.0) / 3.0,
        max(-3.0 - metrics["fall_slope"], 0.0) / 3.0,
        max(metrics["fall_slope"], 0.0) / 3.0,
        max(60.0 - metrics["time_150_190"], 0.0) / 60.0,
        max(metrics["time_150_190"] - 120.0, 0.0) / 60.0,
        max(40.0 - metrics["time_above_217"], 0.0) / 50.0,
        max(metrics["time_above_217"] - 90.0, 0.0) / 50.0,
        max(240.0 - metrics["peak_temperature"], 0.0) / 10.0,
        max(metrics["peak_temperature"] - 250.0, 0.0) / 10.0,
    ]
    return float(sum(terms))


def metrics_feasible(metrics):
    return (
        0.0 <= metrics["rise_slope"] <= 3.0
        and -3.0 <= metrics["fall_slope"] <= 0.0
        and 60.0 <= metrics["time_150_190"] <= 120.0
        and 40.0 <= metrics["time_above_217"] <= 90.0
        and 240.0 <= metrics["peak_temperature"] <= 250.0
    )


def convergence_pair(coarse, fine, absolute, relative):
    return abs(fine - coarse) <= absolute + relative * abs(fine)


def convergence_status(grid_metrics, include_symmetry=True):
    coarse, fine, ultra = grid_metrics

    specifications = {
        "rise_slope": (0.02, 0.005),
        "fall_slope": (0.02, 0.005),
        "time_150_190": (0.2, 0.001),
        "time_above_217": (0.2, 0.001),
        "peak_temperature": (0.2, 0.001),
        "area": (0.2, 0.001),
    }
    if include_symmetry:
        specifications.update({
            "symmetry_area": (0.2, 0.001),
            "delta_tau": (0.2, 0.001),
            "symmetry_normalized": (0.002, 0.005),
        })

    checks = {}
    for name, (absolute, relative) in specifications.items():
        checks[name] = (
            convergence_pair(coarse[name], fine[name], absolute, relative)
            and convergence_pair(fine[name], ultra[name], absolute, relative)
        )
    return checks, all(checks.values())


def evaluate_candidate(y, near_thetas, include_symmetry=True):
    y = require_finite("工艺候选", y)
    settings = y[:4]
    speed = float(y[4])

    if np.any(y < Q3_LOWER - 1e-12) or np.any(y > Q3_UPPER + 1e-12):
        return {
            "category": 3,
            "failure": "decision_bounds_unavailable",
        }

    records = []
    try:
        for record_index, theta in enumerate(near_thetas):
            grid_metrics = []
            ultra_curve = None

            for step in GRID_STEPS:
                times, temperatures, _ = simulate_curve(
                    speed, settings, theta, step
                )
                metrics = calculate_metrics(times, temperatures)
                grid_metrics.append(metrics)
                if step == GRID_STEPS[-1]:
                    ultra_curve = (times, temperatures)

            checks, converged = convergence_status(
                grid_metrics,
                include_symmetry=include_symmetry,
            )
            ultra = grid_metrics[-1]
            records.append({
                "record_index": record_index,
                "grid_metrics": grid_metrics,
                "grid_checks": checks,
                "converged": converged,
                "process_feasible": metrics_feasible(ultra),
                "violation": process_violation(ultra),
                "ultra_metrics": ultra,
                "ultra_curve": ultra_curve,
            })
    except (ValueError, RuntimeError) as error:
        return {
            "category": 3,
            "failure": str(error),
        }

    if not records:
        return {"category": 3, "failure": "empty_parameter_records"}

    all_converged = all(item["converged"] for item in records)
    all_process_feasible = all(
        item["process_feasible"] for item in records
    )

    area_wc = max(item["ultra_metrics"]["area"] for item in records)
    violation_wc = max(item["violation"] for item in records)
    symmetry_wc = max(
        item["ultra_metrics"]["symmetry_area"] for item in records
    )
    delta_tau_wc = max(
        item["ultra_metrics"]["delta_tau"] for item in records
    )

    process_qualified = all_converged and all_process_feasible
    return {
        "category": 0 if process_qualified else 2,
        "process_qualified": process_qualified,
        "area_wc": float(area_wc),
        "violation_wc": float(violation_wc),
        "symmetry_wc": float(symmetry_wc),
        "delta_tau_wc": float(delta_tau_wc),
        "records": records,
    }


# ============================================================
# 问题1
# ============================================================

def solve_q1(near_thetas):
    check_deadline("q1", remaining_calls=len(near_thetas) * 3)
    settings = np.array([173.0, 198.0, 230.0, 257.0])
    speed = 78.0
    positions = np.array([111.25, 217.75, 253.25, 304.0])
    position_times = 60.0 * positions / speed

    record_outputs = []
    reference_curve = None

    for record_index, theta in enumerate(near_thetas):
        point_grids = []
        output_grids = []

        for step in GRID_STEPS:
            times, temperatures, final_time = simulate_curve(
                speed, settings, theta, step
            )
            point_grids.append(
                interpolate_curve(times, temperatures, position_times)
            )

            output_times = np.arange(
                0.0,
                np.floor(final_time / 0.5) * 0.5 + 1e-12,
                0.5,
            )
            if output_times[-1] < final_time - 1e-12:
                output_times = np.append(output_times, final_time)

            output_values = interpolate_curve(
                times, temperatures, output_times
            )
            output_grids.append((output_times, output_values))

            if (
                record_index == 0
                and step == GRID_STEPS[-1]
            ):
                reference_curve = (
                    output_times.copy(),
                    output_values.copy(),
                )

        for point_index in range(len(positions)):
            coarse = point_grids[0][point_index]
            fine = point_grids[1][point_index]
            ultra = point_grids[2][point_index]
            if not (
                convergence_pair(coarse, fine, 0.2, 0.001)
                and convergence_pair(fine, ultra, 0.2, 0.001)
            ):
                raise RuntimeError(
                    "CON-Q1-5失败: q1_numerical_nonconvergence, "
                    f"record={record_index}, point={point_index}, "
                    f"coarse={coarse:.8f}, fine={fine:.8f}, "
                    f"ultra={ultra:.8f}, threshold=0.2+0.001*abs(value)"
                )

        common_times = output_grids[2][0]
        for coarse_times, coarse_values in output_grids[:2]:
            aligned = np.interp(common_times, coarse_times, coarse_values)
            ultra_values = output_grids[2][1]
            tolerance = 0.2 + 0.001 * np.abs(ultra_values)
            maximum_error = float(np.max(np.abs(aligned - ultra_values)))
            maximum_tolerance = float(np.max(tolerance))
            if np.any(np.abs(aligned - ultra_values) > tolerance):
                raise RuntimeError(
                    "CON-Q1-5失败: q1_numerical_nonconvergence, "
                    f"record={record_index}, max_error={maximum_error:.8f}, "
                    f"max_threshold={maximum_tolerance:.8f}"
                )

        record_outputs.append(point_grids[-1])

    point_values = np.max(np.vstack(record_outputs), axis=0)
    output_times, output_temperatures = reference_curve

    result_frame = pd.DataFrame({
        "时间(s)": output_times,
        "焊接区域中心温度(ºC)": output_temperatures,
    })
    require_finite("result.csv", result_frame.to_numpy())
    result_frame.to_csv(
        RESULT_DIR / "result.csv",
        index=False,
        encoding="utf-8-sig",
    )

    figure_data_file = save_figure_data(
        "fig_1_q1_temperature_curve.csv",
        pd.DataFrame({
            "time_s": output_times,
            "temperature_c": output_temperatures,
        }),
    )
    fig, ax = plt.subplots(constrained_layout=True)
    ax.plot(
        output_times,
        output_temperatures,
        label="问题1炉温曲线",
    )
    ax.set_title("问题1焊接区域中心炉温曲线")
    ax.set_xlabel("进入设备后的时间 / s")
    ax.set_ylabel("中心温度 / °C")
    ax.legend()
    figure_name = "fig_1_q1_temperature_curve.png"
    fig.savefig(FIGURE_DIR / figure_name)
    plt.close(fig)

    register_figure(
        figure_name,
        "line",
        figure_data_file,
        "time_s",
        "temperature_c",
        "问题1焊接区域中心炉温曲线",
        "进入设备后的时间 / s",
        "中心温度 / °C",
        "问题1指定设温和78 cm/min速度下的条件预测炉温曲线.",
    )

    return {
        "point_temperatures": point_values,
        "point_times": position_times,
        "curve": reference_curve,
    }


# ============================================================
# 问题2
# ============================================================

def solve_q2(near_thetas):
    settings = np.array([182.0, 203.0, 237.0, 254.0])
    speeds = 65.0 + 0.05 * np.arange(701)
    feasible_speeds = []
    call_times = []

    for index, speed in enumerate(speeds):
        check_deadline(
            "q2",
            remaining_calls=len(speeds) - index,
            recent_call_times=call_times,
        )
        call_start = time.monotonic()
        evaluation = evaluate_candidate(
            np.array([*settings, speed]),
            near_thetas,
            include_symmetry=False,
        )
        call_times.append(time.monotonic() - call_start)

        if evaluation.get("process_qualified", False):
            feasible_speeds.append(float(speed))

    if len(call_times) != 701:
        raise RuntimeError(
            "CON-Q2-4失败: "
            f"completed_points={len(call_times)}, threshold=701"
        )

    if not feasible_speeds:
        raise RuntimeError(
            "CON-Q2-5失败: "
            "q2_no_feasible_speed_on_complete_fixed_grid, "
            "feasible_count=0, required_count>=1"
        )

    return {
        "feasible_speeds": feasible_speeds,
        "maximum_speed": feasible_speeds[-1],
        "completed_points": len(call_times),
        "elapsed": float(sum(call_times)),
    }


# ============================================================
# 问题3和问题4
# ============================================================

def q3_key(evaluation, z):
    if evaluation.get("process_qualified", False):
        return lex_key((0, evaluation["area_wc"], z))
    if evaluation.get("category") == 2:
        return lex_key((1, evaluation["violation_wc"], z))
    failure_code = sum(ord(char) for char in evaluation.get("failure", "")) + 1
    return lex_key((2, failure_code, z))


def q4_key(evaluation, z, area_best, epsilon_area):
    if evaluation.get("category") == 3:
        failure_code = sum(ord(char) for char in evaluation.get("failure", "")) + 1
        return lex_key((3, failure_code, z)), 3, False

    if evaluation.get("process_qualified", False):
        area_violation = max(
            evaluation["area_wc"] - area_best - epsilon_area,
            0.0,
        ) / epsilon_area

        symmetry_grids_ok = all(
            record["converged"] for record in evaluation["records"]
        )
        area_layer = (
            evaluation["area_wc"] <= area_best + epsilon_area
            and symmetry_grids_ok
        )

        if area_layer:
            key = lex_key((
                0,
                evaluation["symmetry_wc"],
                evaluation["delta_tau_wc"],
                evaluation["area_wc"],
                z,
            ))
            return key, 0, True

        key = lex_key((
            1,
            area_violation,
            evaluation["area_wc"],
            z,
        ))
        return key, 1, False

    key = lex_key((
        2,
        evaluation["violation_wc"],
        max(evaluation["area_wc"], 0.0),
        z,
    ))
    return key, 2, False


def select_q3_seed_speeds(feasible_speeds):
    count = len(feasible_speeds)
    if count >= 3:
        middle_index = int(np.ceil(count / 2.0)) - 1
        return [
            feasible_speeds[0],
            feasible_speeds[middle_index],
            feasible_speeds[-1],
        ]
    if count == 2:
        return [
            feasible_speeds[0],
            feasible_speeds[0],
            feasible_speeds[1],
        ]
    if count == 1:
        return [feasible_speeds[0]] * 3
    raise RuntimeError(
        "CON-Q3-2失败: q3_seed_set_unavailable, "
        "feasible_speed_count=0, required_count>=1"
    )


def solve_q3(near_thetas, feasible_speeds):
    seed_speeds = select_q3_seed_speeds(feasible_speeds)
    initial_states = []
    final_states = []
    evaluation_sequence = []
    call_times = []

    for seed_index, speed in enumerate(seed_speeds):
        initial_y = np.array([182.0, 203.0, 237.0, 254.0, speed])
        current_z = y_to_z(initial_y)
        initial_states.append(current_z.copy())

        check_deadline(
            "q3",
            remaining_calls=33 - len(evaluation_sequence),
            recent_call_times=call_times,
        )
        call_start = time.monotonic()
        current_evaluation = evaluate_candidate(
            z_to_y(current_z), near_thetas, include_symmetry=False
        )
        call_times.append(time.monotonic() - call_start)
        current_key = q3_key(current_evaluation, current_z)

        evaluation_sequence.append({
            "index": len(evaluation_sequence) + 1,
            "seed": seed_index + 1,
            "step": 0,
            "z": current_z.copy(),
            "y": z_to_y(current_z),
            "evaluation": current_evaluation,
            "key": current_key,
        })

        for direction_index, direction in enumerate(DIRECTIONS, start=1):
            check_deadline(
                "q3",
                remaining_calls=33 - len(evaluation_sequence),
                recent_call_times=call_times,
            )
            candidate_z = np.clip(
                current_z + PATTERN_ALPHA * direction,
                0.0,
                1.0,
            )
            call_start = time.monotonic()
            candidate_evaluation = evaluate_candidate(
                z_to_y(candidate_z),
                near_thetas,
                include_symmetry=False,
            )
            call_times.append(time.monotonic() - call_start)
            candidate_key = q3_key(candidate_evaluation, candidate_z)

            evaluation_sequence.append({
                "index": len(evaluation_sequence) + 1,
                "seed": seed_index + 1,
                "step": direction_index,
                "z": candidate_z.copy(),
                "y": z_to_y(candidate_z),
                "evaluation": candidate_evaluation,
                "key": candidate_key,
            })

            if candidate_key < current_key:
                current_z = candidate_z
                current_evaluation = candidate_evaluation
                current_key = candidate_key

        final_states.append(current_z.copy())

    if len(evaluation_sequence) != 33:
        raise RuntimeError(
            "CON-Q3-4失败: "
            f"evaluation_count={len(evaluation_sequence)}, threshold=33"
        )

    feasible_indices = [
        item["index"]
        for item in evaluation_sequence
        if item["evaluation"].get("process_qualified", False)
    ]
    if not feasible_indices:
        raise RuntimeError(
            "CON-Q3-6失败: "
            "q3_no_feasible_candidate_in_complete_search, "
            "feasible_count=0, completed_evaluations=33"
        )

    feasible_items = [
        item for item in evaluation_sequence
        if item["evaluation"].get("process_qualified", False)
    ]
    best = min(
        feasible_items,
        key=lambda item: (
            item["evaluation"]["area_wc"],
            *item["z"].tolist(),
        ),
    )

    return {
        "seed_speeds": seed_speeds,
        "initial_states": initial_states,
        "final_states": final_states,
        "sequence": evaluation_sequence,
        "feasible_indices": feasible_indices,
        "best": best,
        "elapsed": float(sum(call_times)),
    }


def solve_q4(near_thetas, q3_result):
    area_best = min(
        item["evaluation"]["area_wc"]
        for item in q3_result["sequence"]
        if item["evaluation"].get("process_qualified", False)
    )
    epsilon_area = 0.2 + 0.001 * abs(area_best)

    evaluation_sequence = []
    final_states = []
    call_times = []

    for seed_index, initial_z in enumerate(q3_result["final_states"]):
        current_z = initial_z.copy()

        check_deadline(
            "q4",
            remaining_calls=33 - len(evaluation_sequence),
            recent_call_times=call_times,
        )
        call_start = time.monotonic()
        current_evaluation = evaluate_candidate(
            z_to_y(current_z), near_thetas, include_symmetry=True
        )
        call_times.append(time.monotonic() - call_start)
        current_key, category, area_layer = q4_key(
            current_evaluation, current_z, area_best, epsilon_area
        )

        evaluation_sequence.append({
            "index": len(evaluation_sequence) + 1,
            "seed": seed_index + 1,
            "step": 0,
            "z": current_z.copy(),
            "y": z_to_y(current_z),
            "evaluation": current_evaluation,
            "key": current_key,
            "category": category,
            "area_layer": area_layer,
        })

        for direction_index, direction in enumerate(DIRECTIONS, start=1):
            check_deadline(
                "q4",
                remaining_calls=33 - len(evaluation_sequence),
                recent_call_times=call_times,
            )
            candidate_z = np.clip(
                current_z + PATTERN_ALPHA * direction,
                0.0,
                1.0,
            )
            call_start = time.monotonic()
            candidate_evaluation = evaluate_candidate(
                z_to_y(candidate_z),
                near_thetas,
                include_symmetry=True,
            )
            call_times.append(time.monotonic() - call_start)
            candidate_key, candidate_category, candidate_area_layer = q4_key(
                candidate_evaluation,
                candidate_z,
                area_best,
                epsilon_area,
            )

            evaluation_sequence.append({
                "index": len(evaluation_sequence) + 1,
                "seed": seed_index + 1,
                "step": direction_index,
                "z": candidate_z.copy(),
                "y": z_to_y(candidate_z),
                "evaluation": candidate_evaluation,
                "key": candidate_key,
                "category": candidate_category,
                "area_layer": candidate_area_layer,
            })

            if candidate_key < current_key:
                current_z = candidate_z
                current_evaluation = candidate_evaluation
                current_key = candidate_key

        final_states.append(current_z.copy())

    if len(evaluation_sequence) != 33:
        raise RuntimeError(
            "CON-Q4-6失败: "
            f"evaluation_count={len(evaluation_sequence)}, threshold=33"
        )

    feasible_items = [
        item for item in evaluation_sequence if item["area_layer"]
    ]
    feasible_indices = [item["index"] for item in feasible_items]

    if feasible_items:
        best = min(
            feasible_items,
            key=lambda item: (
                item["evaluation"]["symmetry_wc"],
                item["evaluation"]["delta_tau_wc"],
                item["evaluation"]["area_wc"],
                *item["z"].tolist(),
            ),
        )
        status = "completed"
    else:
        best = None
        status = "q4_no_feasible_candidate_in_complete_search"

    return {
        "area_best": float(area_best),
        "epsilon_area": float(epsilon_area),
        "sequence": evaluation_sequence,
        "feasible_indices": feasible_indices,
        "final_states": final_states,
        "best": best,
        "status": status,
        "elapsed": float(sum(call_times)),
    }


def serializable_sequence(sequence):
    output = []
    for item in sequence:
        evaluation = item["evaluation"]
        record = {
            "index": item["index"],
            "seed": item["seed"],
            "step": item["step"],
            "z": item["z"].tolist(),
            "y": item["y"].tolist(),
            "key": list(item["key"]),
            "category": int(item.get("category", evaluation.get("category", 3))),
            "process_qualified": bool(
                evaluation.get("process_qualified", False)
            ),
        }
        if "area_layer" in item:
            record["area_layer"] = bool(item["area_layer"])
        if evaluation.get("category") == 3:
            record["failure"] = evaluation.get(
                "failure", "structured_failure"
            )
        else:
            record["area_wc"] = evaluation["area_wc"]
            record["violation_wc"] = evaluation["violation_wc"]
            record["symmetry_wc"] = evaluation["symmetry_wc"]
            record["delta_tau_wc"] = evaluation["delta_tau_wc"]
        output.append(record)
    return output


def save_optimal_curve(figure_index, question, best_item, theta):
    y = best_item["y"]
    times, temperatures, _ = simulate_curve(
        y[4], y[:4], theta, GRID_STEPS[-1]
    )
    data_name = f"fig_{figure_index}_{question}_optimal_curve.csv"
    data_file = save_figure_data(
        data_name,
        pd.DataFrame({
            "time_s": times,
            "temperature_c": temperatures,
        }),
    )

    figure_name = f"fig_{figure_index}_{question}_optimal_curve.png"
    fig, ax = plt.subplots(constrained_layout=True)
    ax.plot(times, temperatures, label=f"{question}最优炉温曲线")
    ax.axhline(217.0, linestyle="--", label="液相线217°C")
    ax.set_title(f"{question}有限检查集最优炉温曲线")
    ax.set_xlabel("进入设备后的时间 / s")
    ax.set_ylabel("中心温度 / °C")
    ax.legend()
    fig.savefig(FIGURE_DIR / figure_name)
    plt.close(fig)

    register_figure(
        figure_name,
        "line",
        data_file,
        "time_s",
        "temperature_c",
        f"{question}有限检查集最优炉温曲线",
        "进入设备后的时间 / s",
        "中心温度 / °C",
        f"{question}条件预测下有限检查集best-found炉温曲线.",
    )
    return times, temperatures


# ============================================================
# 灵敏度分析
# ============================================================

def calibration_loss_for_theta(theta, obs_times, obs_temperatures):
    times, temperatures, _ = simulate_curve(
        70.0,
        [175.0, 195.0, 235.0, 255.0],
        theta,
        CALIBRATION_STEP,
    )
    predicted = interpolate_curve(times, temperatures, obs_times)
    residuals = predicted - obs_temperatures
    value = float(np.sum(residuals ** 2))
    if not np.isfinite(value):
        raise RuntimeError("灵敏度目标非有限")
    return value


def run_sensitivity(theta_ref, obs_times, obs_temperatures):
    baseline = calibration_loss_for_theta(
        theta_ref, obs_times, obs_temperatures
    )
    parameter_indices = [0, 5]
    deltas = [-20, -10, 10, 20]
    experiments = []

    for plot_offset, parameter_index in enumerate(parameter_indices, start=5):
        parameter_name = PARAMETER_NAMES[parameter_index]
        objectives = []

        for delta in deltas:
            candidate = theta_ref.copy()
            requested = theta_ref[parameter_index] * (1.0 + delta / 100.0)
            actual = float(np.clip(
                requested,
                THETA_LOWER[parameter_index],
                THETA_UPPER[parameter_index],
            ))
            candidate[parameter_index] = actual
            objective = calibration_loss_for_theta(
                candidate, obs_times, obs_temperatures
            )
            change_pct = (
                100.0 * (objective - baseline) / baseline
                if baseline > 0
                else 0.0
            )
            experiments.append({
                "param": parameter_name,
                "delta_pct": delta,
                "param_value": actual,
                "objective": objective,
                "change_pct": float(change_pct),
            })
            objectives.append(objective)

        if np.allclose(objectives, baseline, rtol=0.0, atol=1e-12):
            raise RuntimeError(
                f"灵敏度参数无信息量: {parameter_name}"
            )

        frame = pd.DataFrame({
            "delta_pct": deltas,
            "objective_sse": objectives,
            "baseline_sse": [baseline] * len(deltas),
        })
        data_file = save_figure_data(
            f"sensitivity_{parameter_name}.csv",
            frame,
        )

        figure_name = f"sensitivity_{parameter_name}.png"
        fig, ax = plt.subplots(constrained_layout=True)
        ax.plot(
            frame["delta_pct"],
            frame["objective_sse"],
            marker="o",
            label="扰动后标定SSE",
        )
        ax.axhline(
            baseline,
            linestyle="--",
            label="基准标定SSE",
        )
        ax.set_title(f"{parameter_name}灵敏度分析")
        ax.set_xlabel("参数扰动幅度 / %")
        ax.set_ylabel("标定残差平方和 / °C²")
        ax.legend()
        fig.savefig(FIGURE_DIR / figure_name)
        plt.close(fig)

        register_figure(
            figure_name,
            "line",
            data_file,
            "delta_pct",
            ["objective_sse", "baseline_sse"],
            f"{parameter_name}灵敏度分析",
            "参数扰动幅度 / %",
            "标定残差平方和 / °C²",
            f"在原标定边界内扰动{parameter_name}后的标定目标变化.",
        )

    sensitivity = {
        "baseline": {
            "objective": baseline,
            "objective_name": "标定残差平方和",
        },
        "experiments": experiments,
    }
    write_json(RESULT_DIR / "sensitivity.json", sensitivity)
    return sensitivity


# ============================================================
# 最终输出
# ============================================================

def main():
    RESULT_DIR.mkdir(parents=True, exist_ok=True)
    FIGURE_DIR.mkdir(parents=True, exist_ok=True)
    FIGURE_DATA_DIR.mkdir(parents=True, exist_ok=True)

    print("=" * 72)
    print("2020年A题炉温曲线求解")
    print("=" * 72)

    data, eda = load_data()
    obs_times = data["时间(s)"].to_numpy(dtype=float)
    obs_temperatures = data["温度(ºC)"].to_numpy(dtype=float)

    calibration = calibrate(obs_times, obs_temperatures)
    theta_ref = calibration["theta_ref"]
    near_thetas = calibration["near_thetas"]

    print(f"结果: 标定损失={calibration['loss']:.8f}")
    print(f"结果: 标定RMSE={calibration['rmse']:.8f}")
    print(f"结果: 标定NRMSE={calibration['nrmse']:.8f}")
    print(f"结果: 标定R2={calibration['r2']:.8f}")
    print("结果: 参数可辨识性=[OK]")

    q1 = solve_q1(near_thetas)
    q2 = solve_q2(near_thetas)
    q3 = solve_q3(near_thetas, q2["feasible_speeds"])
    q4 = solve_q4(near_thetas, q3)

    q3_best = q3["best"]
    q3_curve = save_optimal_curve(2, "q3", q3_best, theta_ref)

    if q4["best"] is not None:
        q4_curve = save_optimal_curve(3, "q4", q4["best"], theta_ref)
    else:
        q4_curve = None

    write_json(
        RESULT_DIR / "q3_search.json",
        {
            "seed_speeds": q3["seed_speeds"],
            "initial_states": [
                item.tolist() for item in q3["initial_states"]
            ],
            "final_states": [
                item.tolist() for item in q3["final_states"]
            ],
            "evaluation_sequence": serializable_sequence(q3["sequence"]),
            "feasible_indices": q3["feasible_indices"],
            "best_index": q3_best["index"],
            "elapsed_seconds": q3["elapsed"],
            "continuous_domain_optimum": "approximate_not_certified",
            "global_certificate": False,
            "conditional_prediction": True,
            "external_validation": "unavailable",
        },
    )

    q4_payload = {
        "q3_final_states": [
            item.tolist() for item in q3["final_states"]
        ],
        "q4_final_states": [
            item.tolist() for item in q4["final_states"]
        ],
        "A3_best": q4["area_best"],
        "epsilon_A": q4["epsilon_area"],
        "evaluation_sequence": serializable_sequence(q4["sequence"]),
        "feasible_indices": q4["feasible_indices"],
        "status": q4["status"],
        "best_index": (
            q4["best"]["index"] if q4["best"] is not None else None
        ),
        "best_area": (
            q4["best"]["evaluation"]["area_wc"]
            if q4["best"] is not None else None
        ),
        "best_symmetry": (
            q4["best"]["evaluation"]["symmetry_wc"]
            if q4["best"] is not None else None
        ),
        "best_decision": (
            q4["best"]["y"].tolist()
            if q4["best"] is not None else None
        ),
        "q4_最优炉温曲线": (
            "figures/fig_3_q4_optimal_curve.png"
            if q4["best"] is not None else None
        ),
        "call_count": 33,
        "elapsed_seconds": q4["elapsed"],
        "continuous_domain_optimum": "approximate_not_certified",
        "global_certificate": False,
        "conditional_prediction": True,
        "external_validation": "unavailable",
    }
    write_json(RESULT_DIR / "q4_search.json", q4_payload)

    sensitivity = run_sensitivity(
        theta_ref, obs_times, obs_temperatures
    )

    results = []

    add_result(results, "q1_原始样本量", eda["original_rows"], "行",
               "附件Sheet1原始数据行数")
    add_result(results, "q1_有效样本量", eda["valid_rows"], "行",
               "数值转换、排序和完整性检查后的有效行数")
    add_result(results, "q1_缺失单元格数", eda["missing_cells"], "个",
               "附件两个字段的缺失单元格总数")
    add_result(results, "q1_缺失率", eda["missing_rate"] * 100.0, "%",
               "缺失单元格占全部单元格的比例")
    add_result(results, "q1_异常值数量", eda["anomaly_count"], "个",
               "基于一阶差分和变化率IQR规则的合并标记数,未删除")
    add_result(results, "q1_异常值比例", eda["anomaly_rate"] * 100.0, "%",
               "差分序列中被IQR规则标记的比例,标记不等同于测量错误")
    add_result(results, "q1_差分异常下阈值", eda["difference_lower"], "°C",
               "温度一阶差分IQR下界")
    add_result(results, "q1_差分异常上阈值", eda["difference_upper"], "°C",
               "温度一阶差分IQR上界")
    add_result(results, "q1_变化率异常下阈值", eda["rate_lower"], "°C/s",
               "温度变化率IQR下界")
    add_result(results, "q1_变化率异常上阈值", eda["rate_upper"], "°C/s",
               "温度变化率IQR上界")
    add_result(results, "q1_实测平均温度", eda["temperature_mean"], "°C",
               "附件有效观测的平均温度")
    add_result(results, "q1_实测峰值温度", eda["temperature_peak"], "°C",
               "附件有效观测的最高温度")
    add_result(results, "q1_实测峰值时刻", eda["temperature_peak_time"], "s",
               "附件实测曲线最早峰值时刻")
    add_result(results, "q1_实测最大升温斜率", eda["max_rise_rate"], "°C/s",
               "相邻观测点差分所得最大升温斜率")
    add_result(results, "q1_实测最大降温斜率", eda["max_fall_rate"], "°C/s",
               "相邻观测点差分所得最小降温斜率")
    add_result(results, "q1_时间温度Pearson相关系数",
               eda["pearson_time_temperature"], "",
               "仅为EDA总体关联,不作为动态模型验证")
    add_result(results, "q1_标定损失", calibration["loss"], "°C²",
               "附件样本内残差平方和")
    add_result(results, "q1_标定RMSE", calibration["rmse"], "°C",
               "附件样本内均方根误差")
    add_result(results, "q1_标定NRMSE", calibration["nrmse"], "",
               "RMSE除以实测温度极差")
    add_result(results, "q1_标定R2", calibration["r2"], "",
               "附件样本内拟合优度,不是跨工况外部验证")
    add_result(results, "q1_参数可辨识性", 1, "",
               "多起点诊断通过=1")
    add_result(results, "q1_外部验证可用", 0, "",
               "仅有70 cm/min单一工况,跨速度和跨设温外部验证不可用")

    point_names = [
        "q1_温区3中点温度",
        "q1_温区6中点温度",
        "q1_温区7中点温度",
        "q1_温区8结束温度",
    ]
    for name, value in zip(point_names, q1["point_temperatures"]):
        add_result(
            results, name, value, "°C",
            "全部近优参数记录中的最坏侧条件预测值"
        )

    point_time_names = [
        "q1_温区3中点时刻",
        "q1_温区6中点时刻",
        "q1_温区7中点时刻",
        "q1_温区8结束时刻",
    ]
    for name, value in zip(point_time_names, q1["point_times"]):
        add_result(results, name, value, "s",
                   "按x=vt/60计算的进入设备后物理时刻")

    add_result(results, "q2_最大允许速度", q2["maximum_speed"], "cm/min",
               "完整701点固定网格中满足全部近优参数记录制程约束的最大速度")
    add_result(results, "q2_可行速度数量",
               len(q2["feasible_speeds"]), "个",
               "0.05 cm/min固定网格上的可行点数")
    add_result(results, "q2_完成扫描点数", q2["completed_points"], "个",
               "固定速度网格实际完成点数")
    add_result(results, "q2_扫描耗时", q2["elapsed"], "s",
               "701个固定速度候选的累计实际评价耗时")
    add_result(results, "q2_连续域全局证书", 0, "",
               "只完成固定0.05 cm/min网格扫描,未认证连续边界")

    q3_y = q3_best["y"]
    q3_eval = q3_best["evaluation"]
    q3_metrics = q3_eval["records"][0]["ultra_metrics"]
    add_result(results, "q3_最优面积", q3_eval["area_wc"], "°C·s",
               "33项有限检查集内全部近优参数记录的最坏面积")
    add_result(results, "q3_温区1至5设定温度", q3_y[0], "°C",
               "问题3有限检查集best-found方案")
    add_result(results, "q3_温区6设定温度", q3_y[1], "°C",
               "问题3有限检查集best-found方案")
    add_result(results, "q3_温区7设定温度", q3_y[2], "°C",
               "问题3有限检查集best-found方案")
    add_result(results, "q3_温区8至9设定温度", q3_y[3], "°C",
               "问题3有限检查集best-found方案")
    add_result(results, "q3_传送带速度", q3_y[4], "cm/min",
               "问题3有限检查集best-found方案")
    add_result(results, "q3_峰值温度",
               q3_metrics["peak_temperature"], "°C",
               "代表近优参数记录的超细网格指标")
    add_result(results, "q3_峰值时刻", q3_metrics["peak_time"], "s",
               "代表近优参数记录最早峰值时刻")
    add_result(results, "q3_高于217度时间",
               q3_metrics["time_above_217"], "s",
               "包含峰值的闭超水平集连通分支持续时间")
    add_result(results, "q3_可行候选数量",
               len(q3["feasible_indices"]), "个",
               "完整33项评价序列中的制程可行成员数")
    add_result(results, "q3_评价次数", 33, "次",
               "三个起点各评价初值和十个方向")
    add_result(results, "q3_全局最优证书", 0, "",
               "连续域最优仅为approximate_not_certified")

    add_result(results, "q4_问题3面积基准", q4["area_best"], "°C·s",
               "问题3完整可行检查集中的最小最坏面积")
    add_result(results, "q4_面积保持容差", q4["epsilon_area"], "°C·s",
               "0.2加问题3面积基准绝对值的0.001倍")
    add_result(results, "q4_评价次数", 33, "次",
               "三个问题3终点各评价初值和十个方向")
    add_result(results, "q4_面积层可行候选数量",
               len(q4["feasible_indices"]), "个",
               "问题4完整33项序列中的面积层可行成员数")

    if q4["best"] is not None:
        q4_y = q4["best"]["y"]
        q4_eval = q4["best"]["evaluation"]
        add_result(results, "q4_最优面积", q4_eval["area_wc"], "°C·s",
                   "问题4规范方案的最坏面积")
        add_result(results, "q4_最优对称差面积",
                   q4_eval["symmetry_wc"], "°C·s",
                   "问题4规范方案的最坏对称差面积")
        add_result(results, "q4_最优时长差",
                   q4_eval["delta_tau_wc"], "s",
                   "峰值左右高于217度时长的最坏绝对差")
        add_result(results, "q4_温区1至5设定温度", q4_y[0], "°C",
                   "问题4面积保持层内best-found方案")
        add_result(results, "q4_温区6设定温度", q4_y[1], "°C",
                   "问题4面积保持层内best-found方案")
        add_result(results, "q4_温区7设定温度", q4_y[2], "°C",
                   "问题4面积保持层内best-found方案")
        add_result(results, "q4_温区8至9设定温度", q4_y[3], "°C",
                   "问题4面积保持层内best-found方案")
        add_result(results, "q4_传送带速度", q4_y[4], "cm/min",
                   "问题4面积保持层内best-found方案")
        add_result(results, "q4_规范方案可用", 1, "",
                   "完整搜索存在面积层可行候选=1")
    else:
        add_result(results, "q4_规范方案可用", 0, "",
                   "完整33次搜索后面积层可行候选为空")
        add_result(results, "q4_结构化停止状态", 1, "",
                   "q4_no_feasible_candidate_in_complete_search=1")

    add_result(results, "q4_全局最优证书", 0, "",
               "连续域最优仅为approximate_not_certified")
    add_result(results, "q4_条件预测状态", 1, "",
               "单一标定工况外推所得条件预测=1")
    add_result(results, "q4_外部验证可用", 0, "",
               "跨速度及跨设温外部验证不可用")

    for parameter_name, value in zip(PARAMETER_NAMES, theta_ref):
        add_result(
            results,
            f"q1_标定参数_{parameter_name}",
            value,
            "1/s",
            "有效时间尺度参数,不解释为材料参数或Robin系数",
        )

    add_result(
        results,
        "q1_灵敏度基准目标",
        sensitivity["baseline"]["objective"],
        "°C²",
        "标定参数灵敏度分析使用的基准残差平方和",
    )

    print(f"结果: q1温区3中点温度={q1['point_temperatures'][0]:.6f}")
    print(f"结果: q1温区6中点温度={q1['point_temperatures'][1]:.6f}")
    print(f"结果: q1温区7中点温度={q1['point_temperatures'][2]:.6f}")
    print(f"结果: q1温区8结束温度={q1['point_temperatures'][3]:.6f}")
    print(f"结果: q2最大允许速度={q2['maximum_speed']:.6f}")
    print(f"结果: q3最优面积={q3_eval['area_wc']:.6f}")

    if q4["best"] is not None:
        print(
            "结果: q4最优对称差面积="
            f"{q4['best']['evaluation']['symmetry_wc']:.6f}"
        )
    else:
        print(
            "结果: "
            "q4_no_feasible_candidate_in_complete_search"
        )

    write_json(RESULT_DIR / "results.json", results)
    write_json(RESULT_DIR / "figure_manifest.json", figure_manifest)

    final_objective = (
        q4["best"]["evaluation"]["symmetry_wc"]
        if q4["best"] is not None
        else q3_eval["area_wc"]
    )

    runtime = {
        "schema_version": 1,
        "algorithm_class": "heuristic",
        "termination_status": (
            "completed"
            if q4["best"] is not None
            else "completed_with_q4_empty_area_layer"
        ),
        "feasible": True,
        "constraints_checked": HARD_CONSTRAINT_IDS,
        "seed": None,
        "objective_value": float(final_objective),
        "objective_name": (
            "问题4最坏对称差面积"
            if q4["best"] is not None
            else "问题3最坏高温面积"
        ),
        "optimality_certificate": None,
        "q2_completed_points": q2["completed_points"],
        "q3_completed_calls": 33,
        "q4_completed_calls": 33,
        "conditional_prediction": True,
        "external_validation": "unavailable",
        "elapsed_seconds": float(time.monotonic() - START_TIME),
    }
    write_json(RESULT_DIR / "method_runtime.json", runtime)

    print("结果: 全部输出文件写入完成")
    print(f"结果: 总耗时={runtime['elapsed_seconds']:.6f}s")


if __name__ == "__main__":
    main()