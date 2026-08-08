# MMW 现有流程效率与可信度改进 Spec

状态：P0～P3 已实现并进入回归验证
制定日期：2026-08-06

## 1. 当前根因

MMW 已经具备 Modeler、Verifier、Coder 恢复、方法契约、数值审计和 benchmark，但仍存在一种确定性浪费：`stage_model` 明知候选违反本地证据门禁时，仍先把完整候选发送给 Verifier，得到回复后才叠加本地 block。这个调用不能改变结论，只增加 Token、时间和同源噪声。

第二个问题是 research 输出以 Markdown 为主，候选数、基线、失败条件和资料缺口没有稳定 JSON 合同，下游只能依赖自然语言解释，容易让方法数量扩张或遗漏基线。

## 2. 目标

1. 确定性门禁先于 LLM 审查执行。
2. 明确记录每次审查究竟来自本地门禁还是 Verifier。
3. 让 research 的方法候选和资料证据进入有界、可验证的结构化合同。
4. 保持旧检查点、旧项目和默认离线行为兼容。

## 3. P0：Model 确定性门禁前置

### 行为

1. 每轮生成 `method_contract.json` 后，先运行 `_model_evidence_issues`。
2. 若存在问题：
   - 不创建 Verifier LLM 客户端，不调用 Verifier；
   - 本地生成 `verify_status.json`，`severity=block`；
   - 本地生成 `verify_report.md`，逐条列出确定性问题；
   - `revision_history.json` 写入 `review_source=deterministic-gate`；
   - Token 只记录 Modeler 已实际消耗的 usage；
   - 若仍有修订额度，将原样证据交回 Modeler 定向修订。
3. 本地门禁通过后才调用 Verifier，并记录 `review_source=llm-verifier`。
4. 不把未调用的 Verifier 模型写入 `model_used`。

### 验收

- 构造“model 阶段伪造 RMSE”的候选，Verifier 工厂必须零调用。
- 本地 block 仍保存完整检查点和修订历史。
- 候选修复后下一轮正常调用 Verifier。
- 原有 pass/warning/block 语义不变。

## 4. P1：结构化方法候选

### Schema

```json
{
  "schema_version": 1,
  "subproblems": [
    {
      "id": "q1",
      "candidates": [
        {
          "id": "q1_baseline",
          "name": "基线方法",
          "kind": "baseline",
          "required_data": [],
          "assumptions": [],
          "failure_conditions": [],
          "pilot": {
            "metric": "有限输出与约束检查",
            "pass_rule": "所有硬约束通过",
            "budget_seconds": 30
          }
        }
      ]
    }
  ]
}
```

### 门禁

- 只允许分析阶段已有的顶层子问题 ID。
- 每个子问题 1～3 个候选，最多一个 `baseline`，且必须存在 baseline。
- ID 唯一，字符串字段非空，列表字段必须为列表。
- `pilot.budget_seconds` 为 1～30 的整数。
- 不把数据清洗、公式推导等内部步骤扩成新的 q 编号。
- 不满足 schema 时 research 阶段明确失败，不保存看似完成的检查点。

## 5. P2：检索证据边界

- `research_evidence.json` 增加 schema 版本、查询、来源记录和错误记录。
- `external_search_performed=true` 只表示至少一个固定 API 请求成功，不表示找到全文或验证了方法。
- 每条来源明确 `evidence_level=metadata|abstract`。
- Modeler 提示必须声明：metadata 只能证明文献存在，不能证明正文中的参数或结论。
- 来源记录只保存公开元数据，不保存 Cookie、Token、网页会话或供应商原始响应。

## 6. P3：输入证据清单

- 初始化成功后建立 `.mmw/input_evidence.json`。
- 文本题面、DOCX 原生 shape 文本和嵌入图片使用不同 `kind`。
- 所有二进制资产写入受控缓存，使用内容哈希命名，限制单项和总大小。
- 无图片时生成空 `visual_assets`，不得把“无资产”写成“视觉已验证”。

## 7. 非目标

- 不增加顶层阶段或新 Agent。
- 不修改 `.env`、密钥、CI/CD。
- 不默认联网。
- 不安装新依赖。
- 不在本轮实现通用 OCR、PDF 页面渲染器或自动全文下载。
- 不用 Reviewer 多次采样替代独立验证。

## 8. 验证命令

```bash
pytest tests/test_stage_model_revision.py
pytest tests/test_stage_research_evidence.py
pytest tests/test_gui.py -k "docx or initialize"
pytest tests/
python -m compileall -q mmw
git diff --check
```

## 9. 完成定义

- P0～P3 的最小实现和测试全部通过。
- 旧式 workspace 与现代 `.mmw/` 项目均可运行。
- 默认配置下无新增网络请求。
- 文档不声称尚未实现的视觉识别或正式方法试跑已经完成。

## 10. 2026-08-06 实施结果

- P0：确定性 model 证据门禁已前置；本地 block 不再实例化或调用 Verifier，并记录 `review_source=deterministic-gate`。
- P1：Researcher 必须生成 `method_candidates.json`；每个原始顶层子问题限制为 1～3 个候选且恰好一个基线，试跑预算限制为 1～30 秒。
- P2：增加默认关闭的 OpenAlex/Crossref 有界元数据检索；固定 HTTPS 端点、最多 4 个查询、每源每查询最多 3 条、2 MB 响应上限，不下载全文。
- P3：现代项目初始化生成 `.mmw/input_evidence.json`，安全提取受支持的内嵌位图并明确标记 `visual_interpretation.status=not_run`。
- P4：真实题目的三个顶层子问题均稳定生成两个候选且各含一个基线后，已接入同一 `solution.py` 的 30 秒方法试跑；`method_pilot.json` 未通过或试跑污染正式输出时，不启动正式运行。正式运行默认无墙钟上限，并使用确定性停止合同。未新增 `pilot.py`、Agent 或顶层阶段。
- 未实现：通用视觉模型调用，继续受供应商图像能力约束。
