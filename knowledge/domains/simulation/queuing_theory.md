# 排队论

## 方法简介

排队论（随机服务系统理论）研究等待现象的数学模型，分析顾客到达、排队等待、接受服务的随机过程，为服务系统的容量规划和资源配置提供定量依据。

## 适用场景

- 银行/医院窗口数量设计
- 呼叫中心坐席配置
- 计算机系统性能评估
- 生产线缓冲区设计

## 基本原理

排队系统用 **Kendall 记号** $A/B/c/K/N/D$ 描述：到达分布/服务分布/服务台数/系统容量/顾客源数/排队规则。

**M/M/1 模型**（Poisson 到达、指数服务、单服务台）：到达率 $\lambda$，服务率 $\mu$，交通强度 $\rho = \lambda / \mu$（要求 $\rho < 1$）。

稳态性能指标：

$$L_s = \frac{\rho}{1 - \rho} \quad \text{（系统平均顾客数）}$$

$$W_s = \frac{1}{\mu - \lambda} \quad \text{（平均逗留时间）}$$

**Little 公式**（适用于任意排队系统）：

$$L = \lambda W$$

即系统平均顾客数 = 到达率 $\times$ 平均逗留时间。

**M/M/c 模型**：$c$ 个服务台，需用 Erlang-C 公式计算等待概率。

## Python 实现要点

```python
import numpy as np
from scipy.special import factorial

# M/M/1 解析解
def mm1(lam, mu):
    rho = lam / mu
    Ls = rho / (1 - rho)
    Ws = 1 / (mu - lam)
    Wq = rho / (mu - lam)
    Lq = lam * Wq
    return {'rho': rho, 'Ls': Ls, 'Ws': Ws, 'Lq': Lq, 'Wq': Wq}

# M/M/c 模拟（SimPy 框架）
import simpy
def customer(env, server, mu):
    with server.request() as req:
        yield req
        yield env.timeout(np.random.exponential(1/mu))

env = simpy.Environment()
server = simpy.Resource(env, capacity=3)
```

解析解用于验证仿真结果；复杂排队网络（如 Jackson 网络）建议直接用 SimPy 仿真。

## 国赛常见应用举例

- 医院门诊窗口或检查设备的最优数量配置
- 收费站通道数量与排队时间的权衡分析
- 生产系统中机器故障维修的等待优化
