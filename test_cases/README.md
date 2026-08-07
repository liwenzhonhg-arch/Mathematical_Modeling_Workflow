# test_cases — 真题实测案例库

记录用历年真题对 mmw 工作流做完整实测的成品与缺陷，为赛前调优和提示词迭代提供依据。

## 结构约定

```
test_cases/
├── blind_evaluation_protocol.md # 盲测的冻结范围、禁止操作、评分方式与候选题目
├── blind_evaluation_report.md # 三题盲测的汇总结论、共性失败和修复优先级
├── blind_evaluation_fix_plan.md # 经确认后实施的质量门禁修复计划
├── next_iteration_spec.md # 门禁完成后的自动纠错与工程收口规格
├── independent_benchmark_suite_spec.md # 多题独立 Oracle/压力回归基准集规格
├── method_contract_spec.md # model-code-solve-paper-review 方法一致性契约
├── managed_run_controller_spec.md # 一次确认后托管运行、修复和暂停的控制器规格
├── blind_evaluation_snapshot.sha256 # 盲测启动时的核心源码 SHA-256 清单
└── <年份><题号>_<简称>/        # 如 2023B_多波束测线
    ├── case.md                # 案例记录（必有）：题目来源、运行配置、各阶段结果、成品清单、结论
    ├── gaps.md                # 缺陷清单（必有）：勾选框跟踪，修复后打勾并注明修复方式
    ├── reference_solver.py    # 确定性公开基线（可选）：必须注明来源并可独立运行
    ├── reference_expected.json # 交叉验证后的结果范围契约（可选）
    └── deliverables/          # 成品快照（可选）：paper.pdf、关键产出的文本快照
```

## 写入时机

- 每次完整 8 阶段流程实测结束后，新建一个案例目录
- 同一题目重测不新建目录，在原 case.md 追加「第 N 轮」小节，gaps.md 勾掉已修复项
- 无人工修改的盲测开始前，先更新 `blind_evaluation_protocol.md` 并生成 `blind_evaluation_snapshot.sha256`；自主轮结束前不修改快照范围内的代码、提示词和知识库
- 只有公开代码或论文能被至少两条证据交叉验证时才增加参考基线；契约保存宽容范围和条件，不保存单篇题解的“唯一正确答案”
- `reference_expected.json` 是 evaluator-only Oracle：不得复制到工作区、传给 Agent 或写入普通阶段检查点；流水线完成后用 `mmw benchmark --case <案例> --workspace <工作区> --stage code|solve` 独立校验
- schema v1 只定义结果范围；schema v2 可额外定义 `invariants`、`stress_scenarios` 和 `repeatability`。压力场景和不变量仍须由独立证据确定，不能把 Agent 自报“通过”当作现实验证。
- 多案例回归清单保存在 `benchmark_suite.json`，用 `mmw benchmark-suite` 执行；当前核心集的 2020A、2018A 具备独立 Oracle，2023B 保持 `scenario-feasible`，不得补造验证等级。
- 工作区可在 `config.yaml` 写 `benchmark_case` 显式绑定案例；否则只在年份题号能唯一匹配到参考契约时自动使用 Oracle。没有 Oracle 的最终报告最多是 `scenario-feasible`。

## 按修改范围读取规范

详细合同按任务读取，不要为了修改一个模块加载全部规格：

| 修改范围 | 规格入口 |
|---|---|
| Coder 候选保存、恢复、重试 | `coder_candidate_preservation_spec.md`、`coder_model_escalation_spec.md`、`request_boundary_candidate_preservation_spec.md` |
| token 与请求边界 | `codex_token_budget_spec.md`、`request_boundary_token_circuit_spec.md` |
| 方法合同与结果覆盖 | `method_contract_spec.md`、`coder_subproblem_coverage_spec.md`、`fixed_zero_alignment_contract_spec.md` |
| 移动热与可辨识性 | `moving_heat_*_spec.md`、`effective_slab_state_space_spec.md`、`reduced_zone_response_spec.md`、`calibration_identifiability_spec.md` |
| benchmark 与 Oracle | `independent_benchmark_suite_spec.md`、`benchmark_suite.json` 和对应案例的 `reference_expected.json` |
| paper、图表与 PDF | `paper_style_spec.md`、`pdf_visual_quality_spec.md`、`figure_polisher_spec.md`、`typesetter_spec.md`、`origin_figure_backend_spec.md` |
| GUI 与托管运行 | `managed_run_controller_spec.md`、`progress_visibility_spec.md`、`rework_start_spec.md`、`paper_polish_gui_spec.md` |
| Windows 发行 | `v017_release_and_validation_spec.md` |

根 `AGENTS.md` 只保存跨任务稳定边界；算法常数、几何解释、固定扫描点和失败证据必须留在对应案例或功能规格中。

## 清洁盲测冻结

- 正式盲测先冻结代码提交、题面附件、隐藏 Oracle、预算和验收规则，再创建至少两个隔离的新工作区。
- 两轮基线结束前不修改代码、prompt、知识库或验收范围；修复作为后续实验，不回写基线。
- Oracle 覆盖每个数值子问题及题目要求的表格/文件；缺项不能用“8 阶段完成”代替。
- 公开阶段产物不得读取参考答案、验收范围或隐藏不变量。

## 案例专属规则

- 具体几何、数据解释、扫描点、起点、拟合边界和实验结论写入对应案例的 `case.md`/`gaps.md`。
- 通用实现只有经过题目无关的合成回归验证后才能进入 `knowledge/`；案例答案、Oracle 字段和专用拟合常数不得进入公开知识库。
- Agent 处理某一真题时只读取该案例目录，不加载其他案例规则。

## 清理约定

- deliverables/ 只留最终版成品，中间版本不存（中间版本在 workspace 的检查点树里）
- workspace/<案例>/ 本身不进 git；本目录是它的持久化摘要，进 git
- 某个案例的全部 gaps 修复完毕后，案例保留作为回归基线，不删除

## gaps.md 分类约定

- **[工具]** 工作流本身的 bug / 缺失功能（修复对象：mmw 代码）
- **[提示词]** Agent 产出质量问题（修复对象：prompts/）
- **[人工]** 模型/算法本身需要人脑攻坚的部分（修复对象：赛时人的分工）
