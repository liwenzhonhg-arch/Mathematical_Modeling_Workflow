"""2010 CUMCM A 题隐藏几何基线与成品表格评估器。

只在流水线外运行；不得复制到参赛工作区或发送给 Agent。
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.optimize import least_squares


def _segment_area(radius: np.ndarray, level: np.ndarray) -> np.ndarray:
    clipped = np.clip(level, -radius, radius)
    with np.errstate(divide="ignore", invalid="ignore"):
        area = clipped * np.sqrt(np.maximum(0.0, radius**2 - clipped**2))
        area += radius**2 * (
            np.arcsin(np.divide(clipped, radius, out=np.zeros_like(clipped), where=radius > 0))
            + math.pi / 2
        )
    return np.where(level <= -radius, 0.0, np.where(level >= radius, math.pi * radius**2, area))


def small_tank_volume(heights_m: np.ndarray, alpha_rad: float) -> np.ndarray:
    x = np.linspace(0.0, 2.45, 5001)
    horizontal_radius, vertical_radius, probe_x = 0.89, 0.60, 0.40
    level = (
        np.tan(alpha_rad) * (x[None, :] - probe_x)
        - vertical_radius
        + np.asarray(heights_m)[:, None]
    )
    unit = np.clip(level / vertical_radius, -1.0, 1.0)
    area = horizontal_radius * vertical_radius * (
        unit * np.sqrt(np.maximum(0.0, 1.0 - unit**2)) + np.arcsin(unit) + math.pi / 2
    )
    area = np.where(level <= -vertical_radius, 0.0, np.where(
        level >= vertical_radius,
        math.pi * horizontal_radius * vertical_radius,
        area,
    ))
    return np.trapezoid(area, x, axis=1) * 1000.0


def _actual_tank_grid() -> tuple[np.ndarray, np.ndarray]:
    x = np.linspace(0.0, 10.0, 4001)
    sphere_radius = 1.625
    radius = np.where(
        x < 1.0,
        np.sqrt(np.maximum(0.0, sphere_radius**2 - (x - sphere_radius) ** 2)),
        np.where(
            x > 9.0,
            np.sqrt(np.maximum(0.0, sphere_radius**2 - (x - (10.0 - sphere_radius)) ** 2)),
            1.5,
        ),
    )
    return x, radius


def actual_tank_volume(heights_m: np.ndarray, alpha_rad: float, beta_rad: float) -> np.ndarray:
    x, radius = _actual_tank_grid()
    level = (
        np.tan(alpha_rad) * (x[None, :] - 3.0)
        + np.cos(beta_rad) * (-1.5 + np.asarray(heights_m)[:, None])
    )
    return np.trapezoid(_segment_area(radius[None, :], level), x, axis=1) * 1000.0


def solve_reference(attachment1: Path, attachment2: Path) -> dict:
    tilted = pd.read_excel(attachment1, sheet_name="倾斜变位进油")
    q1_heights = tilted.iloc[:, 3].to_numpy(float) / 1000.0
    q1_observed = 215.0 + tilted.iloc[:, 2].to_numpy(float)
    candidates = []
    for sign in (-1.0, 1.0):
        alpha = math.radians(sign * 4.1)
        predicted = small_tank_volume(q1_heights, alpha)
        candidates.append((float(np.sqrt(np.mean((predicted - q1_observed) ** 2))), alpha))
    q1_rmse, q1_alpha = min(candidates)

    actual = pd.read_excel(attachment2)
    heights = actual.iloc[:, 4].to_numpy(float) / 1000.0
    relative_volume = np.cumsum(
        actual.iloc[:, 2].fillna(0).to_numpy(float)
        - actual.iloc[:, 3].fillna(0).to_numpy(float)
    )
    split = len(actual) // 2

    def residual(parameters: np.ndarray) -> np.ndarray:
        alpha, beta, initial = parameters
        return actual_tank_volume(heights[:split], alpha, beta) - (
            initial + relative_volume[:split]
        )

    solutions = [
        least_squares(
            residual,
            guess,
            bounds=([-0.15, 0.0, 0.0], [0.15, 0.35, 100000.0]),
            max_nfev=120,
        )
        for guess in (
            [-0.04, 0.08, 59000.0],
            [-0.02, 0.12, 59000.0],
            [-0.06, 0.03, 59000.0],
        )
    ]
    best = min(solutions, key=lambda item: float(np.mean(item.fun**2)))
    alpha, beta, initial = best.x
    holdout_error = actual_tank_volume(heights[split:], alpha, beta) - (
        initial + relative_volume[split:]
    )
    q1_grid = np.arange(0.0, 1.2001, 0.01)
    q2_grid = np.arange(0.0, 3.0001, 0.10)
    return {
        "q1_alpha_deg": math.degrees(q1_alpha),
        "q1_data_rmse_l": q1_rmse,
        "q1_table": dict(zip(q1_grid.round(2).astype(str), small_tank_volume(q1_grid, q1_alpha))),
        "q2_alpha_abs_deg": abs(math.degrees(alpha)),
        "q2_beta_abs_deg": abs(math.degrees(beta)),
        "q2_initial_volume_l": float(initial),
        "q2_holdout_rmse_l": float(np.sqrt(np.mean(holdout_error**2))),
        "q2_table": dict(zip(q2_grid.round(1).astype(str), actual_tank_volume(q2_grid, alpha, beta))),
    }


def _height_volume_tables(workspace: Path) -> list[dict]:
    tables = []
    for path in workspace.rglob("*"):
        if not path.is_file() or path.suffix.casefold() not in {".csv", ".xlsx"}:
            continue
        relative = path.relative_to(workspace)
        if ".mmw" in relative.parts or path.name.startswith("问题A附件"):
            continue
        try:
            frames = (
                pd.read_excel(path, sheet_name=None)
                if path.suffix.casefold() == ".xlsx"
                else {"": pd.read_csv(path)}
            )
        except Exception:
            continue
        for sheet, frame in frames.items():
            numeric = frame.apply(pd.to_numeric, errors="coerce")
            usable = [column for column in numeric if numeric[column].notna().sum() >= 10]
            if len(usable) < 2:
                continue
            names = {column: str(column).casefold() for column in usable}
            height = next((c for c in usable if any(k in names[c] for k in ("高度", "油高", "height"))), usable[0])
            volume = next((c for c in usable if c != height and any(k in names[c] for k in ("容积", "体积", "储油", "volume"))), usable[1])
            pair = numeric[[height, volume]].dropna().sort_values(height)
            if len(pair) < 10:
                continue
            raw_height = pair[height].to_numpy(float)
            scale = 1.0 if raw_height.max() <= 5 else 100.0 if raw_height.max() <= 500 else 1000.0
            tables.append({
                "path": f"{relative.as_posix()}#{sheet}",
                "height_m": raw_height / scale,
                "volume_l": pair[volume].to_numpy(float),
            })
    return tables


def _check_table(candidates: list[dict], grid: np.ndarray, expected: np.ndarray, tolerance_l: float) -> dict:
    if not candidates:
        return {"passed": False, "reason": "未找到高度-容积表"}
    step = float(np.median(np.diff(grid)))
    candidate = min(
        candidates,
        key=lambda item: abs(float(item["height_m"][-1]) - float(grid[-1]))
        + 5 * abs(float(np.median(np.diff(item["height_m"]))) - step),
    )
    height, volume = candidate["height_m"], candidate["volume_l"]
    covered = (grid >= height.min() - step / 4) & (grid <= height.max() + step / 4)
    coverage = float(np.mean(covered))
    error = float(np.max(np.abs(np.interp(grid[covered], height, volume) - expected[covered]))) if covered.any() else math.inf
    monotonic = bool(np.all(np.diff(volume) >= -1e-6))
    return {
        "passed": coverage >= 0.9 and monotonic and error <= tolerance_l,
        "path": candidate["path"],
        "coverage": coverage,
        "monotonic": monotonic,
        "max_abs_error_l": error,
    }


def evaluate_workspace(workspace: Path, reference: dict) -> dict:
    candidates = _height_volume_tables(workspace)
    q1_grid = np.arange(0.0, 1.2001, 0.01)
    q2_grid = np.arange(0.0, 3.0001, 0.10)
    q1_expected = np.array([reference["q1_table"][str(round(value, 2))] for value in q1_grid])
    q2_expected = np.array([reference["q2_table"][str(round(value, 1))] for value in q2_grid])
    q1 = _check_table(candidates, q1_grid, q1_expected, 150.0)
    q2 = _check_table(candidates, q2_grid, q2_expected, 100.0)
    return {"q1_table": q1, "q2_table": q2, "overall_passed": q1["passed"] and q2["passed"]}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("attachment1", type=Path)
    parser.add_argument("attachment2", type=Path)
    parser.add_argument("--workspace", type=Path)
    args = parser.parse_args()
    reference = solve_reference(args.attachment1, args.attachment2)
    report = {key: value for key, value in reference.items() if not key.endswith("_table")}
    if args.workspace:
        report["workspace_evaluation"] = evaluate_workspace(args.workspace, reference)
    print(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False))
    return 0 if not args.workspace or report["workspace_evaluation"]["overall_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
