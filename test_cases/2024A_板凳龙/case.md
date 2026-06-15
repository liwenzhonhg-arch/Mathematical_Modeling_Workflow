# 案例：2024 国赛 A 题 “板凳龙”闹元宵

- **测试日期**：2026-06-15
- **题目来源**：2024 高教社杯全国大学生数学建模竞赛 A 题，题面与附件模板结构已写入 `workspace/2024_cumcm_A/problem.md`
- **题型**：几何/运动学仿真 + 碰撞检测 + 路径优化（A 类）

## 运行配置

沿用工作区 `.env` 中的 LLM 配置。前 6 阶段由上一轮 Claude Code 实践完成，本轮从 `paper` 阶段接续。

## 各阶段结果

| 阶段 | 最终版本 | 结果 |
|------|---------|------|
| analyze | v1 | 子问题分解为 q1-q5；`sub_problems.json` 正确包含 `result1.xlsx`、`result2.xlsx`、`result4.xlsx` 交付物清单 |
| eda | v1 | 本题无外部数据，数据探索阶段通过 |
| research | v1 | 方法路线围绕螺线运动、SAT 碰撞检测、二分/黄金分割优化展开 |
| model | v1 | Verifier 指出速度递推、最小螺距和 S 形曲线几何方程需严谨化 |
| code | v2 | 人工修复后运行成功，`run_log.txt` 记录修复项：递推方向、弧长符号、自实现 SAT、q2 搜索上限、q3 判定口径、q4 复合路径仿真 |
| solve | v1 | 成功产出 `results.json`、`sensitivity.json`、4 张灵敏度图，以及 `result1.xlsx`、`result2.xlsx`、`result4.xlsx` |
| paper | v1 | 论文生成完成；摘要 4 轮迭代最高 84 分，未达 85，人工压缩摘要后审批 |
| review | v1 | LLM review 成功，但 `checklist.json` 未被解析为独立文件；后续重跑 review 因联网外发风险被拦截，本轮未审批 review |
| compile/export | - | PDF 编译通过，`submission.zip` 打包完整 |

## 关键数值

- 问题 2 碰撞终止时刻：`412.473877 s`
- 问题 3 最小螺距：`0.450329 m`
- 问题 4 最优圆弧比例因子：`k = 2.219438`
- 问题 4 S 形路径长度：`13.621245 m`
- 问题 5 速度放大系数：`\gamma_{\max} = 1.592567`
- 问题 5 龙头最大速度：`1.255834 m/s`

## 成品清单（deliverables/）

- `paper.pdf`
- `submission.zip`
- `abstract.tex`
- `abstract_iterations.json`
- `numeric_audit_v1_stale.md`
- `results.json`
- `sensitivity.json`

`submission.zip` 内容已验证，包含：

- `paper.pdf`
- `code/solution.py`
- `figures/sensitivity_k.png`
- `figures/sensitivity_p1.png`
- `figures/sensitivity_p2.png`
- `figures/sensitivity_v_head.png`
- `result1.xlsx`
- `result2.xlsx`
- `result4.xlsx`

## 本次实测触发的工具修复（已落地进 mmw 代码）

1. **LaTeX 标题转义**：`compile` 用工作区名 `2024_cumcm_A` 作为标题时，下划线导致 `Missing $ inserted`。已在 `mmw/latex/compiler.py` 增加普通文本转义。
2. **编译目录图片复制改为增量复制**：Windows 下 `output/latex_build/figures/*.png` 可能被 TeX 或系统短暂占用，原先强删目录会 `PermissionError`。已改为已有同名同大小图片直接复用，避免编译准备阶段中断。

## 人在环路操作记录

- 摘要最高 84 分，主要扣分点是 609 字超限；人工压缩摘要后审批。
- `model_solution.tex` 引用了不存在的 `q1_trajectory_300s.png`、`q2_collision_config.png`、`q4_s_path.png`，导致 PDF 编译失败；人工删除这些 figure 环境，保留文字结果。
- 数值审计 v1 报 `18.2%` 与 `16.6324` 高置信缺出处。前者是派生百分比，后者是公式近似值；为满足数值出处链，人工删除非必要派生小数，仅保留公式和定性说明。本地纯代码审计确认高置信缺出处已清零。

## 验证记录

- `python -m mmw.cli compile --workspace 2024_cumcm_A`：通过，生成 `workspace/2024_cumcm_A/output/paper.pdf`
- `python -m mmw.cli export --workspace 2024_cumcm_A`：通过，生成 `workspace/2024_cumcm_A/output/submission.zip`
- `pytest tests/test_numeric_audit.py`：23 passed
- `pytest tests/test_stage_solve_collect.py --basetemp workspace\_pytest_tmp_stage_solve2`：7 passed（需要正常本机权限，沙箱下 pytest 临时目录会 PermissionError）

## 结论

2024A 验证了交付物链已端到端生效：`analyze` 的 deliverables 清单能传到 `code/solve/export`，最终三个官方结果表均进入提交包。主要新问题不在求解链，而在论文写作可靠性：Writer 会引用不存在图片，Reviewer 的 `checklist.json` artifact 解析不稳，且数值审计对论文中的派生计算值不做表达式推理。当前产出可形成完整提交包，但模型严谨性和路径/碰撞细节仍需人工加强。
