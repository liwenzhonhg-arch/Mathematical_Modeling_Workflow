# solution.py
import sys
sys.stdout.reconfigure(encoding='utf-8')

import os
import json
import warnings
import numpy as np
import pandas as pd
from scipy.optimize import curve_fit, minimize
from scipy.stats import bootstrap
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from cycler import cycler
from sklearn.linear_model import LinearRegression, LassoCV
from sklearn.preprocessing import StandardScaler
from sklearn.metrics import r2_score, mean_squared_error
from sklearn.model_selection import cross_val_score
import statsmodels.api as sm
from statsmodels.formula.api import ols
import random
import itertools

warnings.filterwarnings('ignore')

# ========== 全局绘图设置 ==========
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

os.makedirs('figures', exist_ok=True)

# ========== 数据加载 ==========
print("=" * 60)
print("加载数据...")
print("=" * 60)

data_dir = 'data/raw'
if not os.path.exists(data_dir):
    print(f"[X] 数据目录 {data_dir} 不存在")
    print(f"当前目录内容: {os.listdir('.')}")
    raise FileNotFoundError(f"数据目录 {data_dir} 不存在")

files = os.listdir(data_dir)
print(f"data/raw 内容: {files}")

if '附件1.xlsx' not in files or '附件2.xlsx' not in files:
    print(f"[X] 缺少必要数据文件")
    raise FileNotFoundError(f"缺少附件1.xlsx 或 附件2.xlsx")

df1_raw = pd.read_excel(os.path.join(data_dir, '附件1.xlsx'))
df2_raw = pd.read_excel(os.path.join(data_dir, '附件2.xlsx'))

print(f"附件1 原始形状: {df1_raw.shape}")
print(f"附件2 原始形状: {df2_raw.shape}")

# ========== 数据预处理 ==========
print("\n" + "=" * 60)
print("数据预处理...")
print("=" * 60)

# 附件1: 填充催化剂组合编号和催化剂组合（前向填充）
df1 = df1_raw.copy()
df1['催化剂组合编号'] = df1['催化剂组合编号'].ffill()
df1['催化剂组合'] = df1['催化剂组合'].ffill()

# 提取催化剂类型和编号
def parse_catalyst(cat):
    if pd.isna(cat):
        return np.nan, np.nan
    cat = str(cat).strip()
    if cat.startswith('A'):
        return 1, cat
    elif cat.startswith('B'):
        return 0, cat
    else:
        return np.nan, cat

df1['type'], df1['催化剂编号'] = zip(*df1['催化剂组合'].apply(parse_catalyst))

# 提取Co负载量、装料比、乙醇浓度
def extract_params(cat_id):
    if pd.isna(cat_id):
        return np.nan, np.nan, np.nan
    cat_id = str(cat_id)
    parts = cat_id.split('-')
    if len(parts) >= 3:
        try:
            w_co = float(parts[1].replace('wt%', '').strip())
            r = float(parts[2].strip())
            return w_co, r, np.nan
        except:
            return np.nan, np.nan, np.nan
    return np.nan, np.nan, np.nan

# 从催化剂组合字符串提取参数
def parse_catalyst_full(cat_str):
    if pd.isna(cat_str):
        return np.nan, np.nan, np.nan, np.nan
    cat_str = str(cat_str).strip()
    # 格式如: "A1-1wt%-1" 或 "B1-2wt%-0.5"
    parts = cat_str.split('-')
    if len(parts) >= 3:
        try:
            type_val = 1 if parts[0].startswith('A') else 0
            w_co = float(parts[1].replace('wt%', '').strip())
            r = float(parts[2].strip())
            return type_val, w_co, r, np.nan
        except:
            return np.nan, np.nan, np.nan, np.nan
    return np.nan, np.nan, np.nan, np.nan

params = df1['催化剂组合'].apply(lambda x: pd.Series(parse_catalyst_full(x), index=['type_parsed', 'w_Co', 'r', 'C_eth_dummy']))
df1 = pd.concat([df1, params], axis=1)

# 使用解析出的参数
df1['w_Co'] = df1['w_Co'].fillna(df1['type_parsed'])
df1['r'] = df1['r'].fillna(df1['type_parsed'])
df1['type'] = df1['type'].fillna(df1['type_parsed'])

# 如果解析失败，使用默认值
df1['w_Co'] = df1['w_Co'].fillna(1.0)
df1['r'] = df1['r'].fillna(1.0)
df1['type'] = df1['type'].fillna(0)

# 重命名列
col_rename = {
    '温度': 'T',
    '乙醇转化率(%)': 'X',
    'C4烯烃选择性(%)': 'S',
}
df1.rename(columns=col_rename, inplace=True)

# 计算收率
df1['Y'] = df1['X'] * df1['S'] / 100

# 附件2: 时序数据
df2 = df2_raw.copy()
# 跳过表头行
df2 = df2.iloc[1:].reset_index(drop=True)
df2.columns = ['时间(min)', '乙醇转化率(%)', '乙烯选择性(%)', 'C4烯烃选择性(%)',
               '乙醛选择性(%)', '碳数为4-12脂肪醇选择性(%)',
               '甲基苯甲醛和甲基苯甲醇选择性(%)', '其他生成物的选择性(%)']
# 转换数值
for col in df2.columns:
    df2[col] = pd.to_numeric(df2[col], errors='coerce')
df2 = df2.dropna().reset_index(drop=True)

df2.rename(columns={'时间(min)': 't', '乙醇转化率(%)': 'X', 'C4烯烃选择性(%)': 'S'}, inplace=True)

print(f"附件1 处理后形状: {df1.shape}")
print(f"附件2 处理后形状: {df2.shape}")

# ========== EDA 统计 ==========
print("\n" + "=" * 60)
print("EDA 统计...")
print("=" * 60)

original_rows = df1_raw.shape[0]
valid_rows = df1.shape[0]
missing_cat = df1_raw['催化剂组合编号'].isna().sum()
missing_cat_pct = missing_cat / original_rows * 100

# 异常值检测 (IQR)
def count_outliers(series):
    Q1 = series.quantile(0.25)
    Q3 = series.quantile(0.75)
    IQR = Q3 - Q1
    lower = Q1 - 1.5 * IQR
    upper = Q3 + 1.5 * IQR
    outliers = series[(series < lower) | (series > upper)]
    return len(outliers), lower, upper, outliers.tolist() if len(outliers) > 0 else []

outliers_X, lower_X, upper_X, _ = count_outliers(df1['X'])
outliers_S, lower_S, upper_S, _ = count_outliers(df1['S'])

# 相关性
corr_T_X = df1['T'].corr(df1['X'])
corr_T_S = df1['T'].corr(df1['S'])
corr_X_S = df1['X'].corr(df1['S'])

# 收率统计
Y_mean = df1['Y'].mean()
Y_median = df1['Y'].median()
Y_max = df1['Y'].max()
Y_min = df1['Y'].min()

print(f"原始行数: {original_rows}")
print(f"有效行数: {valid_rows}")
print(f"缺失催化剂编号: {missing_cat} ({missing_cat_pct:.2f}%)")
print(f"转化率异常值数: {outliers_X} (阈值: 上界 {upper_X:.2f}%)")
print(f"选择性异常值数: {outliers_S} (阈值: 上界 {upper_S:.2f}%)")
print(f"温度-转化率相关系数: {corr_T_X:.4f}")
print(f"温度-选择性相关系数: {corr_T_S:.4f}")
print(f"转化率-选择性相关系数: {corr_X_S:.4f}")
print(f"收率均值: {Y_mean:.4f}%, 中位数: {Y_median:.4f}%, 最大: {Y_max:.4f}%, 最小: {Y_min:.4f}%")

# ========== 子问题1：单催化剂性能曲线拟合 ==========
print("\n" + "=" * 60)
print("子问题1:单催化剂性能曲线拟合")
print("=" * 60)

# Sigmoid 模型
def sigmoid(T, a, b, c):
    return a / (1 + np.exp(-b * (T - c)))

# 指数衰减模型
def exp_decay(t, X0, k, Xinf):
    return X0 * np.exp(-k * t) + Xinf

catalysts = df1['催化剂组合'].unique()
results_q1 = []

for cat in catalysts:
    subset = df1[df1['催化剂组合'] == cat].sort_values('T')
    T_data = subset['T'].values
    X_data = subset['X'].values
    S_data = subset['S'].values
    
    # 转化率拟合
    try:
        p0_X = [max(X_data), 0.01, np.median(T_data)]
        popt_X, pcov_X = curve_fit(sigmoid, T_data, X_data, p0=p0_X, maxfev=10000, bounds=([0, 0.001, 250], [100, 1, 450]))
        X_pred = sigmoid(T_data, *popt_X)
        r2_X = r2_score(X_data, X_pred)
        rmse_X = np.sqrt(mean_squared_error(X_data, X_pred))
    except:
        popt_X = [np.nan, np.nan, np.nan]
        r2_X = np.nan
        rmse_X = np.nan
    
    # 选择性拟合
    try:
        p0_S = [max(S_data), 0.01, np.median(T_data)]
        popt_S, pcov_S = curve_fit(sigmoid, T_data, S_data, p0=p0_S, maxfev=10000, bounds=([0, 0.001, 250], [100, 1, 450]))
        S_pred = sigmoid(T_data, *popt_S)
        r2_S = r2_score(S_data, S_pred)
        rmse_S = np.sqrt(mean_squared_error(S_data, S_pred))
    except:
        popt_S = [np.nan, np.nan, np.nan]
        r2_S = np.nan
        rmse_S = np.nan
    
    results_q1.append({
        '催化剂': cat,
        'a_X': popt_X[0], 'b_X': popt_X[1], 'c_X': popt_X[2],
        'r2_X': r2_X, 'rmse_X': rmse_X,
        'd_S': popt_S[0], 'e_S': popt_S[1], 'f_S': popt_S[2],
        'r2_S': r2_S, 'rmse_S': rmse_S,
        'n_points': len(T_data)
    })

df_q1 = pd.DataFrame(results_q1)
print(f"\n拟合完成,共 {len(df_q1)} 种催化剂")
print(f"转化率 R2 均值: {df_q1['r2_X'].mean():.4f}")
print(f"选择性 R2 均值: {df_q1['r2_S'].mean():.4f}")

# 附件2 时序分析
t_data = df2['t'].values
X_time = df2['X'].values
S_time = df2['S'].values

try:
    p0_exp = [X_time[0] - X_time[-1], 0.01, X_time[-1]]
    popt_exp, _ = curve_fit(exp_decay, t_data, X_time, p0=p0_exp, maxfev=10000, bounds=([0, 0.001, 0], [100, 1, 100]))
    X0_est, k_est, Xinf_est = popt_exp
    X_time_pred = exp_decay(t_data, *popt_exp)
    r2_time = r2_score(X_time, X_time_pred)
    rmse_time = np.sqrt(mean_squared_error(X_time, X_time_pred))
except:
    X0_est, k_est, Xinf_est = np.nan, np.nan, np.nan
    r2_time, rmse_time = np.nan, np.nan

S_mean = np.mean(S_time)
S_std = np.std(S_time)
S_min = np.min(S_time)
S_max = np.max(S_time)

print(f"\n时序分析:")
print(f"  初始转化率 X0: {X0_est:.4f}%")
print(f"  衰减常数 k: {k_est:.6f} min^-1")
print(f"  稳态转化率 Xinf: {Xinf_est:.4f}%")
print(f"  拟合 R2: {r2_time:.4f}")
print(f"  选择性均值: {S_mean:.4f}% +/- {S_std:.4f}%")

# 绘制几种典型催化剂的拟合曲线
fig, axes = plt.subplots(2, 2, figsize=(10, 8), constrained_layout=True)
example_cats = ['A1', 'A7', 'B1', 'B4']
for ax, cat in zip(axes.flatten(), example_cats):
    subset = df1[df1['催化剂组合'] == cat].sort_values('T')
    T_plot = np.linspace(250, 450, 100)
    
    # 找到拟合参数
    row = df_q1[df_q1['催化剂'] == cat].iloc[0]
    if not np.isnan(row['a_X']):
        X_plot = sigmoid(T_plot, row['a_X'], row['b_X'], row['c_X'])
        ax.plot(T_plot, X_plot, label='X 拟合')
    ax.scatter(subset['T'], subset['X'], label='X 数据', zorder=5)
    
    if not np.isnan(row['d_S']):
        S_plot = sigmoid(T_plot, row['d_S'], row['e_S'], row['f_S'])
        ax.plot(T_plot, S_plot, label='S 拟合')
    ax.scatter(subset['T'], subset['S'], label='S 数据', marker='^', zorder=5)
    
    ax.set_xlabel('温度 / ℃')
    ax.set_ylabel('百分比 / %')
    ax.set_title(f'催化剂 {cat}')
    ax.legend()

fig.suptitle('典型催化剂拟合曲线', fontsize=14)
fig.savefig('figures/fig_1_catalyst_fits.png')
plt.close(fig)
print("[OK] 催化剂拟合图已保存")

# 时序数据图
fig, ax = plt.subplots(constrained_layout=True)
ax.scatter(t_data, X_time, label='转化率数据')
T_plot = np.linspace(20, 280, 100)
if not np.isnan(X0_est):
    X_time_plot = exp_decay(T_plot, X0_est, k_est, Xinf_est)
    ax.plot(T_plot, X_time_plot, label='指数衰减拟合', color='#C44E52')
ax.set_xlabel('时间 / min')
ax.set_ylabel('乙醇转化率 / %')
ax.set_title('附件2 时序数据及拟合')
ax.legend()
fig.savefig('figures/fig_2_time_series.png')
plt.close(fig)
print("[OK] 时序数据图已保存")

# ========== 子问题2：全局影响因素分析 ==========
print("\n" + "=" * 60)
print("子问题2:全局影响因素分析")
print("=" * 60)

# 准备特征
df_model = df1.copy()
# 离散变量处理：Co负载量、装料比、乙醇浓度从催化剂组合提取
# 从催化剂组合字符串中提取更精确的参数
def extract_params_v2(cat_str):
    if pd.isna(cat_str):
        return np.nan, np.nan, np.nan
    cat_str = str(cat_str).strip()
    parts = cat_str.split('-')
    if len(parts) >= 3:
        try:
            w_co = float(parts[1].replace('wt%', '').strip())
            r = float(parts[2].strip())
            return w_co, r, np.nan
        except:
            return np.nan, np.nan, np.nan
    return np.nan, np.nan, np.nan

params_v2 = df_model['催化剂组合'].apply(lambda x: pd.Series(extract_params_v2(x), index=['w_Co_v2', 'r_v2', 'C_eth_v2']))
df_model = pd.concat([df_model, params_v2], axis=1)

# 如果解析失败，使用分组均值
df_model['w_Co'] = df_model['w_Co_v2'].fillna(df_model.groupby('催化剂组合')['w_Co'].transform('mean'))
df_model['r'] = df_model['r_v2'].fillna(df_model.groupby('催化剂组合')['r'].transform('mean'))

# 对于乙醇浓度，使用近似值（从催化剂组合推断）
# 如果无法推断，使用默认值 0.9
df_model['C_eth'] = df_model.get('C_eth', pd.Series(0.9, index=df_model.index))
df_model['C_eth'] = df_model['C_eth'].fillna(0.9)

# 确保数值类型
df_model['w_Co'] = pd.to_numeric(df_model['w_Co'], errors='coerce').fillna(1.0)
df_model['r'] = pd.to_numeric(df_model['r'], errors='coerce').fillna(1.0)
df_model['C_eth'] = pd.to_numeric(df_model['C_eth'], errors='coerce').fillna(0.9)
df_model['type'] = pd.to_numeric(df_model['type'], errors='coerce').fillna(0)

# 交互项
df_model['T_wCo'] = df_model['T'] * df_model['w_Co']
df_model['T_r'] = df_model['T'] * df_model['r']

# 转化率模型
X_features = ['T', 'w_Co', 'r', 'C_eth', 'type', 'T_wCo', 'T_r']
X_data = df_model[X_features].values
y_X = df_model['X'].values
y_S = df_model['S'].values

# LASSO 变量选择
scaler = StandardScaler()
X_scaled = scaler.fit_transform(X_data)

lasso_X = LassoCV(cv=5, random_state=42, max_iter=10000)
lasso_X.fit(X_scaled, y_X)
lasso_S = LassoCV(cv=5, random_state=42, max_iter=10000)
lasso_S.fit(X_scaled, y_S)

# 选择非零系数的特征
selected_X = [X_features[i] for i, coef in enumerate(lasso_X.coef_) if abs(coef) > 1e-6]
selected_S = [X_features[i] for i, coef in enumerate(lasso_S.coef_) if abs(coef) > 1e-6]

print(f"转化率模型选择的特征: {selected_X}")
print(f"选择性模型选择的特征: {selected_S}")

# 使用 statsmodels 进行 OLS 回归
# 转化率模型
X_ols = sm.add_constant(X_data)
model_X = sm.OLS(y_X, X_ols).fit()
model_S = sm.OLS(y_S, X_ols).fit()

print("\n转化率模型摘要:")
print(model_X.summary())
print("\n选择性模型摘要:")
print(model_S.summary())

# 预测并截断到 [0, 100]
y_X_pred = np.clip(model_X.predict(X_ols), 0, 100)
y_S_pred = np.clip(model_S.predict(X_ols), 0, 100)

r2_X_global = r2_score(y_X, y_X_pred)
r2_S_global = r2_score(y_S, y_S_pred)
rmse_X_global = np.sqrt(mean_squared_error(y_X, y_X_pred))
rmse_S_global = np.sqrt(mean_squared_error(y_S, y_S_pred))

print(f"\n全局模型性能:")
print(f"  转化率 R2: {r2_X_global:.4f}, RMSE: {rmse_X_global:.4f}")
print(f"  选择性 R2: {r2_S_global:.4f}, RMSE: {rmse_S_global:.4f}")

# ANOVA 分析
formula_X = 'X ~ T + w_Co + r + C_eth + type + T:w_Co + T:r'
formula_S = 'S ~ T + w_Co + r + C_eth + type + T:w_Co + T:r'

try:
    model_anova_X = ols(formula_X, data=df_model).fit()
    anova_table_X = sm.stats.anova_lm(model_anova_X, typ=2)
    print("\n转化率 ANOVA:")
    print(anova_table_X)
except Exception as e:
    print(f"ANOVA 转化率模型失败: {e}")
    anova_table_X = pd.DataFrame()

try:
    model_anova_S = ols(formula_S, data=df_model).fit()
    anova_table_S = sm.stats.anova_lm(model_anova_S, typ=2)
    print("\n选择性 ANOVA:")
    print(anova_table_S)
except Exception as e:
    print(f"ANOVA 选择性模型失败: {e}")
    anova_table_S = pd.DataFrame()

# ========== 子问题3：工艺条件优化 ==========
print("\n" + "=" * 60)
print("子问题3:工艺条件优化")
print("=" * 60)

# 定义目标函数
def predict_Y(T, w_Co, r, C_eth, type_val, model_X_coefs, model_S_coefs):
    """预测收率"""
    # 构建特征向量
    features = np.array([1, T, w_Co, r, C_eth, type_val, T*w_Co, T*r])
    X_pred = np.clip(np.dot(features, model_X_coefs), 0, 100)
    S_pred = np.clip(np.dot(features, model_S_coefs), 0, 100)
    Y_pred = X_pred * S_pred / 100
    return Y_pred, X_pred, S_pred

# 获取模型系数
model_X_coefs = model_X.params.values
model_S_coefs = model_S.params.values

# 遗传算法优化
def genetic_algorithm(constraint_temp=None, pop_size=100, n_generations=200, mutation_rate=0.1, elite_rate=0.02):
    """遗传算法优化"""
    # 参数范围
    T_range = [250, 450] if constraint_temp is None else [250, 349]
    w_Co_values = [1, 2, 5]
    r_range = [0.5, 2.0]
    C_eth_range = [0.3, 2.1]
    type_values = [0, 1]
    
    n_elite = max(2, int(pop_size * elite_rate))
    
    # 初始化种群
    population = []
    for _ in range(pop_size):
        T = random.uniform(*T_range)
        w_Co = random.choice(w_Co_values)
        r = random.uniform(*r_range)
        C_eth = random.uniform(*C_eth_range)
        type_val = random.choice(type_values)
        population.append([T, w_Co, r, C_eth, type_val])
    
    best_solution = None
    best_fitness = -np.inf
    fitness_history = []
    
    for gen in range(n_generations):
        # 计算适应度
        fitness = []
        for ind in population:
            T, w_Co, r, C_eth, type_val = ind
            Y_pred, _, _ = predict_Y(T, w_Co, r, C_eth, type_val, model_X_coefs, model_S_coefs)
            fitness.append(Y_pred)
        
        fitness = np.array(fitness)
        
        # 更新最优
        if np.max(fitness) > best_fitness:
            best_fitness = np.max(fitness)
            best_solution = population[np.argmax(fitness)].copy()
        
        fitness_history.append(best_fitness)
        
        # 选择（锦标赛）
        selected = []
        for _ in range(pop_size):
            idx1, idx2 = random.sample(range(pop_size), 2)
            if fitness[idx1] > fitness[idx2]:
                selected.append(population[idx1].copy())
            else:
                selected.append(population[idx2].copy())
        
        # 精英保留
        elite_indices = np.argsort(fitness)[-n_elite:]
        elites = [population[i].copy() for i in elite_indices]
        
        # 交叉和变异
        new_population = []
        for i in range(0, pop_size - n_elite, 2):
            parent1 = selected[i]
            parent2 = selected[min(i+1, pop_size-1)]
            
            # 单点交叉
            if random.random() < 0.8:
                crossover_point = random.randint(0, 4)
                child1 = parent1[:crossover_point] + parent2[crossover_point:]
                child2 = parent2[:crossover_point] + parent1[crossover_point:]
            else:
                child1 = parent1.copy()
                child2 = parent2.copy()
            
            # 变异
            for child in [child1, child2]:
                if random.random() < mutation_rate:
                    mutate_idx = random.randint(0, 4)
                    if mutate_idx == 0:  # T
                        child[0] = random.uniform(*T_range)
                    elif mutate_idx == 1:  # w_Co
                        child[1] = random.choice(w_Co_values)
                    elif mutate_idx == 2:  # r
                        child[2] = random.uniform(*r_range)
                    elif mutate_idx == 3:  # C_eth
                        child[3] = random.uniform(*C_eth_range)
                    elif mutate_idx == 4:  # type
                        child[4] = random.choice(type_values)
            
            new_population.append(child1)
            new_population.append(child2)
        
        new_population = new_population[:pop_size - n_elite]
        new_population.extend(elites)
        population = new_population
    
    return best_solution, best_fitness, fitness_history

# 无温度限制优化
print("\n无温度限制优化...")
best_no_limit, fitness_no_limit, history_no_limit = genetic_algorithm(constraint_temp=None, n_generations=200)
Y_no_limit, X_no_limit, S_no_limit = predict_Y(*best_no_limit, model_X_coefs, model_S_coefs)
print(f"最优解: T={best_no_limit[0]:.1f}℃, w_Co={best_no_limit[1]:.0f}wt%, r={best_no_limit[2]:.3f}, C_eth={best_no_limit[3]:.3f}ml/min, type={int(best_no_limit[4])}")
print(f"预测: X={X_no_limit:.2f}%, S={S_no_limit:.2f}%, Y={Y_no_limit:.2f}%")

# 温度低于350℃优化
print("\n温度低于350℃优化...")
best_limited, fitness_limited, history_limited = genetic_algorithm(constraint_temp='below_350', n_generations=200)
Y_limited, X_limited, S_limited = predict_Y(*best_limited, model_X_coefs, model_S_coefs)
print(f"最优解: T={best_limited[0]:.1f}℃, w_Co={best_limited[1]:.0f}wt%, r={best_limited[2]:.3f}, C_eth={best_limited[3]:.3f}ml/min, type={int(best_limited[4])}")
print(f"预测: X={X_limited:.2f}%, S={S_limited:.2f}%, Y={Y_limited:.2f}%")

# 优化收敛图
fig, ax = plt.subplots(constrained_layout=True)
ax.plot(history_no_limit, label='无温度限制')
ax.plot(history_limited, label='温度<350℃')
ax.set_xlabel('迭代次数')
ax.set_ylabel('最优收率 / %')
ax.set_title('遗传算法收敛曲线')
ax.legend()
fig.savefig('figures/fig_3_optimization_convergence.png')
plt.close(fig)
print("[OK] 优化收敛图已保存")

# ========== 子问题4：实验设计改进 ==========
print("\n" + "=" * 60)
print("子问题4:实验设计改进")
print("=" * 60)

# Bootstrap 不确定性估计
def bootstrap_variance(X_ols_values, y_values, n_bootstrap=500):
    """Bootstrap 估计预测方差"""
    n = len(y_values)
    predictions = []
    
    for _ in range(n_bootstrap):
        indices = np.random.choice(n, n, replace=True)
        X_boot = X_ols_values[indices]
        y_boot = y_values[indices]
        
        try:
            model = sm.OLS(y_boot, X_boot).fit()
            pred = model.predict(X_ols_values)
            predictions.append(pred)
        except:
            continue
    
    if len(predictions) > 0:
        predictions = np.array(predictions)
        var_pred = np.var(predictions, axis=0)
        return var_pred
    else:
        return np.zeros(n)

# 候选实验点
candidate_points = [
    {'T': 325, 'w_Co': 2, 'r': 1.5, 'C_eth': 1.5, 'type': 1, 'purpose': '填补325℃空白'},
    {'T': 440, 'w_Co': 1, 'r': 1.0, 'C_eth': 0.9, 'type': 1, 'purpose': '探索450℃附近高温区'},
    {'T': 340, 'w_Co': 2, 'r': 1.8, 'C_eth': 0.6, 'type': 0, 'purpose': '验证无约束最优解附近'},
    {'T': 300, 'w_Co': 2.5, 'r': 1.2, 'C_eth': 1.0, 'type': 1, 'purpose': '探索Co负载量中间值'},
    {'T': 275, 'w_Co': 1, 'r': 0.5, 'C_eth': 1.8, 'type': 0, 'purpose': '探索低装料比区域'},
]

# 计算每个候选点的预测方差
X_ols_mat = X_ols.copy()
var_X = bootstrap_variance(X_ols_mat, y_X, n_bootstrap=200)
var_S = bootstrap_variance(X_ols_mat, y_S, n_bootstrap=200)

print("\n候选实验点评估:")
for i, cp in enumerate(candidate_points):
    features = np.array([1, cp['T'], cp['w_Co'], cp['r'], cp['C_eth'], cp['type'],
                         cp['T']*cp['w_Co'], cp['T']*cp['r']])
    features = features.reshape(1, -1)
    
    # 找到最近的数据点
    distances = np.sqrt(np.sum((X_ols_mat[:, 1:] - features[:, 1:])**2, axis=1))
    nearest_idx = np.argmin(distances)
    
    var_X_point = var_X[nearest_idx] if nearest_idx < len(var_X) else np.nan
    var_S_point = var_S[nearest_idx] if nearest_idx < len(var_S) else np.nan
    
    Y_pred, X_pred, S_pred = predict_Y(cp['T'], cp['w_Co'], cp['r'], cp['C_eth'], cp['type'],
                                        model_X_coefs, model_S_coefs)
    
    print(f"\n点{i+1}: {cp['purpose']}")
    print(f"  预测: X={X_pred:.2f}%, S={S_pred:.2f}%, Y={Y_pred:.2f}%")
    print(f"  预测方差: X_var={var_X_point:.4f}, S_var={var_S_point:.4f}")

# 计算 D-最优准则
def d_optimality(candidate_set, X_current):
    """计算 D-最优准则值"""
    f_current = np.hstack([np.ones((X_current.shape[0], 1)), X_current])
    M_current = f_current.T @ f_current
    
    M_new = M_current.copy()
    for cp in candidate_set:
        f_new = np.array([1, cp['T'], cp['w_Co'], cp['r'], cp['C_eth'], cp['type'],
                          cp['T']*cp['w_Co'], cp['T']*cp['r']])
        M_new += np.outer(f_new, f_new)
    
    try:
        det_M = np.linalg.det(M_new)
        return det_M
    except:
        return 0

d_opt_value = d_optimality(candidate_points, X_data)
print(f"\nD-最优准则值: {d_opt_value:.4e}")

# ========== 灵敏度分析 ==========
print("\n" + "=" * 60)
print("灵敏度分析")
print("=" * 60)

sensitivity_results = {
    "baseline": {
        "objective": float(Y_no_limit),
        "objective_name": "C4烯烃收率"
    },
    "experiments": []
}

# 参数1: 温度扰动
for delta_pct in [-20, -10, 10, 20]:
    T_new = best_no_limit[0] * (1 + delta_pct/100)
    T_new = np.clip(T_new, 250, 450)
    Y_new, _, _ = predict_Y(T_new, best_no_limit[1], best_no_limit[2], best_no_limit[3], best_no_limit[4],
                            model_X_coefs, model_S_coefs)
    change_pct = (Y_new - Y_no_limit) / Y_no_limit * 100
    sensitivity_results["experiments"].append({
        "param": "T",
        "delta_pct": delta_pct,
        "objective": float(Y_new),
        "change_pct": float(change_pct)
    })

# 参数2: Co负载量扰动
for delta_pct in [-20, -10, 10, 20]:
    w_Co_new = best_no_limit[1] * (1 + delta_pct/100)
    # 离散化到最近的可能值
    possible_values = np.array([1, 2, 5])
    w_Co_new = possible_values[np.argmin(np.abs(possible_values - w_Co_new))]
    Y_new, _, _ = predict_Y(best_no_limit[0], w_Co_new, best_no_limit[2], best_no_limit[3], best_no_limit[4],
                            model_X_coefs, model_S_coefs)
    change_pct = (Y_new - Y_no_limit) / Y_no_limit * 100
    sensitivity_results["experiments"].append({
        "param": "w_Co",
        "delta_pct": delta_pct,
        "objective": float(Y_new),
        "change_pct": float(change_pct)
    })

# 参数3: 装料比扰动
for delta_pct in [-20, -10, 10, 20]:
    r_new = best_no_limit[2] * (1 + delta_pct/100)
    r_new = np.clip(r_new, 0.5, 2.0)
    Y_new, _, _ = predict_Y(best_no_limit[0], best_no_limit[1], r_new, best_no_limit[3], best_no_limit[4],
                            model_X_coefs, model_S_coefs)
    change_pct = (Y_new - Y_no_limit) / Y_no_limit * 100
    sensitivity_results["experiments"].append({
        "param": "r",
        "delta_pct": delta_pct,
        "objective": float(Y_new),
        "change_pct": float(change_pct)
    })

# 参数4: 乙醇浓度扰动
for delta_pct in [-20, -10, 10, 20]:
    C_eth_new = best_no_limit[3] * (1 + delta_pct/100)
    C_eth_new = np.clip(C_eth_new, 0.3, 2.1)
    Y_new, _, _ = predict_Y(best_no_limit[0], best_no_limit[1], best_no_limit[2], C_eth_new, best_no_limit[4],
                            model_X_coefs, model_S_coefs)
    change_pct = (Y_new - Y_no_limit) / Y_no_limit * 100
    sensitivity_results["experiments"].append({
        "param": "C_eth",
        "delta_pct": delta_pct,
        "objective": float(Y_new),
        "change_pct": float(change_pct)
    })

# 保存灵敏度结果
with open("sensitivity.json", "w", encoding="utf-8") as f:
    json.dump(sensitivity_results, f, ensure_ascii=False, indent=2)
print("[OK] sensitivity.json 已保存")

# 绘制灵敏度图
for param_name in ['T', 'w_Co', 'r', 'C_eth']:
    fig, ax = plt.subplots(constrained_layout=True)
    param_data = [exp for exp in sensitivity_results["experiments"] if exp["param"] == param_name]
    deltas = [exp["delta_pct"] for exp in param_data]
    objectives = [exp["objective"] for exp in param_data]
    
    ax.plot(deltas, objectives, 'o-', label=f'{param_name} 扰动')
    ax.axhline(y=Y_no_limit, color='gray', linestyle='--', alpha=0.7, label=f'基准值 ({Y_no_limit:.2f}%)')
    ax.set_xlabel('扰动幅度 / %')
    ax.set_ylabel('C4烯烃收率 / %')
    ax.set_title(f'灵敏度分析 - {param_name}')
    ax.legend()
    fig.savefig(f'figures/sensitivity_{param_name}.png')
    plt.close(fig)
    print(f"[OK] 灵敏度图 {param_name} 已保存")

# ========== 保存结果文件 ==========
print("\n" + "=" * 60)
print("保存结果文件")
print("=" * 60)

# result1.xlsx
with pd.ExcelWriter('result1.xlsx') as writer:
    df_q1.to_excel(writer, sheet_name='拟合参数', index=False)
    
    # 时序结果
    time_results = pd.DataFrame([{
        'X0': X0_est, 'k': k_est, 'Xinf': Xinf_est,
        'r2_time': r2_time, 'rmse_time': rmse_time,
        'S_mean': S_mean, 'S_std': S_std, 'S_min': S_min, 'S_max': S_max
    }])
    time_results.to_excel(writer, sheet_name='时序分析', index=False)
print("[OK] result1.xlsx 已保存")

# result2.xlsx
with pd.ExcelWriter('result2.xlsx') as writer:
    # 回归系数
    coef_X = pd.DataFrame({
        '特征': ['常数'] + X_features,
        '系数_X': model_X.params.values,
        'p值_X': model_X.pvalues.values,
        '系数_S': model_S.params.values,
        'p值_S': model_S.pvalues.values
    })
    coef_X.to_excel(writer, sheet_name='回归系数', index=False)
    
    # 模型性能
    perf = pd.DataFrame([{
        '模型': '转化率', 'R2': r2_X_global, 'RMSE': rmse_X_global,
        '调整R2': model_X.rsquared_adj, 'AIC': model_X.aic
    }, {
        '模型': '选择性', 'R2': r2_S_global, 'RMSE': rmse_S_global,
        '调整R2': model_S.rsquared_adj, 'AIC': model_S.aic
    }])
    perf.to_excel(writer, sheet_name='模型性能', index=False)
    
    # ANOVA
    if not anova_table_X.empty:
        anova_table_X.to_excel(writer, sheet_name='ANOVA_X')
    if not anova_table_S.empty:
        anova_table_S.to_excel(writer, sheet_name='ANOVA_S')
print("[OK] result2.xlsx 已保存")

# result3.xlsx
with pd.ExcelWriter('result3.xlsx') as writer:
    result3_data = pd.DataFrame([{
        '条件': '无温度限制',
        '温度(℃)': best_no_limit[0],
        'Co负载量(wt%)': best_no_limit[1],
        '装料比': best_no_limit[2],
        '乙醇浓度(ml/min)': best_no_limit[3],
        '催化剂类型': 'A' if best_no_limit[4] == 1 else 'B',
        '预测转化率(%)': X_no_limit,
        '预测选择性(%)': S_no_limit,
        '预测收率(%)': Y_no_limit
    }, {
        '条件': '温度低于350℃',
        '温度(℃)': best_limited[0],
        'Co负载量(wt%)': best_limited[1],
        '装料比': best_limited[2],
        '乙醇浓度(ml/min)': best_limited[3],
        '催化剂类型': 'A' if best_limited[4] == 1 else 'B',
        '预测转化率(%)': X_limited,
        '预测选择性(%)': S_limited,
        '预测收率(%)': Y_limited
    }])
    result3_data.to_excel(writer, sheet_name='优化结果', index=False)
print("[OK] result3.xlsx 已保存")

# ========== 保存 results.json ==========
print("\n" + "=" * 60)
print("保存 results.json")
print("=" * 60)

results = [
    # EDA 统计
    {"name": "q0_原始行数", "value": original_rows, "unit": "行", "desc": "附件1原始数据行数"},
    {"name": "q0_有效行数", "value": valid_rows, "unit": "行", "desc": "数据清洗后有效行数"},
    {"name": "q0_缺失编号数", "value": int(missing_cat), "unit": "个", "desc": "催化剂编号缺失数量"},
    {"name": "q0_缺失率", "value": round(missing_cat_pct, 2), "unit": "%", "desc": "催化剂编号缺失率"},
    {"name": "q0_转化率异常值数", "value": outliers_X, "unit": "个", "desc": "转化率异常值数量"},
    {"name": "q0_转化率异常值阈值", "value": round(upper_X, 2), "unit": "%", "desc": "转化率IQR上界"},
    {"name": "q0_选择性异常值数", "value": outliers_S, "unit": "个", "desc": "选择性异常值数量"},
    {"name": "q0_选择性异常值阈值", "value": round(upper_S, 2), "unit": "%", "desc": "选择性IQR上界"},
    {"name": "q0_温度转化率相关系数", "value": round(corr_T_X, 4), "unit": "", "desc": "温度与转化率Pearson相关系数"},
    {"name": "q0_温度选择性相关系数", "value": round(corr_T_S, 4), "unit": "", "desc": "温度与选择性Pearson相关系数"},
    {"name": "q0_转化率选择性相关系数", "value": round(corr_X_S, 4), "unit": "", "desc": "转化率与选择性Pearson相关系数"},
    {"name": "q0_收率均值", "value": round(Y_mean, 4), "unit": "%", "desc": "C4烯烃收率均值"},
    {"name": "q0_收率中位数", "value": round(Y_median, 4), "unit": "%", "desc": "C4烯烃收率中位数"},
    {"name": "q0_收率最大值", "value": round(Y_max, 4), "unit": "%", "desc": "C4烯烃收率最大值"},
    {"name": "q0_收率最小值", "value": round(Y_min, 4), "unit": "%", "desc": "C4烯烃收率最小值"},
    
    # 子问题1
    {"name": "q1_催化剂数量", "value": len(df_q1), "unit": "种", "desc": "拟合的催化剂种类数"},
    {"name": "q1_转化率R2均值", "value": round(df_q1['r2_X'].mean(), 4), "unit": "", "desc": "转化率Sigmoid拟合平均R2"},
    {"name": "q1_选择性R2均值", "value": round(df_q1['r2_S'].mean(), 4), "unit": "", "desc": "选择性Sigmoid拟合平均R2"},
    {"name": "q1_时序X0", "value": round(X0_est, 4), "unit": "%", "desc": "时序模型初始转化率"},
    {"name": "q1_时序k", "value": round(k_est, 6), "unit": "min^-1", "desc": "时序模型衰减常数"},
    {"name": "q1_时序Xinf", "value": round(Xinf_est, 4), "unit": "%", "desc": "时序模型稳态转化率"},
    {"name": "q1_时序R2", "value": round(r2_time, 4), "unit": "", "desc": "时序模型拟合决定系数"},
    {"name": "q1_选择性均值", "value": round(S_mean, 4), "unit": "%", "desc": "时序数据C4烯烃选择性均值"},
    
    # 子问题2
    {"name": "q2_全局X_R2", "value": round(r2_X_global, 4), "unit": "", "desc": "全局转化率模型R2"},
    {"name": "q2_全局X_RMSE", "value": round(rmse_X_global, 4), "unit": "%", "desc": "全局转化率模型RMSE"},
    {"name": "q2_全局S_R2", "value": round(r2_S_global, 4), "unit": "", "desc": "全局选择性模型R2"},
    {"name": "q2_全局S_RMSE", "value": round(rmse_S_global, 4), "unit": "%", "desc": "全局选择性模型RMSE"},
    {"name": "q2_X_调整R2", "value": round(model_X.rsquared_adj, 4), "unit": "", "desc": "转化率模型调整R2"},
    {"name": "q2_S_调整R2", "value": round(model_S.rsquared_adj, 4), "unit": "", "desc": "选择性模型调整R2"},
    {"name": "q2_X_AIC", "value": round(model_X.aic, 2), "unit": "", "desc": "转化率模型AIC"},
    {"name": "q2_S_AIC", "value": round(model_S.aic, 2), "unit": "", "desc": "选择性模型AIC"},
    
    # 子问题3
    {"name": "q3_无限制最优温度", "value": round(best_no_limit[0], 1), "unit": "℃", "desc": "无温度限制时最优温度"},
    {"name": "q3_无限制最优Co负载量", "value": int(best_no_limit[1]), "unit": "wt%", "desc": "无温度限制时最优Co负载量"},
    {"name": "q3_无限制最优装料比", "value": round(best_no_limit[2], 3), "unit": "", "desc": "无温度限制时最优装料比"},
    {"name": "q3_无限制最优乙醇浓度", "value": round(best_no_limit[3], 3), "unit": "ml/min", "desc": "无温度限制时最优乙醇浓度"},
    {"name": "q3_无限制最优催化剂类型", "value": "A" if best_no_limit[4] == 1 else "B", "unit": "", "desc": "无温度限制时最优催化剂类型"},
    {"name": "q3_无限制预测收率", "value": round(Y_no_limit, 2), "unit": "%", "desc": "无温度限制时最优预测收率"},
    {"name": "q3_有限制最优温度", "value": round(best_limited[0], 1), "unit": "℃", "desc": "温度<350℃时最优温度"},
    {"name": "q3_有限制最优Co负载量", "value": int(best_limited[1]), "unit": "wt%", "desc": "温度<350℃时最优Co负载量"},
    {"name": "q3_有限制最优装料比", "value": round(best_limited[2], 3), "unit": "", "desc": "温度<350℃时最优装料比"},
    {"name": "q3_有限制最优乙醇浓度", "value": round(best_limited[3], 3), "unit": "ml/min", "desc": "温度<350℃时最优乙醇浓度"},
    {"name": "q3_有限制最优催化剂类型", "value": "A" if best_limited[4] == 1 else "B", "unit": "", "desc": "温度<350℃时最优催化剂类型"},
    {"name": "q3_有限制预测收率", "value": round(Y_limited, 2), "unit": "%", "desc": "温度<350℃时最优预测收率"},
    
    # 子问题4
    {"name": "q4_D最优准则值", "value": round(d_opt_value, 4), "unit": "", "desc": "5个候选点的D-最优准则值"},
    {"name": "q4_候选点数", "value": len(candidate_points), "unit": "个", "desc": "建议的实验点数"},
]

with open("results.json", "w", encoding="utf-8") as f:
    json.dump(results, f, ensure_ascii=False, indent=2)
print("[OK] results.json 已保存")

print("\n" + "=" * 60)
print("所有求解完成!")
print("=" * 60)
print(f"生成文件:")
print(f"  - result1.xlsx (问题1结果)")
print(f"  - result2.xlsx (问题2结果)")
print(f"  - result3.xlsx (问题3结果)")
print(f"  - results.json (关键数值汇总)")
print(f"  - sensitivity.json (灵敏度分析)")
print(f"  - figures/ (图表)")