# mmw 下一迭代 Spec：从“能阻止错误”到“能修正错误”

状态：**2018A 已完成可信 8 阶段闭环并导出；2020A 回退到 model block**  
制定日期：2026-07-10  
验证结果：`pytest tests/ -q` 为 177 passed，`compileall` 与 `git diff --check` 通过。

## 1. 当前阶段

项目已经完成第一阶段目标：**知道什么时候不能继续**。

- 2021B：Verifier 发现收率公式量纲错误，model 审批被阻断。
- 2018A：Verifier 发现皮肤边界/观测位置错误，model 审批被阻断。
- 2020A：Coder Key 已修复；当前 code 因连续 300 秒超时被门禁阻断。
- 2023B：可信结果通过 code/solve/paper/review 门禁并成功导出。

当前不是“流水线仍会造假”的问题，而是“流水线发现错误后只会停，不会修”。

## 2. 当前问题排序

### P0：运行前配置没有闭环

Coder 专用 API Key 无效，但系统到完成 analyze、EDA、research、model 后才发现，浪费前序时间和 Token。

### P1：Verifier block 后没有自动修正

结构化 `verify_status.json` 已能指出根因，但 Modeler 不会读取 block issues 生成修订版。2021B 和 2018A 因此只能停在 model v1。

### P2：Coder 的运行环境兼容性仍不稳

首轮 2020A 生成代码使用当前 NumPy 已移除的 `np.trapz`。现有语法清洗能处理包裹文本和全角字符，但还不能预防库版本/API 兼容错误。

### P3：剩余工程缺陷

- paper 的错误闭合标签 `\end{artifact}` 仍可能导致解析失败但 CLI 返回 0。
- IQR 直接用于单调升温时序会把正常过渡段标成异常值。
- Rich Live 在重定向日志时输出重复且过大；部分 Windows 输出仍有编码显示问题。
- 工作树目前有 68 个变更/未跟踪条目，且包含本轮之前已有的用户改动，不能直接整体提交。

## 3. 本轮目标

1. 在任何 LLM 阶段执行前发现全部角色的无效配置。
2. Verifier 判定 block 时，Modeler 最多自动修正 2 轮，每轮都生成独立版本和验证证据。
3. Coder 在调用前获得真实依赖版本，在执行前完成语法和关键 API 兼容检查。
4. 收口 paper、EDA 和终端日志三个剩余高频缺陷。
5. 整理可提交变更边界，不混入未知历史改动。

## 4. 非目标

- 不增加新 Agent。
- 不自动审批任何阶段。
- 不修改 `.env`、Key、CI/CD 或系统配置。
- 不安装新依赖。
- 不承诺三题都能一次求出正确答案；本轮只要求能够自动修正已明确指出的错误。

## 5. 功能规格

### 5.1 配置预检

新增显式命令：

```bash
python -m mmw.cli check-config
```

行为：

- 汇总 8 个角色最终生效的 `base_url`、model、max_tokens，只显示 Key 是否存在及末 4 位掩码，不打印完整 Key。
- 对每个不同的 `(base_url, api_key, model)` 组合执行一次最小请求。
- 401/403 立即返回失败；连接超时、限流和服务端错误按现有可重试规则处理。
- 任一角色失败时命令退出码为 1，并列出受影响角色。
- `mmw run analyze` 不自动联网预检，避免隐式额外费用；完整竞赛开始前由用户显式运行。

验收：当前配置应在开始前直接指出 Coder 失败，而不是到阶段 5 才发现。

### 5.2 Modeler 自动修正闭环

当首次 Verifier 返回 `severity=block`：

1. 把 `verify_status.json` 和 `verify_report.md` 作为修订输入交给同一 Modeler。
2. 要求只修 block issues，不进行无关重写。
3. 重新运行 Verifier。
4. 最多 2 轮；每轮保存独立 model 版本，不覆盖历史产物。
5. 最终仍为 block 时保留最新版 completed，但审批门禁继续拒绝。
6. pass/warning 时停止修订，等待人工审批。

新增/调整 artifact：

- `model.md`
- `equations.json`
- `params.json`
- `verify_report.md`
- `verify_status.json`
- `revision_history.json`：轮次、修复 issue、前后 severity、Token。

验收：

- 2021B 必须修正百分数口径，收率公式结果不再可能超过 100%。
- 2018A 必须修正皮肤外侧观测位置/边界条件，不得把测量点固定为 37°C。
- 不要求自动审批；最终 severity 不是 block 才允许用户审批。

### 5.3 Coder 环境兼容

在 Coder prompt 中增加程序生成的运行环境摘要：Python、NumPy、pandas、SciPy、scikit-learn 版本。

执行前检查：

- `ast.parse()` 必须通过。
- 对已知移除 API 做最小映射检查，首项为 `np.trapz -> np.trapezoid`。
- 兼容错误进入现有反思循环，但同一错误第二次出现时停止。
- 不做通用 AST 重写器；只维护盲测实际遇到的确定性兼容项。

验收：用固定代码片段证明 `np.trapz` 会在执行前被识别并修正/拒绝，不能重复运行两次才发现。

### 5.4 paper artifact 收口

- `run paper` 缺关键章节时必须返回退出码 1。
- 允许把完全匹配的 `\end{artifact}` 规范化为 `</artifact>` 后重新解析一次。
- 不对任意损坏 XML 猜测修复；一次规范化后仍缺 artifact 就失败。

验收：复现 2018A 首轮响应，确认能够恢复；无法恢复的响应不保存 paper 检查点。

### 5.5 EDA 时序异常检测

- 对有时间列且明显单调/趋势型序列，不在原始温度值上直接使用全局 IQR 判异常。
- 默认对一阶差分、变化率或模型残差做异常检测。
- 报告必须区分“统计异常”和“物理不合理”，不得自动删除过渡段。

验收：2018A 的正常升温段不再被报告为 21.68% 异常数据。

### 5.6 终端输出

- 非 TTY 或输出重定向时禁用 Rich Live 重绘，仅输出阶段开始、重试、错误和完成摘要。
- TTY 交互模式保留 Live。
- Windows 子进程继续强制 UTF-8；日志文件始终 UTF-8。

验收：单阶段重定向日志不再包含重复面板，日志体积显著下降且保留最终错误。

## 6. 实施顺序

| 批次 | 内容 | 依赖 |
|---|---|---|
| A | `check-config` 与测试 | 无 |
| B | Modeler block 修订闭环 | A 通过后 |
| C | Coder 版本摘要与 `np.trapz` 兼容检查 | A 通过后 |
| D | paper parser、EDA 时序规则、非 TTY 日志 | B/C 后 |
| E | 三题第三轮回归、2023B 正常回归、变更清单整理 | A-D 完成 |

## 7. 测试要求

```bash
pytest tests/test_config.py
pytest tests/test_state_machine.py
pytest tests/test_coder_retry.py
pytest tests/test_stage_eda_digest.py
pytest tests/
python -m compileall -q mmw
```

新增最小测试：

- 认证失败不重试，`check-config` 返回 1 且不泄露 Key。
- Modeler block -> 修订 -> warning/pass；连续 block 最多两轮。
- `np.trapz` 在执行前被识别。
- `\end{artifact}` 单次规范化成功，无法恢复时失败。
- 趋势时序不使用原始值 IQR。
- 非 TTY 不启用 Live。

## 8. 回归标准

### 失败题

- 2021B、2018A：不只停在 model；应至少生成一次有针对性的 model 修订并重新验证。
- 2020A：配置预检先指出 Coder Key；用户确认修复后，`np.trapz` 问题未再出现，当前暴露为计算超时。

### 正常题

- 2023B：原有合法 active versions 仍能通过质量检查并导出。

### 工程

- 完整测试通过。
- 不修改 `.env`。
- 不删除任何旧检查点或盲测证据。
- 提交前只选择本轮明确修改的文件；68 个现有工作树条目必须先分类，不整体提交。

## 9. 外部条件处理结果

用户已明确确认修改 `.env`：移除失效的 Coder 专用覆盖项，让 Coder 回退到可用默认 Key。修改后 `check-config` 的 8 个角色全部通过。

## 10. 2026-07-10 执行结果

- `check-config` 已实现：按配置组合去重探测，Key 只显示末 4 位；修复后全部配置通过。
- Modeler 修订闭环已实现：block 最多修订 2 轮，每轮保存版本和 `revision_history.json`。
- 2018A 实测：以 model v1 block 为输入定向修订，生成 v2；Verifier 从 block 变为 pass，v2 可审批。
- 2021B 实测：重新建模生成 v2，Verifier 未再判 block，v2 可审批；未触发额外修订。
- 2020A 实测：Verifier 不再把固定的 10～11 温区建议为决策变量；两次定向修订流程最终生成 model v5，severity 降为 warning 并已激活。
- Coder 获得真实 Python/NumPy/pandas/SciPy/scikit-learn 版本摘要；当前 NumPy 无 `np.trapz` 时自动替换为 `np.trapezoid`。
- paper 支持一次 `\end{artifact}` 规范化；关键章节缺失时 `run paper` 返回退出码 1。
- EDA 结构摘要能识别强趋势时序，明确要求使用差分/变化率/残差而不是原始值全局 IQR。
- 非 TTY/重定向输出已关闭 Rich Live；两次 model 实测日志均只有 6 行、低于 500 字节。
- 2023B 正常路径再次 export 成功。
- 用户确认后已移除失效的 Coder 覆盖项，8 个 Agent 配置全部通过。三题随后均进入 code，分别因奇异矩阵、未定义变量和尾部 Markdown 裸文本失败；审批门禁均正确阻断。
- 第二轮 Coder 修复加入安全尾部裁剪、奇异矩阵伪逆和升级反思。回归后：2021B code/solve/paper 成功但 review fail；2020A 因连续超时停止；2018A 因 Excel 表头识别错误停止。
- 第三轮门禁加入百分比物理范围、明确占位结果、超时预算、Excel 表头上下文、数值审计约束/符号表降噪和 Markdown checklist 语义恢复。
- 2021B 重跑 solve v2 后被物理范围门禁阻断：检测到负转化率/选择性与 `1000000%` 收率，没有再进入 paper。
- 2020A code v3 在一次超时反思后完成，但日志明确承认“使用默认值输出占位结果”，新门禁拒绝审批。
- 2018A 不再复现 Excel 表头转换错误，但两版程序均超过 300 秒；反思循环在第 2 次超时后停止并拒绝审批。
- code 重跑现在复用上一版 `solution.py`、运行日志和当前质量门禁错误，不再每次从零生成；格式漂移时恢复回复中最长的 Python 代码块。
- 新增非有限数值、罚函数值和“未找到可行解”门禁；历史上已审批的错误版本在 export 时也会被当前门禁重新阻断。
- 2018A code v5 经超时、NaN 和序列化错误反思后成功，solve/paper 已审批；review 加入题面数值和分钟/秒换算后仍有 4 个派生数值缺出处并停止。
- 2020A code v4/v5 虽能运行，但仍没有可行解且把罚函数当目标值；失败证据回传 model 后生成 v6/v7，Verifier 连续判 block，未再继续消耗 code 阶段。
- 2018A review 反馈可回传 code：v6 修正 `h_skin` 灵敏度并把派生值写入 `results.json`；solve v2、paper v4、review v6 全部通过。
- paper 现在自动附带 `solution.py` 附录，摘要后分页，Reviewer 可见参考文献与 artifact 清单；单个数值审计失败只定向修订被点名小节。
- 2018A PDF 编译成功并导出 `submission.zip`；最终 PDF、代码、结果、审计和 `problem1.xlsx` 已更新到 `test_cases/2018A_高温服装/deliverables/`。
