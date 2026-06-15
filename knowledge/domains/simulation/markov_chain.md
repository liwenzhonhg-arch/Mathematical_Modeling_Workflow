# 马尔可夫链

## 方法简介

马尔可夫链是一类具有"无记忆性"的离散时间随机过程：系统下一状态仅取决于当前状态，与历史路径无关。它为状态转移分析和长期行为预测提供了优雅的数学框架。

## 适用场景

- 品牌市场份额预测（顾客转移模型）
- 天气状态预测
- PageRank 网页排名算法
- 基因序列分析（隐马尔可夫模型）
- 随机游走与扩散过程

## 基本原理

设状态空间 $S = \{s_1, s_2, \ldots, s_n\}$，转移概率矩阵 $P$ 中元素 $p_{ij}$ 表示从状态 $i$ 转移到状态 $j$ 的概率：

$$p_{ij} = P(X_{t+1} = s_j \mid X_t = s_i), \quad \sum_{j} p_{ij} = 1$$

经过 $k$ 步后的状态分布：

$$\boldsymbol{\pi}^{(k)} = \boldsymbol{\pi}^{(0)} P^k$$

**稳态分布**（若存在）满足：

$$\boldsymbol{\pi} = \boldsymbol{\pi} P, \quad \sum_i \pi_i = 1$$

对于不可约非周期链，稳态分布唯一存在，且与初始状态无关。

## Python 实现要点

```python
import numpy as np

# 转移概率矩阵
P = np.array([[0.7, 0.2, 0.1],
              [0.3, 0.5, 0.2],
              [0.1, 0.3, 0.6]])

# k 步后状态分布
pi_0 = np.array([1, 0, 0])  # 初始状态
pi_k = pi_0 @ np.linalg.matrix_power(P, 50)

# 求稳态分布（解线性方程组）
A = np.vstack([(P.T - np.eye(3)), np.ones(3)])
b = np.append(np.zeros(3), 1)
pi_steady = np.linalg.lstsq(A, b, rcond=None)[0]

# 稳态分布也是 P^T 特征值 1 对应的特征向量
eigenvalues, eigenvectors = np.linalg.eig(P.T)
idx = np.argmin(np.abs(eigenvalues - 1))
pi_steady2 = np.real(eigenvectors[:, idx])
pi_steady2 /= pi_steady2.sum()
```

要点：转移矩阵行和为 1；用特征值法或迭代法求稳态分布均可，大规模稀疏矩阵用 `scipy.sparse`。

## 国赛常见应用举例

- 市场份额预测（品牌间顾客流转的长期均衡）
- 信用评级迁移模型（违约概率估计）
- 人口迁移模型（城市间人口流动的稳态分析）
