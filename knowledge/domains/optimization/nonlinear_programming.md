# 非线性规划 (Nonlinear Programming)

## 方法简介

非线性规划处理目标函数或约束条件中含有非线性项的优化问题。相比线性规划，非线性规划的可行域和目标函数形状更复杂，可能存在多个局部最优解。

## 适用场景

- 目标函数或约束包含二次项、指数、对数、三角函数等非线性表达
- 曲线拟合、参数估计、工程设计优化
- 投资组合优化（二次规划是其特例）

## 基本原理

一般形式：

$$\min \quad f(\mathbf{x})$$
$$\text{s.t.} \quad g_i(\mathbf{x}) \leq 0, \quad h_j(\mathbf{x}) = 0$$

**KKT 条件**（Karush-Kuhn-Tucker）是约束优化的一阶必要条件：

$$\nabla f(\mathbf{x}^*) + \sum_i \mu_i \nabla g_i(\mathbf{x}^*) + \sum_j \lambda_j \nabla h_j(\mathbf{x}^*) = 0$$
$$\mu_i \geq 0, \quad \mu_i g_i(\mathbf{x}^*) = 0$$

常用算法：序列二次规划（SQP）将问题逐步近似为二次规划子问题求解；内点法处理大规模稀疏问题；信赖域方法在局部区域内构造近似模型。

凸优化是特殊情形——目标函数为凸、可行域为凸集时，局部最优即全局最优。

## Python 实现要点

```python
from scipy.optimize import minimize

# 无约束
res = minimize(f, x0, method='BFGS')

# 有约束
constraints = [{'type': 'ineq', 'fun': g}, {'type': 'eq', 'fun': h}]
res = minimize(f, x0, method='SLSQP', constraints=constraints, bounds=bounds)
```

- `scipy.optimize.minimize`：支持 BFGS、L-BFGS-B、SLSQP、trust-constr 等方法
- `cvxpy`：凸优化建模框架，自动验证凸性并选择求解器
- 多起点策略应对多局部极值：用随机初始点多次求解取最优

## 国赛常见应用举例

- **2018-A 高温作业专用服装设计**：热传导方程参数优化
- **曲线/曲面拟合**：最小二乘非线性回归
- **投资组合**：均值-方差模型的二次规划
- **工程设计**：结构尺寸、材料参数的最优设计
