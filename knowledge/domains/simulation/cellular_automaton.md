# 元胞自动机

## 方法简介

元胞自动机 (CA) 是一种离散时空动力学模型：空间被划分为规则网格，每个元胞有有限状态集，按局部规则同步更新。简单局部规则可涌现出复杂的全局行为，适合模拟自组织和空间扩散现象。

## 适用场景

- 交通流模拟（车辆跟驰与堵塞）
- 森林火灾蔓延与传染病空间传播
- 城市扩张与土地利用变化
- 晶体生长与物理形态模拟

## 基本原理

CA 由四元组 $(L, S, N, f)$ 定义：
- $L$：元胞空间（一维链、二维网格等）
- $S$：状态集合（如 $\{0, 1\}$）
- $N$：邻域（Von Neumann 四邻域或 Moore 八邻域）
- $f: S^{|N|+1} \to S$：状态转移函数

每个时间步，所有元胞根据自身及邻居状态同步更新：

$$s_i^{t+1} = f(s_i^t, s_{N(i)}^t)$$

**经典模型——Conway 生命游戏**（Moore 邻域）：
- 活细胞：邻居活细胞数为 2 或 3 则存活，否则死亡
- 死细胞：邻居活细胞数恰好为 3 则复活

**NaSch 交通流模型**：加速、减速、随机慢化、前进四步规则。

## Python 实现要点

```python
import numpy as np

def game_of_life_step(grid):
    neighbors = sum(np.roll(np.roll(grid, i, 0), j, 1)
                    for i in (-1, 0, 1) for j in (-1, 0, 1)
                    if (i, j) != (0, 0))
    birth = (neighbors == 3) & (grid == 0)
    survive = ((neighbors == 2) | (neighbors == 3)) & (grid == 1)
    return (birth | survive).astype(int)

grid = np.random.choice([0, 1], size=(100, 100), p=[0.8, 0.2])
for _ in range(200):
    grid = game_of_life_step(grid)
```

性能提示：用 `numpy` 向量化操作替代逐元胞循环，速度提升百倍以上。

## 国赛常见应用举例

- 交通流量仿真与信号灯优化（NaSch 模型）
- 森林火灾蔓延范围预测
- 传染病在空间网格上的传播动态模拟
