# MMW 独立基准集 Spec

状态：**框架已实现；第二个独立 Oracle 证据待补齐（2026-07-28）**
制定日期：2026-07-28
适用范围：真题回归、隐藏 Oracle、压力测试、可信等级认证

## 1. 问题

当前单题流水线可以证明“程序能运行、通用约束未发现失败”，但没有独立
Oracle 时最多只能得到 `scenario-feasible`。Agent 自评、Verifier 通过、
退出码为 0 和论文完整都不能证明答案正确。

现有 `mmw/benchmark.py` 已支持单案例隐藏评测，本 Spec 不另建评测框架，
只把它扩展为可重复执行的核心基准集。

## 2. 目标

1. 建立至少 3 道不同类型的官方历史题回归集。
2. 至少 2 道题具有不进入 Agent 上下文的独立 Oracle，可达到 `verified`。
3. 对没有唯一数值答案的题，使用不变量、小规模精确解和压力场景验证。
4. 一次命令输出整套通过率、失败阶段、可信等级和版本绑定。
5. 防止参考答案、容差和验收区间泄漏到 prompt、工作区或普通检查点。

## 3. 非目标

- 不把单篇题解的数值当作唯一真值。
- 不要求所有数学建模题都有唯一最优解。
- 不用另一个 LLM 代替独立验证。
- 不让 Agent 根据 benchmark 期望值反向调参。
- 不为了通过基准而降低现有质量门禁。

## 4. 首批案例选择

首批候选为：

- `2020A_炉温曲线`：连续过程、微分方程与参数约束。
- `2018A_高温服装`：传热模型、边界条件和硬性交付物。
- `2023B_多波束测线`：几何规划、覆盖约束和路线/测线优化。

进入核心集前必须满足：

1. 题目来自官方或可核验归档。
2. 参考算法来源可追溯。
3. 关键结果至少有两条独立证据交叉验证。
4. `reference_solver.py` 可在无网络环境独立运行。
5. `reference_expected.json` 只保存合理区间、不变量和容差。

不满足第 3～5 项的案例可以进入压力回归集，但不得标记为 `verified`。

## 5. 目录与清单

沿用现有案例目录，不增加平行存储：

```text
test_cases/<案例>/
├── case.md
├── gaps.md
├── reference_solver.py
└── reference_expected.json
```

新增一个根级清单：

```text
test_cases/benchmark_suite.json
```

最小 schema：

```json
{
  "schema_version": 1,
  "suites": {
    "core-v1": [
      {"case": "2020A_炉温曲线", "required_level": "verified"},
      {"case": "2018A_高温服装", "required_level": "verified"},
      {"case": "2023B_多波束测线", "required_level": "scenario-feasible"}
    ]
  }
}
```

清单只保存案例名和要求等级，不保存答案、容差或参考结果。

## 6. 验证层级

### 6.1 通用门禁

所有案例必须检查：

- `results.json` 和 `sensitivity.json` 为本次运行新产物。
- 数值有限且单位、名称、子问题覆盖完整。
- 不存在“未找到可行解”、罚函数冒充目标值或明确占位结果。
- 题目硬性交付物存在、非空且与本次 solve 版本绑定。
- review、数值审计和最终 benchmark 均与激活版本一致。

### 6.2 独立 Oracle

存在 `reference_expected.json` 时：

- 只由 benchmark evaluator 读取。
- 不复制到题目工作区。
- 不传入任何 Agent、Writer、Reviewer 或 Verifier prompt。
- 评测报告记录 reference contract 的 SHA256，不复制隐藏区间正文。

### 6.3 小规模精确实例

对难以直接验证的大规模优化题，增加不含原题答案的合成小实例：

- 穷举或确定性精确算法可得到真值。
- 生成代码必须满足同一组约束和目标函数。
- 固定随机种子并保存实例生成器版本。

### 6.4 变形与压力测试

没有唯一答案时至少包含：

- 输入顺序置换后结果语义不变。
- 单调参数变化符合已证明的不变量。
- 极小、边界和不可行情景能被明确识别。
- 重复运行满足 `reference_expected.json` 的重复性容差。

## 7. 执行接口

新增最小命令：

```bash
python -m mmw.cli benchmark-suite --suite core-v1
```

实现必须复用现有 `evaluate_benchmark()`，只负责：

1. 读取案例清单。
2. 找到各案例已绑定的测试工作区或显式传入的工作区映射。
3. 顺序执行现有 evaluator。
4. 汇总报告。

输出：

```text
output/benchmark-suite-core-v1.json
output/benchmark-suite-core-v1.md
```

单案例失败不终止其他案例；命令最终有任一必选案例失败时退出码为 1。

## 8. 可信等级规则

- `verified`：独立 Oracle/精确小实例、通用门禁和压力测试全部通过。
- `scenario-feasible`：通用门禁和压力测试通过，但没有独立现实 Oracle。
- `unverified`：缺结构化证据、报告过期或任一硬门禁失败。

基准集整体等级取所有必选案例中的最低等级，不用平均分掩盖失败。

## 9. 安全与隔离

- `reference_expected.json` 不进入 ZIP 提交包、工作区、普通检查点或 LLM 日志。
- evaluator 只读案例契约，不能修改阶段产物。
- 报告不得输出隐藏上下界，只输出检查项名称、pass/fail 和误差摘要。
- 基准失败不能自动触发 Agent 读取期望值后重做。
- 参考求解器若来自外部，必须记录来源、许可证和本地审查结果。

## 10. 测试要求

最小自动化测试：

- 清单拒绝路径穿越和不存在案例。
- 单案例失败后继续评测其余案例。
- 必选案例失败时总退出码为 1。
- `verified` 要求 Oracle 可用且通过。
- evaluator 运行期间 Agent 输入中不存在参考契约内容。
- 报告与 solve/review 版本或内容哈希不一致时失效。

验证命令：

```bash
pytest tests/test_benchmark.py
pytest tests/test_benchmark_suite.py
pytest tests/
python -m compileall -q mmw
git diff --check
```

## 11. 验收标准

- `core-v1` 至少包含 3 道不同类型题目。
- 至少 2 道达到 `verified`。
- 每道题都有可复跑的通用门禁和至少 1 组压力/变形测试。
- 隐藏契约不出现在工作区、检查点、prompt、LLM 日志或提交包。
- 一次命令生成版本绑定的汇总报告。
