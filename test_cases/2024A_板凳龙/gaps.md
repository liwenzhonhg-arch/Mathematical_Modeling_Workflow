# 缺陷与待改进清单 — 2024A

分类：[工具] mmw 代码 / [提示词] prompts/ / [人工] 赛时人脑攻坚。修复后打勾并注明方式。

## 严重（影响得分）

- [ ] **[人工] 速度递推与刚性约束推导仍需人工复核**：Verifier 与 Reviewer 均指出速度投影公式推导不够完整，需确认切向方向、杆方向投影、分母接近 0 的物理解释和数值处理。
- [ ] **[人工] 问题 3 最小螺距模型口径需复核**：当前以“全程无碰撞且能到达调头边界”为判据，Reviewer 认为题意中“可达性/碰撞约束/恰好进入边界”的逻辑需更严谨说明。
- [ ] **[人工] S 形调头路径几何推导不足**：`R_s = -|A|^2/(A\cdot n_A)`、法向方向、圆心角与 `k` 的关系仍需要补充推导，才能支撑 q4/q5 结果可信度。

## 中等（影响质量）

- [x] **[提示词] Writer 引用不存在的图片**：`model_solution.tex` 引用 `q1_trajectory_300s.png`、`q2_collision_config.png`、`q4_s_path.png`，实际只生成灵敏度图，导致编译失败。→ 本轮人工删除不存在图片的 figure 环境；后续应在 writer 提示词中要求“只引用 figures_list.json 或 workspace/figures 中真实存在的图片”。
- [ ] **[工具] Reviewer 的 `checklist.json` artifact 解析失败**：v1 输出中出现 `checklist.json` 内容，但最终检查点只保存了 `review.md` 和 `numeric_audit.md`，缺独立 `checklist.json`。疑似 Reviewer 输出把 JSON 包进 Markdown 代码块或 artifact 格式不稳。
- [ ] **[工具] 数值审计不理解派生表达式**：`(0.55-0.450329)/0.55` 这类论文内明示计算仍被判缺出处。当前处理是删除非必要派生小数；长期可考虑允许“同一上下文内由已匹配数值构成的简单表达式”降级为低置信提示。
- [ ] **[提示词] 摘要 4 轮迭代最高 84 分未达标**：扣分主因是字数略超 600。需要让 writer 在最后一轮更强制压缩，而不是只维持信息完整。

## 轻微（体验/健壮性）

- [x] **[工具] LaTeX 标题未转义下划线**：`2024_cumcm_A` 进入 `\title{}` 后触发 `Missing $ inserted`。→ `compiler.py` 新增 `_escape_latex_text()`，组装 main.tex 时转义标题。
- [x] **[工具] Windows 编译目录图片强删容易 PermissionError**：`prepare_compile_dir()` 每次删除 `output/latex_build/figures`，遇到图片短暂占用会失败。→ 改为增量复制，同名同大小图片直接复用。
- [ ] **[工具] pytest 在沙箱下临时目录权限异常**：默认 `C:\Users\moonman\AppData\Local\Temp\pytest-of-moonman` 和工作区内 `--basetemp` 均出现 `PermissionError`；用正常本机权限运行通过。需要确认是 Codex 沙箱限制还是本机临时目录 ACL 问题。
- [ ] **[工具] review 重跑依赖联网 LLM，外发风险需要显式确认**：本轮尝试重跑 review v2 时因需要向外部 LLM 发送论文内容被安全策略拦截。后续应把“纯本地数值审计”和“联网 LLM 评审”拆成两个命令，便于低风险复核。

## 已修复（本次实测中）

- [x] **[提示词→人工修复] 非必要派生小数导致数值审计高置信缺出处**：删除 `18.2%/18.1%` 和 `16.6324/16.6320` 这类非 results 原始数值，本地审计确认高置信缺出处清零。
- [x] **[工具] 交付物链端到端验证**：`result1.xlsx`、`result2.xlsx`、`result4.xlsx` 均由 solve 阶段生成，并被 `export` 打入 `submission.zip`。
- [x] **[工具] PDF 完整性校验继续有效**：首次编译留下损坏 PDF 时被 `%%EOF` 校验拦住，避免误报成功。
