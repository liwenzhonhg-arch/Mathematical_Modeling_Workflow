# 方差分析 (ANOVA)

## 方法简介

方差分析用于比较三组及以上样本均值是否存在显著差异。核心思想是将数据的总变异分解为组间变异和组内变异，通过二者比值判断分组因素是否有显著效应。

## 适用场景

- 多种方案/策略效果对比
- 多因素对指标的影响分析
- 实验设计中处理效应的检验

## 基本原理

单因素 ANOVA 将总平方和分解：

$$SS_T = SS_B + SS_W$$

其中 $SS_B = \sum_{i=1}^{k} n_i(\bar{X}_i - \bar{X})^2$ 为组间平方和，$SS_W = \sum_{i=1}^{k}\sum_{j=1}^{n_i}(X_{ij} - \bar{X}_i)^2$ 为组内平方和。构造 F 统计量：

$$F = \frac{SS_B / (k-1)}{SS_W / (N-k)}$$

当 $F > F_{\alpha}(k-1, N-k)$ 时拒绝"各组均值相等"的原假设。双因素 ANOVA 进一步考察交互效应。

## Python 实现要点

```python
from scipy import stats
import statsmodels.api as sm
from statsmodels.formula.api import ols

# 单因素 ANOVA
F_stat, p_value = stats.f_oneway(group1, group2, group3)

# 双因素 ANOVA（含交互项）
model = ols('y ~ C(A) * C(B)', data=df).fit()
anova_table = sm.stats.anova_lm(model, typ=2)
```

注意：ANOVA 显著后需做事后多重比较（如 Tukey HSD），用 `statsmodels.stats.multicomp.pairwise_tukeyhsd()`。

## 国赛常见应用举例

- 比较多种调度策略对生产效率的影响
- 分析不同区域/时段对某指标的差异
- 实验方案优选中多水平因素的效果对比
