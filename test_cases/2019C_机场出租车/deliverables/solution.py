from __future__ import annotations

import json
import math
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


ROOT = Path.cwd()
RAW = ROOT / "data" / "raw"
FIG = ROOT / "figures"
FIG.mkdir(exist_ok=True)

AIRPORT_LNG = 113.8108
AIRPORT_LAT = 22.6260
AIRPORT_RADIUS_KM = 2.0
BASE_FARE = 10.0
FARE_PER_KM = 2.6
TIME_COST_PER_MIN = 0.45
AVG_PASSENGERS_PER_FLIGHT = 150
SERVICE_MIN_PER_TAXI = 1.5


def haversine(lng1, lat1, lng2, lat2):
    lng1 = np.radians(lng1)
    lat1 = np.radians(lat1)
    lng2 = np.radians(lng2)
    lat2 = np.radians(lat2)
    dlng = lng2 - lng1
    dlat = lat2 - lat1
    a = np.sin(dlat / 2) ** 2 + np.cos(lat1) * np.cos(lat2) * np.sin(dlng / 2) ** 2
    return 6371.0 * 2 * np.arcsin(np.sqrt(a))


def gini(values):
    arr = np.sort(np.asarray(values, dtype=float))
    arr = arr[np.isfinite(arr)]
    if len(arr) == 0 or np.allclose(arr.sum(), 0):
        return 0.0
    n = len(arr)
    return float((2 * np.arange(1, n + 1) @ arr) / (n * arr.sum()) - (n + 1) / n)


def read_data():
    taxi_cols = [
        "taxi_id",
        "pickup_time",
        "dropoff_time",
        "pickup_lng",
        "pickup_lat",
        "dropoff_lng",
        "dropoff_lat",
    ]
    taxi_raw = pd.read_csv(RAW / "Taxi_Trips.csv", header=None, names=taxi_cols)
    taxi = taxi_raw.copy()
    taxi["pickup_time"] = pd.to_datetime(taxi["pickup_time"], errors="coerce")
    taxi["dropoff_time"] = pd.to_datetime(taxi["dropoff_time"], errors="coerce")
    taxi = taxi.dropna(subset=["pickup_time", "dropoff_time"]).copy()
    taxi["duration_min"] = (taxi["dropoff_time"] - taxi["pickup_time"]).dt.total_seconds() / 60
    taxi["distance_km"] = haversine(
        taxi["pickup_lng"], taxi["pickup_lat"], taxi["dropoff_lng"], taxi["dropoff_lat"]
    )
    taxi["speed_kmh"] = taxi["distance_km"] / (taxi["duration_min"] / 60)
    valid_time = taxi[(taxi["duration_min"] > 0) & taxi["speed_kmh"].notna()].copy()
    duration_q1, duration_q3 = valid_time["duration_min"].quantile([0.25, 0.75])
    distance_q1, distance_q3 = valid_time["distance_km"].quantile([0.25, 0.75])
    speed_q1, speed_q3 = valid_time["speed_kmh"].quantile([0.25, 0.75])
    duration_iqr = duration_q3 - duration_q1
    distance_iqr = distance_q3 - distance_q1
    speed_iqr = speed_q3 - speed_q1
    duration_upper = float(duration_q3 + 1.5 * duration_iqr)
    distance_upper = float(distance_q3 + 1.5 * distance_iqr)
    speed_upper = float(speed_q3 + 1.5 * speed_iqr)
    duration_outliers = int((valid_time["duration_min"] > duration_upper).sum())
    distance_outliers = int((valid_time["distance_km"] > distance_upper).sum())
    speed_outliers = int((valid_time["speed_kmh"] > speed_upper).sum())
    taxi = valid_time[valid_time["speed_kmh"].between(1, 120)].copy()
    taxi["pickup_airport"] = (
        haversine(taxi["pickup_lng"], taxi["pickup_lat"], AIRPORT_LNG, AIRPORT_LAT)
        <= AIRPORT_RADIUS_KM
    )
    taxi["dropoff_airport"] = (
        haversine(taxi["dropoff_lng"], taxi["dropoff_lat"], AIRPORT_LNG, AIRPORT_LAT)
        <= AIRPORT_RADIUS_KM
    )
    taxi["hour"] = taxi["pickup_time"].dt.hour
    taxi["fare_proxy"] = BASE_FARE + FARE_PER_KM * taxi["distance_km"]

    flights_raw = pd.read_excel(RAW / "flight_data.xlsx", sheet_name="Sheet2")
    required_flight_cols = ["计划到达时间", "出发地/经停点", "航空公司/航班号"]
    flight_missing_rows = int(flights_raw[required_flight_cols].isna().any(axis=1).sum())
    flights = flights_raw.dropna(subset=["计划到达时间", "出发地/经停点"]).copy()
    flights["arrival_time"] = pd.to_datetime(
        flights["计划到达时间"].astype(str), format="%H:%M:%S", errors="coerce"
    )
    flights["hour"] = flights["arrival_time"].dt.hour
    profile = {
        "flight_raw_rows": int(len(flights_raw)),
        "flight_missing_rows": flight_missing_rows,
        "flight_missing_rate": float(flight_missing_rows / len(flights_raw) * 100),
        "taxi_raw_rows": int(len(taxi_raw)),
        "taxi_unique_ids": int(taxi_raw["taxi_id"].nunique()),
        "taxi_valid_time_rows": int(len(valid_time)),
        "duration_outlier_upper": duration_upper,
        "duration_outliers": duration_outliers,
        "duration_outlier_rate": float(duration_outliers / len(valid_time) * 100),
        "distance_outlier_upper": distance_upper,
        "distance_outliers": distance_outliers,
        "distance_outlier_rate": float(distance_outliers / len(valid_time) * 100),
        "speed_outlier_upper": speed_upper,
        "speed_outliers": speed_outliers,
        "speed_outlier_rate": float(speed_outliers / len(valid_time) * 100),
    }
    return taxi, flights, profile


def mmc_metrics(lam_per_hour, mu_per_hour, c):
    rho = lam_per_hour / (c * mu_per_hour)
    if rho >= 1:
        return {
            "c": c,
            "rho": rho,
            "Lq": math.inf,
            "Wq_min": math.inf,
            "throughput": c * mu_per_hour,
            "stable": 0,
            "feasible": 0,
        }
    a = lam_per_hour / mu_per_hour
    p0_inv = sum((a**k) / math.factorial(k) for k in range(c))
    p0_inv += (a**c) / (math.factorial(c) * (1 - rho))
    p0 = 1 / p0_inv
    lq = ((a**c) * rho * p0) / (math.factorial(c) * (1 - rho) ** 2)
    wq_hour = lq / lam_per_hour if lam_per_hour > 0 else 0
    wq_min = wq_hour * 60
    return {
        "c": c,
        "rho": rho,
        "Lq": lq,
        "Wq_min": wq_min,
        "throughput": min(lam_per_hour, c * mu_per_hour),
        "stable": 1,
        "feasible": int(rho <= 0.85 and wq_min <= 10),
    }


def main():
    np.random.seed(2026)
    taxi, flights, profile = read_data()
    airport_out = taxi[taxi["pickup_airport"] & ~taxi["dropoff_airport"]].copy()
    airport_in = taxi[~taxi["pickup_airport"] & taxi["dropoff_airport"]].copy()
    airport_internal = taxi[taxi["pickup_airport"] & taxi["dropoff_airport"]].copy()
    city = taxi[~taxi["pickup_airport"] & ~taxi["dropoff_airport"]].copy()

    hourly_taxi = airport_out.groupby("hour").size().reindex(range(24), fill_value=0)
    hourly_flights = flights.groupby("hour").size().reindex(range(24), fill_value=0)
    p_taxi = (hourly_taxi / (hourly_flights * AVG_PASSENGERS_PER_FLIGHT).replace(0, np.nan)).clip(0, 1)
    p_taxi = p_taxi.fillna(p_taxi[p_taxi > 0].median())

    airport_fares = airport_out["fare_proxy"].to_numpy()
    city_fares = city["fare_proxy"].to_numpy()
    airport_mean_fare = float(np.mean(airport_fares))
    city_mean_fare = float(np.mean(city_fares))

    scenarios = []
    for hour in range(24):
        n_q = int(max(10, hourly_taxi.rolling(3, min_periods=1).mean().iloc[hour] * 0.18))
        n_f = int(hourly_flights.iloc[hour])
        service_rate = 60 / SERVICE_MIN_PER_TAXI
        wait_min = n_q / service_rate
        returns = []
        for _ in range(2500):
            ra = np.random.choice(airport_fares) if len(airport_fares) else airport_mean_fare
            rb = np.random.choice(city_fares) if len(city_fares) else city_mean_fare
            pt = float(np.clip(np.random.normal(p_taxi.iloc[hour], 0.04), 0.03, 0.95))
            city_wait = float(np.clip(np.random.normal(10, 4), 3, 30))
            queue_profit = pt * ra - TIME_COST_PER_MIN * wait_min
            return_profit = rb - TIME_COST_PER_MIN * (25 + city_wait)
            returns.append((queue_profit, return_profit))
        arr = np.array(returns)
        queue_mean = float(arr[:, 0].mean())
        return_mean = float(arr[:, 1].mean())
        scenarios.append(
            {
                "hour": hour,
                "flights": n_f,
                "airport_trips": int(hourly_taxi.iloc[hour]),
                "p_taxi_proxy": float(p_taxi.iloc[hour]),
                "queue_wait_min": float(wait_min),
                "queue_profit": queue_mean,
                "return_profit": return_mean,
                "decision": "queue" if queue_mean >= return_mean else "return",
            }
        )
    result1 = pd.DataFrame(scenarios)

    result2 = pd.DataFrame(
        {
            "metric": [
                "valid_taxi_trips",
                "airport_departures",
                "airport_arrivals",
                "airport_internal",
                "valid_flights",
                "airport_mean_distance_km",
                "city_mean_distance_km",
                "airport_mean_fare_proxy",
                "city_mean_fare_proxy",
            ],
            "value": [
                len(taxi),
                len(airport_out),
                len(airport_in),
                len(airport_internal),
                len(flights),
                float(airport_out["distance_km"].mean()),
                float(city["distance_km"].mean()),
                airport_mean_fare,
                city_mean_fare,
            ],
        }
    )

    lam = float(max(1, hourly_taxi.quantile(0.90)))
    mu = 60 / SERVICE_MIN_PER_TAXI
    queue_rows = [mmc_metrics(lam, mu, c) for c in range(1, 25)]
    result3 = pd.DataFrame(queue_rows)
    result3["marginal_capacity"] = result3["throughput"].diff().fillna(result3["throughput"])
    result3["operational_score"] = (
        result3["Wq_min"].replace(math.inf, 9999)
        + 0.08 * result3["c"]
        + 40 * (result3["rho"] > 0.85).astype(int)
    )
    feasible = result3[result3["feasible"] == 1].copy()
    best_c = int(feasible.loc[feasible["operational_score"].idxmin(), "c"] if not feasible.empty else result3.loc[result3["operational_score"].idxmin(), "c"])
    best_queue = result3[result3["c"] == best_c].iloc[0].to_dict()

    distances = airport_out["distance_km"].dropna()
    threshold_candidates = np.linspace(max(1.0, distances.quantile(0.15)), distances.quantile(0.5), 8)
    base_income = BASE_FARE + FARE_PER_KM * distances
    priority_rows = []
    for threshold in threshold_candidates:
        is_short = distances <= threshold
        income_after = base_income.copy()
        income_after[is_short] = income_after[is_short] + TIME_COST_PER_MIN * result1["queue_wait_min"].median()
        priority_rows.append(
            {
                "short_threshold_km": float(threshold),
                "short_share": float(is_short.mean()),
                "gini_before": gini(base_income),
                "gini_after": gini(income_after),
                "mean_income_before": float(base_income.mean()),
                "mean_income_after": float(income_after.mean()),
                "efficiency_loss_rate": float(is_short.mean() * 0.02),
            }
        )
    result4 = pd.DataFrame(priority_rows)
    best_priority = result4.loc[result4["gini_after"].idxmin()].to_dict()

    result1.to_excel(ROOT / "result1.xlsx", index=False)
    result2.to_excel(ROOT / "result2.xlsx", index=False)
    result3.to_excel(ROOT / "result3.xlsx", index=False)
    result4.to_excel(ROOT / "result4.xlsx", index=False)

    plt.figure(figsize=(10, 5))
    plt.plot(result1["hour"], result1["queue_profit"], label="Queue")
    plt.plot(result1["hour"], result1["return_profit"], label="Return")
    plt.xlabel("Hour")
    plt.ylabel("Expected profit proxy")
    plt.legend()
    plt.tight_layout()
    plt.savefig(FIG / "fig_01_decision_profit.png", dpi=160)
    plt.close()

    plt.figure(figsize=(8, 5))
    plt.plot(result3["c"], result3["Wq_min"], marker="o")
    plt.axvline(best_c, color="red", linestyle="--", label=f"recommended c={best_c}")
    plt.xlabel("Number of pickup points")
    plt.ylabel("Mean queue wait (min)")
    plt.legend()
    plt.tight_layout()
    plt.savefig(FIG / "fig_02_pickup_points.png", dpi=160)
    plt.close()

    plt.figure(figsize=(8, 5))
    plt.plot(result4["short_threshold_km"], result4["gini_before"], label="Before")
    plt.plot(result4["short_threshold_km"], result4["gini_after"], label="After")
    plt.xlabel("Short-trip threshold (km)")
    plt.ylabel("Income Gini")
    plt.legend()
    plt.tight_layout()
    plt.savefig(FIG / "fig_03_priority_gini.png", dpi=160)
    plt.close()

    sensitivity = {}
    base_hour = int(result1.loc[(result1["queue_profit"] - result1["return_profit"]).abs().idxmin(), "hour"])
    base_row = result1[result1["hour"] == base_hour].iloc[0]
    base_queue_profit = float(base_row["queue_profit"])
    base_return_profit = float(base_row["return_profit"])
    decision_margin = result1["queue_profit"] - result1["return_profit"]
    queue_recommend_hours = int((decision_margin >= 0).sum())
    high_flight_hours = set(hourly_flights.sort_values(ascending=False).head(6).index.astype(int))
    high_flight_queue_hours = int(result1[result1["hour"].isin(high_flight_hours)]["decision"].eq("queue").sum())
    high_flight_alignment_rate = float(high_flight_queue_hours / len(high_flight_hours) * 100)
    hourly_corr = float(hourly_flights.corr(hourly_taxi))
    peak_lag_hours = int((int(hourly_taxi.idxmax()) - int(hourly_flights.idxmax())) % 24)
    lag_adjusted_corr = float(hourly_flights.corr(hourly_taxi.shift(-peak_lag_hours, fill_value=0)))
    queue_wait_threshold = None
    p_taxi_threshold = None
    for factor, values in {
        "p_taxi": np.linspace(0.05, 0.6, 12),
        "queue_wait_min": np.linspace(2, 35, 12),
        "time_cost": np.linspace(0.2, 1.2, 12),
    }.items():
        rows = []
        for val in values:
            pt = base_row["p_taxi_proxy"]
            wait = base_row["queue_wait_min"]
            cost = TIME_COST_PER_MIN
            if factor == "p_taxi":
                pt = val
            elif factor == "queue_wait_min":
                wait = val
            else:
                cost = val
            qp = pt * airport_mean_fare - cost * wait
            rp = city_mean_fare - cost * (25 + 10)
            rows.append({"value": float(val), "queue_profit": float(qp), "return_profit": float(rp)})
        sensitivity[factor] = rows
        if factor in {"p_taxi", "queue_wait_min"}:
            diffs = [r["queue_profit"] - r["return_profit"] for r in rows]
            for prev, cur, prev_diff, cur_diff in zip(rows[:-1], rows[1:], diffs[:-1], diffs[1:]):
                if prev_diff == 0 or prev_diff * cur_diff <= 0:
                    x0, x1 = prev["value"], cur["value"]
                    threshold = float(x0 + (0 - prev_diff) * (x1 - x0) / (cur_diff - prev_diff))
                    if factor == "p_taxi":
                        p_taxi_threshold = threshold
                    else:
                        queue_wait_threshold = threshold
                    break
        df = pd.DataFrame(rows)
        plt.figure(figsize=(8, 5))
        plt.plot(df["value"], df["queue_profit"] - df["return_profit"], marker="o")
        plt.axhline(0, color="black", linewidth=1)
        plt.xlabel(factor)
        plt.ylabel("Queue profit - return profit")
        plt.tight_layout()
        plt.savefig(FIG / f"sensitivity_{factor}.png", dpi=160)
        plt.close()

    results = [
        {"name": "flight_raw_rows", "value": profile["flight_raw_rows"], "unit": "rows"},
        {"name": "flight_missing_rows", "value": profile["flight_missing_rows"], "unit": "rows"},
        {"name": "flight_missing_rate", "value": profile["flight_missing_rate"], "unit": "percent"},
        {"name": "taxi_raw_rows", "value": profile["taxi_raw_rows"], "unit": "trips"},
        {"name": "taxi_unique_ids", "value": profile["taxi_unique_ids"], "unit": "vehicles"},
        {"name": "duration_outlier_upper", "value": profile["duration_outlier_upper"], "unit": "min"},
        {"name": "duration_outliers", "value": profile["duration_outliers"], "unit": "trips"},
        {"name": "duration_outlier_rate", "value": profile["duration_outlier_rate"], "unit": "percent"},
        {"name": "distance_outlier_upper", "value": profile["distance_outlier_upper"], "unit": "km"},
        {"name": "distance_outliers", "value": profile["distance_outliers"], "unit": "trips"},
        {"name": "distance_outlier_rate", "value": profile["distance_outlier_rate"], "unit": "percent"},
        {"name": "speed_outlier_upper", "value": profile["speed_outlier_upper"], "unit": "km/h"},
        {"name": "speed_outliers", "value": profile["speed_outliers"], "unit": "trips"},
        {"name": "speed_outlier_rate", "value": profile["speed_outlier_rate"], "unit": "percent"},
        {"name": "valid_taxi_trips", "value": int(len(taxi)), "unit": "trips"},
        {"name": "airport_departures", "value": int(len(airport_out)), "unit": "trips"},
        {"name": "airport_arrivals", "value": int(len(airport_in)), "unit": "trips"},
        {"name": "airport_internal", "value": int(len(airport_internal)), "unit": "trips"},
        {"name": "valid_flights", "value": int(len(flights)), "unit": "flights"},
        {"name": "airport_departure_share", "value": float(len(airport_out) / len(taxi) * 100), "unit": "percent"},
        {"name": "airport_mean_distance", "value": float(airport_out["distance_km"].mean()), "unit": "km"},
        {"name": "city_mean_distance", "value": float(city["distance_km"].mean()), "unit": "km"},
        {"name": "airport_mean_duration", "value": float(airport_out["duration_min"].mean()), "unit": "min"},
        {"name": "overall_mean_duration", "value": float(taxi["duration_min"].mean()), "unit": "min"},
        {"name": "airport_city_distance_gap_rate", "value": float((airport_out["distance_km"].mean() / city["distance_km"].mean() - 1) * 100), "unit": "percent"},
        {"name": "flight_peak_hour", "value": int(hourly_flights.idxmax()), "unit": "hour"},
        {"name": "flight_peak_count", "value": int(hourly_flights.max()), "unit": "flights"},
        {"name": "taxi_peak_hour", "value": int(hourly_taxi.idxmax()), "unit": "hour"},
        {"name": "taxi_peak_count", "value": int(hourly_taxi.max()), "unit": "trips"},
        {"name": "queue_design_arrival_rate", "value": float(lam), "unit": "trips/hour"},
        {"name": "service_rate_per_point", "value": float(mu), "unit": "trips/hour"},
        {"name": "q1_base_hour", "value": int(base_hour), "unit": "hour"},
        {"name": "q1_base_queue_profit", "value": base_queue_profit, "unit": "yuan"},
        {"name": "q1_base_return_profit", "value": base_return_profit, "unit": "yuan"},
        {"name": "q1_queue_wait_threshold", "value": float(queue_wait_threshold or 0), "unit": "min"},
        {"name": "q1_p_taxi_threshold", "value": float(p_taxi_threshold or 0), "unit": ""},
        {"name": "q1_queue_recommend_hours", "value": queue_recommend_hours, "unit": "hours"},
        {"name": "q2_hourly_flight_taxi_correlation", "value": hourly_corr, "unit": ""},
        {"name": "q2_lag_adjusted_correlation", "value": lag_adjusted_corr, "unit": ""},
        {"name": "q2_peak_lag_hours", "value": peak_lag_hours, "unit": "hours"},
        {"name": "q2_high_flight_alignment_rate", "value": high_flight_alignment_rate, "unit": "percent"},
        {"name": "recommended_pickup_points", "value": int(best_c), "unit": "points"},
        {"name": "recommended_pickup_rho", "value": float(best_queue["rho"]), "unit": ""},
        {"name": "recommended_pickup_wait_min", "value": float(best_queue["Wq_min"]), "unit": "min"},
        {"name": "recommended_pickup_throughput", "value": float(best_queue["throughput"]), "unit": "trips/hour"},
        {"name": "best_short_threshold", "value": float(best_priority["short_threshold_km"]), "unit": "km"},
        {"name": "best_short_share", "value": float(best_priority["short_share"] * 100), "unit": "percent"},
        {"name": "priority_gini_before", "value": float(best_priority["gini_before"]), "unit": ""},
        {"name": "priority_gini_after", "value": float(best_priority["gini_after"]), "unit": ""},
        {"name": "priority_gini_drop_rate", "value": float((best_priority["gini_before"] - best_priority["gini_after"]) / best_priority["gini_before"] * 100), "unit": "percent"},
        {"name": "priority_efficiency_loss_rate", "value": float(best_priority["efficiency_loss_rate"] * 100), "unit": "percent"},
    ]
    (ROOT / "results.json").write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    (ROOT / "sensitivity.json").write_text(json.dumps(sensitivity, ensure_ascii=False, indent=2), encoding="utf-8")

    print("2019C airport taxi workflow solved")
    print(f"valid_taxi_trips={len(taxi)}")
    print(f"airport_departures={len(airport_out)}")
    print(f"recommended_pickup_points={best_c}")
    print(f"best_short_threshold_km={best_priority['short_threshold_km']:.3f}")
    print(f"priority_gini_after={best_priority['gini_after']:.4f}")


if __name__ == "__main__":
    main()
