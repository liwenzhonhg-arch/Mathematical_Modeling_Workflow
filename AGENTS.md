# AGENTS.md

本文件是 Codex 接手本仓库时自动加载的最高优先级项目规范。`CLAUDE.md` 只提供架构背景；冲突时以本文件为准。详细质量合同按下方路由表读取，不得一次加载全部规格。

## 项目定位

`mmw` 是面向 CUMCM 的多 Agent 数学建模工作流。固定八阶段为：

1. `analyze`：问题分析与顶层子问题合同。
2. `eda`：数据提取、摘要、代码和统计图表。
3. `research`：HMML/人工资料调研，每个顶层子问题最多 3 个候选且恰有一个基线。
4. `model`：Modeler 建模，Verifier 独立验证。
5. `code`：生成并受控执行 `solution.py`。
6. `solve`：收集结构化结果、敏感性、图表和硬性交付物。
7. `paper`：生成中文国赛 LaTeX 论文并优化摘要。
8. `review`：评审、数值出处审计、benchmark 和最终交付门禁。

`FigurePolisherAgent` 与 `TypesetterAgent` 只是阶段内受约束子 Agent，不得改变模型、数值、引用事实或新增顶层阶段。

## 目录与产物

- `mmw/`：核心包；CLI 入口为 `mmw/cli.py`，流水线位于 `mmw/pipeline/`，Agent 位于 `mmw/agents/`。
- `mmw/prompts/`：Jinja2 prompt；`system/` 保存角色系统提示。
- `mmw/gui/`：仅监听本机回环地址的正式 GUI；静态入口固定为 `mmw/gui/static/index.html`，不得依赖 CDN。
- `mmw/latex/`、`mmw/utils/`：论文编译和通用确定性门禁。
- `skills/`：可独立复制的项目辅助 Skill；目录名使用 kebab-case，每个 Skill 必须包含 `SKILL.md`，脚本仅使用已声明依赖。Skill 评测样例随 Skill 保存，临时运行结果不得进入该目录。
- `knowledge/`：题目无关的 HMML/建模知识，不得包含案例答案或 Oracle。
- `tests/`：自动化测试；`test_cases/`：规格、真题记录和 evaluator-only 基线，必须进 git。
- GUI 新项目保持原始 PDF/DOCX/附件原位；内部状态写入题目目录 `.mmw/`，最终成果写入 `output/`。
- `workspace/`、`build/`、`dist/` 和 `.env` 不进 git。
- `gui-prototype/` 只保存无构建静态原型、预览图和浏览器验证记录；正式方案确定后经确认归档或清理。
- `tools/` 仅保存可复用的仓库工具；案例专属导出脚本必须在文件名、README 和调用入口中显式标注案例范围，不得被通用流程导入或打包。新增工具前先写用途、命名和清理规则，一次性脚本放受控临时目录。
- 新目录必须先说明用途、命名和清理规则；一次性文件放受控临时位置并在任务结束时报告。

## 常用命令

```powershell
pip install -r requirements.txt
python -m mmw.cli <command>
python -m mmw.cli status --workspace <workspace_name>
python -m mmw.cli run <stage> --workspace <workspace_name>
python -m mmw.cli approve <stage> --workspace <workspace_name>
python -m mmw.cli compile --workspace <workspace_name>
python -m mmw.cli audit --workspace <workspace_name>
python -m mmw.cli export --workspace <workspace_name>
pytest tests/
powershell -ExecutionPolicy Bypass -File .\build-windows.ps1
```

代码变更后按影响范围运行测试；文档-only 变更至少重读文件、检查引用和 `git diff --check`。

## 流水线不变量

- 检查点状态固定为 `pending -> completed -> approved`；每版包含产物、`meta.json` 和 `status.json`。
- `config.yaml.active_versions` 决定现役版本；无激活记录时读取最新版本。
- 新 branch 在审批激活前不得触发下游 `upstream_changed`；人工确认无影响时使用 `mmw ack`。
- GUI 只读扫描不得创建文件；只有用户启动流程后才能创建 `.mmw/` 和 `output/`。
- `.docx` 只用 Python 标准库只读提取；旧 `.doc` 明确要求另存为 `.docx`，不得静默忽略。
- `RESEARCH_WEB_ENABLED` 默认 `false`；启用时只访问受限 OpenAlex/Crossref 元数据端点，不下载全文或保存凭据、Cookie、原始响应。
- 生成代码执行默认要求可证明的 OS 隔离；当前平台无法建立时返回 `execution_isolation_unavailable`。`MMW_EXECUTION_MODE=trusted-local` 仅用于明确授权的本机开发/测试，不得称为沙箱或隔离执行。

## 顶层质量合同

- Coder 必须产出可复算的 `solution.py`，并尽量生成 `results.json`、`sensitivity.json`；存在方法候选合同时先执行受限 pilot。
- 完整候选应立即写入 recovery；恢复候选首次执行前不调用 LLM，不得重复运行已被证据否决的旧候选。
- `model -> code -> solve -> paper -> review` 必须绑定同一方法合同；目标、约束、算法类别、近似声明和结果哈希不一致时阻断下游。
- 数值子问题必须保留 analyze 定义的规范 ID 和结果名；数据清洗等内部步骤不得冒充新顶层问题。
- 正式数值程序默认不设墙钟截止，以预声明的候选数、最大迭代数、收敛阈值和连续无改进轮数确定性停止；只有用户显式设置 `MMW_MAX_RUNTIME_SECONDS` 时才启用共同墙钟保护。显式墙钟触发必须标记 `incomplete` 并阻断审批，不得使用部分结果。供应商调用继续记录真实 usage，多个子问题不得重复分配同一显式预算。
- 结果性数值来自结构化结果、参数、敏感性或运行日志；实现合同数值可来自绑定的方法/运行合同。
- 正常流水线和 Agent 不得读取 evaluator-only Oracle、答案范围或隐藏不变量。
- 隐藏参考全部通过才可标记 `verified`；无独立 Oracle 时最多为 `scenario-feasible`，失败或无证据为 `unverified`。
- review 必须执行确定性数值审计和当前版本 benchmark；报告缺失、失败或版本过期时不得审批。
- paper 必须区分数学 formulation 与实际 implementation，不得把启发式或有限搜索宣称为全局最优。
- paper 使用 LaTeX 生成论文时，必须在同一版本、同一次阶段交付中同时生成 Markdown 论文；其正文结构、公式、表格、图表引用、关键数值及出处应与现役 `.tex` 和 PDF 保持一致并可对应追溯，Markdown 不替代 `.tex` 与 PDF。
- 图表只以当前 solve 的 CSV/manifest 为数值来源；Origin 是 Windows 可选后端，Matplotlib 是默认和回退后端。
- 最终导出必须通过 benchmark、数值审计、方法追踪、PDF 视觉质量和硬性交付物检查。

## 配置与安全

- 不为理解项目主动打开、打印或复制 `.env`；密钥、token、密码不得进入代码、日志、测试快照、prompt 或提交说明。
- 默认后端是 OpenAI-compatible API/BYOK；可选 Codex CLI 只调用本机已有 `codex`/`codex.cmd` 并复用登录态，不读取会话凭据。
- Codex CLI 缺失或未登录必须明确暂停，不得静默切换 API；usage 缺失时 token 预算显示不可用。
- GUI 只向浏览器返回脱敏 Key；权限控制由服务端实现，不依赖 prompt。
- GUI 项目路径只能由原生选择器产生，并在后端绑定不透明 `project_id`；文件访问限制在项目目录内，修改 API 校验本机会话令牌。
- 最近项目路径只能由后端保存在本机用户目录，重新加载时重新校验；浏览器不得用 `localStorage` 保存绝对路径或密钥。
- Windows 包不得包含 `.env`、登录态、工作区、测试产物或本机绝对路径；更新包必须校验 digest、大小和路径穿越，并安装到新版本目录。
- GUI 不得以“8 阶段完成”代替可信等级；长任务展示阶段、状态、时间和脱敏失败原因，不返回原始供应商响应或完整异常。
- 不安装全局依赖、不修改系统配置。修改 `.env`、密钥、CI/CD、删除文件、Git 历史、`git push`/rebase/reset、公开发布前必须获得用户明确确认。

## 详细规范路由

| 修改范围 | 必读内容 |
|---|---|
| 项目整体审查整改、执行隔离、GUI 请求安全、发行加固 | `test_cases/project_audit_remediation_spec.md`，并按具体范围继续读取下列专项规格 |
| Coder、recovery、重试 | `test_cases/coder_candidate_preservation_spec.md`、`test_cases/coder_model_escalation_spec.md`、`test_cases/request_boundary_candidate_preservation_spec.md` |
| 模型假设、逻辑链、人工交接 | `test_cases/model_assumption_handoff_spec.md`、`tests/test_model_handoff.py` |
| 方法合同、结果门禁 | `test_cases/method_contract_spec.md`、`test_cases/coder_subproblem_coverage_spec.md` 及对应测试 |
| 可选领域合同、竞赛合规 | `test_cases/optional_domain_and_competition_contracts_spec.md` |
| 移动热模型 | `knowledge/domains/differential_equations/moving_heat_process.md`、`test_cases/moving_heat_runtime_contract_spec.md`、`test_cases/effective_slab_state_space_spec.md` |
| benchmark、Oracle | `test_cases/README.md`、`test_cases/independent_benchmark_suite_spec.md`、benchmark tests |
| paper、文字表达、图表、PDF | `test_cases/paper_style_spec.md`、`test_cases/paper_human_writing_skill_spec.md`、`test_cases/pdf_visual_quality_spec.md`、`test_cases/figure_polisher_spec.md`、`test_cases/typesetter_spec.md` |
| GUI、托管运行 | `test_cases/managed_run_controller_spec.md`、`test_cases/progress_visibility_spec.md`、`test_cases/rework_start_spec.md` 及对应测试 |
| Windows 发行 | `test_cases/v017_release_and_validation_spec.md`、`tests/test_release_validation.py` |
| 具体真题 | 只读取对应 `test_cases/<案例>/`，不得把案例事实提升为全局规则 |

## 开发纪律

- 先读现有实现、调用方和测试，再修改共享根因；优先复用仓库已有模式、标准库和现有依赖。
- 修改 prompt 时同时检查 Agent、阶段输入和 prompt 测试；修改阶段时检查状态机、检查点和相关测试。
- 不通过注释错误、降低阈值或添加绕过标记让测试通过。
- 保持最小、单一目的变更；文档拆分、prompt 优化和代码行为修改分开提交。
- 完整实测记录、清洁盲测冻结、Oracle 和案例目录约定以 `test_cases/README.md` 为准。

## 接手备注

项目实践变化时先更新规则或对应规格，再修改实现。详细实验结论进入案例/规格，根文件只保留跨任务稳定边界。
