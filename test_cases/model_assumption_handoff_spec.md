# 建模假设、逻辑链与交接件规范

## 1. 目标

`analyze -> model -> code/paper` 必须保留一条可审计、可阅读的建模链路：

`题目要求 -> 题面事实/数据 -> 建模抽象 -> 真正假设 -> 变量与方程 -> 求解方法 -> 输出 -> 验证`。

本规范解决三个问题：假设过多导致可行域被无依据收窄、`model.md` 随修订不断追加、
Coder/Writer 无法快速识别现役模型。

## 2. 假设分类

以下内容不得混称为模型假设：

- `given`：题面或附件直接给出的事实；
- `hard_constraint`：题目明确要求满足的约束；
- `definition`：指标、状态、单位和计算口径；
- `implementation_choice`：离散步长、候选预算、算法和停止规则；
- `modeling_assumption`：题面未直接给出、但为了闭合模型必须引入的简化。

`assumptions.json` 是唯一结构化来源，`assumptions.md` 由它确定性生成。每条真正假设必须包含：

- 稳定 ID；
- 假设陈述；
- 依据；
- 作用子问题；
- 对模型结构的影响；
- 放宽该假设后的变化。

默认核心假设不超过 8 条；超过 8 条必须给出 `overflow_reason`。超过 12 条视为未完成分类。
数量不是唯一门禁：能够归入题面事实、硬约束、定义或实现选择的条目即使总数较少也必须移出假设。

## 3. 模型逻辑合同

新生成的 `equations.json` 使用 `schema_version=2`。每个顶层子问题至少包含：

- `title`、`requirement`；
- `inputs`、`outputs`；
- `logic_chain`；
- `variables`；
- `formulas`（核心状态、指标或转移方程）；
- `objective`、`constraints`；
- `method`、`validation`；
- `assumption_refs`。

每个逻辑步骤包含 `id/from/action/to/reason`，用于回答“依据什么，做了什么抽象，得到什么”。
约束必须标明来源类型，不能把实现选择伪装成题面硬约束。旧版 `equations.json` 继续兼容读取，
但只提供降级交接，不得伪装成具备完整逻辑链。

## 4. 人工交接件

模型阶段确定性生成 `model_handoff.md`，每个子问题按固定顺序展示：

1. 题目要求；
2. 输入与输出；
3. 建模逻辑链；
4. 变量、目标和约束；
5. 假设引用；
6. 求解与确定性停止；
7. 验证和失败条件。

Coder 和 Writer 优先消费该交接件及方法契约。`model.md` 保留完整推导，只作为详细参考。

## 5. 修订规则

- `model.md` 只保存当前完整模型，不保存 `v42/v43/...` 等历史追加章节；
- 被替代的方程、预算和方法从现役正文删除；
- 修订原因、Verifier issue 和版本差异写入 `revision_history.json`；
- 同一顶层子问题标题只能出现一次；
- 定向修订仍须自包含，但“自包含”不等于附加一份新版本合同；
- 结构化逻辑、方法契约与 `model_handoff.md` 必须由当前 `equations.json` 同源生成。

## 6. 下游规则

- Coder 优先读取 `model_handoff.md + params.json + method_contract.json`；
- Writer 的假设章节只读取确定性生成的 `assumptions.md`；
- Writer 的建模章节优先读取 `model_handoff.md + solve method_contract`；
- 旧检查点缺少新交接件时允许回退 `model.md`，但不得修改旧检查点。

## 7. 验收测试

1. 非法或过量假设合同被拒绝；
2. `assumptions.md` 只包含真正假设，不包含分类备注；
3. schema v2 缺失逻辑链、输出或验证时报告失败；
4. schema v2 可生成固定结构的 `model_handoff.md`；
5. 旧版 equations 仍可生成明确标注为降级的交接件；
6. 修订版出现历史版本标题或重复子问题标题时被拒绝；
7. 结构化目标/约束对象仍能生成稳定方法契约；
8. Code/Paper 阶段优先使用 `model_handoff.md`；
9. 专项测试、完整测试和 `git diff --check` 通过。
