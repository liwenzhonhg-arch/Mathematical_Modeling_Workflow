# 多目标优化 (Multi-Objective Optimization)

## 方法简介

多目标优化同时优化两个或多个相互冲突的目标函数。由于各目标之间存在权衡关系，通常不存在单一最优解，而是求取一组**Pareto 最优解**（非支配解集），供决策者根据偏好选择。

## 适用场景

- 多个目标相互矛盾：成本 vs 质量、效率 vs 公平、收益 vs 风险
- 需要展示目标间的权衡关系，辅助决策
- 工程设计、资源分配、投资组合等多准则决策场景

## 基本原理

**Pareto 支配**：解 $\mathbf{x}^*$ 是 Pareto 最优的，当且仅当不存在另一个可行解在所有目标上都不劣于 $\mathbf{x}^*$ 且至少一个目标严格更优。

$$\min \quad \{f_1(\mathbf{x}), f_2(\mathbf{x}), \ldots, f_k(\mathbf{x})\} \quad \text{s.t.} \quad \mathbf{x} \in \Omega$$

主要求解策略：

1. **加权求和法**：$\min \sum_{i=1}^k w_i f_i(\mathbf{x})$，通过改变权重 $w_i$ 获得不同 Pareto 解，简单但无法找到非凸 Pareto 前沿上的点
2. **$\varepsilon$-约束法**：优化一个目标，其余目标作为约束 $f_j(\mathbf{x}) \leq \varepsilon_j$，可以找到非凸前沿
3. **进化多目标算法**：NSGA-II 通过非支配排序和拥挤度距离维持 Pareto 前沿的多样性和收敛性；MOEA/D 将多目标分解为一组单目标子问题

## Python 实现要点

```python
# 方法一：加权求和 + scipy
from scipy.optimize import minimize
res = minimize(lambda x: w1*f1(x) + w2*f2(x), x0, constraints=cons)

# 方法二：NSGA-II（pymoo 框架）
from pymoo.algorithms.moo.nsga2 import NSGA2
from pymoo.optimize import minimize as moo_minimize
from pymoo.core.problem import Problem

class MyProblem(Problem):
    def __init__(self):
        super().__init__(n_var=2, n_obj=2, n_constr=0, xl=0.0, xu=1.0)
    def _evaluate(self, x, out, *args, **kwargs):
        out["F"] = np.column_stack([f1(x), f2(x)])

res = moo_minimize(MyProblem(), NSGA2(pop_size=100), termination=('n_gen', 200))
# res.F 为 Pareto 前沿，res.X 为对应决策变量
```

- `pymoo`：多目标优化主流框架，内置 NSGA-II/III、MOEA/D 等算法
- `DEAP`：也支持多目标，灵活度更高但需更多手动配置
- 结果可视化：绘制 Pareto 前沿散点图，直观展示目标间权衡

## 国赛常见应用举例

- **2022-B 无人机遂行编队飞行**：时间与能耗的多目标优化
- **投资组合**：收益最大化与风险最小化的 Pareto 分析
- **物流调度**：成本、时效、客户满意度的多目标均衡
- **资源分配**：效率与公平性之间的权衡决策
