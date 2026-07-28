# 移动热坐标单位契约 Spec

状态：**已实现并经 r8 失败候选对照验证，待真实 Coder 续跑（2026-07-29）**

## 问题

r8 Coder 用秒构造 `sample_times`，位置节点单位为厘米，却把题面的
`70 cm/min` 原值直接传给 `simulate_moving_slab(speed=...)`。模块按
`position=speed*time` 计算，等价于 `70 cm/s`，使物体约 6 秒走完整个炉体。

在已修正 Robin 边界后，原失败候选的 NRMSE 为 `0.270448`；仅把传入速度改为
`speed/60` 后降至 `0.096197`，证明坐标单位错配是独立真实根因。

## 规则

1. `sample_times` 的时间单位、`speed` 的分母时间单位必须一致。
2. `air_position_knots`、`transfer_position_knots` 与 `speed*time` 的位置单位必须
   一致。
3. 题面速度为 `cm/min` 且采样时间为秒时，调用受测模块前显式换成 `cm/s`；结束
   时间仍按同一单位计算。
4. 模块保持通用，不猜测或自动转换调用方单位。

## 验收

- 模块文档、Modeler、Coder、错误反思、运行摘要和知识条目使用同一契约。
- 自动测试锁定提示中的 `cm/min -> cm/s` 示例，并保留通用合成回归。
- r8 后续候选不得再把 `70 cm/min` 当作 `70 cm/s`。
