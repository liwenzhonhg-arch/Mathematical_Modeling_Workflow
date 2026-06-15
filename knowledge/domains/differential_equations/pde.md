# 偏微分方程 (PDE)

## 方法简介

偏微分方程描述未知函数关于多个自变量（如空间和时间）的偏导数关系，用于刻画空间分布随时间演化的连续场问题。

## 适用场景

- 热传导与温度场分布
- 流体力学（Navier-Stokes 方程）
- 波动传播与振动分析
- 污染物扩散与浓度分布

## 基本原理

三类经典 PDE：

**热传导方程**（抛物型）：

$$\frac{\partial u}{\partial t} = \alpha \nabla^2 u$$

**波动方程**（双曲型）：

$$\frac{\partial^2 u}{\partial t^2} = c^2 \nabla^2 u$$

**Laplace 方程**（椭圆型）：

$$\nabla^2 u = 0$$

其中 $\nabla^2$ 为 Laplacian 算子。求解需指定边界条件（Dirichlet / Neumann / Robin）和初始条件。

**数值方法**：
- **有限差分法 (FDM)**：将连续域离散为网格，用差商近似导数
- **有限元法 (FEM)**：将区域分割为单元，构造弱形式求解
- **谱方法**：用全局基函数展开，精度高但适用于规则域

## Python 实现要点

```python
# 有限差分法求解一维热传导
import numpy as np

Nx, Nt = 100, 1000
dx, dt = 1.0/Nx, 0.001
alpha = 0.01
r = alpha * dt / dx**2  # 稳定性要求 r <= 0.5

u = np.zeros(Nx + 1)
u[40:60] = 1.0  # 初始条件

for n in range(Nt):
    u[1:-1] = u[1:-1] + r * (u[2:] - 2*u[1:-1] + u[:-2])

# 复杂问题推荐 FEniCS 框架
# from fenics import *
```

注意有限差分的 CFL 稳定性条件：$r = \alpha \Delta t / \Delta x^2 \leq 0.5$，否则数值解会发散。

## 国赛常见应用举例

- 高温作业服装的温度分布建模（2018 A 题）
- 污染物在河流/大气中的扩散模拟
- 地下水渗流与热量传输分析
