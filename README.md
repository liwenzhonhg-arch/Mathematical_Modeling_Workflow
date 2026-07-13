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
python -m mmw.cli compile --workspace 2026_cumcm_A
python -m mmw.cli export --workspace 2026_cumcm_A
```

每阶段产物保存在 `workspace/<name>/checkpoints/`。只有审批并通过机器门禁的 active 版本可进入正式编译和导出。

## 验证

```powershell
pytest -q
python -m compileall -q mmw
git diff --check
```

## 安全边界

生成代码会经过网络、子进程和动态执行检查，并移除子进程环境中的密钥变量；它仍不是操作系统级容器。只在隔离账户或虚拟机中处理不可信题目附件和参考资料。
