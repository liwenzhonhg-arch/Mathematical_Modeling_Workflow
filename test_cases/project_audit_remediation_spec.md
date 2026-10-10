# 项目整体审查整改 Spec

状态：第二轮自动化整改已实施；Windows 发行包与双版本实机切换证据仍待完成

基线提交：`28ad04df2b5bc6befa25b95ed99d18c4917f1263`

第二轮审查基线：`5d5d598d738803d715d96c79c86b05bed4d9a545`

审查日期：2026-08-22；第二轮审查日期：2026-09-01

## 1. 目标

本 Spec 将 2026-08-22 项目整体审查中确认的问题转换为可实现、可回归、可阻断发布的合同。
整改完成后必须同时满足：

1. LLM 生成代码不能访问授权工作目录之外的文件，也不能默认联网；
2. 本机 GUI 的会话令牌、写接口、审批和任务状态不能被跨站请求或并发竞争绕过；
3. schema v2 模型结构失败、混合版本修订和越界假设不能进入下游或获得审批；
4. Skill、配色资源和科研绘图基准在干净 checkout、wheel 与 Windows 包中行为一致；
5. 案例事实只留在对应案例，文档、规格、测试和发行报告只陈述当前可复验证据。

本 Spec 不把 `pytest` 通过等同于安全、发行或真实赛题能力已经验证。每一类结论必须通过本节后续定义的专项证据。

## 2. 范围与非目标

### 2.1 范围

- `mmw/utils/executor.py` 及 EDA、Coder、Solve 的生成代码执行路径；
- `mmw/gui/server.py`、`providers.py`、`managed_run.py` 的请求、锁、日志和任务状态；
- `mmw/pipeline/stage_model.py`、`state_machine.py`、`model_handoff.py` 及 Coder/Writer 输入；
- `mmw/update.py`、`release_validation.py`、`pyproject.toml`、`mmw-windows.spec`；
- `skills/`、科研配色运行时资源和科研绘图 benchmark；
- 全局 prompt、`test_cases/README.md` 和与本次整改直接相关的规格。

### 2.2 非目标

- 不增加第九个顶层阶段、新 Agent、新 GUI 页面或新状态机；
- 不安装全局依赖，不把 Docker、WSL 或第三方容器设为默认前提；
- 不修改算法答案、Oracle、历史检查点或真实赛题数值；
- 不借安全整改重写全部 GUI、执行器或模型 schema；
- 不把本次整改宣称为抵御同一 Windows 用户下所有本机恶意程序；
- 不删除或迁移现有文件。删除、迁移和历史清理在实施时仍需单独遵守用户确认红线。

## 3. 全局不变量

以下不变量优先于各模块的局部实现：

- **AR-GEN-001 默认拒绝**：安全前置条件无法建立时停止操作，不得静默降级为不安全路径。
- **AR-GEN-002 单一事实来源**：同一模型、配色、任务状态或发行文件不得存在未校验的平行现役版本。
- **AR-GEN-003 原子写操作**：检查前置条件、状态变更和任务登记必须位于同一项目级临界区。
- **AR-GEN-004 安全摘要**：浏览器响应和持久化日志只接收统一脱敏器产生的摘要。
- **AR-GEN-005 干净环境证据**：涉及打包、安装和复算的能力必须在干净 checkout 或临时安装目录验证。
- **AR-GEN-006 兼容但不伪装**：旧检查点允许只读降级；缺少新合同不能标成新合同通过。
- **AR-GEN-007 测试不得自证**：测试必须覆盖真实 consumer、真实 validator 或真实安装产物，不能只检查字符串存在。

## 4. 生成代码执行边界

### 4.1 威胁模型

EDA、Coder 和 Solve 执行的 Python 均视为不受信任输入。来源包括模型错误、题目附件中的提示注入和恢复候选。
`python -I`、AST 黑名单和删除敏感环境变量只属于纵深防御，不构成安全隔离证明。

### 4.2 执行合同

- **AR-EXEC-001**：默认执行模式必须建立操作系统级隔离；如果当前平台不能建立，阶段在执行前阻断并返回固定错误码 `execution_isolation_unavailable`。
- **AR-EXEC-002**：隔离进程只获得本轮临时工作目录和显式复制进去的输入；不得继承项目父目录、用户目录、`APPDATA`、`.env` 或登录态访问能力。
- **AR-EXEC-003**：隔离进程默认无网络。任何联网能力必须属于单独的、非生成代码路径，并服从已有 Research 白名单。
- **AR-EXEC-004**：只把显式白名单环境变量传给子进程；禁止从父进程复制后再按名称删减。
- **AR-EXEC-005**：输出只能从临时目录中声明的相对路径收集。绝对路径、`..`、符号链接、junction、硬链接或解析后越界均拒绝。
- **AR-EXEC-006**：超时、输出上限和进程树终止继续保留；终止时必须结束子进程树，不能只结束顶层 Python。
- **AR-EXEC-007**：界面和文档只有在 AR-EXEC-001～006 全部通过当前平台测试时才使用“隔离执行”；否则必须明确显示“生成代码执行不可用”，不得称为“沙箱”。

### 4.3 最小攻击回归

测试必须在临时 canary 上验证以下程序均失败，且 canary 内容不变：

1. `pathlib.Path(outside).write_text(...)`；
2. `open(outside, "rb")`；
3. `shutil.copytree(...)` 越界；
4. `os.remove(...)` 越界；
5. 通过 `ctypes` 调用文件 API；
6. `httpx`、`urllib`、socket 和子进程发起网络请求；
7. 通过 symlink/junction 指向工作目录外；
8. 子进程再启动孙进程并在超时后继续存活。

正常程序仍须能读取获准 CSV、写入声明的 JSON/CSV/PNG，并由 EDA、Code、Solve 三条真实调用路径收集。

## 5. GUI 请求与并发安全

### 5.1 本机来源校验

- **AR-GUI-001**：在返回 HTML、静态资源或会话令牌前校验 `Host`。只接受启动时实际绑定的 loopback host/port，以及等价的 `localhost`/`127.0.0.1`/`[::1]` 形式；其他 Host 返回固定拒绝响应。
- **AR-GUI-002**：所有写请求同时校验会话令牌和同源信息。浏览器请求的 `Origin` 必须与当前 loopback origin 完全一致；跨站 `Sec-Fetch-Site` 请求拒绝。
- **AR-GUI-003**：会话令牌不得进入 URL、日志或错误消息；含令牌页面和 API 响应设置 `Cache-Control: no-store`。
- **AR-GUI-004**：页面至少返回 `Content-Security-Policy`（含 `frame-ancestors 'none'`）和 `X-Frame-Options: DENY`；不得为此引入 CDN。
- **AR-GUI-005**：GET 路由必须只读。重启恢复、orphan 标记或 managed-run 状态修正必须由启动恢复流程或带令牌的写操作完成。

### 5.2 项目级原子操作

- **AR-GUI-006**：以下序列必须位于同一项目级锁中：检查 active job → 重读目标版本 → 执行审批门禁 → approve/rework 状态变更 → 决策记录 → 必要时登记 Job。
- **AR-GUI-007**：`approve`、`rework`、`rework_and_run`、普通 `start_run`、托管恢复共享同一锁和唯一 active-job 判定。
- **AR-GUI-008**：锁内不得执行 LLM、编译或网络下载等长任务；只完成状态核验和原子登记。
- **AR-GUI-009**：并发失败不能产生审批记录、半写状态或重复 Job。

专项测试使用 barrier/event 固定竞争窗口，至少覆盖 `approve vs start`、`approve vs rework_and_run`、双击 start 和双击 approve。

### 5.3 统一脱敏

- **AR-GUI-010**：异常、CLI stdout/stderr、供应商错误和更新错误在写入 `Job.message` 前统一经过一个脱敏函数；API 与 `jobs.jsonl` 不得各自实现不同规则。
- **AR-GUI-011**：脱敏覆盖常见 Key/Bearer/token/cookie/URL 凭据形式，并对未知原文设置长度上限；原始供应商响应和完整命令不得持久化。
- **AR-GUI-012**：预期失败、非零退出码、未知异常和恢复失败使用同一脱敏路径。

回归夹具至少包含 `sk-*`、`Bearer ...`、查询参数 token、JSON key、Basic URL 凭据和多行 stderr。

### 5.4 心跳语义

- **AR-GUI-013**：区分 `process_heartbeat_at` 与 `worker_activity_at`。watchdog 只能证明 GUI 进程活着，不能刷新 worker 活动时间。
- **AR-GUI-014**：worker 活动只由执行线程、流式响应/请求观察器或确定性步骤边界更新。
- **AR-GUI-015**：等待已知外部调用时显示 `waiting_external` 和真实耗时；超过该调用的明确超时后失败。非外部等待且 worker 活动超阈值才显示 stalled。
- **AR-GUI-016**：运行态继续覆盖检查点完成态；stalled 只是可诊断状态，不自动伪造阶段失败或重跑。

## 6. 模型结构、修订与下游一致性

### 6.1 结构门禁接入审批

- **AR-MODEL-001**：`model_structure_issues()` 的 blocking 结果必须在保存 `verify_status.json` 前并入本轮 severity。
- **AR-MODEL-002**：`model_quality_report.json.status=fail` 必须被 `state_machine.can_approve(MODEL)` 直接拒绝；缺失报告的新 schema v2 版本也拒绝。
- **AR-MODEL-003**：下一轮不能重新初始化并遗失上一轮结构问题；传给修订 Agent 的 issue 必须来自已保存的规范化问题列表。
- **AR-MODEL-004**：LLM Verifier 的 `pass` 不能覆盖确定性结构失败；两者取更严重等级。

### 6.2 修订原子性

- **AR-MODEL-005**：每次模型修订必须完整返回 `model.md`、`equations.json` 和 `params.json`。任一缺失时本轮不保存可审批模型版本。
- **AR-MODEL-006**：禁止把本轮部分 artifact 与上一轮 canonical artifact 静默合并为新版本。
- **AR-MODEL-007**：`model_handoff.md`、`method_contract.json`、质量报告和 revision history 只能从同一轮通过校验的三个 canonical artifact 生成。
- **AR-MODEL-008**：修订后记录三个输入 artifact 的 SHA-256；下游发现哈希不一致时阻断，不回退到旧 handoff。
- **AR-MODEL-009**：旧 schema 检查点继续按既有降级读取，但对旧检查点的修订一旦保存为新版本，就必须满足当前完整合同。

### 6.3 假设与来源交叉校验

- **AR-MODEL-010**：子问题引用某个假设时，该子问题 ID 必须存在于假设 `scope`；`scope=["all"]` 仅在 schema 明确定义后允许，不能隐式猜测。
- **AR-MODEL-011**：`constraint.source_type=modeling_assumption` 时，`source_ref` 必须指向存在、作用域匹配且同时列入该子问题 `assumption_refs` 的假设。
- **AR-MODEL-012**：硬约束、题面事实、定义和实现选择继续使用各自来源类型，不允许用真实假设 ID 掩盖错误分类。

### 6.4 Writer/Coder 输入完整性

- **AR-MODEL-013**：Coder 按当前子问题取得完整 handoff 段和全局参数，不使用对整个文件的盲目字符截断。
- **AR-MODEL-014**：生成 `symbols.tex` 的批次必须看到全部变量、参数和公式中的符号。容量控制按结构化条目选择，不能从条目中间截断。
- **AR-MODEL-015**：论文符号门禁同时核对 equations 的 variables/formulas 与生成的符号表，不能只扫描 method-contract 的大写单词。
- **AR-MODEL-016**：多子问题长 handoff 回归必须把最后一个子问题的唯一符号放在旧 2000 字截断点后，并证明其仍进入 prompt 和 `symbols.tex`。

## 7. Skill、运行时资源与科研图表复算

### 7.1 Skill 有效性

- **AR-SKILL-001**：项目内每个 `SKILL.md` 必须通过当前实际 Skill validator；不支持的 frontmatter 字段不得靠自定义字符串测试放行。
- **AR-SKILL-002**：测试至少解析真实 frontmatter 允许字段；开发/交付验证命令调用项目指定 validator。validator 不可用时状态为 pending，不得写“Skill is valid”。
- **AR-SKILL-003**：Skill 的 `compatibility` 信息如需保留，移入正文或允许的 metadata，不扩展平台 schema。
- **AR-SKILL-004**：项目内调用不等同于全局安装；不得因修复 validator 自动安装 Skill。

### 7.2 配色资源打包

- **AR-PKG-001**：配色目录保持一个规范来源，并由一个公共 resolver 定位；源码、wheel 和 Windows 包不得各自硬编码不同路径。
- **AR-PKG-002**：wheel 与 Windows 包必须包含运行时所需目录、选择器和许可证/notice；缺失时 renderer 明确失败，不能静默换回另一套颜色后仍报告目标 `palette_id`。
- **AR-PKG-003**：打包后质量报告中的目录 SHA-256、`palette_id` 和角色 HEX 必须与源码测试一致。
- **AR-PKG-004**：在临时目录安装 wheel 后实际调用 renderer；Windows 发行测试从解压后的包调用同一 resolver。

### 7.3 benchmark 干净复算

- **AR-FIG-001**：validator 要求存在并校验哈希的基准文件必须由 Git 跟踪，或由同一测试在临时目录确定性生成；二者只能选择一种，不得依赖开发机遗留文件。
- **AR-FIG-002**：本项目选择跟踪 Matplotlib、MATLAB 基准的受控 PNG/PDF；`.gitignore` 只为 `test_cases/scientific_figure_benchmark/outputs/**` 增加窄范围 PDF 例外，不放开全仓 PDF。
- **AR-FIG-003**：Origin 继续按真实能力记录 `supported/degraded`；缺失的图不能用总体 `passed=true` 隐藏，报告必须单列覆盖率。
- **AR-FIG-004**：validator 在一个新 clone 等价目录执行，证明报告未读取被忽略文件或仓库外路径。
- **AR-FIG-005**：实验规格、人工评审和 Skill 状态必须使用绝对日期和当前状态；“尚未形成 Skill”等历史说法只能放历史小节。

## 8. 更新、供应商与发行安全

### 8.1 更新安装

- **AR-UPD-001**：已存在的版本目录不能只凭 `.mmw-update.json` marker 复用。必须重新校验必需文件、大小和发行 manifest/digest；无法证明一致时安装到新的临时版本目录。
- **AR-UPD-002**：禁止原地覆盖当前版本；下载、校验、解压、资源验证全部完成后才允许进入切换阶段。
- **AR-UPD-003**：更新 Job 只有在新版本完成启动握手后才标记 `completed`。`Popen` 成功不等于新 GUI 可用。
- **AR-UPD-004**：切换由独立 helper 完成：先验证新可执行文件可启动，再关闭旧服务；新服务健康检查失败时保留可恢复旧版本的明确状态。
- **AR-UPD-005**：任何失败不得同时留下“completed”记录和不可用的新版本路径。

### 8.2 供应商 URL

- **AR-PROVIDER-001**：`http://` 只允许 loopback 地址；其他主机必须使用 `https://`。
- **AR-PROVIDER-002**：URL 禁止 userinfo、fragment 和非 HTTP(S) scheme；解析后的 host 必须重新校验，不能只检查字符串前缀。
- **AR-PROVIDER-003**：测试覆盖 IPv4、IPv6、localhost、外部域名、userinfo 和重定向后的降级协议。

### 8.3 发行敏感文件

- **AR-REL-001**：路径门禁覆盖 `.env*`、credentials/auth/token/cookie/session/key 等常见名称及浏览器/CLI 登录态目录，大小写不敏感。
- **AR-REL-002**：对受支持的文本配置执行轻量内容扫描；命中疑似私钥、Bearer、API Key 时失败并只报告文件路径和规则名，不打印秘密。
- **AR-REL-003**：扫描白名单必须极小且有测试，不能通过改名绕过。
- **AR-REL-004**：现有 digest、路径穿越、大小、重复路径和新目录安装门禁继续保留。

## 9. 案例隔离、工具与文档

- **AR-DOC-001**：从所有全局 system/user prompt、通用运行时摘要和默认知识上下文移除 `2020A`、精确温区、固定扫描次数、探针结构等案例事实。
- **AR-DOC-002**：增加无关题目负向渲染测试，覆盖 Analyst、Modeler、Verifier、Coder、Writer、revision 和条件运行时摘要；测试断言案例语义不存在，而非只检查案例编号。
- **AR-DOC-003**：移动热等领域能力只由当前结构化方法合同选择；文本中的否定句、历史描述或无关题目不能触发。
- **AR-DOC-004**：`test_cases/README.md` 的规格路由同步模型交接、论文写作、科研配色及本 Spec。
- **AR-DOC-005**：规格中的可执行命令使用仓库相对路径；本机绝对路径只允许出现在带日期的历史证据块，并明确不可复用。
- **AR-DOC-006**：`tools/export_q1_rolling_hourly_submission.py` 归类为案例专属工具；迁移到对应案例前先获得删除/移动授权。授权前不得被通用流程导入或打包。
- **AR-DOC-007**：`tools/` 的用途、命名和清理规则必须先写入项目规则，再新增通用脚本。
- **AR-DOC-008**：修复所有 staged `git diff --check` 错误；CRLF 转换提示可以保留为 warning，但不得把真实尾随空格或 EOF 错误称为通过。

## 10. 测试与证据矩阵

| 合同 | 最小自动化证据 | 额外证据 |
|---|---|---|
| AR-EXEC-* | `tests/test_executor.py` 的越界、网络、链接和进程树攻击测试；EDA/Code/Solve 调用测试 | Windows 实机隔离探针 |
| AR-GUI-001～005 | Host/Origin/Sec-Fetch/GET 只读/安全头测试 | 本地浏览器 DNS rebinding 夹具 |
| AR-GUI-006～009 | barrier 控制的并发测试 | jobs/decisions/版本状态复核 |
| AR-GUI-010～016 | 多来源秘密脱敏、worker 卡死、外部等待测试 | 刷新后的 UI 状态检查 |
| AR-MODEL-* | model loop、`can_approve()`、完整修订、scope/source、长 handoff 测试 | 一个旧 schema 降级夹具 |
| AR-SKILL-* | 两个 Skill 的真实 validator | validator 版本与命令记录 |
| AR-PKG-* | 临时 wheel 安装和 PyInstaller 资源检查 | Windows 解压包 smoke test |
| AR-FIG-* | clean-checkout validator | 人工检查最终栏宽/灰度 |
| AR-UPD-* | 伪 marker、篡改目录、启动失败和握手测试 | 独立 helper 的 Windows 测试 |
| AR-PROVIDER-* | URL 参数化测试 | 无真实 Key 网络调用 |
| AR-REL-* | 文件名与内容秘密夹具 | 最终 ZIP 扫描报告 |
| AR-DOC-* | 全 prompt 负向渲染、相对路径和文档引用检查 | neat-freak 只读收尾 |

完整验证命令至少包括：

```powershell
python -m pytest -q tests/
python -m compileall -q mmw skills tools tests
python test_cases/scientific_figure_benchmark/scripts/validate_outputs.py
python C:\Users\moonman\.codex\skills\.system\skill-creator\scripts\quick_validate.py skills/mmw-paper-human-writing
python C:\Users\moonman\.codex\skills\.system\skill-creator\scripts\quick_validate.py skills/scientific-chart-palette
git diff --check
powershell -ExecutionPolicy Bypass -File .\build-windows.ps1
```

其中 Skill validator 的绝对路径仅是当前本机验证入口；实现时应提供可发现的当前平台入口，不能把该路径固化进公共测试。

## 10.1 当前验收状态（2026-08-22）

已验证：全量测试、compileall、项目内 Skill validator、科研绘图 benchmark、wheel 干净
checkout 资源检查、wheel 临时目录实际 resolver 消费、`git diff --check`。

待验证或有边界：Windows PyInstaller 构建与解压包 smoke test 尚未在本轮执行；当前平台没有
OS 级生成代码隔离后端，因此默认路径按 `execution_isolation_unavailable` fail-closed，
只有显式 `trusted-local` 才可用于授权的本地测试。`.tmp/` 中的干净 checkout 和构建现场保留，
清理需另行确认。

## 10.2 第二轮审查新增缺口（2026-09-01）

第二轮只读审查在提交 `5d5d598` 上复现并确认以下问题。它们重新打开本 Spec；
在本节要求全部通过前，不得把项目整体整改标记为最终验收完成。

### 10.2.1 上游变更与历史版本激活

- **AR-STATE-001**：`get_next_runnable()` 必须把最早的 `upstream_changed` 现役阶段视为待重跑，
  不得跳过它并返回下游阶段，也不得把整条流水线报告为已完成。
- **AR-STATE-002**：`can_run(stage)` 必须检查该阶段之前的全部现役阶段；任一阶段未审批、
  `upstream_changed=true` 或当前确定性质量门禁失败时，均阻断运行并返回具体阶段和原因。
- **AR-STATE-003**：CLI 和 GUI 激活历史已审批版本时，必须重新执行当前确定性质量门禁，
  并在同一原子操作中切换版本、刷新该阶段及全部下游的 `upstream_changed` 标记和记录决定。
- **AR-STATE-004**：历史版本与当前上游不一致时可以被用户选为现役比较方案，但必须明确标记
  为 stale，并阻断下游；只有重跑或显式 `mmw ack` 才能解除该状态。
- **AR-STATE-005**：GUI、CLI、托管运行和直接状态机调用必须共享上述判定，不得各自维护
  一套“可运行”逻辑。

最小失败复现：审批 `analyze v1 -> eda v1`，再生成并审批 `analyze v2`。此时
`eda v1.upstream_changed=true`，`get_next_runnable()` 不得返回 `research`，
`can_run(research)` 必须失败。

### 10.2.2 Windows 更新切换与回退

- **AR-UPD-006**：不得在证明候选版本可启动前关闭旧 GUI。候选版本的预检必须由独立 helper
  完成，且不能只以 `Popen` 成功或文件 marker 作为健康证据。
- **AR-UPD-007**：启动证据必须包含真实 HTTP 健康检查，并核对候选版本号；在最终固定端口
  上完成健康检查后，更新 Job 才能标记 `completed`。
- **AR-UPD-008**：最终切换失败时，helper 必须重新启动旧版本并留下可读取的失败状态；
  不得同时出现“更新完成”和两个版本均不可用。
- **AR-UPD-009**：启动握手文件只能作为进程间通知，不能替代端口监听、HTTP 响应和版本核对。
  临时文件无论成功或失败都必须清理。

### 10.2.3 敏感值识别

- **AR-REL-005**：发行内容扫描必须识别带前缀的常用变量名，包括 `LLM_API_KEY`、
  `<ROLE>_API_KEY`、`OPENAI_API_KEY`、`ANTHROPIC_API_KEY`，不能因变量名前的下划线使
  `api_key` 单词边界失效。
- **AR-GUI-017**：GUI 与 `jobs.jsonl` 的统一脱敏必须覆盖上述变量名、Bearer、Basic、
  JSON 键值、查询参数、Cookie 和 URL userinfo；只报告规则名或 `<redacted>`，不回显原值。
- **AR-REL-006**：发行扫描和 GUI 脱敏使用相同的敏感键命名合同；实现可以不同，但测试夹具
  必须共用，避免一处修复而另一处继续泄漏。

### 10.2.4 缺失的回归证据

- **AR-TEST-001**：执行器测试逐项覆盖 4.3 的八类攻击；当前无 OS 隔离后端时仍应逐项证明
  默认路径在执行前返回 `execution_isolation_unavailable`，不得只用一个普通打印用例代替。
- **AR-TEST-002**：GUI 使用 `Barrier`/`Event` 固定竞争窗口，覆盖 `approve vs start`、
  `approve vs rework_and_run`、双击 start、双击 approve 和初始化并发。
- **AR-TEST-003**：更新测试覆盖候选预检失败、最终健康检查失败、旧版本恢复、伪 marker、
  已安装文件篡改、HTTPS 重定向降级和临时握手清理。
- **AR-TEST-004**：敏感值测试使用真实项目变量名；断言响应、Job、`jobs.jsonl` 和发行错误消息
  均不包含夹具中的秘密原文。

第二轮审查时已有 `589 passed`、compileall、两个 Skill validator、科研绘图 benchmark 和
`git diff --check` 通过；这些结果只证明现有测试为绿，不覆盖本节新增失败复现。Windows 标准
构建和解压包更新回退实测仍为 pending。

## 10.3 第二轮证据矩阵

| 合同 | 必须新增或扩展的自动化证据 | 额外证据 |
|---|---|---|
| AR-STATE-001～005 | `tests/test_state_machine.py`、`tests/test_checkpoint.py`、`tests/test_gui.py` 的 stale 链和历史激活测试 | CLI 实际命令输出 |
| AR-UPD-006～009 | `tests/test_update.py`、`tests/test_gui.py` 的 helper/HTTP/rollback 测试 | Windows 两个便携版本切换实测 |
| AR-REL-005～006、AR-GUI-017 | 共享秘密夹具驱动 `tests/test_release_validation.py` 和 `tests/test_gui.py` | 最终 ZIP 扫描报告 |
| AR-TEST-001～004 | 对应测试名和 requirement ID 映射表 | clean checkout 重跑记录 |

停止条件：若更新回退只能通过覆盖或删除现有版本目录实现，或状态机修复需要静默清除
`upstream_changed`，立即停止并重新评审设计；不得以降低门禁或自动 `ack` 通过测试。

### 10.4 第二轮实施状态（2026-09-01）

已验证：AR-STATE-001～005、AR-REL-005～006、AR-GUI-017、AR-TEST-001～004 的代码与
自动化回归已落地；全量 `625 passed`，compileall、两个 Skill validator、科研绘图 benchmark
和 `git diff --check` 通过。更新 helper 的候选预检、HTTP 版本核对、最终失败回退和状态文件已由
单元/本机 HTTP 测试覆盖。

仍为 pending：当前 `dist/MMW-Windows-x64-v0.1.7.zip` 已存在，标准构建按不覆盖规则停止；
未删除或覆盖该发行物。因此当前代码的 Windows 新包扫描、两个真实便携版本切换和最终固定端口
回退尚未实测，不能标记为发布验收完成。当前平台仍无 OS 级生成代码隔离后端，默认路径继续以
`execution_isolation_unavailable` fail closed。

## 11. 实施批次与停止条件

| 批次 | 范围 | 完成条件 |
|---|---|---|
| A | AR-EXEC、AR-GUI-001～012 | 越界、跨站、竞争和秘密夹具全部失败关闭 |
| B | AR-GUI-013～016、AR-MODEL | 任务状态可信，模型结构和修订无法绕过审批 |
| C | AR-SKILL、AR-PKG、AR-FIG | validator、wheel、Windows 资源和 clean checkout 一致 |
| D | AR-UPD、AR-PROVIDER、AR-REL | 篡改目录、启动失败、明文外部 URL 和敏感包均阻断 |
| E | AR-DOC 与全量回归 | 案例隔离、文档路由、`git diff --check` 和 neat-freak 通过 |

每个批次单独实现、验证和复核。任一批次出现以下情况立即停止，不进入下一批：

- 为通过测试降低既有质量或安全阈值；
- 需要删除、迁移、修改 `.env`、安装全局依赖或改系统配置但尚未获得授权；
- 只能通过继续依赖开发机残留文件才能通过；
- 真实 consumer 与测试替身行为不一致；
- 发现修复会改变题目数值、Oracle 或历史检查点。

## 12. 最终验收

### 2026-09-10 赛前增量修复

- 数值门禁不得把名称中任意位置出现的“时间”“比例”等词当作范围合同。保留可明确识别的指标尾部语义检查；通用比例、偏移、差值和变化量不据此硬性否决，题目专属范围仍由方法合同和独立验证负责。
- GUI 首页脚本使用每次响应新生成的 CSP nonce；保留同源及禁止嵌入策略。现有动态样式允许内联 CSS，但不得允许任意内联脚本；数据图标仅在 img-src 放行。
- 供应商测试/发现必须先合并保存配置与请求，再统一校验最终 Base URL；回归只使用虚构密钥。
- HMML 索引与领域正文必须声明为 knowledge 包资源，不能列入排除项；验证区分配置检查与实际 wheel 检查。
- 本批不实现论文 Markdown 同步，不修改历史题数值或 Oracle，不自动开启 trusted-local，不声称完成真实题目端到端或 Windows 发布验收。

本批验证记录：4 项新增回归先失败，修复后专项 144 passed，全量 629 passed（55.17s）。
浏览器使用真实首页响应与 CSP、虚构 API 数据：boot 已定义，接口页导航可用，CSS 生效，
控制台 0 errors / 0 warnings；不代表真实供应商或完整 GUI 业务验收。
仓库 .venv 的 setuptools build_py 资源枚举包含 HMML 索引与 42 篇领域文档；
未构建实际 wheel 或 Windows 包。结果名尾部语义仍属启发式，并非完整的题目范围合同；
已消除本轮通用比例与有符号变化量误判，不宣称解决任意命名的语义理解。
历史题真实求解、论文 Markdown 同步及发行验收保持 pending。审查用浏览器证据保留在
工具管理的 .playwright-mcp/，未经确认不清理。

### 2026-10-09 增量审查合同

- 审批、下一阶段选择和托管恢复必须只读重算上游 hash；非现役待审批分支、人工编辑后未刷新的状态标记均不能绕过过期检查。过期 completed 版本应允许重跑，最新版本被明确标记 pending 时不得因旧现役版本已审批而跳过重做。
- GUI 更新与项目初始化、阶段运行、托管运行和质量工具必须互斥；更新登记后不得启动新项目任务。任务收尾只能移除自身的活动登记，确认上游变更同样服从项目空闲锁。
- Job 的结构化 result 按敏感键名脱敏，历史日志读取使用相同规则；短口令、含空格或转义引号的值不得泄漏。发行内容扫描继续使用共同的敏感字段合同。
- HTTP 请求体长度必须为非负有界整数，不能对负数调用无限读取。
- 执行器创建的临时脚本使用独占的新文件名，只清理本次创建的文件；即使默认隔离不可用，也不得覆盖或删除工作区已有同名脚本。
- 更新 Job 必须取得明确成功的健康确认才报告完成；失败后的结构化结果不能保留 `ok=true`。切换 helper 的等待预算须覆盖端口释放、候选检查、终止和旧版本恢复的完整上限。
- 模型结构报告存在时必须包含合法状态，问题列表如有提供必须为数组；空对象、未知状态及非法 Verifier 严重等级均返回明确门禁错误，不能被当作通过或导致审批接口异常。
- GUI 的“下一阶段”区分运行中、等待审批、待处理和全部审批完成，不得把 `next_stage=null` 直接显示为全部完成。

本轮结果：上述缺陷均已修复；新增 24 项回归，全量 **653 passed**（66.22s，
进程内关闭外部 pytest 插件自动加载）。`compileall`、CLI `--help`、首页 JavaScript
语法检查和核心包未定义名称/语法扫描通过；扫描还修复了配色资源加载失败分支中一个未定义变量。
两个项目 Skill 的实际 validator 与科研图表基准校验通过；Origin 仍保留原报告的降级警告。

| 范围 | 本轮证据 |
|---|---|
| 非现役分支、手工编辑与重做 | `tests/test_state_machine.py`，`tests/test_managed_run.py` |
| 更新互斥、旧任务收尾、ack 锁、非法长度、结构化脱敏 | `tests/test_gui.py`，包含 Barrier 控制的更新/阶段启动竞争 |
| 同名脚本保护 | `tests/test_executor.py`，isolated 与 trusted-local 两条路径 |
| 短口令、空格和转义值 | `tests/security_fixtures.py` 同时驱动 GUI 与发行扫描 |
| 空/非法模型报告与 Verifier 严重等级 | `tests/test_state_machine.py` 的五项失败回归 |
| 实际页面 | 临时项目：运行中审批与重做禁用，刷新保持任务；同源忙碌审批返回 400，跨站返回 403；无控制台 error/warning。等待审批/完成文案另用合成摘要验证 |
| wheel 资源 | 临时干净源码构建实际 wheel，解包到新目录，从包内导入 mmw、42 篇知识文档、配色选择器和脱敏模块成功 |

本轮没有调用真实供应商、消耗竞赛正式测试机会或运行真题全流程；没有构建/替换 Windows
EXE，因此双版本实机更新仍为 pending。默认生成代码的 OS 隔离后端仍不可用并按原合同阻断。
论文 Markdown 同步仍是前一批已记录的功能待办。本轮临时构建、浏览器夹具与静态检查依赖已清理；
已有历史检查点、发行物、`.playwright-mcp/` 旧证据和用户原有未提交改动保持原状。

整改完成必须同时具备：

1. 本 Spec 的全部 requirement ID 均有代码位置和测试映射；
2. P1 问题有失败测试先证实、修复后转绿；
3. 完整测试、compile、Skill validator、clean-checkout 图表验证和 Windows 构建通过；
4. Windows 包内实际存在并能加载配色/Skill 所需资源；
5. GUI 浏览器验证覆盖跨站拒绝、运行中禁止审批、安全错误摘要和真实 worker 状态；
6. 新生成模型的质量报告失败不能审批，部分修订不能形成混合版本；
7. 无关题目渲染不含其他案例的几何、常数和运行指令；
8. README、AGENTS、test_cases 路由和实现保持一致；
9. 最终代码审核与 `/neat-freak` 只读收尾完成；
10. 未执行 `git push`、发布、删除、迁移或全局安装，除非用户在对应步骤单独授权。
