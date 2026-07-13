# 案例：2019 国赛 C 题 “机场的出租车问题”

- **测试日期**：2026-06-16
- **题目来源**：2019 高教社杯全国大学生数学建模竞赛 C 题，当前题面为公开题意整理版，写入 `workspace/2019_cumcm_C/problem.md`
- **题型**：交通运筹 / 排队论 / 司机决策 / 公平性优化

## 参考资料

- 本地优秀论文图片目录：`G:\MCM\神秘资源\2019全国大学生数学建模竞赛论文展示`
- C 题优秀论文候选：`C044`、`C137`、`C308`
- 本轮已人工查看 `C044\1.jpeg`，确认题名为“机场的出租车问题”，摘要涉及效用模型、排队模拟、M/M/c、短途优先权。
- GitHub 数据参考：`Shulin-Li22/airport_taxi_optimization-CUMCM2019`
- GitHub 论文参考：`mame0521/2019CUMCM`

## 运行配置

工作区：`workspace/2019_cumcm_C`

数据文件：

- `data/raw/flight_data.xlsx`：航班计划到达数据，字段为 `计划到达时间`、`出发地/经停点`、`航空公司/航班号`
- `data/raw/Taxi_Trips.csv`：处理后的出租车行程数据，无表头，字段约定见 `data/raw/source_notes.md`

关键限制：

- 当前未找到官方题面 PDF，题面是公开题意整理版。
- `Taxi_Trips.csv` 不是官方原始附件，而是 GitHub 处理后数据。
- 数据中机场到达行程极少，不能可靠构造“送客司机是否排队”的真实监督标签。

## 各阶段结果

| 阶段 | 最终版本 | 结果 |
|------|---------|------|
| analyze | v1 | 成功拆分 q1-q4，并识别 `result1.xlsx` 到 `result4.xlsx` 四个硬性交付物 |
| eda | v1 | 成功读取无表头出租车 CSV 与航班 Excel，生成 6 张 EDA 图；发现行程速度和时长存在明显异常值 |
| research | v2 | v1 错误倾向监督分类；加入 `references/method_constraints.md` 后，v2 改为期望收益、排队论、仿真和公平性优化主线 |
| model | v1 | Verifier 指出期望收益、q4 目标函数、M/M/c 单位等问题；人工修正“真实标签/分类准确率”相关表述后审批 |
| code | v1 | 原阶段标记 completed 但未保存 `solution.py`；为推进测验人工补入 `solution.py` 并运行成功 |
| solve | v2 | 正式重跑成功，收集 `results.json`、`sensitivity.json`、12 张图和 4 个 Excel 交付物；修复了清理临时脚本导致 CLI 失败的问题 |
| paper | v1 | 论文生成完成，摘要评分 85 分达标；评审指出问题二缺少吞吐量等具体数值 |
| review | v1 | 数值审计发现 26 个高置信缺出处数值；LLM 评审认为整体约为省三/成功参赛水平，本轮未审批 review |

## 关键数值

- 有效出租车行程：`12669`
- 机场出发行程：`7398`
- 机场到达行程：`71`
- 有效航班记录：`571`
- 机场出发行程平均距离：`5.7418 km`
- 市区行程平均距离：`4.5552 km`
- 推荐上车点数量：`1`
- 短途优先阈值：`3.7797 km`
- 优先权前基尼系数：`0.2195`
- 优先权后基尼系数：`0.2057`

## 成品清单（deliverables/）

- `results.json`
- `sensitivity.json`
- `abstract_score.json`
- `numeric_audit.md`
- `review.md`

本轮没有编译 PDF，也没有导出 `submission.zip`。原因是 review 已明确指出数值出处和模型合理性缺陷，继续打包意义不大。

## 本次实测触发的工具修复（已落地进 mmw 代码）

1. **solve 临时脚本清理不再导致阶段失败**：Windows 下 `workspace/<case>/solution.py` 可能短暂拒绝删除，原逻辑在检查点保存后仍抛出 `PermissionError`，导致 CLI 返回失败。已改为尽力清理，失败只提示，不影响已完成检查点。
2. **新增回归测试**：`tests/test_stage_solve_collect.py` 增加 `_cleanup_temp_script` 对 `PermissionError` 的覆盖。
3. **忽略 pytest 临时目录**：失败测试在 `test_cases/pytest_tmp*` 留下不可访问目录，已在 `.gitignore` 中忽略，避免误入 git。

## 人在环路操作记录

- 人工建立 `references/README.md` 和 `references/method_constraints.md`，约束方法选择，避免把无真实标签问题硬做监督学习。
- 人工修正 `model.md` 中“准确率/混淆矩阵”等不成立的验证表述，改为代理验证和一致性检查。
- 人工补入 `checkpoints/05_code/v1/solution.py`，因为 code 阶段原产物缺失实际代码文件。
- 未删除 `workspace/2019_cumcm_C/solution.py` 临时文件；该文件由 solve 清理失败保留，删除需用户确认。

## 验证记录

- `python checkpoints\05_code\v1\solution.py`：通过，生成四个结果表和结构化结果。
- `python -m mmw.cli run solve --workspace 2019_cumcm_C`：v2 通过，临时脚本清理仅警告。
- `pytest tests/test_stage_solve_collect.py --basetemp test_cases\pytest_tmp_run_2019c_escalated`：8 passed（需沙箱外权限；沙箱内 pytest 临时目录会拒绝访问）。
- `python -m mmw.cli run paper --workspace 2019_cumcm_C`：通过，摘要 85 分。
- `python -m mmw.cli run review --workspace 2019_cumcm_C`：通过，数值审计发现 26 个高置信缺出处数值。

## 结论

2019C 暴露的问题比 2024A 更贴近真实赛场：方法选择必须先判断标签是否可观测，不能把“司机决策”粗暴转成监督分类；论文阶段必须严格限制只能使用 `results.json`、`sensitivity.json` 和可审计派生值，否则会扩写出大量无出处数字。本轮工作流能跑完整 8 阶段，但当前成品不应视为可提交论文，主要价值是形成下一轮提示词和工具修复清单。

## 第二轮：面向可上交版本的修订

- **修订日期**：2026-06-16
- **目标**：在不重新换题的前提下，把 2019C 从“工作流测验样本”修改为基本可上交的作品。

### 关键修订

1. **补强结构化结果**：`solution.py` 新增 EDA 统计、问题 1 临界参数、问题 2 代理验证指标、问题 3 排队系统关键指标和问题 4 效率损失指标，避免论文扩写出无出处数字。
2. **修正问题 3 结论**：原先推荐 `1` 个上车点不可信。新版本以高峰设计流量 `418.4` 辆/小时、单点服务率 `40.0` 辆/小时建 M/M/c 模型，推荐 `14` 个上车点，服务强度 `0.7471`，平均排队等待 `0.0964` 分钟。
3. **修正司机决策模型**：把空载返回策略的返城与市区接客时间成本设为更合理的 `25 + 10` 分钟；新结果显示基准场景排队收益 `2.1839` 元、空载返回收益 `5.9160` 元，乘客选择出租车比例临界值为 `0.2756`，全天有 `6` 个时段建议排队。
4. **重写论文数值链**：手工修订 `paper v3` 摘要、正文和灵敏度分析，删除不能由结果支撑的表述；本地纯代码数值审计确认所有 `89` 个提取数值均能匹配求解产出。
5. **补充正文引用**：在蒙特卡洛模拟、M/M/c 排队论和基尼系数处加入引用，使参考文献能进入编译结果。

### 第二轮阶段状态

| 阶段 | 最终版本 | 结果 |
|------|---------|------|
| solve | v4 | 生成新版 `results.json`、`sensitivity.json`、图表和四个 `result*.xlsx` |
| paper | v3 | 人工修订后审批；数值审计本地通过，摘要压缩到可用版本 |
| review | v2 | 正式评审通过；数值审计无缺出处，LLM 评审预估“全国二等奖/省一等奖”水平 |
| compile | - | 通过，生成 `workspace/2019_cumcm_C/output/paper.pdf` |
| export | - | 通过，生成 `workspace/2019_cumcm_C/output/submission.zip` |

### 第二轮成品清单（deliverables/）

- `paper.pdf`
- `solution.py`
- `results.json`
- `sensitivity.json`
- `numeric_audit.md`
- `review.md`
- `abstract_score.json`（保留第一轮快照，第二轮 Writer 的摘要评分解析失败，最终以手工审计和 review 为准）

`submission.zip` 内容已验证，包含：

- `paper.pdf`
- `code/solution.py`
- 12 张图表
- `result1.xlsx`
- `result2.xlsx`
- `result3.xlsx`
- `result4.xlsx`

### 第二轮验证记录

- `python checkpoints\05_code\v1\solution.py`：通过，无 pandas 时间解析和 Matplotlib 中文字体警告。
- `python -m mmw.cli run solve --workspace 2019_cumcm_C`：v4 通过。
- 本地数值审计：`89` 个数值全部匹配，`0` 个高置信缺出处，`0` 个低置信可疑。
- `python -m mmw.cli run review --workspace 2019_cumcm_C`：v2 通过，正式审计无缺出处。
- `python -m mmw.cli compile --workspace 2019_cumcm_C`：通过，生成 `paper.pdf`。
- `python -m mmw.cli export --workspace 2019_cumcm_C`：通过，生成 `submission.zip`。

### 第二轮结论

当前版本已经具备“可上交”的基本形态：论文可编译、提交包完整、代码与四个结果表齐全、论文关键数值可追溯。仍需人工赛前复核的问题是：题面不是官方原文，数据来自 GitHub 处理版；M/M/c 中“车辆到达率/乘客到达率”的口径还可以进一步严谨化；2013 年数据的时效性需要在正式参赛时换成题目原始附件。

## 第三轮：把反馈固化到工作流

- **修订日期**：2026-06-16
- **目标**：不只修 2019C 单题，而是把本轮暴露出的失败模式沉淀到 `mmw` 的提示词、阶段门禁和回归测试中。

### 已落地改动

1. **code 阶段门禁**：`stage_code.py` 增加 `_has_solution_py()`，缺少非空 `solution.py` 时拒绝保存 completed 检查点。
2. **code 阶段回归测试**：新增 `tests/test_stage_code_gate.py`，覆盖“缺 solution.py 不保存检查点”。
3. **Research 提示词强化**：`system/researcher.j2` 和 `research.j2` 增加标签可观测性检查；无真实标签时不得主推监督学习或准确率验证。
4. **Coder 提示词强化**：`system/coder.j2` 和 `code.j2` 明确 `results.json` 必须包含 EDA 统计和所有论文会引用的中间量，不只写最终最优值。
5. **Writer 提示词强化**：`system/writer.j2` 和 `paper_section.j2` 明确全文所有结果性数值只能来自结构化求解产出；缺数值时不能编造。
6. **Reviewer 提示词强化**：`system/reviewer.j2` 和 `review.j2` 明确高置信缺出处数值要降级结果可信度；真实标签不可观测时不得建议监督学习准确率作为主验证。
7. **Modeler/Verifier 提示词强化**：`system/modeler.j2`、`model.j2`、`system/verifier.j2`、`verify.j2` 增加数据可观测性与工程常识性检查，防止模型阶段重新引入不可验证指标或不现实结论。

### 第三轮验证记录

- `pytest tests/test_stage_code_gate.py tests/test_coder_retry.py`：7 passed。
- `pytest tests/test_stage_solve_collect.py`：当前沙箱内仍受 pytest 临时目录权限问题影响，未能完整复跑；此前沙箱外已通过 8 passed。

### 第三轮结论

本轮训练反馈已经从单题人工修订推进到工作流层面。下一轮应换新真题验证：Research 是否还会误推监督分类，Model/Verifier 是否能拦住不可观测标签，Writer 是否还会写出无出处数字，code 阶段是否还会在缺少 `solution.py` 时误完成。
