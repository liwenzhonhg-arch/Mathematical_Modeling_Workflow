# mmw

面向全国大学生数学建模竞赛的 8 阶段、人工审批式工作流 CLI。

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
```

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
`gui` 会在 `http://127.0.0.1:8765/` 启动本地审查台。用户可选择本机任意包含题目 PDF 的可写文件夹；点击启动后，MMW 在其中创建 `.mmw/` 运行记录和 `output/` 最终成果，不修改原始 PDF 与附件。

## 验证

```powershell
pytest -q
python -m compileall -q mmw
git diff --check
```

## 安全边界

生成代码会经过网络、子进程和动态执行检查，并移除子进程环境中的密钥变量；它仍不是操作系统级容器。只在隔离账户或虚拟机中处理不可信题目附件和参考资料。
