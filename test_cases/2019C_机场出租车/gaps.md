# 缺陷与待改进清单 — 2019C

分类：[工具] mmw 代码 / [提示词] prompts/ / [人工] 赛时人脑攻坚。修复后打勾并注明修复方式。

## 严重（影响得分）

- [x] **[工具] code 阶段缺少 `solution.py` 仍标记 completed**：本轮 `code` 检查点最初只有 `code_explanation.md`、`meta.json`、`status.json`，没有 `solution.py` 和 `run_log.txt`，但阶段状态仍为 completed。→ 已在 `stage_code.py` 增加 `_has_solution_py()` 门禁，缺代码时拒绝保存 completed 检查点，并新增 `tests/test_stage_code_gate.py`。
- [x] **[提示词/工具] Coder artifact 格式不稳**：Coder 可能输出普通 Markdown 代码块而非 `solution.py` artifact，导致检查点无法保存代码。→ 现有 Coder 已有裸代码块兜底；本轮新增 stage_code 门禁，保证兜底失败时不会误完成。
- [x] **[提示词] Research v1 忽略监督学习标签可观测性**：v1 主推 Logistic/决策树，但本题缺少可靠的“送客司机是否排队”真实标签。→ 已在 `system/researcher.j2` 和 `research.j2` 增加“标签可观测性铁律”。
- [x] **[提示词→人工修订] Writer 扩写出大量无出处数值**：review 阶段数值审计发现 26 个高置信缺出处数值。→ 第二轮补强 `results.json` 并手工修订 `paper v3`，纯代码审计确认 89 个数值全部匹配，缺出处清零。
- [x] **[人工] q3 推荐上车点数量为 1 的结论不可信**：该结果与优秀案例和机场运营常识不一致。→ 第二轮改用高峰设计流量 `418.4` 辆/小时和单点服务率 `40.0` 辆/小时，推荐 `14` 个上车点。

## 中等（影响质量）

- [x] **[提示词] Model/Verifier 对“真实标签不可观测”约束不够敏感**：虽然后续人工修正了 `model.md`，但模型产物仍出现过准确率、召回率、混淆矩阵等不成立表述。→ 已在 `system/modeler.j2`、`model.j2`、`system/verifier.j2`、`verify.j2` 加入数据可观测性和工程常识性审查。
- [x] **[提示词] Reviewer 又建议构建分类器验证司机决策**：review 中建议用逻辑回归比较真实司机决策准确率，但本轮数据并无可靠真实决策标签。→ 已在 `system/reviewer.j2` 和 `review.j2` 明确：真实标签不可观测时不得建议监督学习准确率作为主验证。
- [x] **[工具→代码产物补强] 数值审计不能区分 EDA 统计值与求解结果来源**：`1769`、`1198`、`67.7%` 等来自 EDA 或原始数据统计，但未进入 `results.json`，因此被判高置信缺出处。→ 第二轮把 EDA 统计写入 `results.json`，审计通过。
- [x] **[工具→代码产物补强] `results.json` 指标粒度不足**：摘要评审指出问题二缺少系统吞吐量具体数值。→ 第二轮新增 q1/q2/q3/q4 关键指标，`paper v3` 和 `review v2` 均基于新版结果。
- [x] **[提示词→人工修订] Paper 阶段摘要达标但质量偏低**：摘要评分 85 分刚好达标，问题包括吞吐量缺失、方法名不够具体、字数偏短。→ 第二轮手工压缩摘要并补足方法与结果，review v2 给摘要质量 9/10。
- [ ] **[人工] 当前题面不是官方原文**：`problem.md` 基于公开题意整理，后续应替换为官方 C 题 PDF 的准确题面。
- [ ] **[人工] 当前数据不是官方原始附件**：出租车数据来自 GitHub 处理后 CSV，机场到达行程只有 71 条，限制模型验证。

## 轻微（体验/健壮性）

- [x] **[工具] solve 清理临时脚本导致成功阶段返回失败**：Windows 下 `solution.py` 删除触发 `PermissionError`，原逻辑在保存 solve 检查点后仍抛异常。→ 已新增 `_cleanup_temp_script()`，清理失败只提示，测试覆盖 `PermissionError`。
- [ ] **[工具] solve 清理失败时提示级别过重**：当前用 `print_error` 输出清理失败，虽然退出码为 0，但视觉上像阶段失败。后续可增加 `print_warning` 或将这类非致命问题标为 warning。
- [ ] **[工具] pytest 沙箱内临时目录权限异常**：默认临时目录和 `--basetemp` 指到仓库内都会出现 `PermissionError`；沙箱外 pytest 可通过。需要确认是 Codex 沙箱限制还是本机 ACL 问题。
- [x] **[工具→代码产物修订] Matplotlib 中文字体缺失**：手工运行 `solution.py` 时出现 CJK glyph 缺失警告，图中的中文标签可能显示异常。→ 第二轮将图表标签改为英文，手工运行无字体警告。
- [ ] **[工具] pytest 失败留下不可访问临时目录**：本轮在 `test_cases/pytest_tmp*` 留下不可访问目录；已加 `.gitignore` 忽略，但清理需用户确认。

## 已修复（本次实测中）

- [x] **[提示词→人工约束] 方法主线从监督分类改为期望收益/排队论/仿真/公平性优化**：通过 `references/method_constraints.md` 引导 research v2 修正。
- [x] **[人工修复] `model.md` 中不成立的监督学习验证表述已改为代理验证**：避免在无标签数据上承诺准确率、召回率或混淆矩阵。
- [x] **[工具] `test_cases/pytest_tmp*/` 已加入 `.gitignore`**：避免不可访问临时目录影响后续 git 上传。
