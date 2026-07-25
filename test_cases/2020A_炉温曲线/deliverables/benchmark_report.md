# 2020A 隐藏评测报告（2026-07-21）

## 结论

**BLOCKED**。隐藏评测链路已实现并通过自动化测试，但本轮没有产出一份通过全部门禁的新论文。

| 运行 | 最远阶段 | 通用门禁 | Oracle | 结论 |
|---|---|---|---|---|
| r1 | paper v1 | FAIL | FAIL | code/solve 实际违反约束，paper 数据缺口，审计有 1 个高置信缺出处数值 |
| r2 | code v1 | FAIL | FAIL | 标定 R²=0.7626、RMSE=25.6289°C，五次修订后仍无问题2可行解 |
| r3 | analyze 请求 | 未运行 | 未运行 | DeepSeek HTTP 402 Insufficient Balance |

## 已验证

- Oracle 未进入 Agent 提示词、普通检查点或新工作区。
- 旧 results 未重写时不能形成 code 结果预览。
- code/solve 的失败、约束违规、替代解和上游陈旧状态会阻断 benchmark。
- `reference_expected.json` 的范围不会写入 benchmark 报告。
- `pytest tests/ -q`：262 passed。
- `python -m compileall -q mmw test_cases/2020A_炉温曲线/reference_solver.py`：通过。
- `git diff --check`：通过。

## 未完成

- 新的通过 Oracle 的 `results.json`。
- 通过数值审计的新论文。
- 新 `paper.pdf` 和 `submission.zip`。

旧 `deliverables/paper.pdf` 是 2026-07-10 历史快照，未在本轮刷新。
