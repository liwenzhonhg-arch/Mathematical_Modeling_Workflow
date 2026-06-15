# 最短路径

## 方法简介

最短路径问题是图论中最基础的优化问题，求解图中两点之间权值之和最小的路径。根据问题类型分为单源最短路径和全源最短路径。

## 适用场景

- 交通路线规划与物流配送
- 通信网络路由优化
- 资源分配中的最优路径选择

## 基本原理

**Dijkstra 算法**（非负权图，单源）：贪心策略，每次选取距源点最近的未访问节点并松弛相邻边。时间复杂度 $O((V+E)\log V)$（优先队列实现）。

松弛操作：

$$d[v] = \min(d[v],\ d[u] + w(u, v))$$

**Floyd-Warshall 算法**（全源最短路径）：动态规划，枚举中间节点 $k$：

$$d_{ij}^{(k)} = \min\left(d_{ij}^{(k-1)},\ d_{ik}^{(k-1)} + d_{kj}^{(k-1)}\right)$$

时间复杂度 $O(V^3)$，适合节点数较少但需要全部点对距离的场景。

**Bellman-Ford 算法**：支持负权边，可检测负权环，复杂度 $O(VE)$。

## Python 实现要点

```python
import networkx as nx

G = nx.DiGraph()
G.add_weighted_edges_from([(u, v, w), ...])

# Dijkstra 单源最短路径
path = nx.dijkstra_path(G, source, target)
length = nx.dijkstra_path_length(G, source, target)

# Floyd 全源最短路径
dist_matrix = dict(nx.floyd_warshall(G))
```

大规模稀疏图建议用 `scipy.sparse.csgraph.dijkstra()`，性能远优于 networkx。

## 国赛常见应用举例

- 物流选址与配送路线优化
- 应急救援中最快到达路径规划
- 管道/电缆铺设的最优连接方案
