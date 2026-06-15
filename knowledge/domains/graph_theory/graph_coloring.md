# 图着色

## 方法简介

图着色问题是为图的顶点（或边）分配颜色，使得相邻元素颜色不同，并最小化所用颜色数。最小颜色数称为图的色数 $\chi(G)$。图着色判定问题是 NP-完全的。

## 适用场景

- 考试/会议排程（互斥约束下的分组）
- 频率分配（相邻基站不能用同一频率）
- 地图着色与区域划分
- 寄存器分配（编译优化）

## 基本原理

给定无向图 $G=(V,E)$，求映射 $c: V \to \{1,2,\ldots,k\}$ 使得：

$$\forall (u,v) \in E: c(u) \neq c(v)$$

且 $k = \chi(G)$ 最小。**四色定理**保证任何平面图 $\chi(G) \leq 4$。

**贪心着色**：按某种顺序遍历顶点，为每个顶点分配最小可用颜色。结果取决于顶点顺序，最坏情况下用色数可达 $\Delta(G) + 1$（$\Delta$ 为最大度数），但 Brooks 定理保证除完全图和奇环外 $\chi(G) \leq \Delta(G)$。

**回溯法**：精确求解小规模问题，逐个顶点尝试着色并回溯。

## Python 实现要点

```python
import networkx as nx

G = nx.Graph()
G.add_edges_from([(0,1), (1,2), (2,3), (3,0), (0,2)])

# 贪心着色（启发式）
coloring = nx.coloring.greedy_color(G, strategy='largest_first')
num_colors = max(coloring.values()) + 1

# 可选策略：'largest_first', 'smallest_last', 'DSATUR'
coloring_dsatur = nx.coloring.greedy_color(G, strategy='DSATUR')
```

DSATUR 策略通常效果最好，优先着色饱和度（已着色邻居颜色种数）最高的顶点。

## 国赛常见应用举例

- 考试安排：有共同学生的课程不能同时考试，最少需要几个时间段
- 无线通信频率分配：相邻区域避免频率干扰
- 任务调度：互斥任务分配到最少的时间槽
