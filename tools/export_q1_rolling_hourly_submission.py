"""Reproduce the Q1 rolling-origin forecast evidence without MMW checkpoints.

The competition-provided Excel workbooks are intentionally not bundled in the
supporting-material ZIP.  Pass their directory with ``--data-dir``.  The script
then reads ``solution.py`` and the published Q1 selection/validation CSV files
from the extracted supporting-material directory.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path

import numpy as np
import pandas as pd


EXPECTED_SOLUTION_SHA256 = (
    "1c7778861f312aeed36bafa2c08c8ad58b84db2b9fd6f42257260fe6f72a6b71"
)
EXPECTED_MODEL_SELECTION_SHA256 = (
    "3e383c98c476bdc45466fcf1a813aab08de25a8fa70b5799951c622853cf9eca"
)
EXPECTED_ROLLING_VALIDATION_SHA256 = (
    "9418887c508657daa99fe9caae53e64f0e7fb0172493368a7cbd0ed39753ae4b"
)
EXPECTED_INPUT_FILES = {
    "GPU_information.xlsx",
    "network_latency.xlsx",
    "power_mapping.xlsx",
    "region_time_data.xlsx",
    "storage_information.xlsx",
    "workload_trace.xlsx",
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def require_file(path: Path, expected_sha256: str | None = None) -> None:
    if not path.is_file():
        raise FileNotFoundError(f"required file not found: {path}")
    if expected_sha256 is not None:
        actual = sha256(path)
        if actual != expected_sha256:
            raise RuntimeError(
                f"file hash drift: {path}\nexpected={expected_sha256}\nactual={actual}"
            )


def load_solution(path: Path, data_dir: Path):
    os.environ["MMW_DATA_DIR"] = str(data_dir)
    spec = importlib.util.spec_from_file_location("submitted_solution", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load solution module: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def compute_metrics(selected: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for origin, group in selected.groupby("RollingOrigin", sort=True):
        per_series = []
        for _, series in group.groupby(["Region", "TaskType"], sort=False):
            denominator = float(series["Actual_GPU"].sum())
            if denominator > 0:
                per_series.append(
                    float(series["AbsoluteError_GPU"].sum() / denominator)
                )
        hourly = group.groupby("Hour", sort=True)[
            ["Actual_GPU", "Prediction_GPU"]
        ].sum()
        rows.append(
            {
                "RollingOrigin": int(origin),
                "ValidationStartHour": int(origin),
                "ValidationEndHour": int(origin + 23),
                "Macro_WAPE": float(np.mean(per_series)),
                "Micro_WAPE": float(
                    group["AbsoluteError_GPU"].sum() / group["Actual_GPU"].sum()
                ),
                "System_Aggregate_WAPE": float(
                    (hourly["Prediction_GPU"] - hourly["Actual_GPU"])
                    .abs()
                    .sum()
                    / hourly["Actual_GPU"].sum()
                ),
                "SeriesCount": 18,
                "HourlyPointCount": 24,
                "ObservationCount": int(len(group)),
                "ClosedLoopForecast": True,
                "FeatureUsesValidationTruth": False,
                "FinalTestUsedForSelection": False,
                "SelectedCandidateRule": (
                    "8-window MeanRMSE,MeanMAE,MeanWAPE,fixed_candidate_rank"
                ),
            }
        )
    return pd.DataFrame(rows)


def export(
    solution_path: Path,
    data_dir: Path,
    source_data_dir: Path,
    output_dir: Path,
) -> dict:
    model_selection_path = source_data_dir / "q1_model_selection.csv"
    rolling_validation_path = source_data_dir / "q1_rolling_validation.csv"

    require_file(solution_path, EXPECTED_SOLUTION_SHA256)
    require_file(model_selection_path, EXPECTED_MODEL_SELECTION_SHA256)
    require_file(rolling_validation_path, EXPECTED_ROLLING_VALIDATION_SHA256)

    if not data_dir.is_dir():
        raise FileNotFoundError(f"data directory not found: {data_dir}")
    input_paths = {path.name: path for path in data_dir.glob("*.xlsx")}
    missing_inputs = sorted(EXPECTED_INPUT_FILES - set(input_paths))
    if missing_inputs:
        raise FileNotFoundError(
            "missing competition-provided input workbooks: " + ", ".join(missing_inputs)
        )

    model = load_solution(solution_path, data_dir)
    inputs = model.read_inputs()
    model.validate_inputs(inputs)
    demand, _ = model.aggregate_demand(inputs["workload"])
    table = (
        demand.pivot_table(
            index="Hour",
            columns=["Region", "TaskType"],
            values="GPU_Demand",
            fill_value=0,
        )
        .sort_index()
    )

    selection = pd.read_csv(model_selection_path)
    selected_map = {
        (row.Region, row.TaskType): row.SelectedCandidateID
        for row in selection.itertuples(index=False)
    }
    specs = model._forecast_candidate_specs()
    rows = []
    for region in model.REGIONS:
        for task_type in model.TASK_TYPES:
            y = table[(region, task_type)].to_numpy(float)
            selected_id = selected_map[(region, task_type)]
            for candidate in specs:
                candidate_id = model._candidate_id(candidate)
                for origin in model.Q1_ROLLING_ORIGINS:
                    fitted = (
                        model._fit_huber(
                            y,
                            origin - 1,
                            candidate["HuberEpsilon"],
                            candidate["HuberAlpha"],
                        )
                        if candidate["CandidateModel"] == "Huber"
                        else None
                    )
                    predictions = model._recursive_forecast(
                        y,
                        origin,
                        model.Q1_FORECAST_HORIZON,
                        candidate["CandidateModel"],
                        fitted,
                    )
                    for offset, value in enumerate(predictions):
                        hour = int(origin + offset)
                        actual = float(y[hour])
                        prediction = float(value)
                        rows.append(
                            {
                                "Region": region,
                                "TaskType": task_type,
                                "CandidateID": candidate_id,
                                "CandidateRank": int(candidate["CandidateRank"]),
                                "CandidateModel": candidate["CandidateModel"],
                                "HuberEpsilon": candidate["HuberEpsilon"],
                                "HuberAlpha": candidate["HuberAlpha"],
                                "RollingOrigin": int(origin),
                                "TrainStartHour": 0,
                                "TrainEndHour": int(origin - 1),
                                "ValidationStartHour": int(origin),
                                "ValidationEndHour": int(
                                    origin + model.Q1_FORECAST_HORIZON - 1
                                ),
                                "Hour": hour,
                                "Actual_GPU": actual,
                                "Prediction_GPU": prediction,
                                "AbsoluteError_GPU": abs(prediction - actual),
                                "SelectedCandidateForSeries": bool(
                                    candidate_id == selected_id
                                ),
                                "ClosedLoopForecast": True,
                                "FeatureUsesValidationTruth": False,
                                "FinalTestUsedForSelection": False,
                            }
                        )

    frame = (
        pd.DataFrame(rows)
        .sort_values(
            ["Region", "TaskType", "CandidateRank", "RollingOrigin", "Hour"],
            kind="mergesort",
        )
        .reset_index(drop=True)
    )
    expected_rows = (
        len(model.REGIONS)
        * len(model.TASK_TYPES)
        * len(specs)
        * len(model.Q1_ROLLING_ORIGINS)
        * model.Q1_FORECAST_HORIZON
    )
    if len(frame) != expected_rows:
        raise RuntimeError(f"prediction row count {len(frame)} != {expected_rows}")

    selected = frame.loc[frame["SelectedCandidateForSeries"]].copy()
    expected_selected_rows = (
        len(model.REGIONS)
        * len(model.TASK_TYPES)
        * len(model.Q1_ROLLING_ORIGINS)
        * model.Q1_FORECAST_HORIZON
    )
    if len(selected) != expected_selected_rows:
        raise RuntimeError(
            f"selected prediction row count {len(selected)} != {expected_selected_rows}"
        )

    source_validation = pd.read_csv(rolling_validation_path)
    recomputed = []
    group_columns = ["Region", "TaskType", "CandidateID", "RollingOrigin"]
    for keys, group in frame.groupby(group_columns, sort=False):
        denominator = float(group["Actual_GPU"].sum())
        error = group["Prediction_GPU"] - group["Actual_GPU"]
        recomputed.append(
            {
                "Region": keys[0],
                "TaskType": keys[1],
                "CandidateID": keys[2],
                "RollingOrigin": int(keys[3]),
                "MAE": float(group["AbsoluteError_GPU"].mean()),
                "RMSE": float(np.sqrt(np.mean(np.square(error)))),
                "WAPE": (
                    np.nan
                    if denominator <= 0
                    else float(group["AbsoluteError_GPU"].sum() / denominator)
                ),
            }
        )
    reproduced_validation = pd.DataFrame(recomputed)
    merged = source_validation.merge(
        reproduced_validation,
        on=group_columns,
        suffixes=("_source", "_recomputed"),
        validate="one_to_one",
    )
    residuals = {}
    for metric in ("MAE", "RMSE", "WAPE"):
        source = merged[f"{metric}_source"].to_numpy(float)
        reproduced = merged[f"{metric}_recomputed"].to_numpy(float)
        both_nan = np.isnan(source) & np.isnan(reproduced)
        difference = np.abs(source[~both_nan] - reproduced[~both_nan])
        residuals[metric] = float(difference.max(initial=0.0))
        if not np.allclose(
            source[~both_nan], reproduced[~both_nan], rtol=1e-11, atol=1e-11
        ):
            raise RuntimeError(f"{metric} reproduction failed")

    window_metrics = compute_metrics(selected)
    output_dir.mkdir(parents=True, exist_ok=True)
    prediction_path = output_dir / "q1_rolling_predictions.csv"
    metric_path = output_dir / "q1_rolling_window_metrics.csv"
    frame.to_csv(prediction_path, index=False, float_format="%.15g")
    window_metrics.to_csv(metric_path, index=False, float_format="%.15g")

    report = {
        "schema_version": 2,
        "status": "pass",
        "scope": (
            "Q1 rolling-origin hourly prediction evidence only; "
            "no scheduling or Q2-Q4 solve"
        ),
        "checkpoint_dependency": False,
        "solution_sha256": sha256(solution_path),
        "model_selection_sha256": sha256(model_selection_path),
        "rolling_validation_sha256": sha256(rolling_validation_path),
        "input_sha256": {
            name: sha256(input_paths[name]) for name in sorted(EXPECTED_INPUT_FILES)
        },
        "rolling_origins": [int(value) for value in model.Q1_ROLLING_ORIGINS],
        "horizon_hours": int(model.Q1_FORECAST_HORIZON),
        "candidate_count": len(specs),
        "series_count": 18,
        "prediction_rows": len(frame),
        "selected_prediction_rows": len(selected),
        "window_metric_rows": len(window_metrics),
        "metric_reproduction_max_abs_residual": residuals,
        "outputs": {
            prediction_path.name: {
                "bytes": prediction_path.stat().st_size,
                "sha256": sha256(prediction_path),
            },
            metric_path.name: {
                "bytes": metric_path.stat().st_size,
                "sha256": sha256(metric_path),
            },
        },
        "no_leakage": {
            "closed_loop": True,
            "feature_uses_validation_truth": False,
            "final_test_used_for_selection": False,
            "per_window_winner_used_for_aggregate_curve": False,
        },
    }
    report_path = output_dir / "q1_rolling_hourly_provenance.json"
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return report


def parse_args() -> argparse.Namespace:
    script_dir = Path(__file__).resolve().parent
    package_root = script_dir.parent
    parser = argparse.ArgumentParser(
        description="Reproduce Q1 rolling-origin predictions without an .mmw directory."
    )
    parser.add_argument(
        "--data-dir",
        type=Path,
        required=True,
        help="directory containing the six competition-provided Excel workbooks",
    )
    parser.add_argument(
        "--solution",
        type=Path,
        default=script_dir / "solution.py",
        help="submitted solution.py (default: code/solution.py)",
    )
    parser.add_argument(
        "--source-data-dir",
        type=Path,
        default=package_root / "data",
        help="submitted result CSV directory (default: data/)",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=package_root / "reproduced_q1",
        help="reproduction output directory (default: reproduced_q1/)",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    export(
        args.solution.resolve(),
        args.data_dir.resolve(),
        args.source_data_dir.resolve(),
        args.output_dir.resolve(),
    )
