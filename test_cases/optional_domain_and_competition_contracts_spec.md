# 可选领域与竞赛合规合同

## 边界

- 默认不启用，不改变普通题目的 prompt、阶段顺序或结果门禁。
- 只有 `method_contract.json.domain_contracts` 明确声明时，才校验 prediction、scheduling 或 energy 合同。
- 竞赛合规只有 `config.yaml.competition_profile.enabled=true` 时才启用。

## prediction

- `validation.strategy` 必须为 `rolling_origin`。
- `metrics` 必须包含 `macro_wape`、`micro_wape`、`system_aggregate_wape`。
- `provenance` 必须记录训练、验证、测试数据来源和标签口径。

## scheduling

- `candidate_key_fields` 用于语义候选去重。
- `source_refs` 记录候选来源和版本。
- `closure.all_required_tasks_covered=true` 且 `closure.feasible=true` 才能进入结果。

## energy

- 必须声明 `flows`、有限非负 `balance_tolerance` 和 `recomputed_outputs`。
- `closure_passed=true` 才能提交能源流或碳排结果。

## competition_profile

- 启用后必须填写 `config.team_number`、`config.problem` 和 AI 使用声明。
- `pdf_name`、`zip_name` 只能是安全的单层文件名。
- 合规声明写入 `submission.zip/compliance/ai_declaration.txt`。
