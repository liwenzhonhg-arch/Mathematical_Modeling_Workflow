# mmw 盲测缺陷修复 Plan

状态：**已实施并完成自动化、三题盲测与正常路径回归**  
依据：`blind_evaluation_report.md` 及三道盲测案例  
目标：先让工作流能够可靠地说“失败”，再提高 Agent 产出质量。

## 范围

本轮只修 4 个阻断性问题：

1. 失败的 `code` / `solve` 不能被审批。
2. 缺求解证据的 `paper` / `review` 不能被审批。
3. analyze 幻觉出的文件名不能成为硬交付物。
4. 缺硬交付物或未通过 review 时不能生成提交包。

不在本轮处理：新 Agent、新框架、知识库扩充、模型算法优化、UI、自动修改论文、依赖升级。

## 设计原则

- 沿用现有 `pending -> completed -> approved`，不增加状态类型。
- `completed` 表示产物已经生成；是否合格统一在 `approve` 前做确定性检查。
- 复用现有 `run_log.txt`、`results.json`、`abstract_score.json`、`checklist.json` 和 deliverables 清单，不增加新服务或依赖。
- 所有门禁必须返回明确原因和非零退出码，不能只打印警告。
- 不自动删除旧产物；失败时保留检查点和日志用于排查。

## 第一批：P0 硬门禁

### 1. 审批质量门禁

修改 `mmw/pipeline/state_machine.py`，在现有 `can_approve()` 的状态检查后增加按阶段判断：

| 阶段 | 拒绝审批条件 |
|---|---|
| `code` | `solution.py` 缺失/为空，或 `run_log.txt` 记录执行失败 |
| `solve` | `run_log.txt` 记录失败；`results.json` 缺失、非法、不是非空列表；题面确认的硬交付物缺失 |
| `paper` | `abstract_score.json` 缺失/非法，或 `needs_upstream_data=true` |
| `review` | `checklist.json` 缺失/非法，或任一检查项为 `fail` |

门禁只负责判断，不修改 artifact，不替用户自动 rework。

### 2. 硬交付物去幻觉

修改 `mmw/pipeline/stage_code.py::load_deliverables()`：

- 读取 analyze 给出的文件名后，再检查该文件名是否逐字出现在 `problem.md`。
- 题面未出现的文件名不进入硬交付清单，并打印被忽略项。
- 保留现有字典结构和调用方，不新增 schema。

这会过滤 2021B 的 3 个虚构 Excel，以及 2018A 的 `result2.xlsx`、`result3.xlsx`，同时保留题面明确写出的 `result.csv`、`problem1.xlsx`。

### 3. 导出前置校验

修改 `mmw/cli.py::export_submission()`：

1. 要求 review 的激活版本已经 approved。
2. 在打开 `submission.zip` 前完成 PDF 和硬交付物检查。
3. 任一必需文件缺失时抛出 `typer.Exit(1)`，不创建新 zip。
4. 全部通过后才打包并返回成功。

### 4. 最小测试

优先扩展现有测试，不新建测试框架：

- `tests/test_state_machine.py`
  - code 运行失败时拒绝审批。
  - solve 结果为空/非法时拒绝审批。
  - paper 需要上游数据时拒绝审批。
  - review checklist 缺失或含 fail 时拒绝审批。
  - 合法 artifact 仍可审批。
- `tests/test_stage_solve_collect.py`
  - 题面未出现的 deliverable 被过滤。
  - 题面明确出现的 deliverable 被保留。
- CLI 导出测试仅覆盖两个分支：缺交付物返回 1；文件齐全生成 zip。

## 第二批：P1 稳定性修复

P0 验证通过后再做，避免混入首个根因修复：

1. **LLM 重试分类**：`AuthenticationError` 等永久错误立即失败，只重试连接中断、超时、限流和服务端错误。
2. **本次运行产物边界**：solve 只收集本次新增或内容发生变化的 JSON、图表和二进制交付物，避免旧 EDA 图混入。
3. **artifact 解析**：Reviewer 必须独立生成合法 `checklist.json`；格式漂移视为门禁失败。
4. **数值审计降误报**：排除参考文献页码等非结果数字；回归稳定后，将高置信缺出处数值直接加入 review fail。
5. **Coder 代码净化**：对首行自然语言、代码栅栏和全角句号增加最小语法检查，反思后必须执行实际返回的最终代码。

## 第三批：P2 产出质量

只有在 P0/P1 后仍能稳定阻止错误成品时再做：

- Excel 合并单元格前向填充和文本编码自动探测。
- 时序区间持续时间的连续区间算法与单位校验。
- Verifier 的严重问题结构化输出，使模型阶段也能建立确定性审批门禁。
- research 区分“建议搜索”与“实际取得并引用的资料”。

## 实施顺序与文件

| 顺序 | 文件 | 最小改动 |
|---:|---|---|
| 1 | `mmw/pipeline/stage_code.py` | 过滤无题面证据的 deliverable |
| 2 | `mmw/pipeline/state_machine.py` | 在 `can_approve()` 增加四阶段确定性门禁 |
| 3 | `mmw/cli.py` | export 打包前校验并返回非零 |
| 4 | 现有相关测试文件 | 覆盖失败和成功路径 |
| 5 | P1 涉及的原文件 | P0 回归通过后逐项小提交式修改 |

P0 预计只修改 3 个生产文件；不引入依赖，不改配置和数据模型。

## 验收标准

### 自动化

```bash
pytest tests/test_state_machine.py
pytest tests/test_stage_solve_collect.py
pytest tests/
```

必须全部通过，且新增测试能证明：

- 失败 artifact 不能 approve。
- 合法 artifact 不被误伤。
- export 缺文件时退出码非零且不产生新 zip。

### 真题回归

1. 用新的源码快照创建全新 workspace，重跑 2021B、2020A、2018A。
2. 预期三题在 `code` 审批前如实停止，不再生成伪论文和伪提交包。
3. 再跑已有 2023B 成功案例，确认合法结果仍可走完 8 阶段并导出。
4. 在原 `case.md` 追加“第 2 轮”，不覆盖首轮证据；在 `gaps.md` 勾选已修项目。

## 完成定义

以下条件同时满足才算本轮完成：

- 错误代码、空结果、缺证据论文和 review fail 均无法被审批。
- 缺硬交付物时不会生成新的 `submission.zip`。
- 三题盲测不再出现“内部明确失败、外部仍显示成功导出”。
- 2023B 正常路径通过，完整测试无回归。

## 实施边界

本轮未修改 `.env`、密钥、CI/CD，未安装新依赖，未删除既有盲测证据。

## 2026-07-10 执行记录

- 已完成：题面文件名证据过滤、四阶段审批门禁、export 前置复核。
- 自动化：`pytest tests/ -q`，145 passed；`python -m compileall -q mmw` 通过。
- 旧盲测复核：2021B、2020A、2018A 再次执行 export，均在 code 质量门禁返回退出码 1。
- 新 workspace 回归：2021B、2018A 在 model 的 Verifier `block` 停止；2020A 在 Coder 认证失败时立即停止；三题均未传播为伪论文或伪提交包。
- 正常路径：2023B 重新生成 review v15，checklist 与数值审计通过，export 成功。
- P1/P2 已完成：认证错误不重试、本次求解产物边界、artifact JSON 恢复、数值审计门禁、GBK 编码探测、合并单元格提示、连续时段计算约束、Verifier 结构化严重度和 research 证据清单。
