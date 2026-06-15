# 假设检验

## 方法简介

假设检验是统计推断的核心方法，通过样本数据判断对总体参数的某个假设是否成立。其本质是"反证法"思想：先假设原假设 $H_0$ 为真，再看数据是否与之矛盾。

## 适用场景

- 两组数据均值是否存在显著差异
- 某个比例/均值是否达到预期标准
- 处理前后效果是否有显著变化

## 基本原理

设原假设 $H_0: \mu = \mu_0$，备择假设 $H_1: \mu \neq \mu_0$。构造检验统计量：

$$t = \frac{\bar{X} - \mu_0}{S / \sqrt{n}}$$

其中 $\bar{X}$ 为样本均值，$S$ 为样本标准差，$n$ 为样本量。当 $|t| > t_{\alpha/2}(n-1)$ 时拒绝 $H_0$。p 值表示在 $H_0$ 为真的前提下，观察到当前或更极端结果的概率，$p < \alpha$ 则拒绝原假设。

## Python 实现要点

```python
from scipy import stats

# 单样本 t 检验
t_stat, p_value = stats.ttest_1samp(data, popmean=mu_0)

# 双样本 t 检验
t_stat, p_value = stats.ttest_ind(group1, group2, equal_var=False)

# 配对 t 检验
t_stat, p_value = stats.ttest_rel(before, after)
```

关键点：先用 `stats.shapiro()` 检验正态性；非正态数据改用 `stats.mannwhitneyu()`（非参数检验）。

## 国赛常见应用举例

- 2020 B 题：检验不同穿刺方案成功率是否有显著差异
- 评价类题目中判断某因素对结果的影响是否显著
- 预测模型残差是否满足零均值假设的验证
