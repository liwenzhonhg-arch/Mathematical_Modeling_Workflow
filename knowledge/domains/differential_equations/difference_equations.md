# 差分方程

## 方法简介

差分方程是微分方程的离散对应物，描述离散时间步上状态量的递推关系。当系统状态按固定间隔更新（年度数据、每轮迭代等），差分方程比微分方程更自然。

## 适用场景

- 种群离散世代增长模型
- 经济模型（GDP 增长、投资回报递推）
- 数列递推关系求解
- 数字信号处理（Z 变换）

## 基本原理

一阶线性差分方程：

$$x_{n+1} = ax_n + b$$

通解为 $x_n = a^n(x_0 - x^*) + x^*$，其中不动点 $x^* = \frac{b}{1-a}$（$a \neq 1$ 时）。

**Logistic 差分方程**（离散混沌的经典模型）：

$$x_{n+1} = rx_n(1 - x_n)$$

当 $r > 3.57$ 时系统进入混沌状态，展现对初值的敏感依赖性。

**高阶线性差分方程**的特征方程法：对 $x_{n+2} + ax_{n+1} + bx_n = 0$，特征方程为：

$$\lambda^2 + a\lambda + b = 0$$

通解由特征根 $\lambda_1, \lambda_2$ 决定：$x_n = C_1\lambda_1^n + C_2\lambda_2^n$。

## Python 实现要点

```python
import numpy as np

# 直接迭代求解
def solve_difference_eq(f, x0, n_steps):
    x = np.zeros(n_steps + 1)
    x[0] = x0
    for i in range(n_steps):
        x[i+1] = f(x[i])
    return x

# Logistic 差分方程
trajectory = solve_difference_eq(lambda x: 3.8 * x * (1 - x), 0.1, 100)

# 线性差分方程组用矩阵幂次
A = np.array([[1.05, 0.02], [0.01, 0.98]])
x = np.array([100, 50])
for _ in range(20):
    x = A @ x
```

对线性系统 $\mathbf{x}_{n+1} = A\mathbf{x}_n$，可直接计算 $\mathbf{x}_n = A^n \mathbf{x}_0$，用 `np.linalg.matrix_power()` 实现。

## 国赛常见应用举例

- 人口预测的 Leslie 矩阵模型（按年龄分组递推）
- 贷款还款计划与投资收益的递推计算
- 生态学中离散种群模型与混沌现象分析
