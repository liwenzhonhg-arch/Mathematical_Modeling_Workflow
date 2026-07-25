# 缺陷与待改进清单 — 2018A 盲测

## 严重

- [x] **[工具] Verifier 发现根本模型错误后仍可直接审批**：第二轮结构化判定 block，model 审批返回退出码 1。
- [x] **[工具] Coder 反思结果没有验证到实际代码**：Python 清洗增加首行说明剥离、全角句号处理和语法验证。
- [x] **[工具] code/solve 失败仍可审批传播**：失败或空结果不能审批。
- [x] **[工具] Writer 在空结果下生成安全相关数值**：空 solve 不能审批，paper 另有上游数据门禁。
- [x] **[工具] 题目明确要求的 `problem1.xlsx` 缺失，export 仍成功**：缺失时 solve/export 均阻断。
- [x] **[工具] review 明确要求回退求解阶段仍不影响状态流转**：checklist fail 会拒绝审批。

## 中等

- [x] **[工具] analyze 幻觉硬交付物**：第二轮只保留题面逐字出现的 `problem1.xlsx`。
- [x] **[工具] paper artifact 解析脆弱**：支持一次 `\end{artifact}` 规范化；仍缺关键章节时 CLI 返回 1。
- [x] **[工具] Reviewer 的 checklist 格式漂移**：支持 fenced JSON/Markdown 恢复，缺失时门禁拒绝。
- [x] **[工具] solve 收集 EDA 旧图**：只收集本次新增或重写图表。
- [x] **[提示词/工具] 外部检索需求只是占位符**：`research_evidence.json` 明确记录未执行外部检索。

## 轻微

- [x] **[EDA] IQR 对单调升温时序不适用**：结构摘要识别强趋势，要求对差分/变化率/残差检测并保留过渡段。
- [x] **[体验] 流式终端输出过大**：非 TTY 关闭 Live，第三轮 model 日志只有 6 行。

## 第 4 轮新增

- [x] **[工具] solution.py 尾部混入 Markdown 说明**：仅在前缀可通过 AST 时裁剪明确 Markdown 尾部。
- [x] **[工具] 全角字符清洗不能修复裸中文段落**：第 5 轮不再出现裸说明 SyntaxError。

## 第 5 轮新增

- [x] **[工具] Excel 表头识别错误**：注入 EDA 原始上下文，并要求探测表头、使用 `to_numeric(errors='coerce')`；第 6 轮未复现。
- [x] **[工具] 数据读取类同错误反思仍无效**：已加入 Excel/CSV 表头与脏行专用反思。

## 第 6 轮新增

- [x] **[代码] PDE 嵌套优化超过运行预算**：v5 经定向修订后可在 300 秒内完成，solve 重跑约 9 秒。
- [x] **[工具] 连续超时造成无上限消耗**：连续第 2 次超时即停止，保存失败证据并阻断审批。

## 第 7 轮新增

- [x] **[工具] code 重跑不复用失败代码**：v4/v5 均基于上一检查点代码和真实运行证据定向修订。
- [x] **[工具] 成功退出但结果含 NaN/Inf 仍可审批**：运行日志出现非有限数值时 code/solve 均不可审批，export 也会复检。
- [x] **[代码] `h_skin` 灵敏度边界与校准边界不一致**：review 反馈回传 code v6 后，四组扰动得到不同 RMSE，不再被同一下界裁平。
- [x] **[论文/工具] 4 个高置信派生数值缺出处**：code v6 将派生结果写入 `results.json`，最终 numeric audit 高置信缺出处为 0。

## 第 8 轮新增

- [x] **[工具] Reviewer 看不到已有参考文献和代码文件**：review 输入加入 `references.bib` 与 artifact 清单。
- [x] **[论文] PDF 缺少可复现代码附录**：paper 自动附带 `solution.py`，LaTeX 使用 `lstinputlisting` 组装。
- [x] **[格式] 摘要后正文未分页**：主模板在摘要后增加 `\clearpage`。
- [x] **[效率] 单个数值审计失败导致整篇论文重写**：只定向修订审计点名的小节。

## 第 9 轮新增

- [x] **[工具] solve schema 失败无法反馈给 code**：仅当 solve 的 `upstream_versions.code` 等于当前 code 时，将门禁错误和结构化产物摘录交给 Coder 定向修订。
- [x] **[代码/提示词] 灵敏度实验使用题型字段 `T_max`，缺少统一 `objective`**：solve v4 被门禁拒绝，code v8 修订后 solve v5 通过。
- [x] **[论文/工具] 有 `references.bib` 但正文没有引用**：paper 审批阻断；定向修订同时提供 BibTeX key 与正文，paper v10/v11 包含真实引用。
- [x] **[论文/工具] 正负号相反的 11.07°C 被绝对值误匹配**：数值审计默认保留符号，paper v11 修订后高置信缺出处为 0。
- [x] **[工程] editable 安装因 flat-layout 误发现 `knowledge/workspace/test_cases` 为顶层包**：setuptools 显式只发现 `mmw*`，安装 dry-run 通过。
- [ ] **[人工] 缺少真实参赛队号，无法生成本轮提交 PDF/ZIP**：在 workspace `config.yaml` 填写真实 `title`、`team_number`、`problem` 后重新 compile/export；不得使用占位队号。
