# 项目辅助 Skills

这里保存可独立复制、但与 `mmw` 质量合同一致的 Agent Skill。

## 约定

- Skill 目录使用 kebab-case，并以 `SKILL.md` 作为唯一入口。
- 按需资料放 `references/`，确定性工具放 `scripts/`，评测题放 `evals/`。
- Skill 不得读取 evaluator-only Oracle、`.env`、登录态或真实赛题私有答案。
- `evals/` 只保存输入与期望；临时运行结果放 `.tmp/` 或系统临时目录。
- Skill 是长期维护产物，不按会话清理。废弃或删除前须获得用户确认。

