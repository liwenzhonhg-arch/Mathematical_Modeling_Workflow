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
- `mmw/prompts/`：Jinja2 提示词模板；`system/` 放角色系统提示。
- `mmw/utils/`：检查点、执行器、文件读写、显示、数值审计等通用工具。
- `mmw/latex/`：LaTeX 论文组装与编译逻辑。
- `knowledge/`：HMML 方法知识库，`hmml.json` 为索引，`domains/` 存方法说明。
- `tests/`：自动化测试。
- `test_cases/`：真题完整实测记录，必须进 git。
- `workspace/`：竞赛工作区、数据、检查点、输出和日志，不进 git。

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

# 打包提交物
python -m mmw.cli export --workspace <workspace_name>
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

- 每个竞赛工作区位于 `workspace/<竞赛名>/`。
- 阶段产物保存到 `workspace/<竞赛名>/checkpoints/<阶段目录>/v<N>/`。
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
- 论文中的关键数值应来自 `results.json`、`sensitivity.json`、`params.json` 或求解日志。
- `stage_review` 使用 `mmw/utils/numeric_audit.py` 做纯代码数值出处审计，不能用 LLM 替代。
- `analyze` 的 `sub_problems.json` 可包含 `deliverables` 清单；`code` 和 `solve` 阶段应继承并校验硬性交付物。
- 二进制交付物如 `result*.xlsx` 留在 workspace 根目录，由 `export` 打包，不写入检查点。
- 摘要迭代由 `stage_paper._refine_abstract` 控制，保留历史最高分版本，默认 85 分或 4 轮停止。

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
- 不把密钥、token、密码写入代码、日志、测试快照或提交说明。
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

同一题目重测时，不新建目录；在原 `case.md` 追加新一轮记录，并在 `gaps.md` 勾掉已修复项。

## 接手备注

`CLAUDE.md` 是项目从 Claude Code 迁移过来的原说明，内容仍有参考价值。后续如果项目实践发生变化，先更新本 `AGENTS.md`，再调整代码和流程。
