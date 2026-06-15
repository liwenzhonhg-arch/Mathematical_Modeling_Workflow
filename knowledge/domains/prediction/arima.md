# ARIMA 时间序列

## 方法简介

ARIMA（自回归积分滑动平均模型）是处理时间序列数据的经典方法，由 Box 和 Jenkins 提出。模型记为 ARIMA(p, d, q)，其中 p 为自回归阶数、d 为差分次数、q 为移动平均阶数。适合对具有趋势性和短期相关性的时间序列进行预测。

## 适用场景

- 单变量时间序列的短中期预测
- 数据具有明显的时间依赖结构（自相关性）
- 经济指标、销量、流量等平稳或可差分平稳的序列

## 基本原理

对原始序列做 $d$ 阶差分使其平稳后，建立 ARMA 模型：

$$\phi(B)(1-B)^d X_t = \theta(B)\varepsilon_t$$

其中自回归部分：

$$\phi(B) = 1 - \phi_1 B - \phi_2 B^2 - \cdots - \phi_p B^p$$

移动平均部分：

$$\theta(B) = 1 + \theta_1 B + \theta_2 B^2 + \cdots + \theta_q B^q$$

$B$ 为滞后算子，$\varepsilon_t$ 为白噪声。建模流程：平稳性检验（ADF 检验） -> 差分 -> 定阶（ACF/PACF 图或 AIC/BIC 准则） -> 参数估计 -> 残差白噪声检验 -> 预测。

## Python 实现要点

- `statsmodels.tsa.arima.model.ARIMA` 是核心类
- 用 `adfuller()` 做 ADF 单位根检验判断平稳性
- `pmdarima.auto_arima()` 可自动搜索最优 (p, d, q) 组合
- 季节性数据使用 SARIMA：`SARIMAX(order=(p,d,q), seasonal_order=(P,D,Q,s))`
- 预测区间通过 `get_forecast().conf_int()` 获取

## 国赛常见应用举例

- **人口预测**：对历史人口数据建立 ARIMA 模型进行中短期预测
- **股票/基金收益预测**：金融时间序列分析
- **2022 C 题（古玻璃）**：时间序列分析化学成分的演变趋势
