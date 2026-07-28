# Model 重做反馈保真 Spec

状态：**已实现并经真题恢复验证（2026-07-29）**

## 问题

托管运行遇到 `Verifier=block` 后，控制器记录的通用门禁文案会被下一轮
`run_model` 优先读取，覆盖检查点中的 `verify_status.json` 和
`verify_report.md`。Modeler 因而只知道“模型结论失效”，不知道具体公式、
边界条件和可求解性问题，重复重做仍会失败。

## 规则

1. 最新 model 检查点为 `block` 时，重做必须直接读取该版本的结构化状态和完整报告。
2. GUI/托管的重做理由不得覆盖同版本 Verifier 的详细证据。
3. 最新 model 已通过 Verifier 时，仍允许 code/review/人工意见作为下游反馈触发重做。
4. 不改变 Verifier 严重级别，不自动审批，不增加重做预算。

## 验收

- 同时存在通用重做理由和详细 block 报告时，Modeler 收到详细报告。
- 已有 model 自动修订、状态机和托管运行测试通过。
- 在隔离真题工作区恢复托管后，不再出现“只收到通用错误、盲目猜修”的修订记录。

真题恢复证据：2020A r6 从 model v5 恢复后，v6/v7 的
`revision_history.json` 已保留 v5 的 5 条具体 Verifier issue；后续失败问题已推进为
Robin 离散系数、跨工况时间基准、协方差病态分支等新问题，而非重复猜测旧问题。
