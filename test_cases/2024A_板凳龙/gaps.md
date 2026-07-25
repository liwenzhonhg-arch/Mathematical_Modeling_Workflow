# 缺陷与待改进清单 — 2024A

分类：[工具] mmw 代码 / [提示词] prompts/ / [人工] 赛时人脑攻坚。修复后打勾并注明方式。

## 严重（影响得分）

- [ ] **[人工] 速度递推与刚性约束推导仍需人工复核**：Verifier 与 Reviewer 均指出速度投影公式推导不够完整，需确认切向方向、杆方向投影、分母接近 0 的物理解释和数值处理。
- [ ] **[人工] 问题 3 最小螺距模型口径需复核**：当前以“全程无碰撞且能到达调头边界”为判据，Reviewer 认为题意中“可达性/碰撞约束/恰好进入边界”的逻辑需更严谨说明。
- [ ] **[人工] S 形调头路径几何推导不足**：`R_s = -|A|^2/(A\cdot n_A)`、法向方向、圆心角与 `k` 的关系仍需要补充推导，才能支撑 q4/q5 结果可信度。

## 中等（影响质量）

- [x] **[提示词] Writer 引用不存在的图片**：`model_solution.tex` 引用 `q1_trajectory_300s.png`、`q2_collision_config.png`、`q4_s_path.png`，实际只生成灵敏度图，导致编译失败。→ 本轮人工删除不存在图片的 figure 环境；后续应在 writer 提示词中要求“只引用 figures_list.json 或 workspace/figures 中真实存在的图片”。
- [x] **[工具] Reviewer 的 `checklist.json` artifact 解析失败**：Reviewer 已支持命名 JSON、fenced JSON 和 Markdown 勾选项三层恢复；缺少合法非空清单时审批门禁拒绝，回归测试通过。
- [x] **[工具] 数值审计不理解派生表达式**：现在只对论文中明确写出、且每个操作数均可追溯的三项四则表达式计算派生候选；2024A 本地重审高置信缺出处为 0。
- [x] **[提示词/工具] 摘要 4 轮迭代最高 84 分未达标**：最后一次修订收到 600 字硬约束；paper 审批同时拒绝低于 85 分或正文超过 600 字的摘要。

## 轻微（体验/健壮性）

- [x] **[工具] LaTeX 标题未转义下划线**：`2024_cumcm_A` 进入 `\title{}` 后触发 `Missing $ inserted`。→ `compiler.py` 新增 `_escape_latex_text()`，组装 main.tex 时转义标题。
- [x] **[工具] Windows 编译目录图片强删容易 PermissionError**：`prepare_compile_dir()` 每次删除 `output/latex_build/figures`，遇到图片短暂占用会失败。→ 改为增量复制，同名同大小图片直接复用。
- [ ] **[工具] pytest 在沙箱下临时目录权限异常**：默认 `C:\Users\moonman\AppData\Local\Temp\pytest-of-moonman` 和工作区内 `--basetemp` 均出现 `PermissionError`；用正常本机权限运行通过。需要确认是 Codex 沙箱限制还是本机临时目录 ACL 问题。
- [x] **[工具] review 重跑依赖联网 LLM，外发风险需要显式确认**：新增 `mmw audit --workspace <name>`，纯本地复用 review 的确定性数值审计，不读取 API Key、不调用 LLM；联网评审仍由 `run review` 单独触发。

## 已修复（本次实测中）

- [x] **[提示词→人工修复] 非必要派生小数导致数值审计高置信缺出处**：删除 `18.2%/18.1%` 和 `16.6324/16.6320` 这类非 results 原始数值，本地审计确认高置信缺出处清零。
- [x] **[工具] 交付物链端到端验证**：`result1.xlsx`、`result2.xlsx`、`result4.xlsx` 均由 solve 阶段生成，并被 `export` 打入 `submission.zip`。
- [x] **[工具] PDF 完整性校验继续有效**：首次编译留下损坏 PDF 时被 `%%EOF` 校验拦住，避免误报成功。
