# 主成分分析 (PCA)

## 方法简介

PCA 是一种线性降维方法，通过正交变换将原始高维变量转化为少数几个不相关的主成分，在信息损失最小的前提下降低数据维度。

## 适用场景

- 高维数据降维与可视化
- 消除多重共线性后再做回归
- 综合评价指标构建

## 基本原理

对标准化后的数据矩阵 $\mathbf{X}$，计算协方差矩阵 $\mathbf{C} = \frac{1}{n-1}\mathbf{X}^T\mathbf{X}$，对其进行特征分解：

$$\mathbf{C} \mathbf{v}_i = \lambda_i \mathbf{v}_i$$

特征值 $\lambda_1 \geq \lambda_2 \geq \cdots \geq \lambda_p$ 表示各主成分的方差贡献。第 $k$ 个主成分为：

$$Z_k = \mathbf{v}_k^T \mathbf{X}$$

选取前 $m$ 个主成分使累计方差贡献率达到 85%-95%：

$$\frac{\sum_{i=1}^{m} \lambda_i}{\sum_{i=1}^{p} \lambda_i} \geq 0.85$$

## Python 实现要点

```python
from sklearn.preprocessing import StandardScaler
from sklearn.decomposition import PCA

# 标准化（必须）
X_scaled = StandardScaler().fit_transform(X)

# PCA 降维
pca = PCA(n_components=0.95)  # 保留 95% 方差
X_pca = pca.fit_transform(X_scaled)

# 查看各主成分方差贡献率
print(pca.explained_variance_ratio_)
# 载荷矩阵（解释各原始变量的贡献）
loadings = pca.components_.T * np.sqrt(pca.explained_variance_)
```

关键：PCA 前必须标准化；载荷矩阵用于解释主成分含义，这在论文中是必要的分析步骤。

## 国赛常见应用举例

- 综合评价问题中构建综合得分（替代层次分析法/熵权法的降维方案）
- 多指标数据的降维预处理（如水质多指标评价）
- 聚类分析前的特征压缩，提升聚类效果
