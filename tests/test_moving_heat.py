"""通用移动热过程结构的合成数据回归测试。"""

import numpy as np
import pytest
from scipy.optimize import least_squares

from mmw.utils.moving_heat import (
    MovingSlabConfig,
    assess_multistart_identifiability,
    simulate_effective_slab,
    simulate_moving_slab,
    simulate_piecewise_first_order,
)


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


def test_first_order_response_matches_constant_environment_solution():
    times = np.array([2.0, 3.0, 5.0])
    response = simulate_piecewise_first_order(
        times,
        speed=1.0,
        air_position_knots=[0.0, 10.0],
        air_temperatures=[100.0, 100.0],
        response_position_knots=[0.0, 10.0],
        response_rates=[0.2, 0.2],
        initial_temperature=20.0,
    )

    expected = 100.0 + (20.0 - 100.0) * np.exp(-0.2 * times)
    assert response == pytest.approx(expected)


def test_first_order_response_recovers_synthetic_zone_rates():
    times = np.arange(0.0, 12.1, 0.2)
    common = {
        "speed": 1.0,
        "air_position_knots": [0.0, 3.0, 6.0, 9.0, 12.0],
        "air_temperatures": [20.0, 120.0, 220.0, 100.0, 20.0],
        "response_position_knots": [0.0, 4.0, 8.0, 12.0],
        "initial_temperature": 20.0,
    }
    true_rates = np.array([0.08, 0.16, 0.11, 0.05])
    observed = simulate_piecewise_first_order(
        times, response_rates=true_rates, **common,
    )
    starts = [
        np.array([0.04, 0.08, 0.06, 0.03]),
        np.array([0.10, 0.20, 0.14, 0.08]),
        np.array([0.20, 0.10, 0.20, 0.10]),
    ]
    fits = [
        least_squares(
            lambda rates: simulate_piecewise_first_order(
                times, response_rates=rates, **common,
            ) - observed,
            x0=start,
            bounds=(0.01, 0.5),
        )
        for start in starts
    ]
    report = assess_multistart_identifiability(
        [fit.x for fit in fits],
        [float(np.sum(fit.fun**2)) for fit in fits],
        initial_parameter_sets=starts,
    )

    assert report["identifiable"] is True
    assert np.asarray([fit.x for fit in fits]) == pytest.approx(
        np.tile(true_rates, (3, 1)), rel=1e-4,
    )


def test_first_order_response_rejects_nonpositive_rates():
    with pytest.raises(ValueError, match="response_rates"):
        simulate_piecewise_first_order(
            [0.0, 1.0],
            speed=1.0,
            air_position_knots=[0.0, 1.0],
            air_temperatures=[20.0, 100.0],
            response_position_knots=[0.0, 1.0],
            response_rates=[0.1, 0.0],
            initial_temperature=20.0,
        )


def test_effective_slab_recovers_synthetic_time_scales():
    times = np.arange(0.0, 12.0001, 0.2)

    def simulate(parameters):
        exchange_rate, diffusivity = parameters
        config = MovingSlabConfig(
            thickness=1.0,
            grid_points=7,
            sample_dt=0.2,
            substeps=4,
            diffusivity=diffusivity,
            initial_temperature=20.0,
        )
        return simulate_effective_slab(
            times,
            speed=1.0,
            air_position_knots=[0.0, 3.0, 6.0, 9.0, 12.0],
            air_temperatures=[20.0, 140.0, 220.0, 100.0, 20.0],
            exchange_position_breaks=[0.0, 12.0],
            exchange_rates=[exchange_rate],
            config=config,
        )

    truth = np.array([0.24, 0.018])
    observed = simulate(truth)
    fits = [
        least_squares(
            lambda parameters: simulate(parameters) - observed,
            start,
            bounds=([0.02, 0.002], [0.8, 0.05]),
            max_nfev=30,
        )
        for start in ([0.1, 0.01], [0.35, 0.03], [0.2, 0.025])
    ]

    assert np.asarray([fit.x for fit in fits]) == pytest.approx(
        np.tile(truth, (3, 1)), rel=1e-4,
    )


def test_effective_slab_rejects_unstable_boundary_step():
    config = MovingSlabConfig(
        thickness=1.0,
        grid_points=5,
        sample_dt=1.0,
        substeps=1,
        diffusivity=0.01,
        initial_temperature=20.0,
    )

    with pytest.raises(ValueError, match="边界交换不稳定"):
        simulate_effective_slab(
            [0.0, 1.0],
            speed=1.0,
            air_position_knots=[0.0, 1.0],
            air_temperatures=[20.0, 100.0],
            exchange_position_breaks=[0.0, 1.0],
            exchange_rates=[1.1],
            config=config,
        )


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


def test_robin_coefficient_uses_inverse_length_units():
    config = MovingSlabConfig(
        thickness=1.0,
        grid_points=3,
        sample_dt=1.0,
        substeps=1,
        diffusivity=0.025,
        initial_temperature=20.0,
    )

    center = simulate_moving_slab(
        [0.0, 1.0, 2.0],
        speed=1.0,
        air_position_knots=[0.0, 2.0],
        air_temperatures=[100.0, 100.0],
        transfer_position_knots=[0.0, 2.0],
        surface_transfer_rates=[0.2, 0.2],
        config=config,
    )

    assert center.tolist() == pytest.approx([20.0, 20.0, 20.32])


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


def test_multistart_identifiability_passes_consistent_near_optima():
    report = assess_multistart_identifiability(
        [[1.00, 2.00], [1.02, 1.98], [0.99, 2.01]],
        [1.000, 1.005, 1.008],
        initial_parameter_sets=[[0.5, 1.0], [1.5, 2.5], [2.5, 4.0]],
        outcome_sets=[[100.0], [101.0], [99.5]],
    )

    assert report["identifiable"] is True
    assert report["starts"] == 3
    assert report["near_optimal_count"] == 3
    assert report["failures"] == []


def test_multistart_identifiability_rejects_equally_good_different_parameters():
    report = assess_multistart_identifiability(
        [[1.0, 2.0], [4.0, 2.0], [8.0, 2.0]],
        [1.0, 1.0, 1.0],
        initial_parameter_sets=[[0.5, 1.0], [2.0, 2.0], [6.0, 3.0]],
    )

    assert report["identifiable"] is False
    assert "参数相对跨度超过阈值" in report["failures"][0]


def test_multistart_identifiability_rejects_divergent_outcomes():
    report = assess_multistart_identifiability(
        [[1.00], [1.01], [0.99]],
        [1.0, 1.0, 1.0],
        initial_parameter_sets=[[0.5], [1.5], [2.5]],
        outcome_sets=[[70.0], [85.0], [100.0]],
    )

    assert report["identifiable"] is False
    assert any("下游结果" in failure for failure in report["failures"])


@pytest.mark.parametrize(
    ("parameters", "losses"),
    [
        ([[1.0], [1.0]], [1.0, 1.0]),
        ([[1.0], [1.0], [1.0]], [1.0, np.nan, 1.0]),
        ([[1.0], [1.0], [1.0]], [1.0, -1.0, 1.0]),
    ],
)
def test_multistart_identifiability_rejects_invalid_inputs(parameters, losses):
    with pytest.raises(ValueError):
        assess_multistart_identifiability(
            parameters,
            losses,
            initial_parameter_sets=parameters,
        )


def test_multistart_identifiability_rejects_relaxed_spread_thresholds():
    with pytest.raises(ValueError, match="只能收紧"):
        assess_multistart_identifiability(
            [[1.0], [1.0], [1.0]],
            [1.0, 1.0, 1.0],
            initial_parameter_sets=[[0.5], [1.5], [2.5]],
            parameter_spread_tolerance=0.5,
        )


def test_multistart_identifiability_rejects_repeated_initial_values():
    with pytest.raises(ValueError, match="3 个不同初值"):
        assess_multistart_identifiability(
            [[1.0], [1.0], [1.0]],
            [1.0, 1.0, 1.0],
            initial_parameter_sets=[[0.5], [0.5], [2.5]],
        )
