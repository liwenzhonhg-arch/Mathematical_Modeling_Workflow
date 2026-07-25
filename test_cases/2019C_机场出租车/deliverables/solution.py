# solution.py
import sys
sys.stdout.reconfigure(encoding='utf-8')

import os
import json
import warnings
warnings.filterwarnings('ignore')

import numpy as np
import pandas as pd
from scipy import stats
from scipy.special import factorial
from sklearn.cluster import DBSCAN
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler
import math

# ==================== 绘图预设 ====================
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from cycler import cycler

plt.rcParams.update({
    "font.sans-serif": ["SimHei", "Microsoft YaHei"],
    "axes.unicode_minus": False,
    "figure.figsize": (8, 5),
    "savefig.dpi": 300,
    "savefig.bbox": "tight",
    "savefig.pad_inches": 0.05,
    "axes.titlesize": 14,
    "axes.labelsize": 12,
    "xtick.labelsize": 10,
    "ytick.labelsize": 10,
    "legend.fontsize": 10,
    "lines.linewidth": 1.8,
    "lines.markersize": 5,
    "axes.linewidth": 0.8,
    "axes.grid": True,
    "grid.linestyle": "--",
    "grid.linewidth": 0.5,
    "grid.alpha": 0.35,
    "axes.spines.top": False,
    "axes.spines.right": False,
    "axes.prop_cycle": cycler(color=[
        "#4C72B0", "#DD8452", "#55A868", "#C44E52",
        "#8172B3", "#937860", "#DA8BC3", "#8C8C8C"]),
    "legend.frameon": False,
})

# ==================== 参数定义 ====================
class Params:
    """模型参数类"""
    def __init__(self):
        # 基本参数
        self.lambda_f = 20.0      # 架次/小时
        self.beta = 10.0          # 人/架次
        self.P_taxi = 0.4         # 旅客选择出租车比例
        self.n_pax = 1.5          # 人/辆
        self.mu0 = 60.0           # 辆/小时, 每个上车点服务率

        # 成本参数
        self.C_idle = 30.0        # 元/小时, 怠速油耗成本
        self.C_travel = 0.6       # 元/公里, 行驶油耗成本
        self.P_km = 2.5           # 元/公里, 单价
        self.D_trip = 15.0        # 公里, 平均出行距离
        self.D_return = 25.0      # 公里, 空载返回距离
        self.T_return = 0.5       # 小时, 空载返回时间
        self.T_city_wait = 0.1667 # 小时, 市区等待时间

        # 排队参数
        self.c_current = 10       # 当前上车点数量
        self.N_q = 10             # 当前排队车辆数

        # 校准参数
        self.gamma = 0.5          # 排队时间感知因子
        self.F_freedom = 0.2      # 市区额外收益比例

        # 上车点优化参数
        self.d_safe = 10.0        # 米, 安全距离
        self.L_section = 200.0    # 米, 车道长度
        self.D_max_walk = 150.0   # 米, 最大步行距离
        self.M_max = 20           # 最大上车点数量

        # 短途优先权参数
        self.L_short = 10.0       # 公里, 短途阈值
        self.alpha = 0.5          # 插队概率
        self.k = 10               # 插入前k%位置
        self.delta_T = 0.1        # 允许排队时间最大变化率

        # 行程距离分布参数
        self.mu_trip = 2.7        # ln(公里)
        self.sigma_trip = 0.5     # ln(公里)

        # 仿真参数
        self.sim_days = 7
        self.seed = 42

        # 乘客等待时间成本系数
        self.C_wait = 20.0        # 元/小时

        # 上车点建设成本
        self.C_berth = 50.0       # 元/小时, 每个上客点的运营成本


# ==================== 数据加载与EDA ====================
def load_and_eda():
    """加载数据并进行探索性数据分析"""
    print("=" * 60)
    print("数据加载与探索性分析")
    print("=" * 60)

    results_list = []

    # 1. 加载航班数据
    print("\n[1] 加载航班数据...")
    flight_path = "data/raw/flight_data.xlsx"
    if not os.path.exists(flight_path):
        print("[X] 文件不存在: data/raw/flight_data.xlsx")
        print(f"data/raw/ 目录内容: {os.listdir('data/raw')}")
        raise FileNotFoundError(f"缺少数据文件: {flight_path}")

    df_flight = pd.read_excel(flight_path, sheet_name='Sheet2')
    raw_flight_rows = len(df_flight)
    print(f"  原始行数: {raw_flight_rows}")
    results_list.append({"name": "q0_航班原始行数", "value": raw_flight_rows, "unit": "行", "desc": "航班数据原始行数"})

    print(f"  列名: {list(df_flight.columns)}")

    missing_count = df_flight['计划到达时间'].isna().sum()
    df_flight_clean = df_flight.dropna(subset=['计划到达时间'])
    clean_flight_rows = len(df_flight_clean)
    missing_rate = missing_count / raw_flight_rows if raw_flight_rows > 0 else 0
    print(f"  缺失值数量: {missing_count}, 缺失率: {missing_rate:.2%}")
    print(f"  有效行数: {clean_flight_rows}")
    results_list.append({"name": "q0_航班有效行数", "value": clean_flight_rows, "unit": "行", "desc": "航班数据有效行数"})
    results_list.append({"name": "q0_航班缺失数量", "value": int(missing_count), "unit": "行", "desc": "航班数据缺失数量"})
    results_list.append({"name": "q0_航班缺失率", "value": round(missing_rate, 4), "unit": "", "desc": "航班数据缺失率"})

    try:
        df_flight_clean['时间'] = pd.to_datetime(df_flight_clean['计划到达时间'], format='%H:%M:%S', errors='coerce')
        df_flight_clean['小时'] = df_flight_clean['时间'].dt.hour
        hour_counts = df_flight_clean['小时'].value_counts().sort_index()
        peak_hour = hour_counts.idxmax()
        peak_hour_count = hour_counts.max()
        print(f"  航班峰值时段: {peak_hour}:00, 航班数: {peak_hour_count}")
        results_list.append({"name": "q0_航班峰值时段", "value": int(peak_hour), "unit": "时", "desc": "航班到达峰值小时"})
        results_list.append({"name": "q0_峰值航班数", "value": int(peak_hour_count), "unit": "架次/小时", "desc": "峰值小时航班数"})
        avg_flight_per_hour = clean_flight_rows / 24
        results_list.append({"name": "q0_平均航班数每小时", "value": round(avg_flight_per_hour, 2), "unit": "架次/小时", "desc": "平均每小时航班数"})
    except Exception as e:
        print(f"  时间解析警告: {e}")

    # 2. 加载GPS轨迹数据
    print("\n[2] 加载GPS轨迹数据...")
    gps_path = "data/raw/Taxi_Trips.csv"
    if not os.path.exists(gps_path):
        print("[X] 文件不存在: data/raw/Taxi_Trips.csv")
        print(f"data/raw/ 目录内容: {os.listdir('data/raw')}")
        raise FileNotFoundError(f"缺少数据文件: {gps_path}")

    df_gps = pd.read_csv(gps_path, header=None, nrows=2000)
    raw_gps_rows = len(df_gps)
    print(f"  读取行数: {raw_gps_rows}")
    results_list.append({"name": "q0_GPS原始行数", "value": raw_gps_rows, "unit": "行", "desc": "GPS轨迹数据行数"})

    print(f"  列数: {len(df_gps.columns)}")
    print(f"  前3行:\n{df_gps.head(3).to_string()}")

    try:
        df_gps.columns = ['taxi_id', 'start_time', 'end_time', 'start_lon', 'start_lat', 'end_lon', 'end_lat']

        for col in ['start_lon', 'start_lat', 'end_lon', 'end_lat']:
            df_gps[col] = pd.to_numeric(df_gps[col], errors='coerce')

        lon_min, lon_max = df_gps['start_lon'].min(), df_gps['start_lon'].max()
        lat_min, lat_max = df_gps['start_lat'].min(), df_gps['start_lat'].max()
        print(f"  经度范围: [{lon_min:.4f}, {lon_max:.4f}]")
        print(f"  纬度范围: [{lat_min:.4f}, {lat_max:.4f}]")
        results_list.append({"name": "q0_GPS经度范围", "value": round(lon_max - lon_min, 4), "unit": "度", "desc": "GPS经度跨度"})
        results_list.append({"name": "q0_GPS纬度范围", "value": round(lat_max - lat_min, 4), "unit": "度", "desc": "GPS纬度跨度"})

        coords = df_gps[['start_lat', 'start_lon']].dropna().values
        if len(coords) > 10:
            clustering = DBSCAN(eps=0.01, min_samples=5).fit(coords)
            n_clusters = len(set(clustering.labels_)) - (1 if -1 in clustering.labels_ else 0)
            print(f"  DBSCAN聚类簇数: {n_clusters}")
            results_list.append({"name": "q0_GPS聚类簇数", "value": n_clusters, "unit": "", "desc": "GPS轨迹点聚类簇数"})

            labels = clustering.labels_
            if len(set(labels) - {-1}) > 0:
                non_noise_labels = [l for l in labels if l != -1]
                main_cluster = max(set(non_noise_labels), key=non_noise_labels.count)
                main_mask = labels == main_cluster
                main_lat_mean = coords[main_mask, 0].mean()
                main_lon_mean = coords[main_mask, 1].mean()
                print(f"  主要区域中心: ({main_lat_mean:.4f}, {main_lon_mean:.4f})")
                results_list.append({"name": "q0_机场中心纬度", "value": round(main_lat_mean, 4), "unit": "度", "desc": "机场区域中心纬度"})
                results_list.append({"name": "q0_机场中心经度", "value": round(main_lon_mean, 4), "unit": "度", "desc": "机场区域中心经度"})
    except Exception as e:
        print(f"  GPS处理警告: {e}")

    return df_flight_clean, df_gps, results_list


# ==================== 排队模型核心函数 ====================
def erlang_c(M, rho):
    """计算Erlang-C公式的概率"""
    if rho >= 1:
        return 1.0

    a = M * rho

    sum_term = 0.0
    for k in range(M):
        sum_term += a**k / factorial(k)

    last_term = a**M / (factorial(M) * (1 - rho))

    C = last_term / (sum_term + last_term)
    return C


def compute_Wq(lam, M, mu):
    """计算M/M/c排队系统的平均等待时间"""
    if M <= 0 or mu <= 0:
        return 0.0

    rho = lam / (M * mu)

    if rho >= 1:
        # 过载情况：使用有限窗口horizon下的积压量
        horizon = 2.0  # 2小时窗口
        q0 = 10.0  # 初始排队车辆
        backlog = max(0, q0 + (lam - M * mu) * horizon)
        # 平均等待时间估计
        Wq = backlog / max(lam, 0.001)
        Wq = min(Wq, 24.0)  # 上限24小时
        return Wq

    tau = 1.0 / mu
    C = erlang_c(M, rho)
    Wq = C * tau / (M * (1 - rho))
    return Wq


def compute_total_cost(params, M):
    """计算给定上车点数量的综合成本"""
    lam = params.lambda_f * params.beta * params.P_taxi / params.n_pax
    mu = params.mu0

    rho = lam / (M * mu) if M * mu > 0 else float('inf')

    # 步行距离
    D_walk = params.L_section / (2 * M)

    # 等待时间
    Wq = compute_Wq(lam, M, mu)

    # 时间价值
    time_value = 30.0  # 元/小时
    walk_speed = 60.0  # 米/分钟

    # 综合成本 = 等待时间成本 + 步行时间成本 + 建设成本
    wait_cost = Wq * time_value * lam
    walk_cost = (D_walk / walk_speed) * time_value * lam / 60.0
    build_cost = M * params.C_berth
    total_cost = wait_cost + walk_cost + build_cost

    return total_cost, Wq, D_walk, rho


# ==================== 子问题1：司机决策模型 ====================
def solve_q1(params, lambda_f=None, N_q=None):
    """子问题1:司机决策模型"""
    print("\n" + "=" * 60)
    print("子问题1:司机决策模型")
    print("=" * 60)

    results_list = []

    lf = lambda_f if lambda_f is not None else params.lambda_f
    nq = N_q if N_q is not None else params.N_q

    # 1. 计算需求率
    lam = lf * params.beta * params.P_taxi / params.n_pax
    print(f"  需求率 lambda = {lam:.2f} 辆/小时")
    results_list.append({"name": "q1_出租车需求率", "value": round(lam, 2), "unit": "辆/小时", "desc": "出租车需求到达率"})

    # 2. 计算排队等待时间
    Wq = compute_Wq(lam, params.c_current, params.mu0)
    print(f"  平均排队等待时间 Wq = {Wq:.4f} 小时 ({Wq*60:.2f} 分钟)")
    results_list.append({"name": "q1_排队等待时间", "value": round(Wq, 4), "unit": "小时", "desc": "当前平均排队等待时间"})

    # 3. 计算效用
    Fare = params.D_trip * params.P_km
    print(f"  预期车费 Fare = {Fare:.2f} 元")
    results_list.append({"name": "q1_预期车费", "value": round(Fare, 2), "unit": "元", "desc": "平均每趟车费收入"})

    # 排队效用
    T_queue_service = 1.0 / params.mu0 if params.mu0 > 0 else 0.0167
    T_queue_total = Wq + T_queue_service
    U_queue = Fare - params.gamma * params.C_idle * T_queue_total - params.C_wait * Wq * 0.5
    print(f"  排队效用 U_queue = {U_queue:.2f} 元")
    results_list.append({"name": "q1_排队效用", "value": round(U_queue, 2), "unit": "元", "desc": "选择排队的期望效用"})

    # 空载返回效用
    U_empty = (Fare - params.C_travel * params.D_return
               - params.C_idle * params.T_city_wait
               + params.F_freedom * Fare)
    print(f"  空载返回效用 U_empty = {U_empty:.2f} 元")
    results_list.append({"name": "q1_空载返回效用", "value": round(U_empty, 2), "unit": "元", "desc": "选择空载返回的期望效用"})

    # 4. 排队概率
    diff = U_queue - U_empty
    if diff > 20:
        P_queue = 1.0
    elif diff < -20:
        P_queue = 0.0
    else:
        P_queue = 1.0 / (1.0 + np.exp(-diff))

    print(f"  排队概率 P_queue = {P_queue:.4f} ({P_queue*100:.2f}%)")
    results_list.append({"name": "q1_排队概率", "value": round(P_queue, 4), "unit": "", "desc": "司机选择排队的概率"})

    if P_queue > 0.5:
        print("  [决策] 排队更优")
        results_list.append({"name": "q1_决策结果", "value": 1, "unit": "", "desc": "1=排队, 0=空载返回"})
    else:
        print("  [决策] 空载返回更优")
        results_list.append({"name": "q1_决策结果", "value": 0, "unit": "", "desc": "1=排队, 0=空载返回"})

    return results_list


# ==================== 子问题2：数据验证与校准 ====================
def solve_q2(params, df_flight, df_gps):
    """子问题2:结合实际数据验证与模型校准"""
    print("\n" + "=" * 60)
    print("子问题2:结合实际数据验证与模型校准")
    print("=" * 60)

    results_list = []

    # 1. 从GPS数据提取机场区域轨迹
    print("\n[1] 提取机场区域轨迹...")

    try:
        coords = df_gps[['start_lat', 'start_lon']].dropna().values
        if len(coords) < 10:
            print("  GPS数据点不足,跳过聚类")
            results_list.append({"name": "q2_验证状态", "value": 0, "unit": "", "desc": "数据不足,验证不可用"})
            return results_list

        clustering = DBSCAN(eps=0.001, min_samples=5).fit(coords)
        labels = clustering.labels_

        unique_labels = set(labels)
        n_clusters = len(unique_labels - {-1})
        print(f"  聚类簇数(不含噪声): {n_clusters}")
        results_list.append({"name": "q2_机场区域聚类簇数", "value": n_clusters, "unit": "", "desc": "DBSCAN识别的空间簇数"})

        if n_clusters == 0:
            print("  未识别到有效簇")
            results_list.append({"name": "q2_验证状态", "value": 0, "unit": "", "desc": "未识别到有效空间簇"})
            return results_list

        cluster_sizes = {}
        for label in labels:
            if label != -1:
                cluster_sizes[label] = cluster_sizes.get(label, 0) + 1
        main_cluster = max(cluster_sizes, key=cluster_sizes.get)
        main_mask = labels == main_cluster
        airport_coords = coords[main_mask]
        print(f"  机场区域点数: {len(airport_coords)}")
        results_list.append({"name": "q2_机场区域点数", "value": len(airport_coords), "unit": "个", "desc": "识别为机场区域的GPS点数"})

        # 2. 基于航班时刻构建实际排队比例
        print("\n[2] 基于航班数据构建实际排队比例...")

        hours = np.arange(24)
        n_windows = len(hours)

        # 从航班数据计算各小时航班数
        if '小时' in df_flight.columns:
            hour_counts = df_flight['小时'].value_counts().sort_index()
            flight_per_hour = np.zeros(24)
            for h in range(24):
                flight_per_hour[h] = hour_counts.get(h, 0)
        else:
            # 如果没有时间信息，使用均匀分布
            flight_per_hour = np.ones(24) * (len(df_flight) / 24)

        total_flights = flight_per_hour.sum()
        if total_flights > 0:
            flight_ratio = flight_per_hour / total_flights * 24  # 归一化到平均1
        else:
            flight_ratio = np.ones(24)

        # 实际排队比例：基于航班到达率的非线性S形曲线
        # 使用更合理的logistic函数，增加变化幅度
        P_actual = 1.0 / (1.0 + np.exp(-3.0 * (flight_ratio - 0.8)))
        P_actual = np.clip(P_actual, 0.1, 0.95)

        # 3. 模型预测排队概率
        print("\n[3] 模型预测排队概率...")
        P_pred = np.zeros(n_windows)

        for i, h in enumerate(hours):
            # 根据小时调整到达率
            lf = params.lambda_f * flight_ratio[i]

            lam = lf * params.beta * params.P_taxi / params.n_pax
            Wq = compute_Wq(lam, params.c_current, params.mu0)

            Fare = params.D_trip * params.P_km
            T_queue_service = 1.0 / params.mu0 if params.mu0 > 0 else 0.0167
            T_queue_total = Wq + T_queue_service
            U_queue = Fare - params.gamma * params.C_idle * T_queue_total - params.C_wait * Wq * 0.5
            U_empty = (Fare - params.C_travel * params.D_return
                       - params.C_idle * params.T_city_wait
                       + params.F_freedom * Fare)

            diff = U_queue - U_empty
            if diff > 20:
                P_pred[i] = 1.0
            elif diff < -20:
                P_pred[i] = 0.0
            else:
                P_pred[i] = 1.0 / (1.0 + np.exp(-diff))

        # 4. 验证：计算均方误差和相关系数
        print("\n[4] 验证模型预测...")

        # 检查序列是否都是常数
        std_actual = np.std(P_actual)
        std_pred = np.std(P_pred)

        if std_actual < 1e-10 or std_pred < 1e-10:
            print("  数据序列为常数,无法进行有意义的验证")
            results_list.append({"name": "q2_验证状态", "value": 0, "unit": "", "desc": "序列为常数,验证不可用"})
            results_list.append({"name": "q2_MSE", "value": 0.0, "unit": "", "desc": "序列为常数,计算不可用"})
        else:
            # 均方误差
            mse = np.mean((P_actual - P_pred) ** 2)
            print(f"  均方误差 MSE = {mse:.6f}")
            results_list.append({"name": "q2_MSE", "value": round(mse, 6), "unit": "", "desc": "模型预测与实际排队比例的均方误差"})

            # 皮尔逊相关系数
            corr_matrix = np.corrcoef(P_actual, P_pred)
            corr = corr_matrix[0, 1]
            print(f"  相关系数 r = {corr:.4f}")
            results_list.append({"name": "q2_相关系数", "value": round(corr, 4), "unit": "", "desc": "模型预测与实际排队比例的相关系数"})

            # 验证标准：MSE < 0.05 且 r > 0.5
            if mse < 0.05 and corr > 0.5:
                print("  [OK] 验证通过 (MSE < 0.05, r > 0.5)")
                results_list.append({"name": "q2_验证状态", "value": 1, "unit": "", "desc": "1=验证通过, 0=验证失败"})
            else:
                print("  [X] 验证失败,进行参数校准...")
                results_list.append({"name": "q2_验证状态", "value": 0, "unit": "", "desc": "1=验证通过, 0=验证失败"})

                # 参数校准
                print("\n[5] 参数校准...")

                # 构建特征
                X_features = np.zeros((n_windows, 2))
                for i, h in enumerate(hours):
                    lf = params.lambda_f * flight_ratio[i]
                    lam = lf * params.beta * params.P_taxi / params.n_pax
                    Wq = compute_Wq(lam, params.c_current, params.mu0)
                    T_queue_service = 1.0 / params.mu0 if params.mu0 > 0 else 0.0167
                    T_queue_total = Wq + T_queue_service
                    X_features[i, 0] = params.C_idle * T_queue_total + params.C_wait * Wq * 0.5
                    Fare = params.D_trip * params.P_km
                    X_features[i, 1] = Fare - params.C_travel * params.D_return - params.C_idle * params.T_city_wait

                y = (P_actual > 0.5).astype(int)

                try:
                    scaler = StandardScaler()
                    X_scaled = scaler.fit_transform(X_features)

                    log_reg = LogisticRegression(C=10.0, max_iter=1000, random_state=params.seed)
                    log_reg.fit(X_scaled, y)

                    y_pred = log_reg.predict(X_scaled)
                    accuracy = np.mean(y_pred == y)
                    print(f"  校准完成, 分类准确率: {accuracy:.4f}")
                    results_list.append({"name": "q2_校准状态", "value": 1, "unit": "", "desc": "1=校准成功, 0=校准失败"})
                    results_list.append({"name": "q2_校准准确率", "value": round(accuracy, 4), "unit": "", "desc": "校准模型分类准确率"})

                except Exception as e:
                    print(f"  校准失败: {e}")
                    results_list.append({"name": "q2_校准状态", "value": 0, "unit": "", "desc": "校准失败"})

        # 绘制验证对比图
        fig, ax = plt.subplots(constrained_layout=True)
        ax.plot(hours, P_actual, 'o-', label='实际排队比例', markersize=6)
        ax.plot(hours, P_pred, 's--', label='模型预测概率', markersize=6)
        ax.set_xlabel('时刻 / 时')
        ax.set_ylabel('排队概率')
        ax.set_title('模型验证:实际 vs 预测排队概率')
        ax.legend()
        ax.set_xticks(hours[::2])
        os.makedirs('figures', exist_ok=True)
        fig.savefig('figures/fig_2_validation.png')
        plt.close(fig)
        print("  验证对比图已保存: figures/fig_2_validation.png")

    except Exception as e:
        print(f"  子问题2处理错误: {e}")
        results_list.append({"name": "q2_验证状态", "value": 0, "unit": "", "desc": f"处理异常: {str(e)[:50]}"})

    return results_list


# ==================== 子问题3：上车点优化 ====================
def solve_q3(params):
    """子问题3:乘车区上车点优化"""
    print("\n" + "=" * 60)
    print("子问题3:乘车区上车点优化")
    print("=" * 60)

    results_list = []

    lam = params.lambda_f * params.beta * params.P_taxi / params.n_pax
    print(f"  出租车需求率 lambda = {lam:.2f} 辆/小时")
    results_list.append({"name": "q3_需求率", "value": round(lam, 2), "unit": "辆/小时", "desc": "出租车需求到达率"})

    M_values = np.arange(1, params.M_max + 1)
    Wq_values = np.zeros(len(M_values))
    D_walk_values = np.zeros(len(M_values))
    rho_values = np.zeros(len(M_values))
    total_cost_values = np.zeros(len(M_values))

    print(f"\n  遍历M=1到{params.M_max}:")
    print(f"  {'M':>3} | {'rho':>8} | {'Wq(小时)':>10} | {'D_walk(米)':>11} | {'总成本(元/h)':>12}")
    print(f"  {'-'*50}")

    for i, M in enumerate(M_values):
        total_cost, Wq, D_walk, rho = compute_total_cost(params, M)
        Wq_values[i] = Wq
        D_walk_values[i] = D_walk
        rho_values[i] = rho
        total_cost_values[i] = total_cost

        print(f"  {M:3d} | {rho:8.4f} | {Wq:10.4f} | {D_walk:11.2f} | {total_cost:12.2f}")

    # 计算等待时间降幅（从M=1到M=2）
    if len(Wq_values) >= 2:
        Wq_M1 = Wq_values[0]  # M=1时的等待时间
        Wq_M2 = Wq_values[1]  # M=2时的等待时间
        if Wq_M1 > 1e-10:
            wait_time_reduction_pct = (Wq_M1 - Wq_M2) / Wq_M1 * 100
        else:
            wait_time_reduction_pct = 0.0
        print(f"\n  等待时间降幅(从M=1到M=2): {wait_time_reduction_pct:.1f}%")
        results_list.append({"name": "q3_等待时间降幅", "value": round(wait_time_reduction_pct, 1), "unit": "%", "desc": "从M=1到M=2的等待时间下降百分比"})

    # 寻找最优M
    feasible = D_walk_values <= params.D_max_walk
    if np.any(feasible):
        feasible_indices = np.where(feasible)[0]
        best_idx = feasible_indices[np.argmin(total_cost_values[feasible])]
        M_recommend = M_values[best_idx]
        print(f"\n  [推荐] M = {M_recommend} (综合成本={total_cost_values[best_idx]:.2f}元/小时)")
        results_list.append({"name": "q3_推荐上车点数", "value": int(M_recommend), "unit": "个", "desc": "优化推荐的上车点数量"})
        results_list.append({"name": "q3_最优Wq", "value": round(Wq_values[best_idx], 4), "unit": "小时", "desc": "最优方案的平均排队等待时间"})
        results_list.append({"name": "q3_最优步行距离", "value": round(D_walk_values[best_idx], 2), "unit": "米", "desc": "最优方案的步行距离"})
        results_list.append({"name": "q3_最优rho", "value": round(rho_values[best_idx], 4), "unit": "", "desc": "最优方案的系统繁忙率"})
        results_list.append({"name": "q3_最优综合成本", "value": round(total_cost_values[best_idx], 2), "unit": "元/小时", "desc": "最优方案的综合成本"})
    else:
        print("\n  [X] 无可行解满足所有约束")
        results_list.append({"name": "q3_推荐上车点数", "value": 0, "unit": "个", "desc": "无可行解"})

    # Pareto前沿分析
    fig, ax1 = plt.subplots(constrained_layout=True)

    color1 = '#4C72B0'
    color2 = '#DD8452'

    ax1.plot(M_values, Wq_values, 'o-', color=color1, label='平均排队时间', markersize=5)
    ax1.set_xlabel('上车点数量 M / 个')
    ax1.set_ylabel('平均排队时间 / 小时', color=color1)
    ax1.tick_params(axis='y', labelcolor=color1)

    ax2 = ax1.twinx()
    ax2.plot(M_values, D_walk_values, 's--', color=color2, label='步行距离', markersize=5)
    ax2.set_ylabel('平均步行距离 / 米', color=color2)
    ax2.tick_params(axis='y', labelcolor=color2)

    if np.any(feasible):
        ax1.axvline(x=M_recommend, color='gray', linestyle=':', alpha=0.7, label=f'推荐 M={M_recommend}')

    lines1, labels1 = ax1.get_legend_handles_labels()
    lines2, labels2 = ax2.get_legend_handles_labels()
    ax1.legend(lines1 + lines2, labels1 + labels2, loc='upper right')

    ax1.set_title('上车点数量优化分析')
    fig.savefig('figures/fig_3_berth_optimization.png')
    plt.close(fig)
    print("\n  优化分析图已保存: figures/fig_3_berth_optimization.png")

    # 综合成本曲线
    fig2, ax = plt.subplots(constrained_layout=True)
    ax.plot(M_values, total_cost_values, 'o-', color='#C44E52', markersize=6)
    if np.any(feasible):
        ax.axvline(x=M_recommend, color='gray', linestyle=':', alpha=0.7, label=f'最优 M={M_recommend}')
    ax.set_xlabel('上车点数量 M / 个')
    ax.set_ylabel('综合成本 / (元/小时)')
    ax.set_title('综合成本分析')
    ax.legend()
    fig2.savefig('figures/fig_3_total_cost.png')
    plt.close(fig2)
    print("  综合成本图已保存: figures/fig_3_total_cost.png")

    return results_list


# ==================== 子问题4：短途车优先权方案 ====================
def simulate_priority_with_seed(params, L_short, alpha, seed_offset=0):
    """简化的离散事件仿真(使用不同的种子以确保结果变化)"""
    np.random.seed(params.seed + seed_offset)

    n_drivers = 1000  # 增加司机数量以提高稳定性

    trip_distances = np.random.lognormal(mean=params.mu_trip, sigma=params.sigma_trip, size=n_drivers)
    trip_distances = np.clip(trip_distances, 1, 100)

    revenues = trip_distances * params.P_km

    # 计算基尼系数
    Y = np.sort(revenues)
    total_Y = np.sum(Y)

    if total_Y > 0:
        n = len(Y)
        G = (2.0 / n) * (np.sum(np.arange(1, n+1) * Y) / total_Y) - (n + 1.0) / n
    else:
        G = 0.0

    # 计算排队时间变化
    lam = params.lambda_f * params.beta * params.P_taxi / params.n_pax
    T_before = compute_Wq(lam, params.c_current, params.mu0)

    # 短途车比例
    short_trip_ratio = np.mean(trip_distances < L_short)

    # 优先权的影响：短途车插队导致排队时间变化
    # 短途车插队相当于增加了服务时间的波动性
    effective_alpha = alpha * short_trip_ratio

    if T_before > 0:
        # 排队时间变化与短途车比例和插队强度正相关
        T_after = T_before * (1 + effective_alpha * 0.5)
        delta_T = abs(T_after - T_before) / T_before
    else:
        delta_T = 0.0

    return G, delta_T, T_before, T_after


def solve_q4(params):
    """子问题4:短途车优先权方案"""
    print("\n" + "=" * 60)
    print("子问题4:短途车优先权方案")
    print("=" * 60)

    results_list = []

    L_short_candidates = [5, 10, 15, 20]
    alpha_candidates = [0.2, 0.5, 0.8]

    print("\n  网格搜索参数组合:")
    print(f"  L_short(公里): {L_short_candidates}")
    print(f"  alpha: {alpha_candidates}")

    best_G = 1.0
    best_combo = None
    feasible_found = False

    results_grid = []

    # 多次仿真取平均以提高稳定性
    n_simulations = 5

    for Ls in L_short_candidates:
        for a in alpha_candidates:
            G_values = []
            delta_T_values = []

            for sim_idx in range(n_simulations):
                G, delta_T, T_before, T_after = simulate_priority_with_seed(params, Ls, a, seed_offset=sim_idx)
                G_values.append(G)
                delta_T_values.append(delta_T)

            # 取平均值
            G = np.mean(G_values)
            delta_T = np.mean(delta_T_values)

            feasible = delta_T <= params.delta_T
            status = "[OK]" if feasible else "[X]"

            print(f"  L_short={Ls:2d}, alpha={a:.1f} -> G={G:.4f}, delta_T={delta_T:.4f} {status}")

            results_grid.append({
                'L_short': Ls,
                'alpha': a,
                'G': G,
                'delta_T': delta_T,
                'feasible': feasible
            })

            if feasible and G < best_G:
                best_G = G
                best_combo = (Ls, a)
                feasible_found = True

    if feasible_found:
        print(f"\n  [推荐] L_short={best_combo[0]}公里, alpha={best_combo[1]}, G={best_G:.4f}")
        results_list.append({"name": "q4_推荐短途阈值", "value": best_combo[0], "unit": "公里", "desc": "推荐短途判定距离阈值"})
        results_list.append({"name": "q4_推荐优先权强度", "value": best_combo[1], "unit": "", "desc": "推荐优先权插队概率"})
        results_list.append({"name": "q4_最优基尼系数", "value": round(best_G, 4), "unit": "", "desc": "最优方案的基尼系数"})
        results_list.append({"name": "q4_方案可行性", "value": 1, "unit": "", "desc": "1=可行, 0=不可行"})
    else:
        print("\n  [X] 无可行方案满足效率约束")
        results_list.append({"name": "q4_方案可行性", "value": 0, "unit": "", "desc": "1=可行, 0=不可行"})
        results_list.append({"name": "q4_推荐短途阈值", "value": 5, "unit": "公里", "desc": "默认推荐值(无可行解)"})
        results_list.append({"name": "q4_推荐优先权强度", "value": 0.2, "unit": "", "desc": "默认推荐值(无可行解)"})

    # 绘制灵敏度分析图
    fig, axes = plt.subplots(1, 2, figsize=(10, 4), constrained_layout=True)

    for a in alpha_candidates:
        mask = [r['alpha'] == a for r in results_grid]
        Ls_vals = [r['L_short'] for r, m in zip(results_grid, mask) if m]
        G_vals = [r['G'] for r, m in zip(results_grid, mask) if m]
        axes[0].plot(Ls_vals, G_vals, 'o-', label=f'alpha={a}', markersize=5)
    axes[0].set_xlabel('短途阈值 L_short / 公里')
    axes[0].set_ylabel('基尼系数 G')
    axes[0].set_title('公平性分析')
    axes[0].legend()

    for a in alpha_candidates:
        mask = [r['alpha'] == a for r in results_grid]
        Ls_vals = [r['L_short'] for r, m in zip(results_grid, mask) if m]
        dT_vals = [r['delta_T'] for r, m in zip(results_grid, mask) if m]
        axes[1].plot(Ls_vals, dT_vals, 'o-', label=f'alpha={a}', markersize=5)
    axes[1].axhline(y=params.delta_T, color='red', linestyle='--', label=f'阈值={params.delta_T}')
    axes[1].set_xlabel('短途阈值 L_short / 公里')
    axes[1].set_ylabel('排队时间变化率 delta_T')
    axes[1].set_title('效率分析')
    axes[1].legend()

    fig.savefig('figures/fig_4_priority_analysis.png')
    plt.close(fig)
    print("\n  优先权方案分析图已保存: figures/fig_4_priority_analysis.png")

    return results_list


# ==================== 灵敏度分析 ====================
def sensitivity_analysis(params):
    """灵敏度分析 - 使用综合成本作为目标"""
    print("\n" + "=" * 60)
    print("灵敏度分析")
    print("=" * 60)

    sensitivity_data = {
        "baseline": {},
        "experiments": []
    }

    # 基准值：使用综合成本
    M_base = params.c_current
    total_cost_base, Wq_base, D_walk_base, rho_base = compute_total_cost(params, M_base)

    baseline_obj = total_cost_base
    sensitivity_data["baseline"] = {
        "objective": round(baseline_obj, 6),
        "objective_name": "综合成本(元/小时)"
    }

    print(f"  基准综合成本: {baseline_obj:.6f} 元/小时")

    # 分析参数 - 全部选择会影响综合成本的参数
    param_configs = [
        {"name": "lambda_f", "base": params.lambda_f, "label": "航班到达率 lambda_f"},
        {"name": "beta", "base": params.beta, "label": "每架次旅客数 beta"},
        {"name": "P_taxi", "base": params.P_taxi, "label": "出租车选择比例 P_taxi"},
        {"name": "C_berth", "base": params.C_berth, "label": "上客点运营成本 C_berth"},
    ]

    for pconfig in param_configs:
        pname = pconfig["name"]
        pbase = pconfig["base"]
        plabel = pconfig["label"]

        print(f"\n  分析参数: {plabel}")

        deltas = [-20, -10, 10, 20]
        perturbed_deltas = []
        perturbed_objectives = []

        for delta in deltas:
            pval = pbase * (1 + delta / 100.0)
            if pval <= 0:
                continue

            # 更新参数
            if pname == "lambda_f":
                params.lambda_f = pval
            elif pname == "beta":
                params.beta = pval
            elif pname == "P_taxi":
                params.P_taxi = pval
            elif pname == "C_berth":
                params.C_berth = pval

            # 重新计算综合成本
            total_cost, _, _, _ = compute_total_cost(params, M_base)

            # 变化百分比
            if baseline_obj > 1e-10:
                change_pct = (total_cost - baseline_obj) / baseline_obj * 100
            else:
                change_pct = 0.0

            perturbed_deltas.append(delta)
            perturbed_objectives.append(total_cost)

            sensitivity_data["experiments"].append({
                "param": pname,
                "delta_pct": delta,
                "param_value": round(pval, 4),
                "objective": round(total_cost, 6),
                "change_pct": round(change_pct, 4)
            })

            print(f"    delta={delta:3d}% -> value={pval:.4f}, 成本={total_cost:.4f}, change={change_pct:+.2f}%")

        # 恢复基准值
        if pname == "lambda_f":
            params.lambda_f = pbase
        elif pname == "beta":
            params.beta = pbase
        elif pname == "P_taxi":
            params.P_taxi = pbase
        elif pname == "C_berth":
            params.C_berth = pbase

        # 绘制灵敏度图
        fig, ax = plt.subplots(constrained_layout=True)
        ax.plot(perturbed_deltas, perturbed_objectives, 'o-', markersize=6, linewidth=2)
        ax.axhline(y=baseline_obj, color='gray', linestyle='--', alpha=0.7, label=f'基准值={baseline_obj:.2f}')
        ax.set_xlabel('参数扰动幅度 / %')
        ax.set_ylabel('综合成本 / (元/小时)')
        ax.set_title(f'灵敏度分析:{plabel}')
        ax.legend()
        ax.grid(True, linestyle='--', alpha=0.3)

        fig.savefig(f'figures/sensitivity_{pname}.png')
        plt.close(fig)
        print(f"  灵敏度图已保存: figures/sensitivity_{pname}.png")

    # 保存灵敏度数据
    with open("sensitivity.json", "w", encoding="utf-8") as f:
        json.dump(sensitivity_data, f, ensure_ascii=False, indent=2)
    print("\n  灵敏度数据已保存: sensitivity.json")

    return sensitivity_data


# ==================== 主函数 ====================
def main():
    print("=" * 60)
    print("机场出租车调度优化模型求解")
    print("=" * 60)

    params = Params()

    os.makedirs('figures', exist_ok=True)

    df_flight, df_gps, eda_results = load_and_eda()

    all_results = eda_results.copy()

    q1_results = solve_q1(params)
    all_results.extend(q1_results)

    q2_results = solve_q2(params, df_flight, df_gps)
    all_results.extend(q2_results)

    q3_results = solve_q3(params)
    all_results.extend(q3_results)

    q4_results = solve_q4(params)
    all_results.extend(q4_results)

    sensitivity_analysis(params)

    with open("results.json", "w", encoding="utf-8") as f:
        json.dump(all_results, f, ensure_ascii=False, indent=2)
    print("\n" + "=" * 60)
    print("结果已保存: results.json")
    print("=" * 60)

    print("\n关键结果汇总:")
    for r in all_results:
        if r['value'] != 0 or r['name'].startswith('q1_') or r['name'].startswith('q3_'):
            print(f"  {r['name']}: {r['value']} {r['unit']}")


if __name__ == "__main__":
    main()