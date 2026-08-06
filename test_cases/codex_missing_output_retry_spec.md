# Codex 缺失响应恢复 SPEC

## 问题

`codex exec` 偶发以退出码 0 结束，却没有生成 `--output-last-message` 文件。
当前实现直接读取文件，抛出不可重试的 `FileNotFoundError`，使已经保存检查点的阶段中断。

## 合同

1. 非零退出码继续按登录态区分登录错误与可重试 CLI 错误。
2. 退出码为 0，但响应文件缺失或内容为空时，抛出 `CodexCLIError`。
3. 错误不得包含 Codex stdout、stderr、prompt 或临时文件内容。
4. Agent 现有重试器负责重新请求；不得伪造空响应或回退其他供应商。

## 验收

- 自动化测试覆盖响应文件缺失和空文件两种情况。
- `tests/test_llm_codex.py` 与完整测试通过。
