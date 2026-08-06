# 案例：2018 国赛 A 题“高温作业专用服装设计”盲测

## 测试性质

- 轮次：三题盲测第 3 题
- 测试日期：2026-07-10
- 快照 SHA-256：`825815dd405e8b112a6d39a94e3de5e60983d14595d8222802946dde2c4f7a22`
- 题面和附件来自 `yushugulao/CUMCM-Archive` 的公开赛题目录。
- `references/` 为空，未向 Agent 提供优秀论文、评阅要点、题解或参考代码。
- 未人工修改任何检查点产物、代码、数据、图表或论文。

## 运行配置干预

Coder 专用 API Key 与前两题相同，无法通过认证。为继续检验工作流后半程，仅在当次进程中让 Coder 使用已工作的默认 Key，没有修改 `.env`、提示词或任何产物。干预记录保存在 workspace 的 `logs/blind_interventions.jsonl`。

`paper` 首次运行因 Writer 的 artifact 结束标签格式错误而未保存检查点；按盲测协议允许同阶段原样重试一次，第二次生成 v1。重试期间没有修改任何输入或产物。

## 阶段结果

| 阶段 | 版本 | 结果 |
|---|---:|---|
| analyze | v1 | 正确拆为 3 个子问题；正确识别 `problem1.xlsx`，但又把题目未要求的 `result2.xlsx`、`result3.xlsx` 幻觉为硬交付物 |
| eda | v1 | 读取实验温度并生成 4 张图，提取约 48.08°C 稳态等数据特征；用 IQR 把正常升温段标为大量异常点，但最终没有删除 |
| research | v1 | 给出多层非稳态热传导、参数校准和代理优化路线；列出的外部搜索需求未真正获得资料 |
| model | v1 | 建立 PDE 与优化框架；Verifier 发现根本性边界/观测位置错误：模型输出无法与“皮肤外侧温度”实验值正确比较，继续优化会推荐不安全厚度 |
| code | v1 | 两轮都因生成文件首行包含未注释中文而报 `SyntaxError: invalid character '。'`；反思文本声称已删除该行，实际生成代码仍保留，阶段仍 completed |
| solve | v1 | 立即因同一语法错误失败；`results.json=[]`、`sensitivity.json={}`，仍保存 completed，并收集 4 张 EDA 旧图 |
| paper | v1 | 首次因 artifact 格式失败；原样重试后，在空结果下编造 6.0 mm、46.5°C、4.8 min 等结果，摘要评分 78 且 `needs_upstream_data=true`，仍保存 completed |
| review | v1 | 审计发现 11 个高置信缺出处数值；Reviewer 明确要求回到求解阶段、指出代码附录和可追溯结果缺失，但 `checklist.json` 未独立解析保存，阶段仍可审批 |

## 流水线报告与真实状态的差异

- CLI 最终显示 8 个阶段均为 approved，PDF 编译与 zip 导出成功。
- 实际模型有根本边界定义问题，代码连语法都未通过，所有求解结果为空，题目明确要求的 `problem1.xlsx` 缺失。
- Writer 仍生成一组“满足约束”的具体最优厚度和温度；这些数值没有任何求解证据。
- `export` 明确报告 `problem1.xlsx`、`result2.xlsx`、`result3.xlsx` 缺失，仍返回成功并生成压缩包；后两项本身还是 analyze 阶段幻觉出的要求。

## Token

- 输入：95,274
- 输出：56,097
- 合计：151,371

## 自主版暂评

| 维度 | 得分 |
|---|---:|
| 流程完成度 | 7/15 |
| 硬交付物 | 0/15 |
| 结果可复现 | 0/15 |
| 硬约束满足 | 0/20 |
| 模型正确性 | 4/20 |
| 论文与证据一致 | 1/15 |
| **总分** | **12/100** |

这不是对论文奖项的模拟评定，而是对工作流“能否独立形成可信交付物”的暂评。

## 结论

第三题表明 Verifier 并非完全无效：它已经发现会导致工程安全结论错误的根本模型问题；真正的缺口是系统没有把验证结论变成状态机约束。当前“验证”和“评审”只产出报告，不控制能否继续。

## 第 2 轮：质量门禁回归（2026-07-10）

- 新 workspace：`blind2_2018_cumcm_A`，未复用首轮检查点。
- analyze 只保留题面明确要求的 `problem1.xlsx`，没有再把问题 2、3 结果幻觉为 Excel 硬交付物。
- Verifier 输出 `severity=block`，明确指出把皮肤外侧测量点设为 37°C 恒温边界会使输出与实际温升矛盾。
- `approve model` 返回退出码 1，流水线在根本模型错误处停止；未生成代码、论文或提交包。

本轮修复了首轮最关键的问题：Verifier 已发现的工程安全错误现在会真正阻断下游。

## 第 3 轮：Verifier block 定向修订（2026-07-10）

- `run model` 检测到 v1 的 `severity=block`，没有重新盲写模型，而是把原 `verify_status.json` 和报告交给 Modeler 定向修订。
- 生成 model v2，`revision_history.json` 保留 v1 的边界条件问题和本轮验证结果。
- v2 将人体内部 37°C 与皮肤外侧观测点分开，引入皮肤等效换热边界；Verifier 由 block 变为 pass。
- v2 审批成功；重定向日志只有 6 行、414 bytes。

这是自动修订闭环的首个真实通过案例：系统不仅能停下，还能针对明确根因修正并重新验证。

## 第 4 轮：Coder Key 修复后实跑（2026-07-10）

- Coder 成功调用并生成 solution.py。
- solution artifact 尾部混入 Markdown 代码说明，导致第 846 行出现裸文本。
- 最终错误：`SyntaxError: invalid character '、' (U+3001)`；反思后仍未移除尾部说明。
- code v1 审批被拒绝，后续阶段未运行。

结论：首行自然语言清洗已经覆盖，但 artifact 内“代码后追加说明”的格式漂移仍未处理。

## 第 5 轮：solution 清洗增强后回归（2026-07-10）

- code v2 不再出现尾部 Markdown 裸文本，安全裁剪生效。
- 新错误为读取附件时把表头字符串 `时间 (s)` 当作数据并执行 `astype(float)`。
- 连续 3 轮反思仍未修正 Excel 表头识别，code 审批被拒绝。

结论：artifact 格式问题已解决，下一瓶颈是 Coder 对真实 Excel 表头/数据起始行的识别。

## 第 6 轮：Excel 上下文与超时回归（2026-07-11）

- Coder 获得 EDA 原始输出片段，并被要求使用 `header=None`、`pd.to_numeric(errors='coerce')` 和非数据行核验；本轮不再出现 `时间 (s)` 转 float 错误。
- 新瓶颈是多层热传导有限差分嵌套优化：初版和反思版均超过 300 秒。
- 反思循环在连续第 2 次超时后停止，code v3 保存失败证据，审批返回 1；没有进入 solve/paper。

结论：数据入口问题已越过，但当前生成的 PDE 优化复杂度仍不满足竞赛工作流的运行预算。

## 第 7 轮：跨版本修订推进到 review（2026-07-11）

- code v4 复用 v3 超时证据后在第二次执行完成，但输出包含 `NaN/Inf` 和发散温度；新增非有限数值门禁使旧的已审批版本也无法 export。
- code v5 继续复用失败代码，依次处理超时、NaN/Inf、JSON 序列化错误，第 4 次执行成功。
- 最终校准 `RMSE=0.4676°C`；问题2得到 `L_II=9.3688mm`，问题3得到 `L_II=20.2138mm`、`L_IV=4.6144mm`，约束检查通过。
- solve v1 与 paper v1 已审批；review 初次发现 8 个高置信缺出处数值。
- 数值候选加入题面原文和分钟/秒换算后，review v3 降为 4 个；剩余均是 Writer 自行计算但未写回结构化结果的差值/厚度和，审批继续被拒绝。

结论：跨检查点修订解决了反复从零生成的问题，2018A 已完整走到最终评审；当前剩余问题集中在论文数值出处和灵敏度边界一致性。

## 第 8 轮：完整闭环与最终导出（2026-07-11）

- review v3 的失败证据回传 code v5，Coder 生成 v6：`h_skin` 的四组扰动结果不再相同，派生厚度和/差值写入 `results.json`。
- solve v2 通过；paper v2 的程序数值审计首次达到 0 个高置信缺出处数值。
- LaTeX 组装增加摘要后分页、`solution.py` 代码附录，并把参考文献和 artifact 清单提供给 Reviewer，消除“缺参考文献/附录”的上下文误判。
- Writer 对单个审计失败只修订被点名的 `sensitivity.tex`，不再整篇随机重写；review v6 checklist 全部 pass。
- PDF 编译成功，`submission.zip` 包含 `paper.pdf`、`code/solution.py`、`problem1.xlsx` 和图表；最终快照已更新到本案例 `deliverables/`。

结论：2018A 已完成从模型修订、代码执行、求解、论文、评审、编译到导出的完整可信闭环。

## 第 9 轮：版本溯源、提交门禁与真实回归（2026-07-13）

- 以 `blind2_2018_cumcm_A` 继续回归，新链路最终激活版本为 code v8、solve v5、paper v11、review v11，8 个阶段全部 approved，且无上游变更警告。
- solve v4 首次暴露 `sensitivity.json` 用题型字段 `T_max` 代替统一字段 `objective`；系统现在会拒绝该产物，并把同一 code 版本产生的 solve 门禁错误回传给 Coder。v8 修订后统一 schema，solve v5 通过。
- 灵敏度目标由“校准 RMSE”改为“皮肤最高温度”，覆盖 `h`、`h_skin` 两个参数；论文不再把校准误差误写成模型输出灵敏度。
- Writer 首次仍生成了未引用的 `references.bib`；paper 门禁阻断审批。定向修订现在同时提供正文与 BibTeX 条目，paper v10 起产生真实 `\\cite{...}`。
- review v10 的程序审计发现 1 个符号相反的 11.07°C；paper v11 定向删除/改写后，review v11 高置信缺出处数值为 0，checklist 仅保留“附录运行说明” warning，可审批。
- 全量自动化回归为 `186 passed`；`compileall`、`pip check` 和 editable 安装 dry-run 均通过。
- 本轮没有覆盖旧的 `deliverables/` 快照：新编译门禁要求先填写真实 `title`、`team_number`、`problem`，当前 workspace 的 `team_number` 为空，因此 `compile` 按设计返回退出码 1。待提供真实队号后再生成新 PDF、manifest 和 submission.zip。

结论：本轮验证了“下游 schema 失败回传 code → 重算 solve → 论文引用门禁 → 数值审计定向修订”的闭环；剩余提交阻塞不是模型或代码错误，而是缺少不得猜测的真实参赛队号。

## 第 10 轮：第二独立 Oracle（2026-07-28）

- 增加 evaluator-only `reference_solver.py` 与 schema v2 `reference_expected.json`，不读取或复用 MMW 生成结果。
- Oracle 交叉采用组委会公开展示的 A401、A440 两篇论文及一份独立参赛论文。三者对“最优”的权衡和离散精度不同，因此只用公开结果包络验证关键厚度、约束可行性和重复性，不把单篇论文的单点答案当作唯一真值。
- 公开基线：A401 为问题 2 的 II 层 19.3 mm、问题 3 的 II/IV 层 21.7/6.4 mm；A440 为 17.5 mm、19.2/6.4 mm；独立参赛论文为 12.26 mm、15.42/3.00 mm。
- 当前旧快照的 `q2_最优L_II=10.4172 mm` 低于三份公开论文中报告的可行下界，新的 Oracle 会正确拒绝该结果；不能因旧流程已全阶段审批而降级门禁。
- `core-v1` 中 2018A 的要求由 `scenario-feasible` 提升为 `verified`。这使基准套件现在包含两个独立 Oracle 案例。

来源：

- https://dxs.moe.gov.cn/zx/2018/1101/1541041099335.pdf
- https://dxs.moe.gov.cn/zx/a/hd_sxjm_sxjmlw_2018qgdxssxjmjslwzs_2018atlw/240206/1699834.shtml
- https://xinxinliu-bioinfor.github.io/Liuxinxin.github/2018_CUMCM_Entry.pdf
