# 参与贡献

MMW 优先接受可验证、范围清楚的改进。提交代码前，请先阅读根目录的 [`AGENTS.md`](AGENTS.md)；它定义了项目架构、目录约定、质量门禁和安全边界。

## 适合提交的内容

- 可复现的 CLI、GUI、检查点或状态机缺陷。
- 能降低错误答案通过率的确定性质量门禁。
- 不含题目答案、专用拟合常数和私有数据的通用建模方法。
- 对现有测试案例、文档和 Windows 使用体验的小范围改进。

较大的新功能请先创建 Issue，说明目标、非目标、数据流、兼容性和验收方式，避免实现完成后才发现方向不一致。

## 本地开发

```powershell
git clone https://github.com/liwenzhonhg-arch/Mathematical_Modeling_Workflow.git
Set-Location Mathematical_Modeling_Workflow
python -m pip install -e ".[dev]"
pytest -q
python -m compileall -q mmw
git diff --check
```

要求 Python 3.11+。不要为测试填写真实 API Key；涉及 LLM 的测试应使用 mock、fixture 或明确隔离的测试配置。

## 提交要求

1. 保持改动小而集中，不混入无关重构。
2. 修改流水线时，同时检查状态机、检查点读写和相关测试。
3. 修改提示词时，同时检查对应 Agent、阶段输入和测试案例。
4. 修改 GUI 时，保持仅监听本机回环地址，不在浏览器持久化密钥或任意绝对路径。
5. 新增行为必须补充测试；修复缺陷应尽量先加入可复现失败的测试。
6. Pull Request 说明应包含：问题、根因、方案、验证命令、已知限制。

## 真题与 benchmark

- 真题实测记录放在 `test_cases/<年份><题号>_<简称>/`。
- evaluator-only 的 `reference_expected.json` 不能进入 Agent 提示词、工作区或普通检查点。
- 确定性参考基线必须记录公开来源，不能把单篇题解的精确答案当作唯一真值。
- 从参考求解器提取的公开方法不得包含题目答案、验收范围或专用拟合常数。

## 敏感信息

以下内容不得进入 Issue、Pull Request、日志、测试快照或提交：

- `.env`、API Key、token、密码。
- Codex 登录态、会话文件、缓存和机器专用配置。
- 未经许可的竞赛数据、个人信息和第三方受限资料。
- 用户工作区、构建目录和本机绝对路径。

安全缺陷请按照 [`SECURITY.md`](SECURITY.md) 提交，不要先公开利用细节。
