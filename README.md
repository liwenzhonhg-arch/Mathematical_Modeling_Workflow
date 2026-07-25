# mmw

面向全国大学生数学建模竞赛的 8 阶段、人工审批式工作流 CLI。

## Windows 便携版

不安装 Python 的用户可从 [GitHub Releases](https://github.com/liwenzhonhg-arch/Mathematical_Modeling_Workflow/releases) 下载 `MMW-Windows-x64-v<版本>.zip`，完整解压后双击 `MMW.exe`。程序启动后会异步检查官方 Release；发现新版时，右上角可一键下载、校验 SHA256、安装到当前用户目录并重启。API Key 或 Codex 登录态由用户自行配置，不包含在发行包中；生成最终 PDF 仍需另外安装 MiKTeX/TeX Live。

新建项目可直接选择包含 `.pdf` 或 `.docx` 题目文件的文件夹；旧版 `.doc` 请先用 Word 另存为 `.docx`。

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
```

## 两种模型模式

- **API / BYOK（默认）**：保持 `.env` 中 `LLM_BACKEND=openai`，填写 `LLM_API_KEY`、`LLM_BASE_URL` 和 `LLM_MODEL`。支持 OpenAI-compatible Chat Completions 接口，也支持八个 Agent 分别覆盖模型。
- **本机 Codex（可选）**：先安装 Codex CLI，运行 `codex login` 和 `codex login status`，再将 `LLM_BACKEND=codex`。该模式调用用户自己的本机 Codex 登录态，不需要 API Key，也不会读取或上传 Codex 会话凭据。

两种模式共用同一套流水线、检查点和 GUI，不是两份代码。Codex 在这里仅作为文本生成后端，八个 Agent 的调度、检查点和质量门禁仍由 MMW 控制；Codex 只在隔离的临时空目录中以只读、临时会话运行。GUI 的“模型与运行模式”页可检测、测试并切换 Codex；激活任一 API 供应商会自动切回 API 模式。Codex 不存在或未登录时程序会明确失败，不会静默改用 API。

## 使用

```powershell
python -m mmw.cli init 2026_cumcm_A --problem A --year 2026
python -m mmw.cli run next --workspace 2026_cumcm_A
python -m mmw.cli approve analyze --workspace 2026_cumcm_A
python -m mmw.cli status --workspace 2026_cumcm_A
python -m mmw.cli audit --workspace 2026_cumcm_A
python -m mmw.cli benchmark --case 2020A_炉温曲线 --workspace 2026_cumcm_A --stage solve
python -m mmw.cli gui
python -m mmw.cli compile --workspace 2026_cumcm_A
python -m mmw.cli export --workspace 2026_cumcm_A
```

CLI 旧式项目的阶段产物保存在 `workspace/<name>/checkpoints/`。只有审批并通过机器门禁的 active 版本可进入正式编译和导出。
`audit` 只读取本地检查点并执行确定性数值出处审计，不调用 LLM；发现高置信缺出处数值时返回退出码 1。
有可信公开基线的真题可在 `test_cases/<case>/reference_expected.json` 保存 evaluator-only 参考范围。正常流水线和 Coder 不读取该文件；运行结束后由 `benchmark` 独立检查 code/solve 结果。契约必须记录多个可交叉验证的来源，示例见 `test_cases/2020A_炉温曲线/`。
`review` 生成检查点后会自动执行最终 benchmark，并把报告写入 `output/benchmark.json` 和 `output/benchmark.md`。报告与当前 `solve/review` 版本不一致或未通过时，`review` 不能审批。存在独立隐藏 Oracle 且通过时等级为 `verified`；没有 Oracle 时即使通用门禁通过也只标记为 `scenario-feasible`，不代表已经过真实场地部署验证。
`reference_expected.json` schema v2 还可定义 `invariants`、`stress_scenarios` 和 `repeatability`；重复性检查比较 code 阶段试运行与 solve 阶段正式运行的同名结果，不把容差或期望范围暴露给 Agent。
`gui` 会在 `http://127.0.0.1:8765/` 启动本地审查台。用户可选择本机任意包含题目 PDF 或 DOCX 的可写文件夹；点击启动后，MMW 在其中创建 `.mmw/` 运行记录和 `output/` 最终成果，不修改原始题目与附件。审查台按“流程总览 → 阶段审查 → 质量与验证 → 版本与方案 → 论文与交付”组织操作；审批或重做必须填写人工判断理由，记录保存到项目内部 `decisions.jsonl`。最终可信等级单独显示，不能用“8 阶段完成”代替 benchmark 结论。

## 验证

```powershell
pytest -q
python -m compileall -q mmw
git diff --check
```

## 安全边界

生成代码会经过网络、子进程和动态执行检查，并移除子进程环境中的密钥变量；它仍不是操作系统级容器。只在隔离账户或虚拟机中处理不可信题目附件和参考资料。
