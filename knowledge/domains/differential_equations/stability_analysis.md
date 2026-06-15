# 稳定性分析

## 方法简介

稳定性分析研究动力系统在平衡点附近的行为：受到小扰动后系统是否会回到平衡状态。它是微分方程建模中不可或缺的理论分析环节。

## 适用场景

- 判断生态系统平衡态是否可持续
- 控制系统的稳定性设计
- 传染病模型中无病平衡点与地方病平衡点的稳定性
- 经济模型中均衡状态的可达性

## 基本原理

对自治系统 $\frac{d\mathbf{x}}{dt} = \mathbf{f}(\mathbf{x})$，先求平衡点 $\mathbf{x}^*$（令 $\mathbf{f}(\mathbf{x}^*) = \mathbf{0}$），再在平衡点处线性化：

$$\frac{d\boldsymbol{\xi}}{dt} = J(\mathbf{x}^*) \boldsymbol{\xi}$$

其中 $J$ 为 Jacobian 矩阵，$J_{ij} = \frac{\partial f_i}{\partial x_j}\Big|_{\mathbf{x}^*}$。

**稳定性判据**：Jacobian 矩阵的所有特征值实部为负，则平衡点渐近稳定：

$$\text{Re}(\lambda_i) < 0, \quad \forall i \implies \text{渐近稳定}$$

若存在 $\text{Re}(\lambda_i) > 0$，则不稳定。纯虚特征值对应中心型（需非线性分析）。

**Lyapunov 方法**：构造正定函数 $V(\mathbf{x})$，若 $\dot{V} \leq 0$ 则稳定，$\dot{V} < 0$ 则渐近稳定，无需求解方程。

## Python 实现要点

```python
import numpy as np
from scipy.optimize import fsolve

# 定义系统
def f(x):
    return [x[0]*(1 - x[0]) - 0.5*x[0]*x[1],
            x[1]*(0.8 - x[1]) - 0.3*x[0]*x[1]]

# 求平衡点
eq_point = fsolve(f, [0.5, 0.5])

# 计算 Jacobian 特征值
from scipy.misc import approx_fprime
J = np.array([approx_fprime(eq_point, lambda x: f(x)[i], 1e-8)
              for i in range(2)])
eigenvalues = np.linalg.eigvals(J)
is_stable = all(np.real(eigenvalues) < 0)
```

也可用 `sympy` 符号计算精确 Jacobian，适合写论文时展示推导过程。

## 国赛常见应用举例

- SIR 模型中基本再生数 $R_0$ 与无病平衡点稳定性的关系
- Lotka-Volterra 竞争模型的共存平衡点分析
- 供需模型中价格均衡的稳定性讨论
