# mmw

面向全国大学生数学建模竞赛的 8 阶段、人工审批式工作流 CLI。

## Windows 便携版

不安装 Python 的用户可从 [GitHub Releases](https://github.com/liwenzhonhg-arch/Mathematical_Modeling_Workflow/releases) 下载 `MMW-Windows-x64-v<版本>.zip`，完整解压后双击 `MMW.exe`。程序启动后会异步检查官方 Release；发现新版时，右上角可一键下载、校验 SHA256、安装到当前用户目录并重启。API Key 或 Codex 登录态由用户自行配置，不包含在发行包中；生成最终 PDF 仍需另外安装 MiKTeX/TeX Live。

新建项目可直接选择包含 `.pdf` 或 `.docx` 题目文件的文件夹；旧版 `.doc` 请先用 Word 另存为 `.docx`。
最近打开的已初始化项目记录在当前用户的 `%APPDATA%\MMW\recent-projects.json`；刷新页面或重新启动 EXE 后会由本机后端重新校验并恢复，不在浏览器中持久化绝对路径。

## 安装

```powershell
python -m pip install -e ".[dev]"
Copy-Item .env.example .env
python -m mmw.cli check-config
```

另需安装 `xelatex` 与 `bibtex`。正式编译前，在工作区 `config.yaml` 填写：

```yaml
title: 正式论文题目
team_number: 参赛队号
problem: A
max_pages: 20
# 可选：绑定 test_cases 下的隐藏独立评测案例
benchmark_case: 2020A_炉温曲线
# 可选：Windows 已安装 Origin 2024 时使用 origin；默认 matplotlib
figure_backend: matplotlib
# 测试项目可设为 true；正式提交保持 false
allow_test_placeholders: false
```

## 两种模型模式

- **API / BYOK（默认）**：保持 `.env` 中 `LLM_BACKEND=openai`，填写 `LLM_API_KEY`、`LLM_BASE_URL` 和 `LLM_MODEL`。支持 OpenAI-compatible Chat Completions 接口，也支持各角色 Agent 覆盖模型。
- **本机 Codex（可选）**：先安装 Codex CLI，运行 `codex login` 和 `codex login status`，再设置 `LLM_BACKEND=codex` 和 `CODEX_MODEL=gpt-5.6-sol`。该模式调用用户自己的本机 Codex 登录态，不需要 API Key，也不会读取或上传 Codex 会话凭据；模型通过 `codex exec --model` 显式指定。

两种模式共用同一套流水线、检查点和 GUI，不是两份代码。Codex 在这里仅作为文本生成后端，八阶段及其受约束子 Agent 的调度、检查点和质量门禁仍由 MMW 控制；Codex 只在隔离的临时空目录中以只读、临时会话运行。GUI 的“模型与运行模式”页可检测、测试并切换 Codex；激活任一 API 供应商会自动切回 API 模式。Codex 不存在或未登录时程序会明确失败，不会静默改用 API。

## 使用

```powershell
python -m mmw.cli init 2026_cumcm_A --problem A --year 2026
python -m mmw.cli run next --workspace 2026_cumcm_A
python -m mmw.cli approve analyze --workspace 2026_cumcm_A
python -m mmw.cli status --workspace 2026_cumcm_A
python -m mmw.cli audit --workspace 2026_cumcm_A
python -m mmw.cli benchmark --case 2020A_炉温曲线 --workspace 2026_cumcm_A --stage solve
python -m mmw.cli benchmark-suite --suite core-v1 --workspace-map "2020A_炉温曲线=E:\case-2020A"
python -m mmw.cli gui
python -m mmw.cli polish-figures --workspace 2026_cumcm_A
python -m mmw.cli typeset --workspace 2026_cumcm_A
python -m mmw.cli compile --workspace 2026_cumcm_A
python -m mmw.cli layout-check --workspace 2026_cumcm_A
python -m mmw.cli export --workspace 2026_cumcm_A
```

CLI 旧式项目的阶段产物保存在 `workspace/<name>/checkpoints/`。只有审批并通过机器门禁的 active 版本可进入正式编译和导出。
`audit` 只读取本地检查点并执行确定性数值出处审计，不调用 LLM；发现高置信缺出处数值时返回退出码 1。
有可信公开基线的真题可在 `test_cases/<case>/reference_expected.json` 保存 evaluator-only 参考范围。正常流水线和 Coder 不读取该文件；运行结束后由 `benchmark` 独立检查 code/solve 结果。契约必须记录多个可交叉验证的来源，示例见 `test_cases/2020A_炉温曲线/`。
`review` 生成检查点后会自动执行最终 benchmark，并把报告写入 `output/benchmark.json` 和 `output/benchmark.md`。报告与当前 `solve/review` 版本不一致或未通过时，`review` 不能审批。存在独立隐藏 Oracle 且通过时等级为 `verified`；没有 Oracle 时即使通用门禁通过也只标记为 `scenario-feasible`，不代表已经过真实场地部署验证。
`benchmark-suite` 按 `test_cases/benchmark_suite.json` 批量执行相互隔离的案例，输出聚合 JSON/Markdown 报告；案例没有独立 Oracle 时不会提升到 `verified`。核心清单已包含 `2020A_炉温曲线` 和 `2018A_高温服装` 两个独立 Oracle；后者使用多篇独立公开结果的交叉包络，不把单篇题解当作唯一真值。2010A 仅位于 `qualification-v1`，连续两轮清洁验证通过前不进入核心集。
`reference_expected.json` schema v2 还可定义 `invariants`、`stress_scenarios` 和 `repeatability`；重复性检查比较 code 阶段试运行与 solve 阶段正式运行的同名结果，不把容差或期望范围暴露给 Agent。
`model -> code -> solve -> paper -> review` 会携带同一方法契约，绑定目标、硬约束、实际算法声明和结果哈希；solve 还绑定程序写出的 `method_runtime.json`，全局最优声明必须提供穷举覆盖或求解器 gap 证书。任一阶段契约不一致会被机器门禁阻塞，相关证据随最终提交包导出。
移动热过程还会注入受测的一维瞬态导热、经验分区一阶响应与多起点可辨识性诊断；PDE 物理参数不可辨识时只允许退回少量炉区组的条件预测模型，不会升级到依赖题面缺失几何量的二维结构。少于 3 个初值、近最优参数分叉或下游结果不一致时不得进入 solve。
`gui` 会在 `http://127.0.0.1:8765/` 启动本地审查台。用户可选择本机任意包含题目 PDF 或 DOCX 的可写文件夹；点击启动后，MMW 在其中创建 `.mmw/` 运行记录和 `output/` 最终成果，不修改原始题目与附件。审查台按“流程总览 → 阶段审查 → 质量与验证 → 版本与方案 → 论文与交付”组织操作；全局任务栏会显示当前步骤、耗时和完成/失败状态，刷新页面后继续跟踪后台任务。后台线程每 5 秒写独立存活心跳，超过 20 秒只提示“可能卡住”而不伪造失败；服务重启后的普通运行中任务显示为已中断、可重新启动。审批或重做必须填写人工判断理由；阶段审查页可选择“仅标记重做”或“重做并立即运行”，决定保存到项目内部 `decisions.jsonl`。流程总览也可显式启动“托管运行到最终交付”：机器门禁通过后记录 `managed-controller` 激活，错误重复、缺数据或预算耗尽时暂停，修复后可恢复；code 的运行证据确认当前模型结构不足时回退 model，review 的结构化失败会回退 model/code/paper，只有 checklist 输出损坏才原地重跑 Reviewer。启动时可设置 token 请求边界上限和总活跃分钟数；供应商在单次请求完成后返回 usage，达到上限会阻止后续请求，但当前请求可能越界。进度同时记录包含暂停期的墙钟时间，超限版本不会自动激活。最终可信等级单独显示，不能用“8 阶段完成”代替 benchmark 结论。

项目初始化还会生成 `.mmw/input_evidence.json`：DOCX/PDF 中可安全提取的内嵌位图会按哈希保存到 `.mmw/cache/problem-assets/`。只有供应商配置显式声明支持图像时，Analyst 才接收这些受限图片，并把证据 ID、结论和置信度写入 `visual_evidence.json`；Codex CLI 和未声明能力的供应商保持 `not_run`。必答几何依赖未解释位图时 analyze 会暂停，后续 Agent 不得猜图。Researcher 对每个顶层子问题固定生成 1～3 个候选方法（恰好一个基线）；Coder 会先用同一 `solution.py` 做最长 30 秒的方法试跑，通过后按预声明候选数、最大迭代数或收敛条件执行正式运行，默认不设墙钟上限。只有用户显式设置 `MMW_MAX_RUNTIME_SECONDS` 时才启用共同保护性墙钟，触发后结果必须标记 `incomplete` 并阻断审批。如需查询公开学术元数据，可在本机配置 `RESEARCH_WEB_ENABLED=true`，最多把 4 个明确资料缺口发送到 OpenAlex/Crossref。默认关闭，不下载全文。
“论文与交付”页提供图表重制、Typesetter 自动排版和 PDF 视觉检查。图表默认由 Matplotlib 从 `figure_manifest.json` 与逐图 CSV 可复现生成；Windows 检测到 Origin 2024 时可切换 Origin 后端，调用失败会逐图回退 Matplotlib。`compile` 会生成绑定当前 paper 版本和 PDF SHA256 的 `layout_quality.json`；缺字、空白页、测试占位、超页或低质量图表会阻塞 `export`。
GUI 的成果列表只展示当前 solve 声明的图表；输出目录里保留的旧版图片不会与现役成果混列，也不会被自动删除。

## 验证

```powershell
pytest -q
python -m compileall -q mmw
git diff --check
```

## 安全边界

生成代码会经过网络、子进程和动态执行检查，并移除子进程环境中的密钥变量；它仍不是操作系统级容器。只在隔离账户或虚拟机中处理不可信题目附件和参考资料。
