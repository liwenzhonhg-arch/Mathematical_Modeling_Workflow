# 测试占位信息放行 Spec

状态：已实现并在当前 A 题完成 PDF/ZIP 实测

## 目标

测试运行可以使用临时题目名、队名并产出 PDF/提交包，但不得静默削弱正式项目门禁。

## 配置

- `allow_test_placeholders: false`：默认值；命中 `mmw-test`、`TEST-RUN` 时硬失败。
- `allow_test_placeholders: true`：命中占位信息时降为 warning，其余视觉门禁保持不变。

## 验收

- 默认模式仍阻塞占位信息。
- 放行模式只产生 warning，允许 compile/export。
- 当前 A 题开启后能生成 `paper.pdf` 与 `submission.zip`。
