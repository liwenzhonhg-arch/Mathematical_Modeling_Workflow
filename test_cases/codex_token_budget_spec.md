# Codex 托管运行 Token 预算 Spec

状态：**已实现（2026-07-29）**

## 问题

Codex CLI 后端只读取最终文本，没有读取 `codex exec` 的 token usage。检查点元数据始终
记录 0，托管界面显示“token 用量不可用”，即使设置 `max_total_tokens` 也无法熔断。

## 规则

1. Codex CLI 调用使用官方 `codex exec --json` JSONL 输出。
2. 只解析 `turn.completed.usage` 的输入、缓存输入和输出 token；最终正文仍只从
   `--output-last-message` 文件读取。
3. usage 进入现有 `_track_usage`、调用日志和检查点 `MetaData`，不记录 prompt、CLI
   原始事件、账号信息或本机配置。
4. JSONL 缺失或格式变化时继续返回正文，但明确保持“用量不可用”，不得伪造估算值。
5. 不读取 Codex 会话文件，不取消 `--ephemeral`、`--ignore-user-config`、
   `--ignore-rules` 或只读沙箱。

## 验收

- 模拟 `turn.completed` 时，Codex 客户端累计并写入真实 usage。
- 缺失/损坏 usage 时正文调用仍可用，token 不伪增。
- Codex 命令仍满足临时会话、忽略本机规则和只读执行边界。
- LLM、托管预算及全量测试通过。

本机真实 Codex CLI 探针返回 `input_tokens=20654`、`output_tokens=5`，客户端累计
`20659`，证明不是字符数估算；探针正文仍只读取 `--output-last-message`。
