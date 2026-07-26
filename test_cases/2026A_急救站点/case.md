# 2026A 急救站点选址与调度优化

## 题目与运行配置

- 题目来源：GUI 外部工作区中的本地测试题 `A题.docx`，非历年 CUMCM 官方真题。
- 运行日期：2026-07-25 至 2026-07-26。
- 工作区：GUI 任意文件夹模式，内部记录位于 `.mmw/`，成果位于 `output/`。
- LLM：本机 Codex CLI 模式。
- 可信等级：`scenario-feasible`；没有独立现实 Oracle。
- 测试队号：`TEST-RUN`，正式提交前必须替换。

## 第 1 轮完整实测

| 阶段 | 激活版本 | 结果 |
|---|---:|---|
| analyze | v1 | approved |
| eda | v1 | approved |
| research | v1 | approved |
| model | v25 | approved |
| code | v8 | approved |
| solve | v3 | approved |
| paper | v11 | approved |
| review | v4 | approved |

### 核心结果

- 问题一：唯一容量可行配车为 `(3,2,2,2,1,2)`；两层词典序分配先最大化黄金覆盖，再最小化加权距离。黄金覆盖上界和结果均为 85 次/日，平均距离约 0.942 km。
- 问题二：无等待静态首程代理的平均响应时间约 4.255 min，T95 约 8.497 min；不代表真实排队或逐车动态验证。
- 问题三：十个事故区域只计算 24 小时容量压力下界。区域 1 最不利，未服务量 108 次、派遣率 57.14%、外部车辆容量等价下界 9 辆。

### 最终门禁

- 八阶段：8/8 approved。
- 数值审计：通过。
- benchmark：通用门禁通过，`overall_passed=true`。
- 独立 Oracle：不可用。
- LaTeX：15 页，编译日志 0 个 LaTeX 错误、0 个未定义引用。
- 导出：`submission.zip` 生成成功，只包含当前论文、代码和 5 张当前图表。

### 成品快照

- `deliverables/paper.pdf`
- `deliverables/benchmark.json`
- `deliverables/numeric_audit.md`

## 结论

该轮证明 GUI 流程可从 DOCX 题目运行到 8 阶段审批、数值审计、benchmark、论文编译和提交包导出。结果只达到 `scenario-feasible`：Q2 缺少逐次呼叫与排队数据，Q3 缺少实时车辆、医院和外援数据，不能宣称现实部署有效。
