# 常微分方程 (ODE)

## 方法简介

常微分方程描述未知函数关于单一自变量（通常为时间）的导数关系，是连续动态系统建模的基础工具。数学建模中大量动态过程可用 ODE 刻画。

## 适用场景

- 种群增长与传染病传播模型（SIR/SIS）
- 物理系统动力学（力学、电路、热传导）
- 化学反应动力学
- 经济增长与资源消耗模型

## 基本原理

一般形式为初值问题：

$$\frac{dy}{dt} = f(t, y), \quad y(t_0) = y_0$$

经典模型举例——**Logistic 增长**：

$$\frac{dN}{dt} = rN\left(1 - \frac{N}{K}\right)$$

其中 $r$ 为内禀增长率，$K$ 为环境容纳量。

**数值方法**：
- **Euler 法**：$y_{n+1} = y_n + hf(t_n, y_n)$，一阶精度
- **Runge-Kutta 4 阶法（RK4）**：精度为 $O(h^4)$，是最常用的求解器
- **自适应步长法**（如 RK45）：自动调整步长以平衡精度和效率

## Python 实现要点

```python
from scipy.integrate import solve_ivp
import numpy as np

def sir_model(t, y, beta, gamma):
    S, I, R = y
    return [-beta*S*I, beta*S*I - gamma*I, gamma*I]

sol = solve_ivp(sir_model, [0, 100], [0.99, 0.01, 0],
                args=(0.3, 0.1), t_eval=np.linspace(0, 100, 1000),
                method='RK45')
```

关键参数：`method` 选择求解器（刚性方程用 `'Radau'` 或 `'BDF'`）；`rtol`/`atol` 控制精度。

## 国赛常见应用举例

- 传染病传播建模（SIR/SEIR 模型）是国赛高频考点
- 药物代谢动力学（房室模型）
- 生态系统种群竞争（Lotka-Volterra 方程）
