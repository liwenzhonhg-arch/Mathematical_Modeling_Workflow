# MMW 模型—代码—论文方法契约 Spec

状态：**已实现（2026-07-28）**
制定日期：2026-07-28
适用范围：model、code、solve、paper、review 的方法一致性

## 1. 问题

当前模型阶段描述的求解方式可能与最终代码实际实现不同。例如模型可以写
MTZ/MILP，而代码改用完整路线枚举；两者都可能有效，但 Writer 若继续描述
旧算法，就会出现“模型、代码、结果、论文各说一套”。

文本 Reviewer 可以发现部分矛盾，但不能作为唯一门禁。

## 2. 目标

1. 用一个结构化契约贯穿 model 到 review。
2. 区分“数学模型”与“实际求解算法”，允许等价实现但必须如实披露。
3. 每条目标、约束、结果和最优性声明都有稳定 ID。
4. Writer 只能根据 solve 已验证的实际方法写论文。
5. 方法或声明不一致时，在 paper 前确定性阻断。

## 3. 非目标

- 不要求模型阶段决定唯一编程实现。
- 不用字符串完全相等判断数学等价。
- 不允许 Agent 自报“等价”后直接放行。
- 不创建第九个顶层阶段。
- 不把所有公式转换成通用符号推理系统。

## 4. 唯一契约文件

各阶段均使用同名文件：

```text
method_contract.json
```

下游复制并补全上游契约，不能原地修改已保存检查点。

最小 schema：

```json
{
  "schema_version": 1,
  "problem_scope": ["q1", "q2"],
  "formulation": {
    "model_family": "VRPTW",
    "objectives": [
      {"id": "OBJ-1", "meaning": "最小化总成本", "unit": "CNY"}
    ],
    "constraints": [
      {"id": "CON-1", "meaning": "车辆容量", "hard": true},
      {"id": "CON-2", "meaning": "客户只服务一次", "hard": true}
    ]
  },
  "implementation": {
    "algorithm": "完整合法路线枚举 + 集合划分动态规划",
    "class": "exact",
    "solver": "python",
    "randomized": false,
    "seed": null,
    "covers": ["OBJ-1", "CON-1", "CON-2"],
    "deviations": []
  },
  "claims": {
    "optimality": "global-within-enumerated-feasible-space",
    "approximation": null,
    "limitations": []
  },
  "bindings": {
    "model_version": 8,
    "code_version": 4,
    "solution_sha256": "",
    "results_sha256": ""
  }
}
```

字段只能表达方法事实，不保存题目答案或 benchmark 隐藏范围。

## 5. 阶段责任

### 5.1 model

Modeler 生成：

- `problem_scope`
- `formulation.model_family`
- 带稳定 ID 的 objectives/constraints
- 允许的求解类别和必要假设
- 尚未确定的 implementation 字段使用 `null`，不得编造

Verifier 检查：

- 每个子问题都有目标或明确的可行性任务。
- 每条硬约束有唯一 ID。
- 单位、量纲和约束含义与 `model.md` 一致。

### 5.2 code

Coder 从 model 契约复制并填写：

- 实际算法与 solver。
- exact/heuristic/simulation/statistical 类别。
- 随机性和种子。
- 实际覆盖的目标与约束 ID。
- 与模型建议不同的地方及原因。
- `solution.py` SHA256。

code 门禁必须阻断：

- 任一硬约束 ID 未被实现或检查。
- 声称 exact 但代码存在未披露的 top-k、截断、罚函数或启发式。
- 随机算法未记录 seed。
- 契约绑定的代码哈希与检查点内容不一致。

### 5.3 solve

solve 复制契约并写入：

- 当前 code/solve 版本。
- `results.json` SHA256。
- 每条硬约束的运行验证状态。
- 实际搜索空间、提前停止条件和最优性证据。

代码运行时还必须在 `output/data/method_runtime.json` 写出独立于
`method_contract.json` 的运行证据。solve 将其 SHA256 绑定到契约：

- `claim_class`、`feasible`、`hard_constraints` 与固定随机种子。
- 全局最优声明必须有有限目标值。
- 穷举证明必须记录总候选数、已检查数和可行数。
- 求解器/界证明必须记录 primal bound、dual bound、gap 与容差。

证据不完整、约束 ID 缺失或 gap 超过容差时，solve 门禁阻断审批。

生成：

```text
method_validation.json
```

该报告由确定性代码生成，至少包含：

- 契约 schema 是否有效。
- 目标/约束 ID 覆盖率。
- 代码和结果哈希是否匹配。
- exact/heuristic 声明是否与运行日志一致。
- 未披露偏差列表。

### 5.4 paper

Writer 的方法输入以 solve 契约为准，而不是只读取 `model.md`。

必须满足：

- 论文区分数学模型和实际求解算法。
- 不把启发式、截断或场景可行描述成全局最优。
- 方法章节覆盖全部 objectives/constraints ID。
- 局限性章节包含契约中的 deviations/limitations。

生成：

```text
method_traceability.json
```

记录每个 ID 出现在论文的文件和小节，不保存长篇论文正文。

### 5.5 review

review 确定性检查：

- `method_validation.json` 已通过且与激活 solve 版本绑定。
- `method_traceability.json` 覆盖所有硬约束和最优性声明。
- 论文没有使用高于契约允许等级的结论词。

Reviewer 只处理语义质量，不能覆盖确定性失败。

## 6. 偏差处理

允许的偏差：

- 数学模型不变，代码采用不同但完整的精确算法。
- 求解器或数值方法因环境变化而替换。
- 明确披露并验证的近似、采样或截断。

阻断性偏差：

- 删除或放松硬约束但未说明。
- 只优化部分子问题却宣称完整求解。
- 启发式结果写成全局最优。
- 代码方法变化后论文仍描述旧方法。

阻断后优先重做 code 或 paper；只有 formulation 本身变化时才回退 model。

## 7. 兼容策略

- 旧检查点继续可读，不批量改写历史文件。
- 旧项目没有契约时显示 `legacy-uncontracted`。
- 旧项目若重新运行 model/code/solve 任一阶段，新版本必须生成契约。
- 没有契约的旧成品最多显示 `unverified`；不得因为历史已审批而冒充当前已验证。

## 8. 测试要求

最小测试：

- 约束 ID 缺失、重复或未覆盖时失败。
- model 写 MTZ、code 用完整枚举但 formulation/约束一致时允许，并要求论文描述实际算法。
- top-k 截断未写 deviations 时失败。
- heuristic 被声明为 exact 时失败。
- 代码或结果文件改变后旧契约哈希失效。
- paper 使用“全局最优”但契约不允许时失败。
- legacy 项目保持可读取且等级降为 `unverified`。

验证命令：

```bash
pytest tests/test_method_contract.py
pytest tests/test_state_machine.py
pytest tests/test_numeric_audit.py
pytest tests/
python -m compileall -q mmw
git diff --check
```

## 9. 验收标准

- 新跑案例从 model 到 review 始终只有一条版本绑定的方法契约链。
- 数学 formulation 与实现算法可以不同，但差异必须明确、可审计。
- Writer 不再从过期 model 文本推断实际求解方法。
- 任一硬约束未覆盖、哈希过期或最优性夸大都会阻断下游审批。
- `E:\mmwt2` 同类路线题回归时，不再出现 MTZ 描述与路线枚举实现混写。
