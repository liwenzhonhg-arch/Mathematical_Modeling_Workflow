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

## 第四轮：独立工作区完整产出测试

- **测试日期**：2026-07-13 至 2026-07-19
- **工作区**：`workspace/independent_2019C_20260713`
- **目标**：从独立输入工作区验证 8 阶段闭环、返工路由、PDF 编译和提交包导出。

### 最终激活版本

| 阶段 | 版本 | 状态 |
|------|------|------|
| analyze | v1 | approved |
| eda | v1 | approved |
| research | v1 | approved |
| model | v12 | approved |
| code | v22 | approved |
| solve | v17 | approved |
| paper | v13 | approved |
| review | v8 | approved |

### 闭环过程

1. Model/Verifier 多轮拦截错误的稳态排队公式、`NaN/Inf` 和未标定参数；修复了旧 `verify_status.json` 污染新验证轮次的问题。
2. Code/Solve 门禁连续拦截非有限数值、全零灵敏度、缺少子问题结果、基尼系数和吞吐量下降越界；Coder 最终在 v22 生成可运行代码，Solve v17 通过。
3. Paper v12 因正文无 `\cite` 被拒绝审批，定向修订到 v13 后通过。
4. Review v8 的程序化数值审计提取 123 个数值，匹配 122 个、缩放匹配 1 个，高置信缺出处 0 个。
5. `compile` 生成 10 页 `paper.pdf`；`export` 生成包含 7 个文件的 `submission.zip`，ZIP CRC 检查通过。

### 最终成品

- `paper.pdf`：10 页，216023 字节，SHA-256 `71b55e6a711768c05da8c1475ebab707f04483aa1c52191cba7741ed82a40c78`
- `submission.zip`：850981 字节，包含论文、`solution.py` 和 5 张图，CRC 无错误
- 摘要评分：86
- Reviewer 预估：省二等奖至省三等奖

### 最终关键结果

- 出租车需求到达率：`80.00 辆/小时`
- 司机排队等待：`2.00 分钟`
- 排队期望收益：`36.50 元`
- 空载返回期望收益：`2.50 元`
- 推荐上车点数量：`19`
- 计算平均等待时间：`0.00 分钟`（实际为极小值四舍五入，可信度仍需人工复核）
- 短途优先方案基尼系数：`0.51`
- 优先方案效率损失：`0.08`

### 验证记录

- `pytest -q tests/`：201 passed
- `python -m compileall -q mmw`：通过
- `python -m mmw.cli --help`：通过
- `python -m pip check`：No broken requirements found
- `python -m mmw.cli compile --workspace independent_2019C_20260713`：通过
- `python -m mmw.cli export --workspace independent_2019C_20260713`：通过

### 第四轮结论

工具已经证明可以从独立工作区完整产出论文和提交包，但“能产出”不等于“竞赛结论可靠”。当前论文仍有三处明显质量缺口：问题2真实标签不可观测；问题3等待时间显示为 `0.00` 分钟且推荐 19 个上车点，参数标定偏理想；摘要把 `1.3544` 写成缺失率。Reviewer 报告指出了这些问题，但结构化清单仍给出 `rework_stage: none`，说明评审结构化回退规则仍需加强。

## 第五轮：严格评审、数值和版式闭环

- **测试日期**：2026-07-19
- **工作区**：`workspace/independent_2019C_20260713`
- **目标**：不接受“能编译即完成”，继续返工直到结构化评审可审批、数值审计清零、核心图表进入正文且提交包可复验。

### 最终激活版本

| 阶段 | 版本 | 状态 |
|------|------|------|
| analyze | v1 | approved |
| eda | v1 | approved |
| research | v1 | approved |
| model | v19 | approved |
| code | v46 | approved |
| solve | v41 | approved |
| paper | v41 | approved |
| review | v22 | approved |

`paper_manifest.json` 固化的成品链为 `code v46 -> solve v41 -> paper v41 -> review v22`。另有一次未激活的 `code v47` 试验检查点，不属于最终论文和提交包。

### 本轮闭环过程

1. Reviewer 门禁开始以否定证据覆盖错误勾选，并按失败归属在 `model`、`code`、`paper` 间回退；最终 review v22 为 `12 pass + 2 warning + 0 fail`。
2. Model 多轮修订司机决策、验证不可用口径、上车点优化和短途优先仿真；Verifier 最终对 model v19 给出 `warning`，没有阻断项。
3. Solve 门禁新增比例物理范围、负数哨兵、灵敏度 `objective/change_pct` 一致性、零基准变化率、当前运行图表比例等检查，连续拦截了缺失率 `1.3544`、`-1` 结果、伪灵敏度变化率和异常图表。
4. Paper 门禁要求真实引用和全部核心 `fig_*.png` 入正文；数值审计发现的 `96.9`、`14.76`、`12.25` 等派生值经过“写入结构化结果或从论文删除”闭环处理。
5. 对真实标签、代理序列均不可用的验证，不再逼迫上游伪造成功；最终以 warning 记录数据限制，论文不宣称验证通过。

### 最终成品

- `paper.pdf`：13 页，904063 字节，SHA-256 `447da97ce0099d76e60df87dc4ecfff1d917059a1b6e532494473eac9b1ac11e`
- `submission.zip`：2042642 字节，10 个文件，CRC 检查无错误
- ZIP 内容：论文、`code/solution.py`、4 张核心图和 4 张灵敏度图
- 摘要评分：93，`needs_upstream_data=false`
- 数值审计：提取 206 个数值，匹配 202 个、缩放匹配 4 个，高置信缺出处 0 个、低置信可疑 0 个
- Reviewer 预估：省级二等奖；若补足模型验证，有望冲击省一等奖

### 最终关键结果

- 出租车需求到达率：`53.33 辆/小时`
- 排队效用 / 空载返回效用：`37.25 元 / 25.00 元`
- 问题2：代理序列为常数，验证不可用，未虚构验证通过
- 推荐上车点数量：`2`
- 推荐方案等待时间：`0.0041 小时`
- 推荐方案步行距离：`50.0 米`
- 推荐方案系统繁忙率：`0.4444`
- 短途阈值 / 优先权强度：`5 公里 / 0.2`
- 优先方案基尼系数：`0.276`

### 编译与版式检查

- PDF 共 13 页，不超过 20 页。
- 8 张当前运行图表均进入提交包；宽高比分布为 `1.598` 或 `2.495`，全部在 `1:4` 至 `4:1` 范围内。
- 逐页渲染检查了摘要、模型求解、核心图表、附录和参考文献；未发现裁切、超页或巨大图例。
- LaTeX 日志仅有 `h` 浮动体改为 `ht` 的提示，无 `Float too large`、未定义引用或编译错误。

### 第五轮结论

当前工作流已完成一次可复验的严格 8 阶段论文生产闭环：最终激活版本一致、论文可编译、提交包可解压、核心图表已嵌入、程序化数值审计无高置信缺出处数字。仍不能掩盖的最大限制是问题2缺少可用于区分司机决策的有效观测序列；本轮选择诚实降级为 warning，而不是伪造验证成功。
