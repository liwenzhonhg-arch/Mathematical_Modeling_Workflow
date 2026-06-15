# 模拟退火 (Simulated Annealing)

## 方法简介

模拟退火算法模拟金属退火过程中的降温结晶机制。通过以一定概率接受劣解，避免陷入局部最优，从而实现全局搜索。算法结构简单、实现容易、通用性强，是最常用的元启发式算法之一。

## 适用场景

- 目标函数有大量局部极值的全局优化
- 组合优化问题（TSP、图着色、调度）
- 搜索空间复杂、梯度信息不可用
- 对解的质量要求高但可接受较长计算时间

## 基本原理

**Metropolis 准则**：在温度 $T$ 下，从当前解 $\mathbf{x}$ 移动到邻域解 $\mathbf{x'}$，接受概率为：

$$P(\text{accept}) = \begin{cases} 1 & \text{if } \Delta f = f(\mathbf{x'}) - f(\mathbf{x}) < 0 \\ \exp(-\Delta f / T) & \text{if } \Delta f \geq 0 \end{cases}$$

核心流程：
1. 设定初温 $T_0$、终温 $T_{\min}$、降温系数 $\alpha$
2. 在当前温度下，多次执行：生成邻域解 → 计算目标差 → 按 Metropolis 准则接受/拒绝
3. 降温：$T \leftarrow \alpha T$（通常 $\alpha \in [0.9, 0.999]$）
4. 重复直至 $T < T_{\min}$

高温阶段广泛探索，低温阶段精细开发。温度调度方案直接影响求解质量。

## Python 实现要点

```python
import math, random

def simulated_annealing(f, x0, T0=1000, T_min=1e-6, alpha=0.995, max_iter=200):
    x_best = x_cur = x0
    T = T0
    while T > T_min:
        for _ in range(max_iter):
            x_new = neighbor(x_cur)  # 生成邻域解
            delta = f(x_new) - f(x_cur)
            if delta < 0 or random.random() < math.exp(-delta / T):
                x_cur = x_new
                if f(x_cur) < f(x_best):
                    x_best = x_cur
        T *= alpha
    return x_best
```

- `scipy.optimize.dual_annealing`：内置双退火算法，支持边界约束
- `scikit-opt`（`sko.SA`）：封装完善，支持 TSP 等常见问题
- 关键调参：初温要足够高（初始接受率 > 0.8）、降温要足够慢、内循环次数要充分

## 国赛常见应用举例

- **TSP 类问题**：城市遍历、物流路径的全局优化
- **2021-B 乙醇偶合制备 C4 烯烃**：反应条件参数优化
- **布局优化**：设施选址、芯片布局等空间安排问题
- **调度问题**：车间作业排序、考试排程
