# 旅行商问题 (TSP)

## 方法简介

TSP 要求找到一条经过所有城市恰好一次并返回起点的最短回路。它是组合优化中最经典的 NP-hard 问题，实际求解依赖近似算法和启发式方法。

## 适用场景

- 物流配送路线优化
- PCB 钻孔/激光切割路径规划
- 基因测序中 DNA 片段排列

## 基本原理

给定 $n$ 个城市及距离矩阵 $d_{ij}$，目标为：

$$\min \sum_{i=1}^{n} d_{\pi(i), \pi(i+1)} \quad \text{其中 } \pi(n+1) = \pi(1)$$

$\pi$ 为城市的一个排列。精确解法有动态规划（状态压缩 DP），复杂度 $O(n^2 \cdot 2^n)$，仅适用于 $n \leq 20$。

**常用启发式算法**：
- **最近邻法**：每次选最近的未访问城市，$O(n^2)$，解质量一般
- **2-opt / 3-opt**：局部搜索，反复尝试交换边以改进回路
- **模拟退火 / 遗传算法**：元启发式方法，可跳出局部最优

## Python 实现要点

```python
from python_tsp.exact import solve_tsp_dynamic_programming
from python_tsp.heuristics import solve_tsp_simulated_annealing

import numpy as np
# 距离矩阵
dist_matrix = np.array([[0, 10, 15], [10, 0, 20], [15, 20, 0]])

# 精确解（小规模）
perm, distance = solve_tsp_dynamic_programming(dist_matrix)

# 启发式解（大规模）
perm, distance = solve_tsp_simulated_annealing(dist_matrix)
```

备选：`ortools` 的路由求解器功能更强，支持时间窗、容量约束等扩展。

## 国赛常见应用举例

- 快递/外卖配送路径优化
- 巡检路线规划（电网巡检、景区游览）
- 加工工序排列使换模时间最短
