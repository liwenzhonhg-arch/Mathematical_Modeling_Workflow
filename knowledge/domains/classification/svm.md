# 支持向量机 (SVM)

## 方法简介

支持向量机（Support Vector Machine）是一种基于最大间隔准则的分类方法，通过寻找能将不同类别数据以最大间隔分开的超平面来实现分类。通过核函数技巧可处理非线性分类问题，在小样本、高维数据上表现优异。

## 适用场景

- 二分类和多分类问题（特别是小样本、高维度）
- 特征维度高于样本数量的情况
- 需要明确决策边界的分类任务
- 文本分类、图像识别、生物信息学等领域

## 基本原理

对于线性可分的二分类问题，寻找超平面 $\boldsymbol{w} \cdot \boldsymbol{x} + b = 0$ 使间隔最大化：

$$\max_{\boldsymbol{w}, b} \frac{2}{\|\boldsymbol{w}\|} \quad \Leftrightarrow \quad \min_{\boldsymbol{w}, b} \frac{1}{2}\|\boldsymbol{w}\|^2$$

约束：$y_i(\boldsymbol{w} \cdot \boldsymbol{x}_i + b) \geq 1, \quad i = 1, \ldots, n$

引入拉格朗日乘子 $\alpha_i$ 转化为对偶问题：

$$\max_{\alpha} \sum_{i=1}^{n}\alpha_i - \frac{1}{2}\sum_{i,j}\alpha_i \alpha_j y_i y_j (\boldsymbol{x}_i \cdot \boldsymbol{x}_j)$$

对于非线性问题，使用核函数 $K(\boldsymbol{x}_i, \boldsymbol{x}_j) = \phi(\boldsymbol{x}_i) \cdot \phi(\boldsymbol{x}_j)$ 将数据映射到高维空间。常用核函数：

- **线性核**：$K(x_i, x_j) = x_i \cdot x_j$
- **RBF 核**：$K(x_i, x_j) = \exp(-\gamma\|x_i - x_j\|^2)$
- **多项式核**：$K(x_i, x_j) = (\gamma x_i \cdot x_j + r)^d$

软间隔 SVM 引入松弛变量 $\xi_i$ 和惩罚参数 $C$，容许少量错分。

## Python 实现要点

- `sklearn.svm.SVC`（分类）、`SVR`（回归）
- 关键参数：`C`（正则化强度）、`kernel`（核函数类型）、`gamma`（RBF 核参数）
- 数据必须标准化（SVM 对尺度敏感）
- 用 `GridSearchCV` 搜索最优 `C` 和 `gamma` 组合
- 多分类策略：OvR（一对多）或 OvO（一对一），默认 OvO

## 国赛常见应用举例

- **2017 A 题（CT 系统参数标定）**：SVM 对重建图像中的材料进行分类
- **垃圾邮件分类**：基于文本特征的高维二分类
- **故障诊断**：工业设备多传感器信号的异常分类
