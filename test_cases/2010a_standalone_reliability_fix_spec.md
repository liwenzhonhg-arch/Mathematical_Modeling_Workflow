# 2010A 独立成品能力修复 SPEC

状态：实施中（A–F 已完成，G 待双轮实测）  
冻结基线：`0ae471c8039ca8b4b4108685f19ba5fe95201cba`  
制定日期：2026-08-03

## 1. 目标与成功定义

目标不是让流水线“八阶段显示完成”，而是让一个新工作区只凭官方题面和附件，在无人补写答案的情况下生成可执行、可核验、可导出的完整作品。

成功必须同时满足：

1. 题面图中的尺寸、标注和相对位置能进入问题文本，不能只提取段落正文。
2. Modeler 只声明当前运行环境与总预算内可执行的模型、约束和验证方法。
3. Verifier 的 block 必须包含可操作的事实错误；托管器在界面/状态中显示首要原因，不能只返回 `RuntimeError`。
4. 单次 model 修订不携带重复的完整历史，token 和时长能按 Agent/阶段追踪。
5. 独立 Oracle 不只检查少数标量，还检查题目要求的完整罐容表。
6. 两个全新 post-fix 工作区均完成 `analyze -> review`、论文编译、视觉门禁和导出，并通过同轮与跨轮重复性检查。

## 2. 已确认的基线缺陷

首轮冻结基线 `benchmark_2010A_clean_r1` 停在 model：

- DOCX 的普通文本提取保留了“1m、2m、6m、1m”等标签，却丢失图中位置，导致 Modeler 把实际油罐圆柱段误写为 `6m`，实际应由尺寸链确定为 `2m + 6m = 8m`。
- 错误几何使 code 得到约 `50.527 m³` 总容积，而独立几何基线约为 `64.664 m³`。
- Verifier 还发现空罐边界、协方差二次型、探针坐标证据和相关误差目标不可执行等问题。
- 托管状态只显示通用 `RuntimeError，请查看工作区日志`，用户看不到首要失败项。
- 17 次 Codex 请求累计约 `826169` tokens；日志没有 Agent 角色和请求耗时，无法定位主要消耗。

这些事实只用于确定修复方向；在第二个冻结基线结束前不得修改运行代码、提示词、知识库或验收范围。

## 3. 约束与非目标

### 3.1 必须遵守

- 先完成 `benchmark_2010A_clean_r2`，其代码、输入、预算、Oracle 与 r1 完全一致。
- r2 完成前只允许新增本 SPEC 和记录事实，不修改任何影响流水线行为的文件。
- 不向 Agent 暴露 `reference_solver.py`、`reference_expected.json`、参考数值或验收范围。
- 不修改 `.env`、密钥、Codex 登录态、CI/CD 或系统配置。
- 不安装新依赖；DOCX 修复优先复用标准库 `zipfile` 与 `xml.etree.ElementTree`。
- 不降低现有质量门禁，不用占位结果、扩大容差或跳过 Verifier 换取完成。

### 3.2 本轮不做

- 不加入通用 OCR、视觉大模型或 Office 自动化。
- 不增加新的顶层阶段或新 Agent。
- 不为 2010A 硬编码题号、尺寸或参考答案。
- 不重构整个 benchmark schema；只增加罐容表所需的最小通用表格契约。

## 4. 实施批次

### A. 完成冻结基线 r2

输入与 r1 相同，预算固定为：

- `1,000,000 tokens`
- `180` 分钟进程活跃时间
- 每阶段最多重做 `2` 次
- 全流程最多重做 `8` 次

结束条件：完成、可信门禁停止、供应商阻塞或预算耗尽。无论结果如何，记录阶段、版本、token、活跃时长、最后结构化证据和成品清单。

### B. 保留 DOCX 图形标注空间关系

修改范围：`mmw/project.py`、对应项目扫描/初始化测试。

实现：

1. 保留现有段落文本提取作为主正文。
2. 从 `word/document.xml` 读取 VML/Word shape 的 `style` 中 `left`、`top`，收集后代 `w:t` 文本。
3. 识别分页标记，按 `page -> top -> left` 排序。
4. 在 `problem.md` 末尾追加“图形定位文本”区块，每行包含页码、横纵坐标和标签文本。
5. 没有定位 shape、样式不完整或单个 shape 解析失败时，仍返回原有正文，不使旧 DOCX 失效。

验收：构造最小 DOCX XML，证明四个标签按横坐标稳定排序；对 2010A 初始化后的 `problem.md`，能明确保留同一水平线上的 `1m | 2m | 6m | 1m` 顺序。

### C. 让 Analyst/Modeler 对图示证据负责

修改范围：`mmw/prompts/system/analyst.j2`、`mmw/prompts/analyze.j2`、`mmw/prompts/system/modeler.j2`、`mmw/prompts/model.j2`、`mmw/prompts/model_revision.j2`、`mmw/prompts/system/verifier.j2`、`mmw/prompts/verify.j2`；仅在现有模板中增加最小规则。

规则：

- Analyst 必须把位置化图示标签解释成尺寸链，并在证据不足时列为待确认，不能任选一个数字当总长度。
- Modeler 必须逐项列出“题面直接给定 / 由尺寸链推导 / 待确认”的几何量。
- Verifier 必须复核总尺寸等式、坐标原点、探针位置和空/满罐边界。
- 相关误差、协方差或置信域只有在代码可直接实现且预算覆盖时才能作为硬约束；否则降为披露或使用可执行的加权残差。
- 不允许为了显得高级而增加题面没有、附件不可辨识的自由参数。

验收：prompt 快照/文本断言覆盖上述关键句；不得出现 2010A 专用数值。

### D. 限制 model 修订上下文膨胀

修改范围：`mmw/pipeline/stage_model.py` 及现有 model 阶段测试。

实现：每次 Verifier block 后，用共享 `LLMClient` 新建一个 `ModelerAgent` 再执行定向修订。这样保留累计真实 usage，但不重复携带前几轮完整对话；修订 prompt 仍显式携带当前模型、结构化 Verifier 证据、题面和必要上游产物。

验收：两轮修订时第二轮 Agent 历史只含系统消息和当前修订请求；版本树、累计 token 元数据和最多两轮规则不变。

### E. 暴露安全、可操作的失败原因与请求进度

修改范围：`mmw/managed_run.py`、`mmw/llm.py`、`mmw/agents/base.py`、GUI 已有任务状态展示，以及对应测试。

实现：

- `BaseAgent` 把角色名写入其 `LLMClient` 的日志上下文。
- 每条 token 日志增加 `role` 与 `duration_seconds`，不记录 prompt、原始响应、密钥或供应商完整异常。
- 托管阶段失败后优先读取已落盘的安全结构化证据：model 的 `verify_status.json`、code 的 `rework_request.json`、状态机 `quality_error`。
- 用户可见错误包含阶段、版本、首要失败项和建议动作；只有没有结构化证据时才回退通用错误。
- 继续复用现有 Job 进度模型；不实现无法从供应商获得的“请求内百分比”。界面显示已用时、累计 token、最近完成请求耗时与当前阶段。

验收：model block 测试返回具体 issue；模拟供应商异常仍不泄露 stderr/prompt；旧 token 日志缺少新字段时读取不报错。

### F. 增加隐藏表格 Oracle

修改范围：`mmw/utils/reference_contract.py`、`mmw/benchmark.py`、`tests/test_benchmark.py`、2010A 的 `reference_expected.json`。

最小 schema：

```json
{
  "tables": [
    {
      "name": "q1_capacity_table",
      "files": ["result1.xlsx", "result1.csv"],
      "height_columns": ["高度", "height_cm"],
      "value_columns": ["罐容", "volume_l"],
      "height_min": 0,
      "height_max": 1.2,
      "step": 0.01,
      "min_coverage": 0.9,
      "monotonic": "nondecreasing",
      "samples": [{"height": 1.2, "min": 3862.74, "max": 4162.74}]
    }
  ]
}
```

通用行为：

- 文件只能从工作区最终成果目录/允许的根目录读取，拒绝绝对路径和路径穿越。
- 只接受 `.csv`、`.xlsx`；复用现有 pandas/openpyxl 依赖，不新增包。
- 列名按声明别名匹配；数值必须有限。
- 高度在 evaluator 内统一为米：原表最大高度不超过 5 时按米，大于 5 且不超过 500 时按厘米，否则按毫米；随后检查覆盖、固定步长、重复高度、单调性和预声明抽样范围。
- 失败写入 benchmark 的 `tables.failures`，任一失败都不能获得 `verified`。
- `reference_expected.json` 仍只由 evaluator 读取，不进入任何提示或检查点。

验收：覆盖正常表、缺行、逆序值、错误抽样点、路径穿越和缺文件六个最小测试。

### G. 两轮 post-fix 清洁验证

新建两个与基线隔离的工作区，沿用相同官方输入、隐藏 Oracle 和预算。验收顺序：

1. 两轮都完成 8 阶段并审批现役版本。
2. code 与 solve 的规范结果同轮一致。
3. 两张罐容表分别通过覆盖、步长、单调性和抽样值 Oracle。
4. 论文中的结果数值通过出处审计，方法声明与实现一致。
5. PDF 编译和视觉质量门禁通过，无缺字、空白正文页、测试占位内容和无效图表。
6. `submission.zip` 生成，且只包含现役产物。
7. 两轮参数和抽样罐容值满足冻结的跨轮容差。

若任一轮失败，只记录新证据并回到对应最小修复批次；不得改 Oracle 容差来迁就输出。

## 5. 测试命令

```powershell
F:\python\python.exe -m pytest tests/test_project.py tests/test_stage_model.py tests/test_managed_run.py tests/test_benchmark.py -q
F:\python\python.exe -m pytest tests/ -q
F:\python\python.exe -m compileall -q mmw
git diff --check
```

## 6. 交付物与记录

- 本 SPEC。
- r2 基线事实追加到 `test_cases/2010A_储油罐变位/case.md` 与 `gaps.md`。
- 修复代码、最小回归测试和必要 prompt 规则。
- 两轮 post-fix 记录、benchmark/PDF/export 结果与跨轮比较报告。
- 提交只包含本轮明确修改的文件；不纳入既有未跟踪文件，不推送、不发布。

## 7. 退出标准

只有 G 的全部验收项通过，才能回答“当前流程能独立产出一份经过隐藏 Oracle 验证的合格作品”。如果仍停在某阶段，结论必须写成实际能力边界和下一条根因，不能用“流程已启动”或“八阶段存在”代替完成。
