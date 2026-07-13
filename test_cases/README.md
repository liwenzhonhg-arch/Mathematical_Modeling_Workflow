# test_cases — 真题实测案例库

记录用历年真题对 mmw 工作流做完整实测的成品与缺陷，为赛前调优和提示词迭代提供依据。

## 结构约定

```
test_cases/
├── blind_evaluation_protocol.md # 盲测的冻结范围、禁止操作、评分方式与候选题目
├── blind_evaluation_report.md # 三题盲测的汇总结论、共性失败和修复优先级
├── blind_evaluation_fix_plan.md # 经确认后实施的质量门禁修复计划
├── next_iteration_spec.md # 门禁完成后的自动纠错与工程收口规格
├── blind_evaluation_snapshot.sha256 # 盲测启动时的核心源码 SHA-256 清单
└── <年份><题号>_<简称>/        # 如 2023B_多波束测线
    ├── case.md                # 案例记录（必有）：题目来源、运行配置、各阶段结果、成品清单、结论
    ├── gaps.md                # 缺陷清单（必有）：勾选框跟踪，修复后打勾并注明修复方式
    └── deliverables/          # 成品快照（可选）：paper.pdf、关键产出的文本快照
```

## 写入时机

- 每次完整 8 阶段流程实测结束后，新建一个案例目录
- 同一题目重测不新建目录，在原 case.md 追加「第 N 轮」小节，gaps.md 勾掉已修复项
- 无人工修改的盲测开始前，先更新 `blind_evaluation_protocol.md` 并生成 `blind_evaluation_snapshot.sha256`；自主轮结束前不修改快照范围内的代码、提示词和知识库

## 清理约定

- deliverables/ 只留最终版成品，中间版本不存（中间版本在 workspace 的检查点树里）
- workspace/<案例>/ 本身不进 git；本目录是它的持久化摘要，进 git
- 某个案例的全部 gaps 修复完毕后，案例保留作为回归基线，不删除

## gaps.md 分类约定

- **[工具]** 工作流本身的 bug / 缺失功能（修复对象：mmw 代码）
- **[提示词]** Agent 产出质量问题（修复对象：prompts/）
- **[人工]** 模型/算法本身需要人脑攻坚的部分（修复对象：赛时人的分工）
