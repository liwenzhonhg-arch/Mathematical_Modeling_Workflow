# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 项目概述

`mmw`（Mathematical Modeling Workflow）是一个面向全国大学生数学建模竞赛（CUMCM）的多 Agent 自动化工作流 CLI 工具。8 个流水线阶段由 AI Agent 驱动，产出为人可读文件，通过检查点版本树实现人在环路审查。支持 2-3 人团队 Git 协作。

## 常用命令

```bash
# 安装依赖
pip install -r requirements.txt

# 运行 CLI（开发模式）
python -m mmw.cli <command>

# 测试
pytest tests/
pytest tests/test_checkpoint.py -k "test_version_tree"

# LaTeX 编译（需要 xelatex）
python -m mmw.cli compile
```

## 架构

### 状态机流水线（非线性管线）

流水线不是固定顺序。每个阶段完成后可以 `proceed`（前进）、`rework:stage_name`（回退重做上游）、`branch`（分支平行方案）。检查点形成版本树，重跑某阶段产出新版本号，下游通过 `upstream_hash` 检测上游变更。

`pipeline/state_machine.py` 管理阶段转移逻辑。各 `pipeline/stage_*.py` 是具体阶段实现，调用对应 Agent 并将产出写入检查点。

### 8 个阶段

1. **analyze** — 问题分析，产出 `sub_problems.json`（含子问题依赖声明）
2. **eda** — 数据探索，生成 Python 脚本、结构摘要和统计图表
3. **research** — 方法调研，按关键词读取 HMML 方法正文，并读取 `references/` 下的文本资料
4. **model** — 数学建模，Modeler Agent 生成模型后 Verifier Agent 独立验证
5. **code** — 代码实现，含错误反思循环（生成→执行→检测错误→反思→重试，最多 5 轮）
6. **solve** — 求解运行，subprocess 沙箱执行；有结构化图表 manifest 时可由 FigurePolisher 子 Agent 约束式重制
7. **paper** — 论文写作，分节生成 LaTeX，中文国赛格式；Typesetter 子 Agent 只调整版式
8. **review** — 评审润色，提交清单检查

### Agent 体系

`agents/base.py` 定义 BaseAgent：维护消息历史、token 计数、上下文压缩（超阈值时 LLM 总结旧消息）、流式输出。各角色 Agent 继承基类。

Agent 通过 `llm.py` 调用 LLM。默认使用 openai SDK，通过 `base_url` 兼容 DeepSeek/Claude/Kimi；可选 `LLM_BACKEND=codex` 调用用户本机已登录的 Codex CLI。API 模式下每个 Agent 可在 `.env` 中独立配置模型。

Agent 返回内容用 XML 标签 `<artifact name="filename">content</artifact>` 分段，由基类解析为多个文件写入检查点。

### 检查点版本树与激活版本

`utils/checkpoint.py` 管理 `workspace/<竞赛>/checkpoints/<阶段>/v<N>/` 结构。每个版本目录包含产出文件 + `meta.json`（时间、模型、token）+ `status.json`（审批状态、上游 hash、upstream_changed 标记）。

**激活版本机制**：`config.yaml` 的 `active_versions` 记录各阶段的激活版本，`load_artifacts(stage, version=None)` 读激活版而非最新版（无记录回退 latest）。`approve` 自动激活被审批版本；`mmw approve <stage> --version N` 可切换激活版本。`_compute_upstream_hash` 基于激活版本，branch 出的新版本在激活前不会触发下游 upstream_changed。人工编辑上游检查点后若确认下游无需重跑，用 `mmw ack <stage>` 清除「上游已变更」警告。

### branch 多方案与质量保障链

- **branch**：`mmw branch model` 用 `prompts/model_branch.j2` 生成与激活方案路线级不同的备选方案并独立运行 Verifier；`mmw compare model <v1> <v2>` 用 LLM 生成三维度对比报告到 `output/`
- **数值出处链**：coder 系统提示强制 solution.py 产出 `results.json`（关键数值）和 `sensitivity.json`（参数扰动实验）→ stage_solve 收集进检查点 → writer 写论文时只许引用其中数字 → stage_review 用 `utils/numeric_audit.py`（纯代码零 LLM）提取论文数值比对出处，产出 `numeric_audit.md`
- **隐藏参考回归**：stage_code 只保存本轮新写入的 `results.json` 预览，不读取或传递参考答案。`test_cases/<case>/reference_expected.json` 仅由独立 `mmw benchmark` evaluator 在流水线完成后读取，禁止进入 Agent 提示词和普通检查点。
- **方法契约链**：model 生成稳定目标/约束 ID，code 声明实际算法并绑定代码哈希，solve 绑定结果哈希和 `method_runtime.json` 运行证据；全局最优声明还需穷举覆盖或求解器 gap 证书。paper/review 检查 ID、算法和最优性表述的一致性。
- **批量基准**：`mmw benchmark-suite` 按 `test_cases/benchmark_suite.json` 顺序执行现有 evaluator；没有独立 Oracle 的案例最多为 `scenario-feasible`。
- **GUI 托管**：用户显式启动后，控制器复用现有阶段入口和质量门禁，门禁通过则记录 `managed-controller` 激活；可设置 token 合计与总活跃分钟上限，错误重复、缺数据或预算耗尽时暂停并允许显式恢复。solve 的结构化结果/灵敏度错误会回退 code，不能无效地重复 solve。
- **交付物链**：analyze 的 sub_problems.json 含 `deliverables` 清单（题目硬性要求的 result*.xlsx 等）→ stage_code 传给 coder 强制生成 → stage_solve 校验缺失警告 → `mmw export` 打包进 submission.zip（二进制文件留在 workspace 根，不进检查点）
- **摘要迭代**：stage_paper 在 write_paper 后运行 `_refine_abstract` 循环——AbstractCriticAgent 按国赛标准打分（无记忆，每轮清空历史，保留历史最高分版本）→ writer 修订 → 达 85 分或满 4 轮停止；critic 判定 `needs_upstream_data`（results.json 缺数据）时提前退出提示 rework code；历史存 `abstract_iterations.json`

### 提示词

`prompts/` 下是 Jinja2 阶段模板，`system/` 放各 Agent 系统提示。Coder 的反思提示目前由 `agents/coder.py` 维护。所有提示词中文编写。

### HMML 知识库

`knowledge/hmml.json` 是三级方法树索引（域→子域→方法节点），`knowledge/domains/` 下按域组织的方法详情 Markdown 文件。Researcher Agent 根据问题类型检索匹配方法。

## 关键约定

- **语言**：代码标识符英文，提示词和 Agent 输出中文，注释中文
- **配置**：Pydantic Settings + `.env`；`LLM_BACKEND=openai` 为默认 API/BYOK 模式并支持每 Agent 覆盖（`MODELER_MODEL` 等），`LLM_BACKEND=codex` 为可选本机 Codex CLI 模式
- **检查点状态流转**：pending → completed → approved（proceed/rework/branch）
- **联网搜索**：不内置搜索 API。Agent 在产出中标注 `[需要搜索: 关键词]`，用户在 Claude Code 中用 web-access skill 搜索后将结果放入 `workspace/<竞赛>/references/`
- **LaTeX**：仅国赛模板（CUMCMThesis），xelatex 编译
- **代码执行边界**：`utils/executor.py` 用隔离模式 subprocess、300 秒超时、敏感环境变量剥离和危险导入检查执行生成代码；这不是操作系统级容器
- **Coder 反思循环**：错误信息 + 原始代码 → LLM 修正 → 重试，最多 5 轮；机器质量门禁决定能否审批
- **workspace/ 和 .env 不进 git**
- **真题实测记录**：每次完整流程实测后在 `test_cases/<年份><题号>_<简称>/` 写 case.md（运行记录+成品清单）和 gaps.md（缺陷追踪，分 [工具]/[提示词]/[人工] 三类），成品快照放 deliverables/；约定详见 `test_cases/README.md`。workspace 不进 git，test_cases 进 git
