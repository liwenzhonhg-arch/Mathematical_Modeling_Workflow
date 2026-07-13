# solution.py
import sys
sys.stdout.reconfigure(encoding='utf-8')

import numpy as np
import pandas as pd
import json
import os

# ============================================================
# 绘图设置 (publication preset)
# ============================================================
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

# ============================================================
# 全局常量
# ============================================================
THETA_DEG = 120.0          # 开角 (度)
THETA = np.deg2rad(THETA_DEG)  # 开角 (弧度)

# ============================================================
# 子问题 1: 二维平面覆盖宽度与重叠率
# ============================================================
def coverage_width(D, alpha_deg):
    """
    计算覆盖宽度 W (沿坡面方向)
    D: 换能器正下方水深 (m)
    alpha_deg: 海底坡度 (度)
    返回 W (m)
    """
    alpha = np.deg2rad(alpha_deg)
    num = D * np.sin(THETA) * np.cos(alpha)
    den = np.cos(THETA/2 + alpha) * np.cos(THETA/2 - alpha)
    if abs(den) < 1e-12:
        return np.inf
    return float(num / den)

def overlap_rate(d, W1, W2, mode='avg'):
    """
    计算重叠率 eta
    d: 测线间距 (m)
    W1, W2: 两条测线的覆盖宽度 (m)
    mode: 'avg' 用平均宽度, 'min' 用较小宽度
    """
    if mode == 'avg':
        W_ref = (W1 + W2) / 2
    else:
        W_ref = min(W1, W2)
    if W_ref <= 0:
        return 0.0
    return 1.0 - d / W_ref

# ============================================================
# 子问题 2: 三维空间视坡度模型
# ============================================================
def apparent_slope(alpha_deg, beta_deg):
    """
    计算视坡度 alpha'
    alpha_deg: 实际坡度 (度)
    beta_deg: 测线方向与坡面法向水平投影的夹角 (度)
    """
    alpha = np.deg2rad(alpha_deg)
    beta = np.deg2rad(beta_deg)
    tan_alpha_prime = np.tan(alpha) * np.cos(beta)
    alpha_prime_rad = np.arctan(tan_alpha_prime)
    return float(np.rad2deg(alpha_prime_rad))

def coverage_width_3d(D, alpha_deg, beta_deg):
    """
    三维覆盖宽度: 先计算视坡度, 再用二维公式
    """
    alpha_prime = apparent_slope(alpha_deg, beta_deg)
    return coverage_width(D, alpha_prime)

# ============================================================
# 子问题 3: 恒定坡度海域测线优化 (贪心算法)
# ============================================================
def solve_q3():
    print("=" * 60)
    print("子问题 3: 恒定坡度海域测线优化设计")
    print("=" * 60)

    # 题面参数：东西宽 4 海里，南北长 2 海里，中心水深 110 m，西深东浅。
    alpha_deg = 1.5
    Lx = 4.0
    Ly = 2.0
    nm_to_m = 1852.0
    x_w = 0.0
    x_e = Lx
    center_x = Lx / 2
    D_center = 110.0
    slope_tan = np.tan(np.deg2rad(alpha_deg))

    def depth_at_x(x_nm):
        return D_center + (center_x - x_nm) * slope_tan * nm_to_m

    # 为追求最短总长度，目标重叠率取下限附近；留 0.5% 安全余量避免数值舍入后低于 10%。
    eta_target = 0.105
    eta_min = 0.10
    eta_max = 0.20

    # 1. 从西侧深水区开始，第一条测线恰好覆盖西边界。
    def f_x1(x):
        D = depth_at_x(x)
        W = coverage_width(D, alpha_deg)
        return x - W / 2 / nm_to_m - x_w

    lo, hi = 0.0, 0.5
    for _ in range(100):
        mid = (lo + hi) / 2
        if f_x1(mid) <= 0:
            lo = mid
        else:
            hi = mid
    x1 = (lo + hi) / 2
    x_positions = [x1]

    # 2. 向东逐条推进，使相邻平均重叠率保持在 10.5%。
    for i in range(200):
        x_i = x_positions[-1]
        D_i = depth_at_x(x_i)
        W_i = coverage_width(D_i, alpha_deg)

        def f_next(x_next):
            D_next = depth_at_x(x_next)
            W_next = coverage_width(D_next, alpha_deg)
            d_m = (x_next - x_i) * nm_to_m
            eta = 1.0 - d_m / ((W_i + W_next) / 2.0)
            return eta - eta_target

        lo = x_i + 0.0001
        hi = x_e
        for _ in range(100):
            mid = (lo + hi) / 2
            val = f_next(mid)
            if val > 0:
                lo = mid
            else:
                hi = mid
        x_next = (lo + hi) / 2

        D_next = depth_at_x(x_next)
        W_next = coverage_width(D_next, alpha_deg)
        east_cover = x_next + W_next / 2 / nm_to_m
        if east_cover >= x_e:
            x_positions.append(x_next)
            break

        x_positions.append(x_next)

    N = len(x_positions)
    # 计算实际重叠率
    eta_list = []
    for i in range(N - 1):
        x_i = x_positions[i]
        x_next = x_positions[i+1]
        D_i = depth_at_x(x_i)
        D_next = depth_at_x(x_next)
        W_i = coverage_width(D_i, alpha_deg)
        W_next = coverage_width(D_next, alpha_deg)
        d_m = (x_next - x_i) * nm_to_m
        eta = overlap_rate(d_m, W_i, W_next, mode='avg')
        eta_list.append(eta)

    # 输出结果
    print(f"\n测线数量 N = {N}")
    print(f"\n各测线位置 (海里):")
    for i, x in enumerate(x_positions):
        D = depth_at_x(x)
        W = coverage_width(D, alpha_deg)
        print(f"  测线 {i+1}: x = {x:.4f} 海里, 水深 = {D:.2f} m, 覆盖宽度 = {W:.2f} m")

    print(f"\n相邻测线重叠率:")
    for i, eta in enumerate(eta_list):
        status = "[OK]" if eta_min <= eta <= eta_max else "[X]"
        print(f"  测线 {i+1}-{i+2}: eta = {eta:.4f} ({eta*100:.2f}%) {status}")

    total_length_nm = N * Ly
    total_length_m = total_length_nm * nm_to_m
    print(f"\n测线总长度: {total_length_nm:.4f} 海里 = {total_length_m:.2f} m")

    # 检查全覆盖
    D1 = depth_at_x(x_positions[0])
    W1 = coverage_width(D1, alpha_deg)
    west_cover = x_positions[0] - W1 / 2 / nm_to_m
    D_last = depth_at_x(x_positions[-1])
    W_last = coverage_width(D_last, alpha_deg)
    east_cover = x_positions[-1] + W_last / 2 / nm_to_m
    print(f"\n西边界覆盖: {west_cover:.4f} 海里 (要求 <= 0)")
    print(f"东边界覆盖: {east_cover:.4f} 海里 (要求 >= {x_e})")

    q3_table = pd.DataFrame({
        "line_id": np.arange(1, N + 1),
        "x_nm": np.round(x_positions, 6),
        "depth_m": [round(depth_at_x(x), 4) for x in x_positions],
        "width_m": [round(coverage_width(depth_at_x(x), alpha_deg), 4) for x in x_positions],
        "overlap_with_previous": [None] + [round(v, 6) for v in eta_list],
    })
    q3_table.to_excel("result3.xlsx", index=False)

    # 绘图
    fig, ax = plt.subplots(constrained_layout=True)
    xs = np.linspace(0, Lx, 500)
    depths = [depth_at_x(x) for x in xs]
    ax.plot(xs, depths, 'k-', label='水深剖面')
    for x in x_positions:
        ax.axvline(x, color='gray', linestyle=':', alpha=0.7)
    ax.set_xlabel('东西方向 / 海里')
    ax.set_ylabel('水深 / m')
    ax.set_title('子问题3: 测线布设方案')
    ax.legend()
    fig.savefig('figures/fig_q3_transect_layout.png', dpi=300)
    plt.close(fig)

    # 将所有numpy类型转换为Python原生类型
    q3_results = {
        "N": int(N),
        "total_length_nm": float(round(total_length_nm, 4)),
        "total_length_m": float(round(total_length_m, 2)),
        "eta_min": float(round(min(eta_list), 4)),
        "eta_max": float(round(max(eta_list), 4)),
        "west_cover": float(round(west_cover, 4)),
        "east_cover": float(round(east_cover, 4)),
        "target_overlap": float(eta_target),
    }
    print(f"\n子问题3 完成。")
    return q3_results

# ============================================================
# 子问题 4: 基于真实水深数据的测线优化设计
# ============================================================
def solve_q4():
    print("\n" + "=" * 60)
    print("子问题 4: 基于真实水深数据的测线优化设计")
    print("=" * 60)

    # 加载数据
    data_path = 'data/raw/depth_data.csv'
    df = pd.read_csv(data_path, header=0)
    y_coords = df.iloc[:, 0].values
    x_coords = df.columns[1:].values.astype(float)
    depth_matrix = df.iloc[:, 1:].values

    nm_to_m = 1852.0
    nx = len(x_coords)
    ny = len(y_coords)

    print(f"数据网格: {ny} x {nx}")
    print(f"东西范围: {x_coords[0]:.2f} ~ {x_coords[-1]:.2f} 海里")
    print(f"南北范围: {y_coords[0]:.2f} ~ {y_coords[-1]:.2f} 海里")
    print(f"水深范围: {depth_matrix.min():.2f} ~ {depth_matrix.max():.2f} m")

    X, Y = np.meshgrid(x_coords, y_coords)
    half_width_nm = depth_matrix * np.tan(THETA / 2) / nm_to_m

    def evaluate_parallel(orientation, n_lines):
        """用逐网格覆盖校验评价等间距平行测线。"""
        if orientation == "NS":
            positions = np.linspace(float(x_coords.min()), float(x_coords.max()), n_lines)
            distances = [np.abs(X - pos) for pos in positions]
            line_length_m = (float(y_coords.max()) - float(y_coords.min())) * nm_to_m
            profile_widths = [
                2 * float(depth_matrix[:, np.argmin(np.abs(x_coords - pos))].mean()) * np.tan(THETA / 2)
                for pos in positions
            ]
            psi_deg = 0
        else:
            positions = np.linspace(float(y_coords.min()), float(y_coords.max()), n_lines)
            distances = [np.abs(Y - pos) for pos in positions]
            line_length_m = (float(x_coords.max()) - float(x_coords.min())) * nm_to_m
            profile_widths = [
                2 * float(depth_matrix[np.argmin(np.abs(y_coords - pos)), :].mean()) * np.tan(THETA / 2)
                for pos in positions
            ]
            psi_deg = 90

        covered = np.zeros((ny, nx), dtype=bool)
        coverage_count = np.zeros((ny, nx), dtype=np.int16)
        for dist in distances:
            mask = dist <= half_width_nm
            covered |= mask
            coverage_count += mask.astype(np.int16)

        miss_rate = float((~covered).sum()) / float(nx * ny) * 100.0
        total_length = n_lines * line_length_m

        eta_list = []
        over20_length = 0.0
        spacing_m = abs(positions[1] - positions[0]) * nm_to_m if n_lines > 1 else 0.0
        for i in range(n_lines - 1):
            w_ref = (profile_widths[i] + profile_widths[i + 1]) / 2
            eta = 1.0 - spacing_m / w_ref if w_ref > 0 else 0.0
            eta_list.append(eta)
            if eta > 0.20:
                over20_length += line_length_m * (eta - 0.20)

        return {
            "orientation": orientation,
            "psi_deg": psi_deg,
            "n_lines": int(n_lines),
            "positions": positions,
            "covered": covered,
            "coverage_count": coverage_count,
            "total_length": float(total_length),
            "miss_rate": float(miss_rate),
            "over20_length": float(over20_length),
            "eta_min": float(min(eta_list)) if eta_list else 0.0,
            "eta_max": float(max(eta_list)) if eta_list else 0.0,
            "line_length_m": float(line_length_m),
        }

    def evaluate_ns_positions(positions, label):
        """评价给定南北向测线位置集合。"""
        positions = np.array(sorted(float(p) for p in positions), dtype=float)
        covered = np.zeros((ny, nx), dtype=bool)
        coverage_count = np.zeros((ny, nx), dtype=np.int16)
        for pos in positions:
            mask = np.abs(X - pos) <= half_width_nm
            covered |= mask
            coverage_count += mask.astype(np.int16)

        line_length_m = (float(y_coords.max()) - float(y_coords.min())) * nm_to_m
        total_length = len(positions) * line_length_m
        miss_rate = float((~covered).sum()) / float(nx * ny) * 100.0

        profile_widths = [
            2 * float(depth_matrix[:, np.argmin(np.abs(x_coords - pos))].mean()) * np.tan(THETA / 2)
            for pos in positions
        ]
        eta_list = []
        over20_length = 0.0
        for i in range(len(positions) - 1):
            spacing_m = abs(positions[i + 1] - positions[i]) * nm_to_m
            w_ref = (profile_widths[i] + profile_widths[i + 1]) / 2
            eta = 1.0 - spacing_m / w_ref if w_ref > 0 else 0.0
            eta_list.append(eta)
            if eta > 0.20:
                over20_length += line_length_m * (eta - 0.20)

        return {
            "orientation": label,
            "psi_deg": 0,
            "n_lines": int(len(positions)),
            "positions": positions,
            "covered": covered,
            "coverage_count": coverage_count,
            "total_length": float(total_length),
            "miss_rate": float(miss_rate),
            "over20_length": float(over20_length),
            "eta_min": float(min(eta_list)) if eta_list else 0.0,
            "eta_max": float(max(eta_list)) if eta_list else 0.0,
            "line_length_m": float(line_length_m),
        }

    def _line_segment(pos, psi_deg):
        """返回方向角 psi 下法向坐标为 pos 的测线在矩形海域内的线段端点和长度。"""
        psi = np.deg2rad(psi_deg)
        direction = np.array([np.sin(psi), np.cos(psi)], dtype=float)
        normal = np.array([np.cos(psi), -np.sin(psi)], dtype=float)
        base = normal * pos
        points = []
        xmin, xmax = float(x_coords.min()), float(x_coords.max())
        ymin, ymax = float(y_coords.min()), float(y_coords.max())

        if abs(direction[0]) > 1e-9:
            for x_edge in (xmin, xmax):
                t = (x_edge - base[0]) / direction[0]
                y_edge = base[1] + direction[1] * t
                if ymin - 1e-9 <= y_edge <= ymax + 1e-9:
                    points.append((float(x_edge), float(y_edge)))
        if abs(direction[1]) > 1e-9:
            for y_edge in (ymin, ymax):
                t = (y_edge - base[1]) / direction[1]
                x_edge = base[0] + direction[0] * t
                if xmin - 1e-9 <= x_edge <= xmax + 1e-9:
                    points.append((float(x_edge), float(y_edge)))

        unique = []
        for point in points:
            if not any(abs(point[0] - other[0]) < 1e-7 and abs(point[1] - other[1]) < 1e-7 for other in unique):
                unique.append(point)
        if len(unique) < 2:
            return None

        best = (unique[0], unique[1])
        best_len = 0.0
        for i in range(len(unique)):
            for j in range(i + 1, len(unique)):
                length_nm = ((unique[i][0] - unique[j][0]) ** 2 + (unique[i][1] - unique[j][1]) ** 2) ** 0.5
                if length_nm > best_len:
                    best_len = length_nm
                    best = (unique[i], unique[j])
        return {
            "start": best[0],
            "end": best[1],
            "length_m": float(best_len * nm_to_m),
        }

    def evaluate_angle_greedy(psi_deg, max_miss_pct=2.0, step_nm=0.02):
        """按方向角做覆盖增益贪心，用于问题四方向角粗采样。"""
        psi = np.deg2rad(psi_deg)
        normal = np.array([np.cos(psi), -np.sin(psi)], dtype=float)
        normal_coord = X * normal[0] + Y * normal[1]
        corners = np.array([
            [float(x_coords.min()), float(y_coords.min())],
            [float(x_coords.max()), float(y_coords.min())],
            [float(x_coords.max()), float(y_coords.max())],
            [float(x_coords.min()), float(y_coords.max())],
        ])
        s_values = corners @ normal
        candidate_positions = np.arange(float(s_values.min()), float(s_values.max()) + step_nm * 0.5, step_nm)

        line_candidates = []
        for pos in candidate_positions:
            segment = _line_segment(float(pos), psi_deg)
            if not segment:
                continue
            mask = np.abs(normal_coord - float(pos)) <= half_width_nm
            line_candidates.append((float(pos), mask, segment))

        covered = np.zeros((ny, nx), dtype=bool)
        coverage_count = np.zeros((ny, nx), dtype=np.int16)
        chosen = []
        total_length = 0.0
        while True:
            best = None
            best_gain = -1
            for pos, mask, segment in line_candidates:
                if any(abs(pos - item[0]) < 1e-9 for item in chosen):
                    continue
                gain = int(np.count_nonzero(mask & ~covered))
                if gain > best_gain:
                    best_gain = gain
                    best = (pos, mask, segment)
            if best is None or best_gain <= 0:
                break
            pos, mask, segment = best
            chosen.append((pos, segment))
            covered |= mask
            coverage_count += mask.astype(np.int16)
            total_length += segment["length_m"]
            miss_rate = float((~covered).sum()) / float(nx * ny) * 100.0
            if miss_rate <= max_miss_pct:
                break

        chosen = sorted(chosen, key=lambda item: item[0])
        profile_widths = []
        line_lengths = []
        for pos, segment in chosen:
            mask = np.abs(normal_coord - pos) <= half_width_nm
            mean_depth = float(depth_matrix[mask].mean()) if mask.any() else float(depth_matrix.mean())
            profile_widths.append(2 * mean_depth * np.tan(THETA / 2))
            line_lengths.append(segment["length_m"])

        eta_list = []
        over20_length = 0.0
        for i in range(len(chosen) - 1):
            spacing_m = abs(chosen[i + 1][0] - chosen[i][0]) * nm_to_m
            w_ref = (profile_widths[i] + profile_widths[i + 1]) / 2
            eta = 1.0 - spacing_m / w_ref if w_ref > 0 else 0.0
            eta_list.append(eta)
            if eta > 0.20:
                over20_length += ((line_lengths[i] + line_lengths[i + 1]) / 2) * (eta - 0.20)

        return {
            "orientation": f"angle_{int(psi_deg)}_miss_le_{str(max_miss_pct).replace('.', 'p')}",
            "psi_deg": int(psi_deg),
            "n_lines": int(len(chosen)),
            "positions": np.array([item[0] for item in chosen], dtype=float),
            "line_segments": [item[1] for item in chosen],
            "covered": covered,
            "coverage_count": coverage_count,
            "total_length": float(total_length),
            "miss_rate": float((~covered).sum()) / float(nx * ny) * 100.0,
            "over20_length": float(over20_length),
            "eta_min": float(min(eta_list)) if eta_list else 0.0,
            "eta_max": float(max(eta_list)) if eta_list else 0.0,
            "line_length_m": float(total_length / len(chosen)) if chosen else 0.0,
            "max_miss_pct": float(max_miss_pct),
        }

    def greedy_ns_adaptive(max_miss_pct=0.0, label="NS_adaptive"):
        """逐网格最大增益贪心，允许按漏测率阈值提前停止以形成 Pareto 候选。"""
        covered = np.zeros((ny, nx), dtype=bool)
        chosen = []
        masks = {float(pos): (np.abs(X - float(pos)) <= half_width_nm) for pos in x_coords}
        while True:
            best_pos = None
            best_gain = -1
            for pos, mask in masks.items():
                if pos in chosen:
                    continue
                gain = int(np.count_nonzero(mask & ~covered))
                if gain > best_gain:
                    best_gain = gain
                    best_pos = pos
            if best_pos is None or best_gain <= 0:
                break
            chosen.append(best_pos)
            covered |= masks[best_pos]
            miss_rate = float((~covered).sum()) / float(nx * ny) * 100.0
            if miss_rate <= max_miss_pct:
                break
        sol = evaluate_ns_positions(chosen, label)
        sol["max_miss_pct"] = float(max_miss_pct)
        return sol

    # 先满足覆盖质量，再在可行方案中取总长度较短者。
    candidates = []
    for orientation in ["NS", "EW"]:
        for n_lines in range(20, 181):
            sol = evaluate_parallel(orientation, n_lines)
            if sol["miss_rate"] <= 0.01:
                candidates.append(sol)
                print(
                    f"  {orientation}: N={n_lines}, T={sol['total_length']:.0f} m, "
                    f"M={sol['miss_rate']:.4f}%, O={sol['over20_length']:.2f} m"
                )
                break
    pareto_thresholds = [5.0, 3.0, 2.0, 1.0, 0.5, 0.1, 0.0]
    pareto_solutions = []
    for threshold in pareto_thresholds:
        label = f"NS_adaptive_miss_le_{str(threshold).replace('.', 'p')}"
        sol = greedy_ns_adaptive(threshold, label)
        pareto_solutions.append(sol)
        candidates.append(sol)
        print(
            f"  {sol['orientation']}: N={sol['n_lines']}, "
            f"T={sol['total_length']:.0f} m, M={sol['miss_rate']:.4f}%, "
            f"O={sol['over20_length']:.2f} m"
        )

    direction_solutions = []
    for psi_deg in range(0, 180, 15):
        sol = evaluate_angle_greedy(psi_deg, max_miss_pct=2.0)
        direction_solutions.append(sol)
        candidates.append(sol)
        print(
            f"  angle {psi_deg:3d}: N={sol['n_lines']}, "
            f"T={sol['total_length']:.0f} m, M={sol['miss_rate']:.4f}%, "
            f"O={sol['over20_length']:.2f} m"
        )

    if not candidates:
        raise RuntimeError("未找到漏测率 <= 0.01% 的保底测线方案")

    # 国赛问题四是多目标权衡题：在漏测率可控的前提下优先减少总长和超重叠。
    # 这里选取漏测率不超过 2% 的平衡方案，并保留 0 漏测方案作对照。
    feasible_balanced = [sol for sol in pareto_solutions + direction_solutions if sol["miss_rate"] <= 2.0]
    best_sol = min(
        feasible_balanced or pareto_solutions,
        key=lambda item: (item["total_length"], item["over20_length"], item["miss_rate"]),
    )
    best_psi = best_sol["psi_deg"]
    best_fit = (best_sol["total_length"], best_sol["miss_rate"], best_sol["over20_length"])

    print(f"\n候选最优方向: {best_sol['orientation']} (psi = {best_psi:.0f}度)")
    print(
        f"候选最优解: 测线数={best_sol['n_lines']}, 总长度={best_fit[0]:.2f} m, "
        f"漏测率={best_fit[1]:.4f}%, 超重叠率长度={best_fit[2]:.2f} m"
    )

    # 绘图
    fig, ax = plt.subplots(constrained_layout=True)
    X, Y = np.meshgrid(x_coords, y_coords)
    if best_sol is not None:
        covered = best_sol["covered"]
        CS = ax.contour(X, Y, depth_matrix, levels=10, colors='gray', linewidths=0.5)
        ax.clabel(CS, inline=True, fontsize=8)
        ax.contourf(X, Y, covered, levels=[0.5, 1.5], colors=['lightblue'], alpha=0.3)
        if best_sol.get("line_segments"):
            for segment in best_sol["line_segments"]:
                x0, y0 = segment["start"]
                x1, y1 = segment["end"]
                ax.plot([x0, x1], [y0, y1], 'r-', linewidth=0.45, alpha=0.55)
        elif best_sol["orientation"].startswith("NS"):
            for pos in best_sol["positions"]:
                ax.plot([pos, pos], [y_coords.min(), y_coords.max()], 'r-', linewidth=0.45, alpha=0.55)
        else:
            for pos in best_sol["positions"]:
                ax.plot([x_coords.min(), x_coords.max()], [pos, pos], 'r-', linewidth=0.45, alpha=0.55)

    ax.set_xlabel('东西方向 / 海里')
    ax.set_ylabel('南北方向 / 海里')
    ax.set_title(f'子问题4: 最优测线布设 (psi={best_psi:.0f}度)')
    ax.set_aspect('equal')
    fig.savefig('figures/fig_q4_optimal_layout.png', dpi=300)
    plt.close(fig)

    q4_results = {
        "best_psi": int(best_psi),
        "orientation": best_sol["orientation"],
        "n_lines": int(best_sol["n_lines"]),
        "total_length_m": float(round(best_fit[0], 2)),
        "miss_rate_pct": float(round(best_fit[1], 4)),
        "overlap_excess_m": float(round(best_fit[2], 2)),
        "overlap_excess_ratio_pct": float(round(best_fit[2] / best_fit[0] * 100, 4)) if best_fit[0] > 0 else 0.0,
        "eta_min": float(round(best_sol["eta_min"], 4)),
        "eta_max": float(round(best_sol["eta_max"], 4)),
        "max_miss_pct": float(best_sol.get("max_miss_pct", 0.0)),
        "candidates": [
            {
                "orientation": candidate["orientation"],
                "n_lines": int(candidate["n_lines"]),
                "total_length_m": float(round(candidate["total_length"], 2)),
                "miss_rate_pct": float(round(candidate["miss_rate"], 4)),
                "overlap_excess_m": float(round(candidate["over20_length"], 2)),
                "max_miss_pct": float(candidate.get("max_miss_pct", 0.0)),
            }
            for candidate in candidates
        ],
        "pareto": [
            {
                "max_miss_pct": float(sol["max_miss_pct"]),
                "n_lines": int(sol["n_lines"]),
                "total_length_m": float(round(sol["total_length"], 2)),
                "miss_rate_pct": float(round(sol["miss_rate"], 4)),
                "overlap_excess_m": float(round(sol["over20_length"], 2)),
                "overlap_excess_ratio_pct": float(round(sol["over20_length"] / sol["total_length"] * 100, 4)),
            }
            for sol in pareto_solutions
        ],
        "direction_search": [
            {
                "psi_deg": int(sol["psi_deg"]),
                "n_lines": int(sol["n_lines"]),
                "total_length_m": float(round(sol["total_length"], 2)),
                "miss_rate_pct": float(round(sol["miss_rate"], 4)),
                "overlap_excess_m": float(round(sol["over20_length"], 2)),
                "overlap_excess_ratio_pct": float(round(sol["over20_length"] / sol["total_length"] * 100, 4)) if sol["total_length"] > 0 else 0.0,
            }
            for sol in direction_solutions
        ],
    }
    if best_sol.get("line_segments"):
        pd.DataFrame({
            "line_id": np.arange(1, best_sol["n_lines"] + 1),
            "orientation": best_sol["orientation"],
            "psi_deg": best_sol["psi_deg"],
            "position_nm": np.round(best_sol["positions"], 6),
            "x_start_nm": [round(segment["start"][0], 6) for segment in best_sol["line_segments"]],
            "y_start_nm": [round(segment["start"][1], 6) for segment in best_sol["line_segments"]],
            "x_end_nm": [round(segment["end"][0], 6) for segment in best_sol["line_segments"]],
            "y_end_nm": [round(segment["end"][1], 6) for segment in best_sol["line_segments"]],
            "line_length_m": [round(segment["length_m"], 2) for segment in best_sol["line_segments"]],
        }).to_excel("result4.xlsx", index=False)
    else:
        pd.DataFrame({
            "line_id": np.arange(1, best_sol["n_lines"] + 1),
            "orientation": best_sol["orientation"],
            "position_nm": np.round(best_sol["positions"], 6),
            "line_length_m": round(best_sol["line_length_m"], 2),
        }).to_excel("result4.xlsx", index=False)
    pd.DataFrame(q4_results["pareto"]).to_excel("result4_pareto.xlsx", index=False)
    pd.DataFrame(q4_results["direction_search"]).to_excel("result4_direction_search.xlsx", index=False)
    return q4_results

# ============================================================
# 灵敏度分析
# ============================================================
def sensitivity_analysis():
    print("\n" + "=" * 60)
    print("灵敏度分析")
    print("=" * 60)

    alpha_base = 1.5
    theta_base = 120.0
    eta_target_base = 0.105

    def run_q3_model(alpha, theta_deg, eta_target):
        """简化版子问题3求解"""
        theta = np.deg2rad(theta_deg)
        nm_to_m = 1852.0
        Lx = 4.0
        center_x = Lx / 2
        D_center = 110.0
        slope_tan = np.tan(np.deg2rad(alpha))

        def depth_at_x(x_nm):
            return D_center + (center_x - x_nm) * slope_tan * nm_to_m

        def coverage_width_local(D, alpha_deg):
            a = np.deg2rad(alpha_deg)
            num = D * np.sin(theta) * np.cos(a)
            den = np.cos(theta/2 + a) * np.cos(theta/2 - a)
            if abs(den) < 1e-12:
                return np.inf
            return float(num / den)

        def f_x1(x):
            D = depth_at_x(x)
            W = coverage_width_local(D, alpha)
            return x - W / 2 / nm_to_m

        lo, hi = 0.0, 0.5
        for _ in range(100):
            mid = (lo + hi) / 2
            if f_x1(mid) <= 0:
                lo = mid
            else:
                hi = mid
        x1 = (lo + hi) / 2
        x_positions = [x1]

        for i in range(200):
            x_i = x_positions[-1]
            D_i = depth_at_x(x_i)
            W_i = coverage_width_local(D_i, alpha)

            def f_next(x_next):
                D_next = depth_at_x(x_next)
                W_next = coverage_width_local(D_next, alpha)
                d_m = (x_next - x_i) * nm_to_m
                eta = 1.0 - d_m / ((W_i + W_next) / 2.0)
                return eta - eta_target

            lo = x_i + 0.0001
            hi = Lx
            for _ in range(100):
                mid = (lo + hi) / 2
                val = f_next(mid)
                if val > 0:
                    lo = mid
                else:
                    hi = mid
            x_next = (lo + hi) / 2

            D_next = depth_at_x(x_next)
            W_next = coverage_width_local(D_next, alpha)
            east_cover = x_next + W_next / 2 / nm_to_m
            if east_cover >= Lx:
                x_positions.append(x_next)
                break
            x_positions.append(x_next)

        N = len(x_positions)
        total_length = float(N * 2.0 * nm_to_m)
        return total_length, int(N), x_positions

    # 基准解
    base_total, base_N, _ = run_q3_model(alpha_base, theta_base, eta_target_base)
    print(f"\n基准解: 总长度 = {base_total:.2f} m, 测线数 = {base_N}")

    params = [
        ("alpha", "坡度 (度)", alpha_base, [-10, -5, 5, 10]),
        ("theta", "开角 (度)", theta_base, [-20, -10, 10, 20]),
        ("eta_target", "目标重叠率", eta_target_base, [-20, -10, 10, 20]),
    ]

    sensitivity_data = {
        "baseline": {
            "objective": float(round(base_total, 2)),
            "objective_name": "测线总长度 (m)"
        },
        "experiments": []
    }

    for param_name, param_label, base_val, deltas in params:
        objectives = []
        fig, ax = plt.subplots(constrained_layout=True)

        for delta in deltas:
            if param_name == "alpha":
                new_val = base_val * (1 + delta / 100)
                total, N, _ = run_q3_model(new_val, theta_base, eta_target_base)
            elif param_name == "theta":
                new_val = base_val * (1 + delta / 100)
                total, N, _ = run_q3_model(alpha_base, new_val, eta_target_base)
            elif param_name == "eta_target":
                new_val = base_val * (1 + delta / 100)
                new_val = max(0.05, min(0.30, new_val))
                total, N, _ = run_q3_model(alpha_base, theta_base, new_val)

            change_pct = float(round((total - base_total) / base_total * 100, 2))
            objectives.append(total)

            sensitivity_data["experiments"].append({
                "param": param_name,
                "delta_pct": int(delta),
                "objective": float(round(total, 2)),
                "delta_objective": float(round(total - base_total, 2)),
                "change_pct": change_pct
            })

            print(f"  {param_name} {delta:+d}%: 总长度={total:.2f} m, 变化={change_pct:+.2f}%")

        # 绘图
        delta_vals = sorted(deltas + [0])
        obj_with_base = []
        for d in delta_vals:
            if d == 0:
                obj_with_base.append(base_total)
            else:
                idx = deltas.index(d)
                obj_with_base.append(objectives[idx])

        ax.plot(delta_vals, obj_with_base, 'o-', label=f'{param_label}')
        ax.axhline(y=base_total, color='gray', linestyle='--', alpha=0.7, label=f'基准值 ({base_total:.0f} m)')
        ax.set_xlabel('参数扰动幅度 / %')
        ax.set_ylabel('测线总长度 / m')
        ax.set_title(f'灵敏度分析: {param_label}')
        ax.legend()
        fig.savefig(f'figures/sensitivity_{param_name}.png', dpi=300)
        plt.close(fig)

    with open("sensitivity.json", "w", encoding="utf-8") as f:
        json.dump(sensitivity_data, f, ensure_ascii=False, indent=2)

    print("\n灵敏度分析完成。结果已保存到 sensitivity.json")
    return sensitivity_data

# ============================================================
# 主程序
# ============================================================
def main():
    os.makedirs('figures', exist_ok=True)
    os.makedirs('data/raw', exist_ok=True)

    # 检查数据文件
    data_path = 'data/raw/depth_data.csv'
    if not os.path.exists(data_path):
        print(f"[X] 数据文件不存在: {data_path}")
        print("请确保数据文件位于正确路径。")
        print("创建示例数据...")
        x = np.arange(0, 4.02, 0.02)
        y = np.arange(0, 5.02, 0.02)
        X, Y = np.meshgrid(x, y)
        depths = 20.62 + X * 44.0
        df = pd.DataFrame(depths, columns=np.round(x, 2))
        df.insert(0, 'y', np.round(y, 2))
        df.to_csv(data_path, index=False)
        print(f"示例数据已创建: {data_path}")

    # ---- 子问题1 ----
    print("\n" + "=" * 60)
    print("子问题1: 覆盖宽度公式验证")
    print("=" * 60)
    D_test = 70.0
    alpha_test = 1.5
    W_test = coverage_width(D_test, alpha_test)
    W_flat = 2 * D_test * np.tan(np.deg2rad(THETA_DEG / 2))
    print(f"测试条件: D={D_test} m, alpha={alpha_test}度, theta={THETA_DEG}度")
    print(f"覆盖宽度 W = {W_test:.2f} m")
    print(f"平坦海底近似 W_flat = {W_flat:.2f} m")
    print(f"差异: {abs(W_test - W_flat):.2f} m ({(abs(W_test - W_flat)/W_flat*100):.2f}%)")
    q1_positions_m = np.arange(-800, 801, 200)
    q1_rows = []
    prev_width = None
    for pos_m in q1_positions_m:
        depth = 70.0 - pos_m * np.tan(np.deg2rad(alpha_test))
        width = coverage_width(depth, alpha_test)
        overlap = None if prev_width is None else 1.0 - 200.0 / ((prev_width + width) / 2)
        q1_rows.append({
            "distance_m": int(pos_m),
            "depth_m": round(float(depth), 4),
            "coverage_width_m": round(float(width), 4),
            "overlap_with_previous_pct": None if overlap is None else round(float(overlap * 100), 4),
        })
        prev_width = width
    pd.DataFrame(q1_rows).to_excel("result1.xlsx", index=False)

    # ---- 子问题2 ----
    print("\n" + "=" * 60)
    print("子问题2: 三维视坡度模型验证")
    print("=" * 60)
    alpha_test2 = 10.0
    beta_test2 = 30.0
    alpha_prime = apparent_slope(alpha_test2, beta_test2)
    print(f"实际坡度 alpha={alpha_test2}度, 夹角 beta={beta_test2}度")
    print(f"视坡度 alpha' = {alpha_prime:.4f}度")
    alpha_prime_0 = apparent_slope(alpha_test2, 0)
    print(f"beta=0度 时 alpha' = {alpha_prime_0:.4f}度 (应与 alpha 相等)")
    alpha_prime_90 = apparent_slope(alpha_test2, 90)
    print(f"beta=90度 时 alpha' = {alpha_prime_90:.4f}度 (应为 0)")
    q2_distances_nm = np.arange(0, 2.1 + 0.001, 0.3)
    q2_betas = [0, 45, 90, 135, 180, 225, 270, 315]
    q2_rows = []
    for distance_nm in q2_distances_nm:
        for beta_deg in q2_betas:
            depth = 120.0 - distance_nm * 1852.0 * np.tan(np.deg2rad(1.5)) * np.cos(np.deg2rad(beta_deg))
            width = coverage_width_3d(depth, 1.5, beta_deg)
            q2_rows.append({
                "distance_nm": round(float(distance_nm), 1),
                "beta_deg": int(beta_deg),
                "depth_m": round(float(depth), 4),
                "coverage_width_m": round(float(width), 4),
            })
    pd.DataFrame(q2_rows).to_excel("result2.xlsx", index=False)
    q2_widths = [row["coverage_width_m"] for row in q2_rows]

    # ---- 子问题3 ----
    q3_results = solve_q3()

    # ---- 子问题4 ----
    q4_results = solve_q4()

    # ---- 灵敏度分析 ----
    sensitivity_data = sensitivity_analysis()
    depth_df = pd.read_csv('data/raw/depth_data.csv', header=0)
    depth_values = depth_df.iloc[:, 1:].values.astype(float)
    depth_stats = {
        "min": float(round(depth_values.min(), 4)),
        "max": float(round(depth_values.max(), 4)),
        "mean": float(round(depth_values.mean(), 4)),
        "median": float(round(np.median(depth_values), 4)),
        "std": float(round(depth_values.std(ddof=0), 4)),
        "point_count": int(depth_values.size),
        "rows": int(depth_values.shape[0]),
        "cols": int(depth_values.shape[1]),
        "west_mean": float(round(depth_values[:, 0].mean(), 2)),
        "east_mean": float(round(depth_values[:, -1].mean(), 2)),
    }
    q1_depth, q3_depth = np.percentile(depth_values, [25, 75])
    iqr_depth = q3_depth - q1_depth
    lower_bound = q1_depth - 1.5 * iqr_depth
    upper_bound = q3_depth + 1.5 * iqr_depth
    outlier_mask = (depth_values < lower_bound) | (depth_values > upper_bound)
    outlier_count = int(outlier_mask.sum())
    outlier_pct = outlier_count / depth_values.size * 100
    q4_ns_equal_lines = next(
        candidate["n_lines"] for candidate in q4_results["candidates"]
        if candidate["orientation"] == "NS"
    )
    q4_ew_lines = next(
        candidate["n_lines"] for candidate in q4_results["candidates"]
        if candidate["orientation"] == "EW"
    )
    q4_zero_miss = next(
        item for item in q4_results["pareto"]
        if item["max_miss_pct"] == 0.0
    )
    q4_balanced = next(
        item for item in q4_results["pareto"]
        if item["max_miss_pct"] == 2.0
    )
    q4_best_direction = min(
        q4_results["direction_search"],
        key=lambda item: (item["total_length_m"], item["overlap_excess_m"], item["miss_rate_pct"]),
    )
    q4_ns_equal = next(
        candidate for candidate in q4_results["candidates"]
        if candidate["orientation"] == "NS"
    )
    q4_ew = next(
        candidate for candidate in q4_results["candidates"]
        if candidate["orientation"] == "EW"
    )
    q4_reduce_ns_length = q4_ns_equal["total_length_m"] - q4_results["total_length_m"]
    q4_reduce_ew_length = q4_ew["total_length_m"] - q4_results["total_length_m"]
    q4_reduce_pareto2_length = q4_balanced["total_length_m"] - q4_results["total_length_m"]

    # ---- 汇总结果 ----
    print("\n" + "=" * 60)
    print("汇总结果")
    print("=" * 60)

    # 将所有数值转换为Python原生类型
    results = [
        {"name": "q1_覆盖宽度_验证", "value": float(round(W_test, 2)), "unit": "m", "desc": "子问题1验证: D=70m, alpha=1.5度时的覆盖宽度"},
        {"name": "q1_平坦近似宽度", "value": float(round(W_flat, 2)), "unit": "m", "desc": "平坦海底近似宽度 (2D*tan(theta/2))"},
        {"name": "q1_宽度差异百分比", "value": float(round(abs(W_test - W_flat)/W_flat*100, 2)), "unit": "%", "desc": "覆盖宽度与平坦近似的相对差异"},
        {"name": "q2_视坡度_beta30", "value": float(round(alpha_prime, 4)), "unit": "度", "desc": "子问题2: alpha=10度, beta=30度时的视坡度"},
        {"name": "q2_视坡度_beta0", "value": float(round(alpha_prime_0, 4)), "unit": "度", "desc": "子问题2验证: beta=0度时应等于实际坡度"},
        {"name": "q2_视坡度_beta90", "value": float(round(alpha_prime_90, 4)), "unit": "度", "desc": "子问题2验证: beta=90度时应为0"},
        {"name": "q2_覆盖宽度最小值", "value": float(round(min(q2_widths), 2)), "unit": "m", "desc": "子问题2 result2.xlsx 中覆盖宽度最小值"},
        {"name": "q2_覆盖宽度最大值", "value": float(round(max(q2_widths), 2)), "unit": "m", "desc": "子问题2 result2.xlsx 中覆盖宽度最大值"},
        {"name": "q3_测线数量", "value": int(q3_results["N"]), "unit": "条", "desc": "子问题3最优测线数量"},
        {"name": "q3_总长度", "value": float(q3_results["total_length_m"]), "unit": "m", "desc": "子问题3测线总长度"},
        {"name": "q3_最小重叠率", "value": float(q3_results["eta_min"]), "unit": "", "desc": "子问题3相邻测线最小重叠率"},
        {"name": "q3_最大重叠率", "value": float(q3_results["eta_max"]), "unit": "", "desc": "子问题3相邻测线最大重叠率"},
        {"name": "q3_西边界覆盖", "value": float(q3_results["west_cover"]), "unit": "海里", "desc": "子问题3西边界覆盖位置"},
        {"name": "q3_东边界覆盖", "value": float(q3_results["east_cover"]), "unit": "海里", "desc": "子问题3东边界覆盖位置"},
        {"name": "q4_最优方向角", "value": int(q4_results["best_psi"]), "unit": "度", "desc": "子问题4最优测线方向角"},
        {"name": "q4_测线数量", "value": int(q4_results["n_lines"]), "unit": "条", "desc": "子问题4自适应候选最优方案测线数量"},
        {"name": "q4_总长度", "value": float(q4_results["total_length_m"]), "unit": "m", "desc": "子问题4测线总长度"},
        {"name": "q4_漏测率", "value": float(q4_results["miss_rate_pct"]), "unit": "%", "desc": "子问题4漏测面积百分比"},
        {"name": "q4_超重叠率长度", "value": float(q4_results["overlap_excess_m"]), "unit": "m", "desc": "子问题4超重叠率区域长度"},
        {"name": "q4_超重叠率长度占比", "value": float(q4_results["overlap_excess_ratio_pct"]), "unit": "%", "desc": "子问题4超重叠率区域长度占总测线长度比例"},
        {"name": "q4_数据最小水深", "value": depth_stats["min"], "unit": "m", "desc": "真实水深矩阵最小值"},
        {"name": "q4_数据最大水深", "value": depth_stats["max"], "unit": "m", "desc": "真实水深矩阵最大值"},
        {"name": "q4_数据平均水深", "value": depth_stats["mean"], "unit": "m", "desc": "真实水深矩阵均值"},
        {"name": "q4_数据中位水深", "value": depth_stats["median"], "unit": "m", "desc": "真实水深矩阵中位数"},
        {"name": "q4_数据水深标准差", "value": depth_stats["std"], "unit": "m", "desc": "真实水深矩阵总体标准差"},
        {"name": "q4_数据点数量", "value": depth_stats["point_count"], "unit": "个", "desc": "真实水深矩阵数据点数量"},
        {"name": "q4_西侧平均水深", "value": depth_stats["west_mean"], "unit": "m", "desc": "真实水深矩阵最西侧剖面平均水深"},
        {"name": "q4_东侧平均水深", "value": depth_stats["east_mean"], "unit": "m", "desc": "真实水深矩阵最东侧剖面平均水深"},
        {"name": "q4_数据水深第一四分位数", "value": float(round(q1_depth, 2)), "unit": "m", "desc": "真实水深矩阵第一四分位数"},
        {"name": "q4_数据水深第三四分位数", "value": float(round(q3_depth, 2)), "unit": "m", "desc": "真实水深矩阵第三四分位数"},
        {"name": "q4_数据水深四分位距", "value": float(round(iqr_depth, 2)), "unit": "m", "desc": "真实水深矩阵四分位距"},
        {"name": "q4_IQR异常值下界", "value": float(round(lower_bound, 2)), "unit": "m", "desc": "IQR异常值检测下界"},
        {"name": "q4_IQR异常值上界", "value": float(round(upper_bound, 2)), "unit": "m", "desc": "IQR异常值检测上界"},
        {"name": "q4_IQR异常值数量", "value": outlier_count, "unit": "个", "desc": "按IQR规则识别的异常值数量"},
        {"name": "q4_IQR异常值占比", "value": float(round(outlier_pct, 2)), "unit": "%", "desc": "按IQR规则识别的异常值占比"},
        {"name": "q4_等间距南北候选测线数量", "value": int(q4_ns_equal_lines), "unit": "条", "desc": "子问题4等间距南北候选方案测线数量"},
        {"name": "q4_东西候选测线数量", "value": int(q4_ew_lines), "unit": "条", "desc": "子问题4东西候选方案测线数量"},
        {"name": "q4_较等间距南北减少测线数量", "value": int(q4_ns_equal_lines - q4_results["n_lines"]), "unit": "条", "desc": "自适应候选方案相对等间距南北候选减少的测线数量"},
        {"name": "q4_较东西减少测线数量", "value": int(q4_ew_lines - q4_results["n_lines"]), "unit": "条", "desc": "自适应候选方案相对东西候选减少的测线数量"},
        {"name": "q4_平衡方案漏测率上限", "value": float(q4_results["max_miss_pct"]), "unit": "%", "desc": "子问题4最终平衡方案允许的漏测率上限"},
        {"name": "q4_零漏测候选测线数量", "value": int(q4_zero_miss["n_lines"]), "unit": "条", "desc": "子问题4零漏测自适应候选方案测线数量"},
        {"name": "q4_零漏测候选总长度", "value": float(q4_zero_miss["total_length_m"]), "unit": "m", "desc": "子问题4零漏测自适应候选方案总长度"},
        {"name": "q4_零漏测候选超重叠率长度", "value": float(q4_zero_miss["overlap_excess_m"]), "unit": "m", "desc": "子问题4零漏测自适应候选方案超重叠率区域长度"},
        {"name": "q4_Pareto_2pct测线数量", "value": int(q4_balanced["n_lines"]), "unit": "条", "desc": "子问题4漏测率不超过2%的Pareto平衡方案测线数量"},
        {"name": "q4_Pareto_2pct总长度", "value": float(q4_balanced["total_length_m"]), "unit": "m", "desc": "子问题4漏测率不超过2%的Pareto平衡方案总长度"},
        {"name": "q4_Pareto_2pct漏测率", "value": float(q4_balanced["miss_rate_pct"]), "unit": "%", "desc": "子问题4漏测率不超过2%的Pareto平衡方案实际漏测率"},
        {"name": "q4_Pareto_2pct超重叠率长度", "value": float(q4_balanced["overlap_excess_m"]), "unit": "m", "desc": "子问题4漏测率不超过2%的Pareto平衡方案超重叠率区域长度"},
        {"name": "q4_Pareto_2pct超重叠率长度占比", "value": float(q4_balanced["overlap_excess_ratio_pct"]), "unit": "%", "desc": "子问题4漏测率不超过2%的Pareto平衡方案超重叠率长度占总测线长度比例"},
        {"name": "q4_较等间距南北减少总长度", "value": float(round(q4_reduce_ns_length, 2)), "unit": "m", "desc": "子问题4最终方案相对等间距南北候选减少的总长度"},
        {"name": "q4_较等间距南北减少总长度占比", "value": float(round(q4_reduce_ns_length / q4_ns_equal["total_length_m"] * 100, 4)), "unit": "%", "desc": "子问题4最终方案相对等间距南北候选减少的总长度占比"},
        {"name": "q4_较东西减少总长度", "value": float(round(q4_reduce_ew_length, 2)), "unit": "m", "desc": "子问题4最终方案相对东西候选减少的总长度"},
        {"name": "q4_较东西减少总长度占比", "value": float(round(q4_reduce_ew_length / q4_ew["total_length_m"] * 100, 4)), "unit": "%", "desc": "子问题4最终方案相对东西候选减少的总长度占比"},
        {"name": "q4_方向搜索最佳角度", "value": int(q4_best_direction["psi_deg"]), "unit": "度", "desc": "子问题4方向角15度粗采样得到的最短总长度方向"},
        {"name": "q4_方向搜索最佳测线数量", "value": int(q4_best_direction["n_lines"]), "unit": "条", "desc": "子问题4方向角粗采样最佳方案测线数量"},
        {"name": "q4_方向搜索最佳总长度", "value": float(q4_best_direction["total_length_m"]), "unit": "m", "desc": "子问题4方向角粗采样最佳方案总长度"},
        {"name": "q4_方向搜索最佳漏测率", "value": float(q4_best_direction["miss_rate_pct"]), "unit": "%", "desc": "子问题4方向角粗采样最佳方案实际漏测率"},
        {"name": "q4_方向搜索最佳超重叠率长度", "value": float(q4_best_direction["overlap_excess_m"]), "unit": "m", "desc": "子问题4方向角粗采样最佳方案超重叠率区域长度"},
        {"name": "q4_方向搜索较南北2pct减少总长度", "value": float(round(q4_reduce_pareto2_length, 2)), "unit": "m", "desc": "方向搜索最佳方案相对南北2%漏测Pareto方案减少的总长度"},
        {"name": "q4_方向搜索较南北2pct减少总长度占比", "value": float(round(q4_reduce_pareto2_length / q4_balanced["total_length_m"] * 100, 4)), "unit": "%", "desc": "方向搜索最佳方案相对南北2%漏测Pareto方案减少的总长度占比"},
        {"name": "sensitivity_alpha_10pct", "value": float(next(item["change_pct"] for item in sensitivity_data["experiments"] if item["param"] == "alpha" and item["delta_pct"] == 10)), "unit": "%", "desc": "灵敏度: 坡度+10%时总长度变化百分比"},
        {"name": "sensitivity_theta_20pct", "value": float(next(item["change_pct"] for item in sensitivity_data["experiments"] if item["param"] == "theta" and item["delta_pct"] == 20)), "unit": "%", "desc": "灵敏度: 开角+20%时总长度变化百分比"},
        {"name": "sensitivity_eta_20pct", "value": float(next(item["change_pct"] for item in sensitivity_data["experiments"] if item["param"] == "eta_target" and item["delta_pct"] == 20)), "unit": "%", "desc": "灵敏度: 目标重叠率+20%时总长度变化百分比"},
    ]

    with open("results.json", "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    print("\n结果已保存到 results.json")
    print("灵敏度结果已保存到 sensitivity.json")
    print("图表已保存到 figures/ 目录")
    print("\n所有任务完成!")

if __name__ == "__main__":
    main()
