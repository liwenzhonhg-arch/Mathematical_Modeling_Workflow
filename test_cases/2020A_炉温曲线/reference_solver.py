"""2020 CUMCM A 题确定性参考求解器。

模型逐式移植自 https://github.com/CUMCM/2020-A ，验收范围同时参考
https://github.com/personqianduixue/CUMCM2020A 。它只用于回归验证，
不是竞赛提交代码。
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np

FRONT_LENGTH = BACK_LENGTH = 25.0
ZONE_LENGTH = 30.5
GAP_LENGTH = 5.0
ZONE_COUNT = 11
TOTAL_LENGTH = (
    FRONT_LENGTH
    + BACK_LENGTH
    + ZONE_COUNT * ZONE_LENGTH
    + (ZONE_COUNT - 1) * GAP_LENGTH
)
AMBIENT = 25.0
DT = 0.5
SUBSTEPS = 100
GRID_POINTS = 15
BOARD_LENGTH = 15.0
HK = np.array([0.0074, 0.0196, 0.0214, 0.0311, 0.0197, 0.0109, 4.6050])


def _temperature_profile(zones: np.ndarray, positions: np.ndarray) -> np.ndarray:
    lengths = (
        [0.0, FRONT_LENGTH]
        + [value for _ in range(ZONE_COUNT - 3) for value in (ZONE_LENGTH, GAP_LENGTH)]
        + [
            ZONE_LENGTH,
            GAP_LENGTH + ZONE_LENGTH + GAP_LENGTH / 2,
            GAP_LENGTH / 2 + ZONE_LENGTH,
            BACK_LENGTH,
        ]
    )
    knots = np.cumsum(lengths)
    temperatures = [AMBIENT] + [
        value for zone in zones[:-1] for value in (zone, zone)
    ] + [AMBIENT]
    return np.interp(positions, knots, temperatures)


def _heat_profile(positions: np.ndarray) -> np.ndarray:
    h0 = HK[0]
    h = HK[1:-1]
    values = np.array([
        h0,
        *([h[0]] * 5 + [h[1], h[2], h[3], h[3], h[4], h[4]]),
        h0,
    ])
    lengths = (
        [0.0, FRONT_LENGTH, ZONE_LENGTH + GAP_LENGTH / 2]
        + [ZONE_LENGTH + GAP_LENGTH] * (ZONE_COUNT - 2)
        + [ZONE_LENGTH + GAP_LENGTH / 2, BACK_LENGTH]
    )
    knots = np.cumsum(lengths)
    indexes = np.maximum(
        np.ceil(np.interp(positions, knots, np.arange(len(values) + 1))).astype(int),
        1,
    ) - 1
    return values[indexes]


def _step_operators() -> dict[float, tuple[np.ndarray, np.ndarray]]:
    """把 100 个显式子步合并成一次仿射矩阵运算。"""
    dx = BOARD_LENGTH / (GRID_POINTS - 1)
    diffusion = HK[-1] * (DT / SUBSTEPS) / dx**2
    operators = {}
    for heat in np.unique(HK[:-1]):
        matrix = np.zeros((GRID_POINTS, GRID_POINTS))
        matrix[0, 0] = matrix[-1, -1] = 1 - heat * DT / SUBSTEPS
        for index in range(1, GRID_POINTS - 1):
            matrix[index, index - 1] = diffusion
            matrix[index, index] = 1 - 2 * diffusion
            matrix[index, index + 1] = diffusion
        source = np.zeros(GRID_POINTS)
        source[[0, -1]] = heat * DT / SUBSTEPS
        augmented = np.eye(GRID_POINTS + 1)
        augmented[:GRID_POINTS, :GRID_POINTS] = matrix
        augmented[:GRID_POINTS, -1] = source
        powered = np.linalg.matrix_power(augmented, SUBSTEPS)
        operators[float(heat)] = (
            powered[:GRID_POINTS, :GRID_POINTS],
            powered[:GRID_POINTS, -1],
        )
    return operators


OPERATORS = _step_operators()


def simulate(zones: list[float], speed_cm_min: float) -> tuple[np.ndarray, np.ndarray]:
    speed = speed_cm_min / 60
    times = np.arange(0, TOTAL_LENGTH / speed + 1e-10, DT)
    positions = speed * times
    air = _temperature_profile(np.asarray(zones, dtype=float), positions)
    heat = _heat_profile(positions)
    board = np.full(GRID_POINTS, AMBIENT)
    center = np.full(len(times), AMBIENT)
    for index in range(1, len(times)):
        matrix, source = OPERATORS[float(heat[index])]
        board = matrix @ board + source * air[index]
        center[index] = board[GRID_POINTS // 2]
    return times, center


def process_metrics(times: np.ndarray, temperature: np.ndarray) -> dict[str, float]:
    slope = np.r_[0.0, np.diff(temperature) / np.diff(times)]
    peak_index = int(np.argmax(temperature))
    above_217 = np.flatnonzero(temperature >= 217)
    rising_end = int(np.flatnonzero(slope > 0)[-1])
    above_150 = np.flatnonzero(temperature[: rising_end + 1] > 150)
    below_190 = np.flatnonzero(temperature[: rising_end + 1] < 190)
    return {
        "peak": float(temperature[peak_index]),
        "max_rise": float(slope.max()),
        "max_fall": float(slope.min()),
        "time_150_190": float(times[below_190[-1]] - times[above_150[0]]),
        "time_above_217": (
            float(times[above_217[-1]] - times[above_217[0]])
            if len(above_217)
            else 0.0
        ),
    }


def is_feasible(metrics: dict[str, float]) -> bool:
    return (
        240 <= metrics["peak"] <= 250
        and metrics["max_rise"] <= 3
        and metrics["max_fall"] >= -3
        and 60 <= metrics["time_150_190"] <= 120
        and 40 <= metrics["time_above_217"] <= 90
    )


def solve_reference() -> dict[str, float]:
    zones_q1 = [173] * 5 + [198, 230, 257, 257, 25, 25]
    times, temperature = simulate(zones_q1, 78)
    positions = 78 / 60 * times
    starts = FRONT_LENGTH + (ZONE_LENGTH + GAP_LENGTH) * np.arange(ZONE_COUNT)
    targets = np.r_[starts[[2, 5, 6]] + ZONE_LENGTH / 2, starts[7] + ZONE_LENGTH]
    point_values = np.interp(targets, positions, temperature)

    zones_q2 = [182] * 5 + [203, 237, 254, 254, 25, 25]
    integer_feasible = [
        speed
        for speed in range(65, 101)
        if is_feasible(process_metrics(*simulate(zones_q2, speed)))
    ]
    low = float(integer_feasible[-1])
    high = low + 1
    for _ in range(16):
        middle = (low + high) / 2
        if is_feasible(process_metrics(*simulate(zones_q2, middle))):
            low = middle
        else:
            high = middle

    return {
        "q1_温区3中点温度": float(point_values[0]),
        "q1_温区6中点温度": float(point_values[1]),
        "q1_温区7中点温度": float(point_values[2]),
        "q1_温区8结束温度": float(point_values[3]),
        "q2_最大允许速度": low,
    }


def main() -> int:
    expected = json.loads(
        Path(__file__).with_name("reference_expected.json").read_text(encoding="utf-8")
    )
    results = solve_reference()
    failures = [
        f"{item['name']}={results[item['name']]:.6g} 不在 [{item['min']}, {item['max']}]"
        for item in expected["results"]
        if not item["min"] <= results[item["name"]] <= item["max"]
    ]
    print(json.dumps(results, ensure_ascii=False, indent=2))
    if failures:
        print("\n".join(failures))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
