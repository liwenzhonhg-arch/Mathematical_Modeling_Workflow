# 遗传算法 (Genetic Algorithm)

## 方法简介

遗传算法是受生物进化启发的元启发式优化方法。通过模拟自然选择、交叉和变异等遗传机制，在解空间中进行全局搜索。适合处理传统优化方法难以求解的复杂非凸、离散或黑箱优化问题。

## 适用场景

- 搜索空间大、目标函数不可微或无解析表达式
- 多峰函数优化，需要全局搜索能力
- 组合优化问题（TSP、调度、排列）
- 精确算法计算量不可接受时的近似求解

## 基本原理

核心流程：

1. **编码**：将解表示为"染色体"（二进制串、实数向量或排列）
2. **初始化**：随机生成初始种群 $P_0$
3. **适应度评价**：计算每个个体的适应度 $f(\mathbf{x})$
4. **选择**：按适应度比例选择父代（轮盘赌、锦标赛选择）
5. **交叉**：以概率 $p_c$ 交换父代片段产生子代
6. **变异**：以概率 $p_m$ 随机扰动基因位
7. **迭代**：重复步骤 3-6 直至满足终止条件

选择压力驱动种群向高适应度区域聚集，交叉实现信息重组，变异维持种群多样性防止早熟收敛。

## Python 实现要点

```python
from deap import base, creator, tools, algorithms

creator.create("FitnessMin", base.Fitness, weights=(-1.0,))
creator.create("Individual", list, fitness=creator.FitnessMin)

toolbox = base.Toolbox()
toolbox.register("attr_float", random.uniform, -5, 5)
toolbox.register("individual", tools.initRepeat, creator.Individual, toolbox.attr_float, n=10)
toolbox.register("population", tools.initRepeat, list, toolbox.individual)
toolbox.register("evaluate", eval_func)
toolbox.register("mate", tools.cxTwoPoint)
toolbox.register("mutate", tools.mutGaussian, mu=0, sigma=1, indpb=0.1)
toolbox.register("select", tools.selTournament, tournsize=3)

pop = toolbox.population(n=100)
result = algorithms.eaSimple(pop, toolbox, cxpb=0.7, mutpb=0.2, ngen=200)
```

- `DEAP`：功能完整的进化计算框架，支持自定义编码和算子
- `scikit-opt`（`sko.GA`）：中文文档友好，API 简洁，适合快速实验
- 关键参数：种群大小（50-200）、交叉率（0.6-0.9）、变异率（0.01-0.1）

## 国赛常见应用举例

- **TSP 及路径优化**：车辆路线规划、物流配送路径
- **2020-B 穿越沙漠问题**：多阶段路线策略的组合搜索
- **排班/排课问题**：复杂约束下的可行方案搜索
- **参数标定**：模型参数的全局优化估计
