# 随机森林

## 方法简介

随机森林（Random Forest）是由 Breiman 于 2001 年提出的集成学习方法，通过构建多棵决策树并汇总其预测结果来实现分类或回归。它利用 Bagging（自助采样聚合）和随机特征选择两重随机性来降低过拟合风险，具有精度高、抗噪强、可处理高维数据的优点。

## 适用场景

- 分类和回归任务中需要较高精度
- 特征维度较高，样本量中等以上
- 存在缺失值和噪声数据
- 需要评估特征重要性进行变量筛选

## 基本原理

**Bagging 过程**：从原始数据集 $D$（$n$ 个样本）中有放回地采样 $n$ 次，构造 $T$ 个自助样本集 $\{D_1, D_2, \ldots, D_T\}$。

**随机特征选择**：每棵树在每个节点分裂时，从全部 $p$ 个特征中随机选择 $m$ 个候选特征（通常 $m = \lfloor\sqrt{p}\rfloor$ 用于分类，$m = \lfloor p/3 \rfloor$ 用于回归）。

**集成输出**：分类任务用投票法，回归任务用平均法：

$$\hat{y} = \frac{1}{T}\sum_{t=1}^{T} h_t(x) \quad \text{（回归）}$$

$$\hat{y} = \arg\max_c \sum_{t=1}^{T} \mathbb{I}(h_t(x) = c) \quad \text{（分类）}$$

**特征重要性**：基于 OOB（袋外数据）的置换重要性，或基于基尼指数下降的 MDI 重要性。

泛化误差上界由两棵树的相关性 $\bar{\rho}$ 和单棵树的强度 $s$ 决定：$PE^* \leq \bar{\rho}(1-s^2)/s^2$。

## Python 实现要点

- `sklearn.ensemble.RandomForestClassifier` / `RandomForestRegressor`
- 关键参数：`n_estimators`（树的数量，建议 100-500）、`max_features`、`max_depth`
- `feature_importances_` 属性直接获取特征重要性排名
- OOB 评估：设置 `oob_score=True` 可免去交叉验证
- 可与 `GridSearchCV` 配合进行超参数调优

## 国赛常见应用举例

- **2020 C 题（信贷策略）**：随机森林对企业信用进行分类预测
- **医学诊断**：基于多维指标进行疾病分类并提取关键特征
- **遥感图像分类**：对地物类型进行像元级分类
