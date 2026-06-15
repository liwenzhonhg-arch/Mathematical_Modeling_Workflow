# 贝叶斯方法

## 方法简介

贝叶斯方法以贝叶斯定理为基础，将先验知识与观测数据结合，得到参数的后验分布。与频率派方法不同，贝叶斯方法将参数视为随机变量，能自然地融入领域知识并量化不确定性。

## 适用场景

- 小样本条件下的参数估计
- 需要融合专家经验或历史数据的建模
- 分类问题（朴素贝叶斯）、序贯决策与更新

## 基本原理

贝叶斯定理：

$$P(\theta | D) = \frac{P(D | \theta) \cdot P(\theta)}{P(D)} \propto P(D | \theta) \cdot P(\theta)$$

其中 $P(\theta)$ 为先验分布，$P(D|\theta)$ 为似然函数，$P(\theta|D)$ 为后验分布。随着数据量增加，后验分布逐渐由数据主导。

**朴素贝叶斯分类器**假设特征条件独立：

$$P(C_k | \mathbf{x}) \propto P(C_k) \prod_{i=1}^{n} P(x_i | C_k)$$

## Python 实现要点

```python
# 朴素贝叶斯分类
from sklearn.naive_bayes import GaussianNB
model = GaussianNB()
model.fit(X_train, y_train)

# 贝叶斯参数估计（PyMC）
import pymc as pm
with pm.Model() as model:
    mu = pm.Normal('mu', mu=0, sigma=10)
    sigma = pm.HalfNormal('sigma', sigma=5)
    obs = pm.Normal('obs', mu=mu, sigma=sigma, observed=data)
    trace = pm.sample(2000)
```

轻量替代：无需 PyMC 时可用共轭先验手动推导后验（如 Beta-Binomial）。

## 国赛常见应用举例

- 医疗诊断中结合先验概率和检测结果的后验推断
- 文本分类/垃圾邮件识别（朴素贝叶斯）
- 不确定环境下的动态决策与风险评估
