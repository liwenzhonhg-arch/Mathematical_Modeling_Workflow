# AGENTS.md 上下文拆分规格

## 目标

在不降低工程、安全和质量门禁的前提下，缩短根目录 `AGENTS.md`，减少每次 Codex 对话自动加载的固定上下文。

本次拆分只调整规则的存放位置和按需读取方式，不修改程序行为、提示词、测试阈值、真题结论或发行流程。

## 当前基线

2026-08-07 只读统计：

- `AGENTS.md`：38,740 bytes，269 行。
- 全文件约 168 条项目规则。
- `质量保障链`：74 条规则，是主要上下文来源。
- 根规则中同时混有项目级边界、实现细节、真题专属事实和历史实验结论。

主要问题：

1. GUI、打包或普通代码修改也会加载移动热、2010A、2020A 等无关规则。
2. 已有 `test_cases/*_spec.md` 和知识库说明，但根文件仍重复保存详细合同。
3. 可由代码和测试确定性执行的约束同时以长篇自然语言存在，形成第二套真相。
4. 规则继续追加会扩大上下文压缩频率，并增加新旧条款冲突概率。

## 非目标

- 不新增 Agent 或顶层流水线阶段。
- 不在本次拆分中优化任何 Jinja2 prompt。
- 不删除或降低现有质量门禁。
- 不改写 `mmw/`、`tests/`、`.env`、CI/CD 或发行配置。
- 不把所有规格合并成一个新的大型文档。
- 不建立自动加载全部详细规范的机制；详细规范必须按任务读取。

## 权威层级

拆分后按以下顺序理解项目事实：

1. 根 `AGENTS.md`：Agent 每次接手都必须知道的稳定边界、红线和路由规则。
2. 代码与自动化测试：可确定性执行的行为合同和质量门禁。
3. `test_cases/*_spec.md`：某一功能或验证链的详细验收规格。
4. `knowledge/domains/`：题目无关的数学方法与建模知识。
5. `test_cases/<案例>/`：案例专属事实、Oracle、实验结果和失败证据。
6. `CLAUDE.md`：项目架构背景；与 `AGENTS.md` 冲突时仍以 `AGENTS.md` 为准。

同一详细规则不得在多个自然语言文件中全文复制。根文件只保留顶层不变量和指向权威位置的短链接。

## 根 AGENTS.md 保留内容

根文件保留以下内容：

1. 文件优先级和项目一句话定位。
2. 八阶段固定 ID，以及每阶段一句话职责。
3. 约 10 条高层目录约定。
4. 最小运行、测试和 Windows 构建命令。
5. 检查点状态、active version、审批、rework 和 upstream hash 顶层语义。
6. 下列质量不变量：
   - Coder 必须产出可复算代码和结构化结果。
   - `model -> code -> solve -> paper -> review` 传递同一方法合同。
   - Oracle 与正常流水线隔离。
   - `verified`、`scenario-feasible`、`unverified` 不得混用。
   - 最终导出必须经过 benchmark、数值审计和 PDF 视觉门禁。
7. `.env`、密钥、本机路径、Codex 登录态、联网、文件访问和发行包安全红线。
8. 删除、Git push、系统配置、公开发布等用户确认边界。
9. 开发纪律。
10. 按任务读取详细规范的路由表。

## 迁移映射

### 流水线与检查点

当前 `AGENTS.md` 第 93～109 行：

- 根文件保留状态流转、active version、审批和 upstream hash 的简版语义。
- 架构说明由 `CLAUDE.md` 负责。
- 具体行为以 `tests/test_checkpoint.py` 和 `tests/test_state_machine.py` 为准。

### Coder 恢复、重试与请求预算

当前第 113～132、147～151 行迁出详细说明，路由到：

- `test_cases/coder_candidate_preservation_spec.md`
- `test_cases/coder_model_escalation_spec.md`
- `test_cases/coder_subproblem_coverage_spec.md`
- `test_cases/request_boundary_candidate_preservation_spec.md`
- `test_cases/request_boundary_token_circuit_spec.md`
- `test_cases/codex_token_budget_spec.md`
- `tests/test_coder_retry.py`
- `tests/test_stage_code_gate.py`

根文件只保留“恢复候选优先、不得重跑已否决候选、预算按真实 usage 和共同截止执行”三项顶层原则。

### 移动热、降阶模型与可辨识性

当前第 118～126、138～155 行迁出，路由到：

- `knowledge/domains/differential_equations/moving_heat_process.md`
- `test_cases/moving_heat_coordinate_units_spec.md`
- `test_cases/moving_heat_model_minimality_spec.md`
- `test_cases/moving_heat_robin_contract_spec.md`
- `test_cases/moving_heat_runtime_contract_spec.md`
- `test_cases/effective_slab_state_space_spec.md`
- `test_cases/reduced_zone_response_spec.md`
- `test_cases/calibration_identifiability_spec.md`
- `tests/test_moving_heat.py`

根文件仅保留“移动热实现复用受测模块，连续参数至少三个成功起点并通过可辨识性门禁”。

### 数据语义与模型证据

当前第 133～137、156～158 行中的通用规则路由到：

- `test_cases/method_contract_spec.md`
- `test_cases/fixed_zero_alignment_contract_spec.md`
- 对应的 `tests/test_method_contract.py`、`tests/test_numeric_audit.py`

案例特有的数据解释写入相应 `test_cases/<案例>/case.md`，不得留在根规则。

### benchmark、Oracle 与可信等级

当前第 159～175 行路由到：

- `test_cases/README.md`
- `test_cases/independent_benchmark_suite_spec.md`
- `test_cases/method_contract_spec.md`
- `tests/test_benchmark.py`
- `tests/test_benchmark_suite.py`
- `tests/test_reference_contract.py`

根文件保留 Oracle 隔离、版本绑定和可信等级三项原则。

### 论文、图表与交付

当前第 164～179 行的详细规则路由到：

- `test_cases/paper_style_spec.md`
- `test_cases/pdf_visual_quality_spec.md`
- `test_cases/figure_polisher_spec.md`
- `test_cases/typesetter_spec.md`
- `test_cases/origin_figure_backend_spec.md`
- `tests/test_stage_paper_result.py`
- `tests/test_figure_quality.py`
- `tests/test_layout_quality.py`

根文件保留“数值来源可追溯、不得越权声称最优、最终 PDF 必须通过视觉门禁”。

### GUI、托管运行与进度

当前第 214～232 行的实现合同路由到：

- `test_cases/managed_run_controller_spec.md`
- `test_cases/progress_visibility_spec.md`
- `test_cases/rework_start_spec.md`
- `test_cases/paper_polish_gui_spec.md`
- `tests/test_gui.py`
- `tests/test_managed_run.py`

根文件继续保留项目路径、会话令牌、密钥脱敏、任务显式启动和可信等级展示等安全边界。

### 真题实验规则

当前第 180～185 行及其他包含具体案例编号、几何常数、扫描点数或固定起点的条款迁出：

- 2010A 内容写入 `test_cases/2010A_储油罐变位/case.md` 或该案例已有规格。
- 2020A 内容写入 `test_cases/2020A_炉温曲线/case.md` 或该案例已有规格。
- 清洁盲测通用规则写入 `test_cases/README.md` 和 `test_cases/independent_benchmark_suite_spec.md`。

根 `AGENTS.md` 完成后不得出现 `2010A`、`2020A` 等案例编号，也不得出现案例专属常数。

## 详细规范路由表

根文件应增加一张短路由表：

| 修改范围 | 必读内容 |
|---|---|
| Coder、recovery、重试 | Coder preservation / escalation / request-boundary specs |
| 方法合同、结果门禁 | `method_contract_spec.md`、相关测试 |
| 移动热模型 | 移动热知识库说明、moving-heat/effective-slab specs |
| benchmark、Oracle | `test_cases/README.md`、benchmark specs |
| paper、图表、PDF | paper/figure/typesetter/layout specs |
| GUI、托管运行 | managed-run/progress/rework specs |
| Windows 发行 | `v017_release_and_validation_spec.md`、发行验证测试 |
| 具体真题 | 对应案例目录，不读取其他案例规则 |

路由表只列入口，不复制详细条款。Agent 不得因为修改一个模块而批量读取全部规格。

## 执行顺序

1. 为根 `AGENTS.md` 中每个待移除段落确认现有权威文件和对应测试。
2. 先补齐 `test_cases/README.md` 的规格索引和缺失指针。
3. 将案例专属结论移动到对应案例目录。
4. 将通用方法说明合并到现有知识库或现有规格，不创建同义平行文件。
5. 最后压缩根 `AGENTS.md`，加入详细规范路由表。
6. 重新读取所有改动文档，检查链接、编码和重复条款。
7. 文档拆分单独提交，不与 prompt 或代码行为修改混在同一提交。

## 验收标准

### 体量

- 根 `AGENTS.md` 不超过 12 KiB。
- 根 `AGENTS.md` 不超过 140 行。
- 根文件不包含任何具体真题编号或案例专属数值常量。

### 完整性

- 每个从根文件移除的规则段都有明确的新权威位置。
- 所有根路由链接指向实际存在的文件。
- 不创建与现有 `*_spec.md` 同义的平行规格。
- 安全红线、Git/删除确认边界和 `.env` 规则不得弱化。
- Oracle 隔离、可信等级和最终交付门禁不得弱化。

### 按需加载

- GUI 任务不要求读取移动热或具体真题规则。
- Windows 打包任务不要求读取建模案例规则。
- 移动热任务可从根路由在两步以内定位到完整合同。
- Coder 恢复任务可从根路由在两步以内定位到 recovery 和请求边界合同。

### 验证

文档修改完成后至少执行：

```powershell
git diff --check
git status --short

# 确认案例编号已迁出根规则
Select-String -Path AGENTS.md -Pattern '2010A|2020A|2018A|2019C|2026A'

# 确认路由文件都存在
Get-Content AGENTS.md -Encoding UTF8
Get-Content test_cases/README.md -Encoding UTF8
```

如果拆分过程中修改了代码、prompt 或测试，则不再视为文档-only，必须运行 `pytest tests/`。

## 回滚条件

出现下列任一情况时停止拆分并回滚本轮文档改动：

- 发现规则没有现有权威位置，且无法在不新增平行文档的情况下安置。
- 根文件缩短依赖删除安全边界或质量门禁。
- 路由需要一次加载全部规格才能理解普通任务。
- 规格文件与现役代码或测试明显冲突，无法在文档拆分范围内裁决。

冲突应标记为后续代码/规格对齐任务，不得为了完成体量指标擅自修改程序行为。

## 完成产物

- 精简后的根 `AGENTS.md`。
- 更新后的 `test_cases/README.md` 规格索引。
- 必要的现有规格和案例文档就地补充。
- 一份拆分前后体量、规则去向和验证结果摘要。

## 执行结果（2026-08-07）

- 根 `AGENTS.md` 从 38,740 bytes、269 行缩减为 8,469 bytes、109 行。
- 固定上下文字节数减少约 78%，满足不超过 12 KiB / 140 行的目标。
- 根文件不再包含具体真题编号或案例专属常数。
- `test_cases/README.md` 已增加按修改范围读取的规格索引、清洁盲测冻结和案例专属规则边界。
- 根路由中的具体文件引用均已验证存在。
- 本轮只修改 Markdown，没有修改代码、prompt、测试、配置或质量阈值。
