# 最小生成树

## 方法简介

最小生成树 (MST) 是在连通无向加权图中找到一棵包含所有顶点且边权之和最小的生成树。它是网络设计类问题的基础工具。

## 适用场景

- 通信网络/管道/电缆的最低成本铺设
- 聚类分析中的连通性判断
- 近似求解 TSP 等 NP-hard 问题的辅助手段

## 基本原理

**Kruskal 算法**：按边权从小到大排序，依次加入不构成环的边（并查集判环），直到选出 $V-1$ 条边。时间复杂度 $O(E \log E)$。

**Prim 算法**：从任意节点出发，每次将与已选集合相连的最小权边对应的新节点加入集合。使用优先队列时复杂度为 $O((V+E)\log V)$。

MST 的关键性质——**切割性质**：对图的任意切割，跨越切割的最小权边一定属于某棵 MST。形式化表示：

$$e^* = \arg\min_{e \in \text{cut}(S, V \setminus S)} w(e) \implies e^* \in \text{MST}$$

## Python 实现要点

```python
import networkx as nx

G = nx.Graph()
G.add_weighted_edges_from([(u, v, w), ...])

# Kruskal 算法
mst = nx.minimum_spanning_tree(G, algorithm='kruskal')
total_weight = mst.size(weight='weight')

# 获取 MST 边列表
mst_edges = list(nx.minimum_spanning_edges(G, data=True))
```

大规模图可用 `scipy.sparse.csgraph.minimum_spanning_tree()`，输入为稀疏邻接矩阵，速度更快。

## 国赛常见应用举例

- 村村通公路/通信基站连接的最低成本方案
- 电力网络/供水管网的最优布局
- 层次聚类中基于 MST 的分群方法
