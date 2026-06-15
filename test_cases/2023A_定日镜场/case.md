# 案例：2023 国赛 A 题 定日镜场的优化设计

- **测试日期**：2026-06-11
- **题目来源**：[linggm3/2023_CUMCM_National-First-Prize](https://github.com/linggm3/2023_CUMCM_National-First-Prize) 的 A题.pdf 与 data1.xlsx（1745 面定日镜位置，半径 107.9~337.1 m，与官方附件一致）
- **题型**：机理/仿真型（A 类）——太阳几何 + 光学效率链 + 重计算 + 布局优化

## 运行配置

| Agent | 模型 | max_tokens |
|-------|------|-----------|
| modeler / verifier / coder | mimo-v2.5-pro（Token Plan） | 32768 / 32768 / 49152 |
| 其余 | deepseek-chat | 8192 |

## 各阶段结果

| 阶段 | 最终版本 | 结果 |
|------|---------|------|
| analyze / eda / research | v1 | 顺利通过；EDA（重构后流程）真实执行了镜位分布分析 |
| model | v1 | MiMo 机理建模完整；Verifier 抓到 3 个实质问题：方位角仅余弦公式无法区分上午/下午（会把下午太阳判到东边）、阴影与遮挡计算逻辑描述混淆、截断效率"点光源"简化与考虑镜面尺寸矛盾 |
| code | v1 | 第 3 轮跑通（前两轮：全角句号 SyntaxError、变量名 NameError——反思循环自愈）；**1745 镜 × 60 时点在 300s 超时内完成**（problem.md 中的性能提示起效，coder 做了网格离散+邻域筛选） |
| solve | v1 | results.json + sensitivity.json 正常产出 |
| paper | v2 | **v1 的 BATCH1 输出未用 artifact 标签（纯 Markdown），4 章节全丢且被链式审批放行** → 触发两个工具修复；v2 八章节齐全；摘要 4 轮 54→59→52→50 不达标且回退 → 触发 keep-best 修复，人工取第 2 轮（59 分）版本替换 |
| review | v2 | 数值审计：118 个数值 105 匹配 + 3 缩放，7 个高置信缺出处待人工核 |

## 关键数值

- 问题 1 年平均输出热功率 **30.09 MW**、单位面积 0.479 kW/m²——量级正确但比参考答案（约 36~39 MW）低约 20%，疑似阴影/截断效率估计偏保守（见 gaps）
- 摘要最高 59 分：主因是 q2/q3 优化设计未产出具体数值进 results.json，writer 受禁伪造铁律约束只能写「详见正文」——防伪造机制正常工作，暴露的是上游算法产出不全

## 成品清单（deliverables/）

- `paper.pdf`（11 页有效）、`abstract.tex`（59 分版）、`abstract_iterations.json`、`numeric_audit.md`、`results.json`、`sensitivity.json`

## 本次实测触发的工具修复（已落地进 mmw 代码）

1. **writer 批次格式重试**：批次产出无 artifact 标签时带期望文件清单重试一次（BATCH1 用 Markdown 标题导致 4 章节全丢）
2. **stage_paper 关键章节守卫**：缺 abstract/model_solution 中止不保存，替代旧的「原始响应塞进 model_solution.tex」垃圾兜底
3. **摘要迭代 keep-best**：始终保留历史最高分版本（修订可能回退，本案例 4 轮 54→59→52→50 实证）
4. **关键词硬指标识别 `\keywords{}` 命令**（原先只认中文「关键词」字样，误报缺失）

## 结论

A 类题验证了重计算场景可控（性能提示 + MiMo 工程化实现），Verifier 对机理公式链的查错能力再次得到实证（方位角符号歧义是该题最经典的坑）。短板在优化设计类子问题（q2/q3）的算法产出完整性——与 2023B 的 q4 同型，确认「布局/设计优化是 LLM 的系统性弱项，必须人工主攻」。
