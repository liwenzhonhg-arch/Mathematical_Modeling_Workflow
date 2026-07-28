# AGENTS.md

本文件是 Codex 接手本仓库时的最高优先级项目规范。`CLAUDE.md` 是原 Claude Code 项目说明，仍作为架构背景参考；如果两者冲突，以本文件为准。

## 项目定位

`mmw`（Mathematical Modeling Workflow）是面向全国大学生数学建模竞赛（CUMCM）的多 Agent 自动化工作流 CLI 工具。它把一道竞赛题组织为 8 个可审查阶段，由 AI Agent 生成可读产物，并通过检查点版本树支持人工审批、回退、分支方案和多人协作。

8 个阶段固定标识如下：

1. `analyze`：问题分析，产出 `analysis.md`、`assumptions.md`、`sub_problems.json`。
2. `eda`：数据探索，产出数据摘要、EDA 代码和统计图表。
3. `research`：方法调研，检索 HMML 知识库并读取人工放入 `references/` 的资料。
4. `model`：数学建模，Modeler 生成模型，Verifier 独立验证。
5. `code`：代码实现，Coder 生成 `solution.py`，并执行错误反思重试。
6. `solve`：运行求解代码，收集 `results.json`、`sensitivity.json`、图表和硬性交付物。
7. `paper`：分节生成中文国赛 LaTeX 论文，并迭代优化摘要。
8. `review`：论文评审、清单检查和数值出处审计。

## 目录约定

- `mmw/`：核心 Python 包。
- `mmw/cli.py`：Typer CLI 入口。
- `mmw/models.py`：阶段、状态、配置等 Pydantic 模型。
- `mmw/pipeline/`：8 个阶段的调度实现与状态机。
- `mmw/agents/`：各角色 Agent，统一继承 `BaseAgent`。
- `FigurePolisherAgent` 与 `TypesetterAgent` 是受约束的阶段内子 Agent：前者位于 `solve -> paper` 之间，只重制结构化数据图表；后者位于 `paper` 内部，只修订 LaTeX 版式。二者不得改变模型、数值、引用事实或新增顶层阶段。
- `mmw/prompts/`：Jinja2 提示词模板；`system/` 放角色系统提示。
- `mmw/utils/`：检查点、执行器、文件读写、显示、数值审计等通用工具。
- `mmw/latex/`：LaTeX 论文组装与编译逻辑。
- `mmw/gui/`：仅监听本机回环地址的浏览器 GUI 服务、工作区 API 和后台任务。
- `mmw/gui/static/`：正式 GUI 的无构建静态前端；入口固定为 `index.html`，不依赖 CDN，不在浏览器端持久化密钥。
- `mmw/desktop.py`：Windows EXE 的双击启动入口，只负责启动正式 GUI。
- `mmw-windows.spec`：PyInstaller Windows x64 `onedir` 打包配置；模板、静态资源和知识库必须显式进入发行包。
- `build-windows.ps1`：可重复的 Windows 打包、ZIP 和 SHA256 生成脚本；不得覆盖已有同版本发行物。
- `README-Windows.txt`：随便携包分发的首次使用说明，保持纯文本、短步骤和无密钥示例。
- `knowledge/`：HMML 方法知识库，`hmml.json` 为索引，`domains/` 存方法说明。
- `tests/`：自动化测试。
- `test_cases/`：真题完整实测记录，必须进 git。
- `workspace/`：CLI 旧式工作区和仓库内实测数据，不进 git；GUI 新项目不要求位于此目录。
- `gui-prototype/`：GUI 交互样式原型；保持为无构建步骤的静态文件，入口固定为 `index.html`，样式与脚本优先内联，不引入运行时依赖；`preview-*.png` 保存人工预览图，`playwright-artifacts/` 保存浏览器验证记录。正式 GUI 方案确定后，经确认再归档或清理。
- `build/`、`dist/`：本机打包中间物和发行物，不进 git；Windows 公开发行物命名为 `MMW-Windows-x64-v<版本>.zip`，同时生成同名 `.sha256`。

新建目录前先明确用途、命名和清理规则；不要随手增加临时目录。一次性调试文件优先放到受控的临时位置，任务结束后说明是否保留。

## 常用命令

```bash
# 安装依赖
pip install -r requirements.txt

# 运行 CLI
python -m mmw.cli <command>

# 查看状态
python -m mmw.cli status --workspace <workspace_name>

# 运行阶段
python -m mmw.cli run <stage> --workspace <workspace_name>

# 审批阶段
python -m mmw.cli approve <stage> --workspace <workspace_name>

# 编译论文，需要本机有 xelatex
python -m mmw.cli compile --workspace <workspace_name>

# 纯本地审计论文数值出处，不调用 LLM
python -m mmw.cli audit --workspace <workspace_name>

# 打包提交物
python -m mmw.cli export --workspace <workspace_name>

# 构建 Windows x64 便携版
powershell -ExecutionPolicy Bypass -File .\build-windows.ps1
```

## 验证命令

代码变更后必须主动验证，按影响范围选择：

```bash
pytest tests/
pytest tests/test_checkpoint.py -k "test_version_tree"
pytest tests/test_state_machine.py
pytest tests/test_stage_solve_collect.py
pytest tests/test_numeric_audit.py
```

文档-only 变更可不跑完整测试，但必须至少重新读取或检查被修改文档，确认编码和内容正常。

## 流水线与检查点约定

- CLI 旧式工作区仍可位于 `workspace/<竞赛名>/`；GUI 可显式选择任意本机可写题目文件夹。
- GUI 新项目的原始问题文件（PDF/DOCX）和附件保持原位且不得改名、移动或覆盖；内部记录统一写入所选文件夹的 `.mmw/`，最终成果统一写入 `output/`。
- GUI 主问题文件支持带文本层的 `.pdf` 和现代 Word `.docx`；`.docx` 使用 Python 标准库只读提取正文，不调用本机 Office。旧版二进制 `.doc` 必须提示用户另存为 `.docx`，不得静默忽略。
- GUI 只读扫描阶段不得创建文件；只有用户点击启动后才能创建 `.mmw/` 和 `output/`。
- 新项目阶段产物保存到 `<题目文件夹>/.mmw/checkpoints/<阶段目录>/v<N>/`；旧式项目继续兼容根目录 `checkpoints/`。
- 每个检查点版本目录包含产物文件、`meta.json` 和 `status.json`。
- 状态流转为 `pending -> completed -> approved`。
- `config.yaml` 中的 `active_versions` 决定各阶段的激活版本。
- `load_artifacts(stage, version=None)` 应读取激活版本；没有激活记录时回退最新版本。
- `approve` 会审批并激活版本；`approve <stage> --version N` 可切换已审批历史版本。
- 下游通过 `upstream_hash` 检测上游激活版本变更。
- branch 产生的新版本在未审批激活前，不应触发下游 `upstream_changed`。
- 人工确认上游变更不影响下游时，用 `mmw ack <stage>` 清除警告。

## 质量保障链

- Coder 必须尽量让 `solution.py` 产出 `results.json` 和 `sensitivity.json`。
- Coder 每次生成或修订完整候选代码后，必须立即写入 `checkpoints/05_code/recovery.json`；进程中断且尚无 code 检查点时，下一次运行应先执行该候选，不能重新消耗一次完整生成请求。
- Coder 沙箱可导入临时注入的 `_mmw_moving_heat` 通用仿真模块；该模块由仓库内 `mmw/utils/moving_heat.py` 提供，执行后清理，不复制到工作区或检查点。移动热过程应优先复用该受测模块，不重复手写有限差分求解器。
- 移动热过程的连续参数标定必须至少使用 3 个不同初值，并调用 `_mmw_moving_heat.assess_multistart_identifiability`；近最优参数或下游关键结果不一致时 code 门禁必须阻断，不得任选一组继续。
- code 检查点必须保存每次候选执行的精简历史，不能只留下最后一次错误；跨阶段修订应同时读取该历史。
- 论文中的关键数值应来自 `results.json`、`sensitivity.json`、`params.json` 或求解日志。
- `stage_review` 使用 `mmw/utils/numeric_audit.py` 做纯代码数值出处审计，不能用 LLM 替代。
- `review` 产出后必须自动运行最终 benchmark，并把 `output/benchmark.json` 绑定到当前 `solve` 与 `review` 版本；报告缺失、失败或版本过期时不得审批 `review`。
- solve 必须绑定代码运行时生成的 `method_runtime.json`；全局最优声明只有在穷举覆盖完整或求解器/上下界 gap 不超过容差时才能通过。
- `model -> code -> solve -> paper -> review` 必须传递同一方法契约；目标、硬约束、算法类别、近似声明和结果文件哈希不一致时不得激活下游版本。
- paper 必须按方法契约区分数学 formulation 与实际 implementation；启发式实现不得在摘要中笼统写成“利用求解器”，符号表必须覆盖 formulation 使用的大写单字母符号。
- Writer 分批或定向修订缺少 artifact 时只自动补齐一次；仍缺失必须明确失败，不得用旧章节假装修订成功。
- 批量真题验证使用独立 `benchmark-suite` 清单；公开阶段产物不得读取 evaluator-only 的参考答案、验收范围或隐藏不变量。
- 有隐藏参考契约且全部通过时可信等级为 `verified`；没有独立 Oracle 时最多为 `scenario-feasible`，不得表述为已通过现实部署验证。
- `reference_expected.json` schema v2 可增加隐藏不变量、压力场景结果范围，以及 code 试运行与 solve 正式运行之间的重复性容差。
- 从确定性参考求解器总结可复用方法时，只能提取不含题目答案、验收范围和专用拟合常数的通用物理结构，并写入公开知识库；必须用独立合成数据回归验证。使用这种结构辅助后的实测应标注为“结构辅助回归”，不得继续称为完全盲测。
- `analyze` 的 `sub_problems.json` 可包含 `deliverables` 清单；`code` 和 `solve` 阶段应继承并校验硬性交付物。
- 二进制交付物如 `result*.xlsx` 留在 workspace 根目录，由 `export` 打包，不写入检查点。
- 摘要迭代由 `stage_paper._refine_abstract` 控制，保留历史最高分版本，默认 85 分或 4 轮停止。
- 图表重制必须以当前 solve 的 CSV/manifest 为数值来源；Origin 仅为 Windows 可选后端，Matplotlib 始终可用且是默认值。
- 最终导出除现有 benchmark 和数值审计外，还必须通过 PDF 视觉质量门禁；缺字、超页、空白正文页、无效/低清图表或测试占位信息均不得进入提交包。

## 语言与编码

- 默认中文沟通。
- 代码标识符、变量名、函数名使用英文。
- 提示词、Agent 输出、面向用户的说明使用中文。
- 代码注释可以中文，但只在解释非显然逻辑时添加。
- Markdown 和 Python 文件使用 UTF-8。
- 在 Windows PowerShell 读取中文文件时，优先使用：

```powershell
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8; Get-Content <file> -Raw -Encoding UTF8
```

## 配置与安全

- `.env` 可被程序读取，但不要为了理解项目主动打开、打印或复制其中内容。
- 不修改 `.env`、密钥、token、CI/CD 配置，除非用户明确要求并再次确认。
- `workspace/` 和 `.env` 不进 git。
- 项目公开提供两种 LLM 模式：默认的 OpenAI-compatible API/BYOK 模式，以及可选的通用 Codex CLI 模式。Codex 模式只允许调用用户本机已有的 `codex`/`codex.cmd` 并复用其本地登录态；通用适配器、无凭据配置说明和测试可以进入 GitHub，但账号凭据、会话文件、本机 Codex 配置、日志、缓存和任何机器专用覆盖不得提交、推送或上传。
- API 模式始终是默认和主要路径；Codex CLI 不存在或未登录时必须明确报错，不得静默切换到 API、读取 ChatGPT/Codex 会话凭据或引导用户把订阅凭据填写成 API Key。
- Windows 发行包不得包含 `.env`、API Key、Codex 登录态、用户工作区、测试产物或本机绝对路径；Codex CLI 和 LaTeX 发行版保持外部依赖，不打进 EXE。
- Windows EXE 启动后可异步检查本仓库最新 GitHub Release；一键更新只接受命名匹配的 Windows ZIP，必须校验 Release API 提供的 SHA256 digest、限制下载和解压体积、拒绝路径穿越，并安装到 `%LOCALAPPDATA%\MMW\versions/` 的新版本目录，不覆盖正在运行的便携目录。
- 不把密钥、token、密码写入代码、日志、测试快照或提交说明。
- GUI 只向浏览器返回脱敏后的 API Key；供应商切换必须由后端把默认模型和各角色模型作为一组原子写入 `.env`，写入后立即刷新进程内配置缓存。
- GUI 的项目路径只能来自本机原生文件夹选择器，并在后端绑定为不透明 `project_id`；浏览器不得提交任意绝对路径。
- GUI 可把最近选择的已初始化项目路径保存到本机用户目录的 `recent-projects.json`；重新启动或刷新时必须由后端重新校验路径并签发新的不透明 `project_id`，不得用浏览器 `localStorage` 持久化绝对路径。
- GUI 选定项目后，文件访问必须限制在该项目目录内；修改类 API 必须校验当前本机会话令牌。
- GUI 不得把“8 阶段完成”表述为答案已验证；必须单独展示 `verified`、`scenario-feasible` 或 `unverified` 可信等级，以及 benchmark 绑定的 solve/review 版本。
- GUI 的阶段审批必须展示阶段专属人工检查清单，并保存审批/重做理由到项目内部 `.mmw/decisions.jsonl`（旧式工作区保存到根目录）；空理由不得执行人工决策。
- GUI 必须提供数值审计、benchmark、论文编译和最终导出入口；benchmark 没有独立 Oracle 时只能得到 `scenario-feasible`。
- GUI 成果列表只把当前 solve `figures_list.json` 声明的图表显示为现役成果；输出目录中的旧图可以保留，但不得与当前图表混列。
- GUI 的长任务必须展示当前阶段、运行状态、开始时间和最终失败原因；浏览器不返回供应商原始响应、prompt、密钥或完整异常正文。
- GUI 托管运行必须显式启动，复用现有阶段入口和质量门禁；机器激活记录 `actor=managed-controller`，达到预算或遇到不可裁决问题时必须暂停，不得伪装成人工审批或自动降低标准。
- 托管 review 出现 fail 时必须按结构化失败项回退 model/code/paper；只有 checklist 缺失或损坏才可原地重跑 Reviewer，不得用重复评审洗掉同一份论文的真实失败。
- 托管时长预算按进程实际活跃时间执行，同时单独记录从首次启动起的墙钟时间；Windows 后台日志必须让普通 `print` 与 Rich 共用 UTF-8 标准流。
- GUI 的图表重制、自动排版和版式检查必须复用现有 Job/项目权限模型；浏览器不得提交 Origin 安装路径或任意本机路径。
- 不安装全局依赖，不修改系统配置。
- 不执行 `git push`、`git rebase`、`git reset --hard`、强制推送等操作，除非用户明确要求并确认。
- 删除文件、目录或 git 历史前必须先问用户。

## 开发纪律

- 先读现有实现和测试，再改代码。
- 优先沿用本仓库已有模式，不引入新的框架或抽象。
- 修改提示词时检查对应 Agent、阶段输入和测试案例，不只看模板本身。
- 修改流水线阶段时同时检查状态机、检查点读写和相关测试。
- 修改 `CheckpointManager` 时重点验证激活版本、上游 hash、审批和 rework 行为。
- 修改 LLM 调用时不要破坏 DeepSeek/Claude/Kimi 通过 OpenAI SDK + `base_url` 兼容的设计。
- 不通过注释掉错误或添加绕过标记来让测试通过；定位根因。
- 保持变更小而清楚，避免把无关重构混入功能修复。

## 真题实测记录

每次完整 8 阶段实测后，在 `test_cases/<年份><题号>_<简称>/` 记录：

- `case.md`：题目来源、运行配置、各阶段结果、成品清单、结论。
- `gaps.md`：缺陷清单，按 `[工具]`、`[提示词]`、`[人工]` 分类，用勾选框跟踪。
- `deliverables/`：最终成品快照，可包含 `paper.pdf`、关键文本产物等。
- `reference_solver.py` / `reference_expected.json`：仅在已有公开代码或论文可交叉验证时保存确定性参考基线和验收范围；必须记录来源 URL，不能把单篇题解的精确答案当作唯一真值。
- `reference_expected.json` 仅供独立 benchmark evaluator 读取；不得复制到工作区、传入任何 Agent 提示词或写入普通阶段检查点。正常流水线只执行通用质量门禁，答案正确性由流水线完成后的 `mmw benchmark` 独立评估。
- 工作区 `config.yaml` 可用 `benchmark_case: <案例目录名>` 显式绑定 evaluator-only 案例；未填写时只允许按唯一的 `<年份><题号>_` 前缀自动匹配。

同一题目重测时，不新建目录；在原 `case.md` 追加新一轮记录，并在 `gaps.md` 勾掉已修复项。

## 接手备注

`CLAUDE.md` 是项目从 Claude Code 迁移过来的原说明，内容仍有参考价值。后续如果项目实践发生变化，先更新本 `AGENTS.md`，再调整代码和流程。
