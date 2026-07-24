"""移动物体一维瞬态导热的通用确定性仿真工具。

本模块只实现与具体赛题无关的物理结构，不包含任何真题参数、答案或验收范围。
位置方向描述物体经过的环境，网格方向描述物体内部厚度方向。
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class MovingSlabConfig:
    """一维平板显式有限差分配置。

    `surface_transfer_rate` 由调用方通过位置剖面提供，单位为 1/time，
    表示边界控制体与环境的等效换热速率。
    """

    thickness: float
    grid_points: int
    sample_dt: float
    substeps: int
    diffusivity: float
    initial_temperature: float
    scheme: str = "explicit"

    def __post_init__(self) -> None:
        if self.thickness <= 0:
            raise ValueError("thickness 必须为正数")
        if self.grid_points < 3 or self.grid_points % 2 == 0:
            raise ValueError("grid_points 必须是不小于 3 的奇数")
        if self.sample_dt <= 0 or self.substeps <= 0:
            raise ValueError("sample_dt 和 substeps 必须为正数")
        if self.diffusivity <= 0:
            raise ValueError("diffusivity 必须为正数")
        if self.scheme not in {"explicit", "implicit"}:
            raise ValueError("scheme 必须为 explicit 或 implicit")

    @property
    def spatial_step(self) -> float:
        return self.thickness / (self.grid_points - 1)

    @property
    def internal_dt(self) -> float:
        return self.sample_dt / self.substeps

    @property
    def diffusion_number(self) -> float:
        return self.diffusivity * self.internal_dt / self.spatial_step**2


def _validated_profile(
    knots,
    values,
    *,
    name: str,
    nonnegative: bool = False,
) -> tuple[np.ndarray, np.ndarray]:
    x = np.asarray(knots, dtype=float)
    y = np.asarray(values, dtype=float)
    if x.ndim != 1 or y.ndim != 1 or len(x) != len(y) or len(x) < 2:
        raise ValueError(f"{name} 的 knots/values 必须是一维等长数组且至少含 2 点")
    if not np.all(np.isfinite(x)) or not np.all(np.isfinite(y)):
        raise ValueError(f"{name} 不能包含 NaN/Inf")
    if np.any(np.diff(x) <= 0):
        raise ValueError(f"{name} 的 knots 必须严格递增")
    if nonnegative and np.any(y < 0):
        raise ValueError(f"{name} 不能为负")
    return x, y


def simulate_moving_slab(
    sample_times,
    *,
    speed: float,
    air_position_knots,
    air_temperatures,
    transfer_position_knots,
    surface_transfer_rates,
    config: MovingSlabConfig,
) -> np.ndarray:
    """返回移动平板中心温度序列。

    环境温度和表面对流速率均按位置线性插值。显式离散在每个采样间隔内
    使用 `substeps` 个子步；若 CFL 或边界更新不稳定则拒绝计算。
    """

    times = np.asarray(sample_times, dtype=float)
    if times.ndim != 1 or len(times) < 2 or not np.all(np.isfinite(times)):
        raise ValueError("sample_times 必须是至少含 2 点的有限一维数组")
    if times[0] < 0 or np.any(np.diff(times) <= 0):
        raise ValueError("sample_times 必须从非负时间开始并严格递增")
    if not np.allclose(np.diff(times), config.sample_dt, rtol=1e-9, atol=1e-12):
        raise ValueError("sample_times 间隔必须等于 config.sample_dt")
    if not np.isfinite(speed) or speed <= 0:
        raise ValueError("speed 必须为正的有限数值")

    air_x, air_t = _validated_profile(
        air_position_knots, air_temperatures, name="air_profile",
    )
    transfer_x, transfer_rate = _validated_profile(
        transfer_position_knots,
        surface_transfer_rates,
        name="transfer_profile",
        nonnegative=True,
    )

    r = config.diffusion_number
    if config.scheme == "explicit" and r > 0.5:
        raise ValueError(f"显式格式不稳定: diffusion_number={r:.6g} > 0.5")

    state = np.full(config.grid_points, config.initial_temperature, dtype=float)
    center = np.empty(len(times), dtype=float)
    center[0] = state[config.grid_points // 2]
    sub_dt = config.internal_dt

    for sample_index in range(1, len(times)):
        interval_start = times[sample_index - 1]
        for sub_index in range(config.substeps):
            sub_time = interval_start + (sub_index + 0.5) * sub_dt
            position = speed * sub_time
            air = float(np.interp(position, air_x, air_t))
            boundary_rate = float(np.interp(position, transfer_x, transfer_rate))
            boundary_number = boundary_rate * sub_dt
            if config.scheme == "explicit" and 2 * r + boundary_number > 1:
                raise ValueError(
                    "显式边界格式不稳定: "
                    f"2*r+b={2 * r + boundary_number:.6g} > 1"
                )

            previous = state
            if config.scheme == "implicit":
                matrix = np.zeros((config.grid_points, config.grid_points))
                rhs = previous.copy()
                for index in range(1, config.grid_points - 1):
                    matrix[index, index - 1] = -r
                    matrix[index, index] = 1 + 2 * r
                    matrix[index, index + 1] = -r
                matrix[0, 0] = matrix[-1, -1] = 1 + 2 * r + boundary_number
                matrix[0, 1] = matrix[-1, -2] = -2 * r
                rhs[[0, -1]] += boundary_number * air
                state = np.linalg.solve(matrix, rhs)
            else:
                state = previous.copy()
                state[1:-1] = (
                    previous[1:-1]
                    + r * (previous[2:] - 2 * previous[1:-1] + previous[:-2])
                )
                state[0] = (
                    previous[0]
                    + 2 * r * (previous[1] - previous[0])
                    + boundary_number * (air - previous[0])
                )
                state[-1] = (
                    previous[-1]
                    + 2 * r * (previous[-2] - previous[-1])
                    + boundary_number * (air - previous[-1])
                )
        center[sample_index] = state[config.grid_points // 2]

    if not np.all(np.isfinite(center)):
        raise RuntimeError("仿真产生了非有限温度")
    return center
