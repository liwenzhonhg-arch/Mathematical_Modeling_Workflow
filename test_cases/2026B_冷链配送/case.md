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

## 第二轮实测后的回归修正

- Windows 后台日志曾在同一文件混入 GBK 的普通 `print` 和 UTF-8 的 Rich 输出；现统一复用 UTF-8 标准流，并增加子进程字节级回归测试。
- Writer 定向修订若因 `finish_reason=length` 缺少章节，会自动补齐一次；再次缺失则明确失败。
- paper 门禁新增方法表述与符号一致性检查：摘要必须如实写出 heuristic 实现，MILP formulation 与实际实现必须区分，`K` 等 formulation 大写符号必须进入符号表。
- 托管状态同时保存活跃时长和墙钟时长；预算仍按活跃时长执行，暂停期与外部操作耗时不再不可见。
- 第二轮 paper v3 的 LaTeX 日志没有 Overfull/Underfull，`layout_quality.json` 通过；仍未重新调用真实 LLM 验证上述新增门禁的自动重做路径。

## 新增 paper 门禁真实 API 回归（2026-07-29）

- 以 paper v3 为基线启动新托管运行；前六阶段均复用已审批版本。
- 新门禁正确阻断“摘要未说明 heuristic、符号表缺 K”，Writer 定向生成 paper v4。
- paper v4、review v4、benchmark、10 页 PDF 和提交包均完成；本轮使用 91,068 token，
  活跃时间约 10.2 分钟，检查点累计 717,754 token，仍低于 800,000 上限。
- benchmark 绑定 solve v4/review v4，通用门禁通过，可信等级仍为 `scenario-feasible`；
  4 张现役图均为约 300 DPI。
- Reviewer v2 把“模型未写出算法附加的每车单站约束”判为 fail；但 paper v4 已明确
  区分 MILP formulation 与实际启发式实现，并把每车单站列为附加假设和局限 L1，
  因此该差异应为 warning，而不是要求两套可行域强行一致。Reviewer 提示已补充此规则。
- 旧托管控制器仍不应靠原地重复评审得到 v4 pass；现已改为真 fail 按结构化项回退
  model/code/paper，只有 checklist 缺失或损坏才重跑 Reviewer。
