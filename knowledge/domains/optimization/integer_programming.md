# 整数规划 (Integer Programming)

## 方法简介

整数规划要求部分或全部决策变量取整数值。当决策本质上是离散的（选或不选、分配整数件数），线性规划的连续松弛无法直接使用，需要整数规划建模。0-1 整数规划是其重要特例。

## 适用场景

- 决策变量具有离散性质：选址、排班、指派、装箱
- 含逻辑约束（若…则…）的组合优化问题
- 0-1 变量建模"是否选择"类决策

## 基本原理

在线性规划基础上增加整数约束：

$$\min \quad \mathbf{c}^T \mathbf{x}$$
$$\text{s.t.} \quad A\mathbf{x} \leq \mathbf{b}, \quad x_i \in \mathbb{Z} \; (\text{部分或全部})$$

求解核心方法是**分支定界法**（Branch and Bound）：先求解 LP 松弛获得下界，对非整数变量分支，逐步缩小搜索空间。割平面法通过添加有效不等式加速收敛。现代求解器结合预处理、启发式、割平面和分支定界形成 Branch-and-Cut 框架。

整数规划是 NP-hard 问题，最坏情况下求解时间随变量数指数增长。

## Python 实现要点

```python
from pulp import LpProblem, LpMinimize, LpVariable, LpInteger, LpBinary

prob = LpProblem("IP", LpMinimize)
x = LpVariable("x", cat=LpInteger, lowBound=0)
y = LpVariable("y", cat=LpBinary)  # 0-1变量
prob += 3*x + 5*y  # 目标函数
prob += x + 2*y <= 10  # 约束
prob.solve()
```

- `PuLP` + CBC：免费方案，中小规模问题够用
- `Gurobi` / `CPLEX`：大规模问题首选，学术许可免费
- 建模技巧：用大 M 法将逻辑约束转化为线性不等式

## 国赛常见应用举例

- **2017-B 拍照赚钱的任务定价**：任务分配的 0-1 指派问题
- **选址问题**：在候选点中选择设施位置，最小化总成本
- **车辆路径问题 (VRP)**：整数变量描述路线选择
- **排班/排课问题**：多约束下的可行排列方案
