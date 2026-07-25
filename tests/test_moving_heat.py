"""通用移动热过程结构的合成数据回归测试。"""

import numpy as np
import pytest
from scipy.optimize import least_squares

from mmw.utils.moving_heat import MovingSlabConfig, simulate_moving_slab


def _synthetic_setup():
    config = MovingSlabConfig(
        thickness=1.0,
        grid_points=11,
        sample_dt=0.2,
        substeps=5,
        diffusivity=0.01,
        initial_temperature=20.0,
    )
    times = np.arange(0.0, 12.0001, config.sample_dt)
    common = {
        "speed": 1.0,
        "air_position_knots": [0.0, 2.0, 5.0, 9.0, 12.0],
        "air_temperatures": [20.0, 100.0, 220.0, 140.0, 20.0],
        "transfer_position_knots": [0.0, 3.0, 7.0, 12.0],
        "config": config,
    }
    return config, times, common


def test_uniform_equilibrium_stays_constant():
    config, times, common = _synthetic_setup()
    common["air_temperatures"] = [20.0] * len(common["air_position_knots"])

    center = simulate_moving_slab(
        times,
        surface_transfer_rates=[0.2, 0.4, 0.3, 0.1],
        **common,
    )

    assert np.allclose(center, config.initial_temperature)


def test_synthetic_transfer_scale_is_recovered():
    _, times, common = _synthetic_setup()
    base_rates = np.array([0.3, 0.7, 0.45, 0.2])
    true_scale = 1.4
    observed = simulate_moving_slab(
        times,
        surface_transfer_rates=base_rates * true_scale,
        **common,
    )

    fit = least_squares(
        lambda candidate: simulate_moving_slab(
            times,
            surface_transfer_rates=base_rates * candidate[0],
            **common,
        ) - observed,
        x0=[0.8],
        bounds=(0.1, 3.0),
        max_nfev=15,
    )

    assert fit.x[0] == pytest.approx(true_scale, rel=1e-4)
    assert np.sqrt(np.mean(fit.fun**2)) < 1e-8


def test_unstable_explicit_grid_is_rejected():
    config = MovingSlabConfig(
        thickness=1.0,
        grid_points=11,
        sample_dt=1.0,
        substeps=1,
        diffusivity=0.02,
        initial_temperature=20.0,
    )

    with pytest.raises(ValueError, match="diffusion_number"):
        simulate_moving_slab(
            [0.0, 1.0],
            speed=1.0,
            air_position_knots=[0.0, 1.0],
            air_temperatures=[20.0, 100.0],
            transfer_position_knots=[0.0, 1.0],
            surface_transfer_rates=[0.1, 0.1],
            config=config,
        )


def test_implicit_scheme_handles_stiff_grid():
    times = np.arange(0.0, 2.5, 0.5)
    config = MovingSlabConfig(
        thickness=0.01,
        grid_points=5,
        sample_dt=0.5,
        substeps=1,
        diffusivity=1.0,
        initial_temperature=25.0,
        scheme="implicit",
    )

    center = simulate_moving_slab(
        times,
        speed=1.0,
        air_position_knots=[0.0, 10.0],
        air_temperatures=[100.0, 100.0],
        transfer_position_knots=[0.0, 10.0],
        surface_transfer_rates=[0.1, 0.1],
        config=config,
    )

    assert np.all(np.isfinite(center))
    assert np.all(np.diff(center) >= 0)
