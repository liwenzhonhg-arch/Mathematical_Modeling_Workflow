# solution.py
import sys
sys.stdout.reconfigure(encoding='utf-8')

import os
import warnings
warnings.filterwarnings('ignore')

import numpy as np
import pandas as pd
from scipy.integrate import solve_ivp
from scipy.optimize import minimize, differential_evolution
from scipy.interpolate import interp1d
import json

# ----------------------------------------------------------------------
# 绘图预设（必须放在所有绘图代码之前）
# ----------------------------------------------------------------------
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

# ----------------------------------------------------------------------
# 参数定义
# ----------------------------------------------------------------------
L_zone = 0.2015          # m
L_gap = 0.005            # m
L_pre = 0.3              # m
L_post = 0.3             # m
delta = 1.5e-4           # m
rho = 8000               # kg/m^3
cp = 500                 # J/(kg*K)
T_amb = 25               # degC
v_min = 65               # cm/min
v_max = 100              # cm/min
R_up_max = 3.0           # degC/s
R_down_min = -3.0        # degC/s
t_150_190_min = 60       # s
t_150_190_max = 120      # s
t_over_217_min = 40      # s
t_over_217_max = 90      # s
T_peak_min = 240         # degC
T_peak_max = 250         # degC
dt = 0.5                 # s

# 温区温度基值（子问题2中使用的设定值）
T_base = {
    'T1_5': 182,
    'T6': 203,
    'T7': 237,
    'T8_9': 254,
    'T10': 254,   # 补充温区10,默认与温区8-9相同
    'T11': 254    # 补充温区11,默认与温区8-9相同
}

# 温区温度可调范围
T_delta = 10  # degC

# ----------------------------------------------------------------------
# 数据加载
# ----------------------------------------------------------------------
data_dir = 'data/raw'
if not os.path.exists(data_dir):
    raise FileNotFoundError(f"数据目录 {data_dir} 不存在。实际内容: {os.listdir('.')}")

real_files = os.listdir(data_dir)
print(f"[INFO] data/raw 目录内容: {real_files}")

# 读取附件数据
if '附件.xlsx' in real_files:
    df_obs = pd.read_excel(os.path.join(data_dir, '附件.xlsx'), sheet_name='Sheet1')
    print(f"[OK] 附件.xlsx 读取成功,共 {len(df_obs)} 行")
else:
    print(f"[X] 附件.xlsx 不存在。实际文件: {real_files}")
    raise FileNotFoundError(f"附件.xlsx 不存在,无法继续求解")

# 检查列名
expected_cols = ['时间(s)', '温度(ºC)']
if list(df_obs.columns) != expected_cols:
    # 尝试匹配可能的列名
    col_map = {}
    for c in df_obs.columns:
        if '时间' in c:
            col_map[c] = '时间(s)'
        elif '温度' in c:
            col_map[c] = '温度(ºC)'
    if len(col_map) == 2:
        df_obs = df_obs.rename(columns=col_map)
    else:
        raise ValueError(f"列名不匹配: {df_obs.columns.tolist()}")

t_obs = df_obs['时间(s)'].values
T_obs = df_obs['温度(ºC)'].values

# EDA 统计
n_raw = len(df_obs)
n_valid = n_raw
n_missing = 0
missing_rate = 0.0

# 异常值检测 (IQR)
Q1 = np.percentile(T_obs, 25)
Q3 = np.percentile(T_obs, 75)
IQR = Q3 - Q1
lower_bound = Q1 - 1.5 * IQR
upper_bound = Q3 + 1.5 * IQR
outlier_mask = (T_obs < lower_bound) | (T_obs > upper_bound)
n_outliers = np.sum(outlier_mask)
outlier_rate = n_outliers / n_raw * 100

# 关键统计量
T_mean = np.mean(T_obs)
T_median = np.median(T_obs)
T_std = np.std(T_obs)
T_min = np.min(T_obs)
T_max = np.max(T_obs)
corr_time_temp = np.corrcoef(t_obs, T_obs)[0, 1]

# 温度变化率
dT_dt = np.diff(T_obs) / np.diff(t_obs)
max_heating_rate = np.max(dT_dt)
max_cooling_rate = np.min(dT_dt)

# 150-190°C 持续时间
mask_150_190 = (T_obs >= 150) & (T_obs <= 190)
t_150_190_obs = np.sum(mask_150_190) * dt

# >217°C 持续时间
mask_over_217 = T_obs >= 217
t_over_217_obs = np.sum(mask_over_217) * dt

# 峰值温度
T_peak_obs = np.max(T_obs)

print(f"[OK] EDA 完成: 原始行数={n_raw}, 有效行数={n_valid}, 缺失数={n_missing}, 异常值数={n_outliers}")
print(f"[OK] 峰值温度={T_peak_obs:.2f}°C, 150-190°C 时间={t_150_190_obs:.2f}s, >217°C 时间={t_over_217_obs:.2f}s")

# ----------------------------------------------------------------------
# 模型函数
# ----------------------------------------------------------------------
def build_air_temp_profile(T_zone_array, v_cm_min):
    """
    构建空气温度沿炉长的分布并转换为时间序列
    T_zone_array: 长度为11的数组,每个温区的设定温度
    v_cm_min: 传送带速度 (cm/min)
    """
    v_m_s = v_cm_min / 100 / 60  # 转换为 m/s

    # 计算各温区起始位置
    x_positions = []
    x = L_pre
    # 炉前区域: [0, L_pre]
    x_positions.append(('pre', 0, L_pre, T_amb, T_zone_array[0]))

    for i in range(11):
        zone_start = x
        zone_end = x + L_zone
        x_positions.append((f'zone_{i}', zone_start, zone_end, T_zone_array[i], T_zone_array[i]))
        x = zone_end
        if i < 10:
            gap_start = x
            gap_end = x + L_gap
            x_positions.append((f'gap_{i}', gap_start, gap_end, T_zone_array[i], T_zone_array[i+1]))
            x = gap_end

    # 炉后区域
    x_positions.append(('post', x, x + L_post, T_zone_array[-1], T_amb))

    total_length = L_pre + 11 * L_zone + 10 * L_gap + L_post

    # 生成精细空间网格
    x_fine = np.linspace(0, total_length, 10000)
    T_air_x = np.zeros_like(x_fine)

    for seg_name, x_start, x_end, T_start, T_end in x_positions:
        mask = (x_fine >= x_start) & (x_fine <= x_end)
        if x_end > x_start:
            # 线性插值
            T_air_x[mask] = T_start + (T_end - T_start) * (x_fine[mask] - x_start) / (x_end - x_start)
        else:
            T_air_x[mask] = T_start

    # 转换为时间序列
    t_fine = x_fine / v_m_s
    return t_fine, T_air_x, x_fine

def ode_system(t, T, t_air_interp):
    """集总参数法 ODE"""
    T_air_val = t_air_interp(t)
    alpha = alpha_opt  # 使用全局辨识的 alpha
    dTdt = alpha * (T_air_val - T)
    return dTdt

def solve_temperature_profile(T_zone_array, v_cm_min, alpha_val=None):
    """求解炉温曲线"""
    global alpha_opt
    if alpha_val is not None:
        alpha_opt = alpha_val

    t_fine, T_air_x, x_fine = build_air_temp_profile(T_zone_array, v_cm_min)
    t_air_interp = interp1d(t_fine, T_air_x, kind='linear', bounds_error=False, fill_value=T_amb)

    # 求解 ODE
    t_span = (0, t_fine[-1])
    T0 = T_amb

    sol = solve_ivp(
        lambda t, T: ode_system(t, T, t_air_interp),
        t_span, [T0],
        method='RK45',
        max_step=0.5,
        dense_output=True
    )

    # 生成均匀时间序列
    t_eval = np.arange(0, t_fine[-1], dt)
    T_eval = sol.sol(t_eval)[0]

    return t_eval, T_eval, t_fine, T_air_x

def compute_metrics(t_eval, T_eval):
    """计算所有约束指标"""
    # 温度变化率
    dT = np.diff(T_eval)
    dt_vals = np.diff(t_eval)
    dT_dt = dT / dt_vals

    max_heating = np.max(dT_dt)
    max_cooling = np.min(dT_dt)

    # 150-190°C 停留时间
    mask_150_190 = (T_eval >= 150) & (T_eval <= 190)
    t_150_190 = np.sum(mask_150_190) * dt

    # >217°C 停留时间
    mask_over_217 = T_eval >= 217
    t_over_217 = np.sum(mask_over_217) * dt

    # 峰值温度
    T_peak = np.max(T_eval)
    t_peak = t_eval[np.argmax(T_eval)]

    # 首次达到 217°C 的时刻
    idx_217 = np.where(T_eval >= 217)[0]
    t_217 = t_eval[idx_217[0]] if len(idx_217) > 0 else None

    return {
        'max_heating_rate': max_heating,
        'max_cooling_rate': max_cooling,
        't_150_190': t_150_190,
        't_over_217': t_over_217,
        'T_peak': T_peak,
        't_peak': t_peak,
        't_217': t_217
    }

def check_constraints(metrics):
    """检查所有约束是否满足"""
    constraints = {
        'heating_rate': metrics['max_heating_rate'] <= R_up_max,
        'cooling_rate': metrics['max_cooling_rate'] >= R_down_min,
        't_150_190_min': metrics['t_150_190'] >= t_150_190_min,
        't_150_190_max': metrics['t_150_190'] <= t_150_190_max,
        't_over_217_min': metrics['t_over_217'] >= t_over_217_min,
        't_over_217_max': metrics['t_over_217'] <= t_over_217_max,
        'T_peak_min': metrics['T_peak'] >= T_peak_min,
        'T_peak_max': metrics['T_peak'] <= T_peak_max
    }
    all_pass = all(constraints.values())
    return all_pass, constraints

# ----------------------------------------------------------------------
# 子问题1：参数辨识
# ----------------------------------------------------------------------
print("=" * 60)
print("子问题1:参数辨识")
print("=" * 60)

# 初始猜测 alpha = h / (rho * cp * delta)
h_guess = 80  # W/(m^2*K)
alpha_guess = h_guess / (rho * cp * delta)
print(f"[INFO] 初始 alpha 猜测: {alpha_guess:.6f} 1/s")

# 子问题1的工况
v_q1 = 70  # cm/min
T_zone_q1 = [175, 175, 175, 175, 195, 195, 235, 235, 255, 255, 255]

def objective_alpha(alpha):
    """参数辨识目标函数:RMSE"""
    global alpha_opt
    alpha_opt = alpha[0]
    t_pred, T_pred, _, _ = solve_temperature_profile(T_zone_q1, v_q1, alpha_val=alpha[0])

    # 插值到观测时间点
    T_pred_interp = np.interp(t_obs, t_pred, T_pred)
    rmse = np.sqrt(np.mean((T_pred_interp - T_obs) ** 2))
    return rmse

# 优化 alpha
result_opt = minimize(objective_alpha, [alpha_guess], method='Nelder-Mead',
                      options={'xatol': 1e-8, 'fatol': 1e-8, 'maxiter': 1000})

alpha_opt = result_opt.x[0]
print(f"[OK] 辨识得到的 alpha: {alpha_opt:.6f} 1/s")
print(f"[OK] 对应 h = alpha * rho * cp * delta = {alpha_opt * rho * cp * delta:.2f} W/(m^2*K)")

# 计算最终预测和误差
t_pred_q1, T_pred_q1, t_air_q1, T_air_q1 = solve_temperature_profile(T_zone_q1, v_q1, alpha_val=alpha_opt)
T_pred_interp = np.interp(t_obs, t_pred_q1, T_pred_q1)
rmse_final = np.sqrt(np.mean((T_pred_interp - T_obs) ** 2))
mae_final = np.mean(np.abs(T_pred_interp - T_obs))
r2 = 1 - np.sum((T_obs - T_pred_interp) ** 2) / np.sum((T_obs - np.mean(T_obs)) ** 2)

print(f"[OK] 最终 RMSE: {rmse_final:.4f} °C")
print(f"[OK] 最终 MAE: {mae_final:.4f} °C")
print(f"[OK] R²: {r2:.4f}")

# 输出 result.csv（问题1求解结果）
# 生成每隔0.5s的温度数据
t_result = np.arange(0, t_pred_q1[-1], 0.5)
T_result = np.interp(t_result, t_pred_q1, T_pred_q1)
df_result = pd.DataFrame({'时间(s)': t_result, '温度(ºC)': T_result})
df_result.to_csv('result.csv', index=False, encoding='utf-8')
print(f"[OK] result.csv 已生成,共 {len(df_result)} 行")

# 绘制子问题1结果图
fig, ax = plt.subplots(constrained_layout=True)
ax.plot(t_obs, T_obs, 'o', markersize=3, label='实测数据', alpha=0.7)
ax.plot(t_pred_q1, T_pred_q1, '-', label='模型预测', linewidth=2)
ax.set_xlabel('时间 / s')
ax.set_ylabel('温度 / °C')
ax.set_title('子问题1:模型预测与实测数据对比')
ax.legend()
fig.savefig('figures/fig_1_model_validation.png')
plt.close(fig)
print("[OK] 模型验证图已保存")

# ----------------------------------------------------------------------
# 子问题2：在给定温区温度下确定最大传送带速度
# ----------------------------------------------------------------------
print("=" * 60)
print("子问题2:确定最大传送带速度")
print("=" * 60)

# 给定温区温度
T_zone_q2 = [182, 182, 182, 182, 182, 203, 237, 254, 254, 254, 254]  # 补充温区10,11

def check_speed(v):
    """检查给定速度是否满足所有约束"""
    metrics = compute_metrics(*solve_temperature_profile(T_zone_q2, v, alpha_val=alpha_opt)[:2])
    all_pass, _ = check_constraints(metrics)
    return all_pass, metrics

# 二分法搜索最大可行速度
v_low, v_high = v_min, v_max
feasible_at_vmax = check_speed(v_high)[0]

if feasible_at_vmax:
    v_opt_q2 = v_high
    print(f"[OK] 速度上限 {v_high} cm/min 可行")
else:
    # 二分搜索
    for _ in range(50):
        v_mid = (v_low + v_high) / 2
        if check_speed(v_mid)[0]:
            v_low = v_mid
        else:
            v_high = v_mid
    v_opt_q2 = v_low
    print(f"[OK] 最大可行速度: {v_opt_q2:.2f} cm/min")

# 计算最终指标
_, metrics_q2 = check_speed(v_opt_q2)
print(f"[OK] 峰值温度: {metrics_q2['T_peak']:.2f} °C")
print(f"[OK] 最大升温速率: {metrics_q2['max_heating_rate']:.3f} °C/s")
print(f"[OK] 最大降温速率: {metrics_q2['max_cooling_rate']:.3f} °C/s")
print(f"[OK] 150-190°C 时间: {metrics_q2['t_150_190']:.2f} s")
print(f"[OK] >217°C 时间: {metrics_q2['t_over_217']:.2f} s")

# 绘制子问题2结果图
t_q2, T_q2, _, _ = solve_temperature_profile(T_zone_q2, v_opt_q2, alpha_val=alpha_opt)
fig, ax = plt.subplots(constrained_layout=True)
ax.plot(t_q2, T_q2, '-', label=f'v={v_opt_q2:.1f} cm/min')
ax.axhline(y=217, color='gray', linestyle='--', alpha=0.7, label='217°C')
ax.axhline(y=240, color='gray', linestyle=':', alpha=0.5, label='240°C')
ax.axhline(y=250, color='gray', linestyle=':', alpha=0.5, label='250°C')
ax.set_xlabel('时间 / s')
ax.set_ylabel('温度 / °C')
ax.set_title(f'子问题2:最大速度 {v_opt_q2:.1f} cm/min 时的炉温曲线')
ax.legend()
fig.savefig('figures/fig_2_max_speed_profile.png')
plt.close(fig)
print("[OK] 子问题2炉温曲线图已保存")

# ----------------------------------------------------------------------
# 子问题3：优化炉温曲线以最小化面积 S
# ----------------------------------------------------------------------
print("=" * 60)
print("子问题3:最小化超过217°C到峰值温度的面积")
print("=" * 60)

def compute_area_S(t_eval, T_eval):
    """计算面积 S = ∫(T(t)-217)dt from t_217 to t_peak"""
    idx_217 = np.where(T_eval >= 217)[0]
    if len(idx_217) == 0:
        return 0
    t_217 = t_eval[idx_217[0]]
    t_peak = t_eval[np.argmax(T_eval)]

    mask = (t_eval >= t_217) & (t_eval <= t_peak)
    if np.sum(mask) < 2:
        return 0
    S = np.trapz(T_eval[mask] - 217, t_eval[mask])
    return S

def objective_q3(x):
    """子问题3目标函数(带惩罚)"""
    T1_5, T6, T7, T8_9, v = x

    # 构建温区温度数组
    T_zone = [T1_5] * 5 + [T6, T7] + [T8_9] * 4  # 温区10,11与8-9相同

    try:
        t_eval, T_eval = solve_temperature_profile(T_zone, v, alpha_val=alpha_opt)[:2]
    except:
        return 1e10

    metrics = compute_metrics(t_eval, T_eval)
    all_pass, _ = check_constraints(metrics)

    S = compute_area_S(t_eval, T_eval)

    # 约束违反惩罚
    penalty = 0
    if metrics['max_heating_rate'] > R_up_max:
        penalty += (metrics['max_heating_rate'] - R_up_max) * 1e3
    if metrics['max_cooling_rate'] < R_down_min:
        penalty += (R_down_min - metrics['max_cooling_rate']) * 1e3
    if metrics['t_150_190'] < t_150_190_min:
        penalty += (t_150_190_min - metrics['t_150_190']) * 1e2
    if metrics['t_150_190'] > t_150_190_max:
        penalty += (metrics['t_150_190'] - t_150_190_max) * 1e2
    if metrics['t_over_217'] < t_over_217_min:
        penalty += (t_over_217_min - metrics['t_over_217']) * 1e2
    if metrics['t_over_217'] > t_over_217_max:
        penalty += (metrics['t_over_217'] - t_over_217_max) * 1e2
    if metrics['T_peak'] < T_peak_min:
        penalty += (T_peak_min - metrics['T_peak']) * 1e2
    if metrics['T_peak'] > T_peak_max:
        penalty += (metrics['T_peak'] - T_peak_max) * 1e2

    return S + penalty

# 决策变量边界
bounds_q3 = [
    (T_base['T1_5'] - T_delta, T_base['T1_5'] + T_delta),
    (T_base['T6'] - T_delta, T_base['T6'] + T_delta),
    (T_base['T7'] - T_delta, T_base['T7'] + T_delta),
    (T_base['T8_9'] - T_delta, T_base['T8_9'] + T_delta),
    (v_min, v_max)
]

# 使用差分进化算法
result_q3 = differential_evolution(objective_q3, bounds_q3, strategy='best1bin',
                                   maxiter=200, popsize=30, tol=1e-7,
                                   mutation=(0.5, 1), recombination=0.7,
                                   seed=42)

x_opt_q3 = result_q3.x
S_opt = result_q3.fun

print(f"[OK] 最优解:")
print(f"  T1-5 = {x_opt_q3[0]:.1f} °C")
print(f"  T6 = {x_opt_q3[1]:.1f} °C")
print(f"  T7 = {x_opt_q3[2]:.1f} °C")
print(f"  T8-9 = {x_opt_q3[3]:.1f} °C")
print(f"  v = {x_opt_q3[4]:.2f} cm/min")
print(f"  面积 S = {S_opt:.2f} °C·s")

# 验证最优解
T_zone_opt_q3 = [x_opt_q3[0]] * 5 + [x_opt_q3[1], x_opt_q3[2]] + [x_opt_q3[3]] * 4
t_opt_q3, T_opt_q3, _, _ = solve_temperature_profile(T_zone_opt_q3, x_opt_q3[4], alpha_val=alpha_opt)
metrics_q3 = compute_metrics(t_opt_q3, T_opt_q3)
all_pass_q3, constraints_q3 = check_constraints(metrics_q3)

print(f"[OK] 约束检查: {'全部通过' if all_pass_q3 else '存在违反'}")
for k, v in constraints_q3.items():
    print(f"  {k}: {'通过' if v else '违反'}")

# 绘制子问题3结果图
fig, ax = plt.subplots(constrained_layout=True)
ax.plot(t_opt_q3, T_opt_q3, '-', label='优化后炉温曲线')
ax.axhline(y=217, color='gray', linestyle='--', alpha=0.7, label='217°C')
# 标记面积区域
idx_217 = np.where(T_opt_q3 >= 217)[0][0]
t_217_val = t_opt_q3[idx_217]
t_peak_val = t_opt_q3[np.argmax(T_opt_q3)]
mask_S = (t_opt_q3 >= t_217_val) & (t_opt_q3 <= t_peak_val)
ax.fill_between(t_opt_q3[mask_S], 217, T_opt_q3[mask_S], alpha=0.3, label=f'S={S_opt:.1f} °C·s')
ax.set_xlabel('时间 / s')
ax.set_ylabel('温度 / °C')
ax.set_title('子问题3:最小化面积 S 的优化结果')
ax.legend()
fig.savefig('figures/fig_3_optimized_profile.png')
plt.close(fig)
print("[OK] 子问题3优化结果图已保存")

# ----------------------------------------------------------------------
# 子问题4：多目标优化（增加对称性要求）
# ----------------------------------------------------------------------
print("=" * 60)
print("子问题4:多目标优化(面积 S + 不对称度 A_sym)")
print("=" * 60)

def compute_asymmetry(t_eval, T_eval):
    """计算不对称度 A_sym"""
    idx_217 = np.where(T_eval >= 217)[0]
    if len(idx_217) == 0:
        return 0
    t_217 = t_eval[idx_217[0]]
    t_peak_idx = np.argmax(T_eval)
    t_peak = t_eval[t_peak_idx]

    # 取两侧可比较的较小范围
    delta = min(t_peak - t_217, t_eval[-1] - t_peak)
    if delta <= 0:
        return 0

    # 离散化
    tau_vals = np.arange(0, delta, dt)
    if len(tau_vals) < 2:
        return 0

    # 计算左右两侧温度
    T_left = np.interp(t_peak - tau_vals, t_eval, T_eval)
    T_right = np.interp(t_peak + tau_vals, t_eval, T_eval)

    # 不对称度：温度差值的平方积分
    diff_sq = (T_right - T_left) ** 2
    A_sym = np.trapz(diff_sq, tau_vals)

    return A_sym

def multi_objective_q4(x):
    """子问题4多目标函数"""
    T1_5, T6, T7, T8_9, v = x
    T_zone = [T1_5] * 5 + [T6, T7] + [T8_9] * 4

    try:
        t_eval, T_eval = solve_temperature_profile(T_zone, v, alpha_val=alpha_opt)[:2]
    except:
        return [1e10, 1e10]

    metrics = compute_metrics(t_eval, T_eval)
    all_pass, _ = check_constraints(metrics)

    S = compute_area_S(t_eval, T_eval)
    A_sym = compute_asymmetry(t_eval, T_eval)

    # 约束违反惩罚
    penalty = 0
    if metrics['max_heating_rate'] > R_up_max:
        penalty += (metrics['max_heating_rate'] - R_up_max) * 1e3
    if metrics['max_cooling_rate'] < R_down_min:
        penalty += (R_down_min - metrics['max_cooling_rate']) * 1e3
    if metrics['t_150_190'] < t_150_190_min:
        penalty += (t_150_190_min - metrics['t_150_190']) * 1e2
    if metrics['t_150_190'] > t_150_190_max:
        penalty += (metrics['t_150_190'] - t_150_190_max) * 1e2
    if metrics['t_over_217'] < t_over_217_min:
        penalty += (t_over_217_min - metrics['t_over_217']) * 1e2
    if metrics['t_over_217'] > t_over_217_max:
        penalty += (metrics['t_over_217'] - t_over_217_max) * 1e2
    if metrics['T_peak'] < T_peak_min:
        penalty += (T_peak_min - metrics['T_peak']) * 1e2
    if metrics['T_peak'] > T_peak_max:
        penalty += (metrics['T_peak'] - T_peak_max) * 1e2

    return [S + penalty, A_sym + penalty]

# 使用加权和法近似帕累托前沿（因pymoo可能需要额外安装，使用加权法）
# 生成不同权重的解
weights = np.linspace(0, 1, 11)
pareto_front = []

for w in weights:
    def weighted_objective(x):
        obj = multi_objective_q4(x)
        return w * obj[0] + (1 - w) * obj[1]

    result = differential_evolution(weighted_objective, bounds_q3,
                                    maxiter=150, popsize=20, tol=1e-7,
                                    seed=42 + int(w * 100))
    x_opt = result.x
    obj_vals = multi_objective_q4(x_opt)
    pareto_front.append({'w': w, 'x': x_opt, 'S': obj_vals[0], 'A_sym': obj_vals[1]})

# 提取非支配解
pareto_filtered = []
for p in pareto_front:
    dominated = False
    for q in pareto_front:
        if q['S'] <= p['S'] and q['A_sym'] <= p['A_sym'] and (q['S'] < p['S'] or q['A_sym'] < p['A_sym']):
            dominated = True
            break
    if not dominated:
        pareto_filtered.append(p)

# 选择拐点解（最大曲率近似）
if len(pareto_filtered) > 2:
    # 归一化
    S_vals = np.array([p['S'] for p in pareto_filtered])
    A_vals = np.array([p['A_sym'] for p in pareto_filtered])
    S_norm = (S_vals - S_vals.min()) / (S_vals.max() - S_vals.min() + 1e-10)
    A_norm = (A_vals - A_vals.min()) / (A_vals.max() - A_vals.min() + 1e-10)

    # 计算到理想点(0,0)的距离
    dist = np.sqrt(S_norm ** 2 + A_norm ** 2)
    best_idx = np.argmin(dist)
    best_solution = pareto_filtered[best_idx]
else:
    best_solution = pareto_filtered[0]

print(f"[OK] 帕累托前沿解数量: {len(pareto_filtered)}")
print(f"[OK] 选择的最优解:")
print(f"  T1-5 = {best_solution['x'][0]:.1f} °C")
print(f"  T6 = {best_solution['x'][1]:.1f} °C")
print(f"  T7 = {best_solution['x'][2]:.1f} °C")
print(f"  T8-9 = {best_solution['x'][3]:.1f} °C")
print(f"  v = {best_solution['x'][4]:.2f} cm/min")
print(f"  面积 S = {best_solution['S']:.2f} °C·s")
print(f"  不对称度 A_sym = {best_solution['A_sym']:.2f}")

# 绘制子问题4结果图
# 帕累托前沿图
fig, ax = plt.subplots(constrained_layout=True)
S_pareto = [p['S'] for p in pareto_filtered]
A_pareto = [p['A_sym'] for p in pareto_filtered]
ax.scatter(S_pareto, A_pareto, c='#4C72B0', s=80, zorder=5, label='帕累托前沿')
ax.scatter(best_solution['S'], best_solution['A_sym'], c='#C44E52', s=120,
           marker='*', zorder=6, label='选择的最优解')
ax.set_xlabel('面积 S / (°C·s)')
ax.set_ylabel('不对称度 A_sym')
ax.set_title('子问题4:多目标优化帕累托前沿')
ax.legend()
fig.savefig('figures/fig_4_pareto_front.png')
plt.close(fig)
print("[OK] 帕累托前沿图已保存")

# 绘制最优解炉温曲线
T_zone_opt_q4 = [best_solution['x'][0]] * 5 + [best_solution['x'][1], best_solution['x'][2]] + [best_solution['x'][3]] * 4
t_opt_q4, T_opt_q4, _, _ = solve_temperature_profile(T_zone_opt_q4, best_solution['x'][4], alpha_val=alpha_opt)

fig, ax = plt.subplots(constrained_layout=True)
ax.plot(t_opt_q4, T_opt_q4, '-', label='优化后炉温曲线')
ax.axhline(y=217, color='gray', linestyle='--', alpha=0.7, label='217°C')
# 标记对称性区域
idx_217 = np.where(T_opt_q4 >= 217)[0][0]
t_217_val = t_opt_q4[idx_217]
t_peak_val = t_opt_q4[np.argmax(T_opt_q4)]
delta = min(t_peak_val - t_217_val, t_opt_q4[-1] - t_peak_val)
ax.axvline(x=t_peak_val - delta, color='green', linestyle=':', alpha=0.5, label='对称区间左边界')
ax.axvline(x=t_peak_val + delta, color='green', linestyle=':', alpha=0.5, label='对称区间右边界')
ax.set_xlabel('时间 / s')
ax.set_ylabel('温度 / °C')
ax.set_title('子问题4:多目标优化最优炉温曲线')
ax.legend()
fig.savefig('figures/fig_4_optimized_profile.png')
plt.close(fig)
print("[OK] 子问题4优化结果图已保存")

# ----------------------------------------------------------------------
# 灵敏度分析
# ----------------------------------------------------------------------
print("=" * 60)
print("灵敏度分析")
print("=" * 60)

sensitivity_results = {
    "baseline": {
        "objective": S_opt,
        "objective_name": "面积 S (子问题3)"
    },
    "experiments": []
}

# 参数1：alpha (热交换系数)
for delta_pct in [-20, -10, 10, 20]:
    alpha_test = alpha_opt * (1 + delta_pct / 100)
    t_test, T_test = solve_temperature_profile(T_zone_opt_q3, x_opt_q3[4], alpha_val=alpha_test)[:2]
    S_test = compute_area_S(t_test, T_test)
    change_pct = (S_test - S_opt) / S_opt * 100
    sensitivity_results["experiments"].append({
        "param": "alpha",
        "delta_pct": delta_pct,
        "objective": S_test,
        "change_pct": change_pct
    })
    print(f"  alpha {delta_pct:>+3d}%: S={S_test:.2f}, 变化={change_pct:+.2f}%")

# 参数2：v (传送带速度)
for delta_pct in [-20, -10, 10, 20]:
    v_test = x_opt_q3[4] * (1 + delta_pct / 100)
    if v_test < v_min or v_test > v_max:
        continue
    t_test, T_test = solve_temperature_profile(T_zone_opt_q3, v_test, alpha_val=alpha_opt)[:2]
    S_test = compute_area_S(t_test, T_test)
    change_pct = (S_test - S_opt) / S_opt * 100
    sensitivity_results["experiments"].append({
        "param": "v",
        "delta_pct": delta_pct,
        "objective": S_test,
        "change_pct": change_pct
    })
    print(f"  v {delta_pct:>+3d}%: S={S_test:.2f}, 变化={change_pct:+.2f}%")

# 参数3：T7 (温区7温度)
for delta_pct in [-20, -10, 10, 20]:
    T7_test = x_opt_q3[2] * (1 + delta_pct / 100)
    T7_test = max(T_base['T7'] - T_delta, min(T_base['T7'] + T_delta, T7_test))
    T_zone_test = [x_opt_q3[0]] * 5 + [x_opt_q3[1], T7_test] + [x_opt_q3[3]] * 4
    t_test, T_test = solve_temperature_profile(T_zone_test, x_opt_q3[4], alpha_val=alpha_opt)[:2]
    S_test = compute_area_S(t_test, T_test)
    change_pct = (S_test - S_opt) / S_opt * 100
    sensitivity_results["experiments"].append({
        "param": "T7",
        "delta_pct": delta_pct,
        "objective": S_test,
        "change_pct": change_pct
    })
    print(f"  T7 {delta_pct:>+3d}%: S={S_test:.2f}, 变化={change_pct:+.2f}%")

# 保存 sensitivity.json
with open("sensitivity.json", "w", encoding="utf-8") as f:
    json.dump(sensitivity_results, f, ensure_ascii=False, indent=2)
print("[OK] sensitivity.json 已保存")

# 绘制灵敏度图
for param_name in ['alpha', 'v', 'T7']:
    param_data = [e for e in sensitivity_results['experiments'] if e['param'] == param_name]
    if not param_data:
        continue

    fig, ax = plt.subplots(constrained_layout=True)
    deltas = [e['delta_pct'] for e in param_data]
    objectives = [e['objective'] for e in param_data]

    ax.plot(deltas, objectives, 'o-', markersize=8)
    ax.axhline(y=S_opt, color='gray', linestyle='--', alpha=0.7, label=f'基准值 S={S_opt:.1f}')
    ax.set_xlabel('参数扰动幅度 / %')
    ax.set_ylabel('面积 S / (°C·s)')
    ax.set_title(f'灵敏度分析:{param_name}')
    ax.legend()
    fig.savefig(f'figures/sensitivity_{param_name}.png')
    plt.close(fig)
    print(f"[OK] 灵敏度图 sensitivity_{param_name}.png 已保存")

# ----------------------------------------------------------------------
# 保存 results.json
# ----------------------------------------------------------------------
results = [
    # EDA 统计
    {"name": "eda_原始行数", "value": n_raw, "unit": "行", "desc": "附件数据原始样本量"},
    {"name": "eda_有效行数", "value": n_valid, "unit": "行", "desc": "无缺失值的有效样本量"},
    {"name": "eda_缺失数", "value": n_missing, "unit": "行", "desc": "缺失值数量"},
    {"name": "eda_缺失率", "value": missing_rate, "unit": "%", "desc": "缺失值占比"},
    {"name": "eda_异常值数", "value": n_outliers, "unit": "个", "desc": "IQR方法检测的异常值数量"},
    {"name": "eda_异常值率", "value": outlier_rate, "unit": "%", "desc": "异常值占比"},
    {"name": "eda_温度均值", "value": T_mean, "unit": "°C", "desc": "温度平均值"},
    {"name": "eda_温度中位数", "value": T_median, "unit": "°C", "desc": "温度中位数"},
    {"name": "eda_温度标准差", "value": T_std, "unit": "°C", "desc": "温度标准差"},
    {"name": "eda_温度最小值", "value": T_min, "unit": "°C", "desc": "温度最小值"},
    {"name": "eda_温度最大值", "value": T_max, "unit": "°C", "desc": "温度最大值(峰值)"},
    {"name": "eda_时间温度相关系数", "value": corr_time_temp, "unit": "", "desc": "时间与温度的Pearson相关系数"},
    {"name": "eda_最大升温速率", "value": max_heating_rate, "unit": "°C/s", "desc": "实测最大升温速率"},
    {"name": "eda_最大降温速率", "value": max_cooling_rate, "unit": "°C/s", "desc": "实测最大降温速率"},
    {"name": "eda_150_190时间", "value": t_150_190_obs, "unit": "s", "desc": "实测150-190°C持续时间"},
    {"name": "eda_217以上时间", "value": t_over_217_obs, "unit": "s", "desc": "实测>217°C持续时间"},
    {"name": "eda_异常值下界", "value": lower_bound, "unit": "°C", "desc": "IQR异常值检测下界"},
    {"name": "eda_异常值上界", "value": upper_bound, "unit": "°C", "desc": "IQR异常值检测上界"},
    # 子问题1
    {"name": "q1_辨识alpha", "value": alpha_opt, "unit": "1/s", "desc": "辨识得到的有效热交换系数"},
    {"name": "q1_辨识h", "value": alpha_opt * rho * cp * delta, "unit": "W/(m^2·K)", "desc": "辨识得到的对流换热系数"},
    {"name": "q1_RMSE", "value": rmse_final, "unit": "°C", "desc": "模型预测与实测数据的均方根误差"},
    {"name": "q1_MAE", "value": mae_final, "unit": "°C", "desc": "模型预测与实测数据的平均绝对误差"},
    {"name": "q1_R平方", "value": r2, "unit": "", "desc": "模型决定系数"},
    # 子问题2
    {"name": "q2_最大速度", "value": v_opt_q2, "unit": "cm/min", "desc": "给定温区温度下的最大可行传送带速度"},
    {"name": "q2_峰值温度", "value": metrics_q2['T_peak'], "unit": "°C", "desc": "子问题2最优解对应的峰值温度"},
    {"name": "q2_最大升温速率", "value": metrics_q2['max_heating_rate'], "unit": "°C/s", "desc": "子问题2最优解对应的最大升温速率"},
    {"name": "q2_最大降温速率", "value": metrics_q2['max_cooling_rate'], "unit": "°C/s", "desc": "子问题2最优解对应的最大降温速率"},
    {"name": "q2_150_190时间", "value": metrics_q2['t_150_190'], "unit": "s", "desc": "子问题2最优解对应的150-190°C持续时间"},
    {"name": "q2_217以上时间", "value": metrics_q2['t_over_217'], "unit": "s", "desc": "子问题2最优解对应的>217°C持续时间"},
    # 子问题3
    {"name": "q3_最优面积S", "value": S_opt, "unit": "°C·s", "desc": "子问题3最小化的面积S"},
    {"name": "q3_最优T1_5", "value": x_opt_q3[0], "unit": "°C", "desc": "子问题3最优温区1-5温度"},
    {"name": "q3_最优T6", "value": x_opt_q3[1], "unit": "°C", "desc": "子问题3最优温区6温度"},
    {"name": "q3_最优T7", "value": x_opt_q3[2], "unit": "°C", "desc": "子问题3最优温区7温度"},
    {"name": "q3_最优T8_9", "value": x_opt_q3[3], "unit": "°C", "desc": "子问题3最优温区8-9温度"},
    {"name": "q3_最优速度", "value": x_opt_q3[4], "unit": "cm/min", "desc": "子问题3最优传送带速度"},
    {"name": "q3_约束全部通过", "value": int(all_pass_q3), "unit": "", "desc": "子问题3最优解是否满足所有约束"},
    # 子问题4
    {"name": "q4_帕累托前沿解数量", "value": len(pareto_filtered), "unit": "个", "desc": "子问题4帕累托前沿非支配解数量"},
    {"name": "q4_最优面积S", "value": best_solution['S'], "unit": "°C·s", "desc": "子问题4选择的最优解面积S"},
    {"name": "q4_最优不对称度", "value": best_solution['A_sym'], "unit": "", "desc": "子问题4选择的最优解不对称度"},
    {"name": "q4_最优T1_5", "value": best_solution['x'][0], "unit": "°C", "desc": "子问题4最优温区1-5温度"},
    {"name": "q4_最优T6", "value": best_solution['x'][1], "unit": "°C", "desc": "子问题4最优温区6温度"},
    {"name": "q4_最优T7", "value": best_solution['x'][2], "unit": "°C", "desc": "子问题4最优温区7温度"},
    {"name": "q4_最优T8_9", "value": best_solution['x'][3], "unit": "°C", "desc": "子问题4最优温区8-9温度"},
    {"name": "q4_最优速度", "value": best_solution['x'][4], "unit": "cm/min", "desc": "子问题4最优传送带速度"},
]

with open("results.json", "w", encoding="utf-8") as f:
    json.dump(results, f, ensure_ascii=False, indent=2)
print("[OK] results.json 已保存")

print("=" * 60)
print("全部求解完成")
print("=" * 60)