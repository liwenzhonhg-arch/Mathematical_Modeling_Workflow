# 相关性分析

## 方法简介

相关性分析用于衡量两个或多个变量之间的线性或非线性关联程度和方向。它是特征筛选、变量关系探索和回归建模的前置步骤。

## 适用场景

- 探索性数据分析中变量间关系识别
- 特征选择与多重共线性检测
- 影响因素排序与筛选

## 基本原理

**Pearson 相关系数**（衡量线性关系）：

$$r = \frac{\sum_{i=1}^{n}(X_i - \bar{X})(Y_i - \bar{Y})}{\sqrt{\sum_{i=1}^{n}(X_i - \bar{X})^2 \cdot \sum_{i=1}^{n}(Y_i - \bar{Y})^2}}$$

$r \in [-1, 1]$，$|r|$ 越接近 1 线性关系越强。

**Spearman 秩相关系数**（衡量单调关系）：将原始数据转为秩次后计算 Pearson 系数，适用于非正态或有序数据。

**Kendall $\tau$ 系数**：基于一致对和不一致对的比例，对小样本和有并列值的数据更稳健。

## Python 实现要点

```python
import pandas as pd
from scipy import stats

# 相关系数矩阵
corr_matrix = df.corr(method='pearson')  # 或 'spearman', 'kendall'

# 带 p 值的相关检验
r, p_value = stats.pearsonr(x, y)
rho, p_value = stats.spearmanr(x, y)

# 热力图可视化
import seaborn as sns
sns.heatmap(corr_matrix, annot=True, cmap='RdBu_r', center=0)
```

要点：相关不等于因果；高相关变量（$|r| > 0.8$）进回归模型前需处理共线性（VIF 检验）。

## 国赛常见应用举例

- 评价类问题中筛选关键影响因素
- 多指标综合评价前的指标相关性检查与降维依据
- 时间序列中滞后相关性分析（如气温与用电量的延迟关联）
