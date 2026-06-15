# 网络流

## 方法简介

网络流问题研究在有向图（流网络）中，如何在满足容量约束和流量守恒条件下，实现从源点到汇点的最大流量传输或最小费用传输。

## 适用场景

- 物资调运与运输能力分析
- 任务分配与二分图匹配
- 通信网络带宽优化

## 基本原理

**最大流问题**：给定流网络 $G=(V,E)$，每条边 $(u,v)$ 有容量 $c(u,v)$，求源点 $s$ 到汇点 $t$ 的最大流量。约束条件：

$$0 \leq f(u,v) \leq c(u,v) \quad \text{（容量约束）}$$

$$\sum_{v} f(v,u) = \sum_{v} f(u,v) \quad \forall u \neq s,t \quad \text{（流量守恒）}$$

**最大流-最小割定理**：最大流的值等于最小割的容量：

$$\max |f| = \min_{(S,T)} \sum_{u \in S, v \in T} c(u,v)$$

**最小费用最大流**：在最大流基础上，每条边增加单位费用 $a(u,v)$，在保证最大流量的前提下最小化总费用。

## Python 实现要点

```python
import networkx as nx

G = nx.DiGraph()
G.add_edge('s', 'a', capacity=10)
G.add_edge('a', 't', capacity=8)

# 最大流
flow_value, flow_dict = nx.maximum_flow(G, 's', 't')

# 最小费用最大流
G.add_edge('s', 'a', capacity=10, weight=2)
flow_cost, flow_dict = nx.max_flow_min_cost(G, 's', 't')
```

注意：`weight` 属性表示单位费用；求最小割用 `nx.minimum_cut(G, 's', 't')`。

## 国赛常见应用举例

- 救灾物资从多仓库到多灾区的最优调度
- 人员/任务的最优匹配（转化为二分图最大匹配）
- 交通网络瓶颈识别（最小割对应关键路段）
