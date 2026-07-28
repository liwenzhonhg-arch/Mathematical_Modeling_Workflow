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

---

## 第二轮：API 模式独立工作区实测


## 基本信息

- 实测日期：2026-07-28
- 题目来源：用户本机 `E:\mmwt2\B题.docx`
- 隔离工作区：`E:\mmwt2-independent-20260728`
- LLM：真实 OpenAI-compatible API，`deepseek-v4-pro`
- 运行方式：托管控制器；遇到上游修订路由缺陷时由 Codex 操作员按门禁反馈重做
- 原工作区 `E:\mmwt2`：未修改
- Oracle：无

## 预算

- 首轮总 token 上限：500,000；实测证明不足以覆盖多轮 code 修订和完整论文链。
- 记录首轮证据后，将本次总上限一次性调整为 800,000。
- 最终检查点累计 token：626,686。
- 最终未超过 800,000 token；墙钟时间约 108 分钟。

## 激活版本

| 阶段 | 版本 | 结果 |
|---|---:|---|
| analyze | v1 | approved |
| eda | v1 | approved |
| research | v1 | approved |
| model | v1 | approved |
| code | v10 | approved |
| solve | v4 | approved |
| paper | v3 | approved |
| review | v1 | approved |

## 最终结果

- `paper.pdf`：生成成功。
- `submission.zip`：生成成功。
- benchmark：通过。
- 可信等级：`scenario-feasible`。
- 最优性声明：启发式完成并确认可行，没有宣称全局最优。
- 摘要评分：93。
- 数值审计：无高置信缺出处数值。

本案例证明 8 阶段、论文编译、benchmark 和导出可以在真实 LLM 下完整结束；
由于没有独立现实 Oracle，不能据此声称路线方案是真实全局最优或已部署验证。

## 本轮修复

1. 未访问必访门店但进程退出码为 0 时，code/solve 门禁现在会阻断。
2. 空 CSV 不再让 solve 以未处理 `EmptyDataError` 崩溃，而是保存结构化图表失败证据。
3. 方法契约缺 ID 时优先做小型契约修订，不再重复生成整份代码。
4. 纯“建立模型”子问题可由通过的方法契约证明覆盖，不强造数值结果。
5. solve 的结果/灵敏度错误会回退 code，而不是无效地重复运行 solve。
6. 上游变更后的旧下游版本不得直接重新审批。
7. 灵敏度修订提示会淘汰全零参数并要求真实重跑。
