# 2026B 冷链配送完整实测

## 案例信息

- 运行日期：2026-07-27 至 2026-07-28
- 题目来源：用户本机 `E:\mmwt2\B题.docx`
- 题目性质：本地合成测试题，不是已确认的 CUMCM 官方真题
- LLM 模式：本机 Codex CLI
- 图表后端：Matplotlib
- 独立 Oracle：无

## 最终激活版本

| 阶段 | 版本 | 结果 |
|---|---:|---|
| analyze | v1 | approved |
| eda | v1 | approved |
| research | v1 | approved |
| model | v8 | approved（Verifier warning） |
| code | v4 | approved |
| solve | v9 | approved |
| paper | v23 | approved |
| review | v8 | approved |

## 核心结果

- 正常硬时间窗方案使用 2 辆车。
- 路线 1：`0-2-5-1-4-6-8-0`，载荷 59 箱，里程 47.785494 km。
- 路线 2：`0-3-9-7-0`，载荷 36 箱，里程 32.666947 km。
- 总里程 80.452441 km，总行驶时间 137.966667 min，综合成本 321.809764 元。
- 早到 0 次、迟到 0 次。
- 正常方案不使用有向弧 `2->8`，因此该弧封闭后代理最优路线与成本均不变。
- CVaR 压力分析从 1964 条共同合法路线列出发，仅删除严格分量支配列；保留 63 条路线列并枚举 278 个共享精确覆盖方案。
- 可信等级：`scenario-feasible`。真实 GPS、道路、车辆资格和温度轨迹缺失，现实执行状态未验证。

## 成品

- `deliverables/paper.pdf`
- `deliverables/submission.zip`
- `deliverables/benchmark.json`

原始运行工作区保留在 `E:\mmwt2`；测试案例目录只保存最终快照和复盘文档，不保存密钥、登录态或本机配置。

## 最终验证

- `pytest tests/ -q`：355 passed。
- `python -m compileall -q mmw`：通过。
- `git diff --check`：通过。
- `submission.zip`：25 个文件，含 benchmark、数值审计与版式报告，CRC 完整性检查通过。
- `paper.pdf`：15 页，5 张图均为 300 DPI，版式门禁通过。

## 结论

本轮完整跑通了 8 个阶段、人工重做、数值审计、独立 benchmark、PDF 编译、视觉质量门禁和最终导出。最终 PDF 共 15 页，版式门禁通过；benchmark 通用门禁通过，但因无现实 Oracle，只能得到 `scenario-feasible`。
