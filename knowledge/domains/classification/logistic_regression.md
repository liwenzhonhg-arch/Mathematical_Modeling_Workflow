# 逻辑回归

## 方法简介

逻辑回归（Logistic Regression）虽名为"回归"，实为经典的分类方法。它通过 Sigmoid 函数将线性回归的输出映射到 (0, 1) 区间，表示样本属于某一类别的概率。模型简单、可解释性强、训练高效，是二分类问题的首选基准方法。

## 适用场景

- 二分类问题（如是否违约、是否患病、是否通过）
- 需要输出分类概率而非仅标签
- 特征与对数几率之间近似线性
- 需要高可解释性的场景（系数直接反映影响方向和大小）

## 基本原理

设输入特征为 $\boldsymbol{x}$，逻辑回归模型为：

$$P(y=1|\boldsymbol{x}) = \sigma(\boldsymbol{w}^T \boldsymbol{x} + b) = \frac{1}{1 + e^{-(\boldsymbol{w}^T \boldsymbol{x} + b)}}$$

对数几率（logit）具有线性形式：

$$\ln \frac{P(y=1|\boldsymbol{x})}{1 - P(y=1|\boldsymbol{x})} = \boldsymbol{w}^T \boldsymbol{x} + b$$

参数通过最大似然估计（MLE）求解。对数似然函数：

$$\ell(\boldsymbol{w}, b) = \sum_{i=1}^{n} \left[ y_i \ln \hat{p}_i + (1 - y_i) \ln(1 - \hat{p}_i) \right]$$

等价于最小化交叉熵损失，使用梯度下降或牛顿法求解。

多分类扩展：Softmax 回归将输出推广到 $K$ 个类别：

$$P(y=k|\boldsymbol{x}) = \frac{e^{\boldsymbol{w}_k^T \boldsymbol{x}}}{\sum_{j=1}^{K} e^{\boldsymbol{w}_j^T \boldsymbol{x}}}$$

## Python 实现要点

- `sklearn.linear_model.LogisticRegression`，参数 `C` 控制正则化强度
- `predict_proba()` 输出概率值，可用于设定自定义阈值
- 正则化选择：`penalty='l1'`（特征选择）、`penalty='l2'`（默认，防过拟合）
- 评估指标：准确率、精确率、召回率、F1、AUC-ROC 曲线
- 类别不平衡时设置 `class_weight='balanced'` 或使用 SMOTE 过采样
- `statsmodels.api.Logit` 可输出系数的 p 值和置信区间，适合论文写作

## 国赛常见应用举例

- **2020 C 题（信贷策略）**：逻辑回归预测企业违约概率
- **疾病风险预测**：根据体检指标预测患病概率
- **用户流失预测**：基于行为特征建立二分类流失模型
