# 线性规划 (Linear Programming)

## 方法简介

线性规划是在线性约束条件下，求线性目标函数最优值的数学方法。它是最成熟、应用最广泛的优化方法之一，具有理论完备、求解高效的特点。

## 适用场景

- 目标函数和约束条件均为决策变量的线性函数
- 资源分配、生产计划、运输调度、配料问题等
- 问题规模可以很大（数万变量），求解器仍能高效处理

## 基本原理

标准形式：

$$\min \quad \mathbf{c}^T \mathbf{x}$$
$$\text{s.t.} \quad A\mathbf{x} \leq \mathbf{b}, \quad \mathbf{x} \geq \mathbf{0}$$

核心定理：若线性规划有最优解，则最优解必在可行域的顶点处取得。单纯形法沿顶点搜索，内点法穿越可行域内部，两者均可在多项式/实际高效时间内求解。

对偶理论提供灵敏度分析：影子价格（对偶变量值）表示约束右端项变化一个单位时目标函数的改善量。

## Python 实现要点

```python
from scipy.optimize import linprog

# min c^T x, s.t. A_ub @ x <= b_ub, A_eq @ x = b_eq
res = linprog(c, A_ub=A_ub, b_ub=b_ub, bounds=bounds, method='highs')
```

- `scipy.optimize.linprog`：轻量场景首选，HiGHS 求解器性能优秀
- `PuLP`：建模语法直观，支持调用 CBC/CPLEX/Gurobi 等后端
- 大规模问题推荐 `Gurobi`（学术免费）或 `COPT`

## 国赛常见应用举例

- **2018-A 高温作业专用服装设计**：热传导参数优化可线性化处理
- **生产计划类题目**：多产品多工序产能约束下利润最大化
- **运输问题**：产销平衡的最小运费问题，经典线性规划模型
- **配料/饮食问题**：满足营养约束下的最低成本配方
