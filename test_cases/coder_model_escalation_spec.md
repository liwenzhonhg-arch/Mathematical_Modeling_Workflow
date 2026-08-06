# Coder 模型不足升级 Spec

状态：**已实现并通过 r8 真实回归（2026-07-30）**

## 问题

r8 在固定观测时间偏移为 0 的前提下，Coder 已实际检验模型契约允许的四种过渡
结构，但没有结构能同时通过拟合质量与参数可辨识性门禁。候选明确要求交回 model，
现有托管器仍把它当作普通 code 错误继续反思，浪费 token，最终只能因预算暂停。

## 规则

1. Coder 判断失败来自当前 formulation 时，必须用
   `MODEL_REWORK_REQUIRED: <原因>` 抛出失败，不得修改模型或增加未声明自由度。
2. code 阶段把该标记归一化为系统生成的 `rework_request.json`；只允许目标
   `model`，不信任 Agent 自报的任意阶段名。
3. code 质量门禁优先返回稳定的“需要重做 model”错误，不能被缺少结果或
   identifiability 文件等次生错误覆盖。
4. 托管器首次遇到该错误时消耗一次 model 重做预算，标记 model 重做并从 model
   重新开始；Modeler 继续读取最新 code 的运行日志与候选历史。
5. 没有明确升级标记的普通代码错误仍留在 code，不得把所有失败都推给 model。
6. model 出现尚未激活的失败修订版时，反馈查找不能只接受“绑定最新 model”的
   code；应优先读取绑定最新 model 的 code，没有时读取绑定当前激活 model 的
   最新 code，避免失败修订版遮住仍有效的执行证据。
7. 交回 Modeler 的证据除运行日志和候选历史外，必须包含 code 方法契约中的
   formulation 摘要与 deviations；这样“已否决 PDE / 现役降阶结构”和实现不一致
   不会被压缩成缺少若干约束 ID。

## 验收

- 单元测试证明 code 的模型不足错误会回退 model，随后重新运行 code。
- 普通 code 失败不会误回退 model。
- `rework_request.json` 只包含固定 schema、目标阶段和归一化原因，不包含 prompt、
  密钥或供应商原始响应。
- r8 的最新恢复候选可在不新增 LLM 请求的情况下重放，并触发 model 重做。
- 未激活 model 版本存在时，绑定激活 model 的 code 证据仍能进入下一轮 Modeler。
- 反馈只包含结构化方法摘要和偏差，不包含供应商响应、prompt、密钥或 Oracle。

## 实测结果

- r8 在新托管运行中以 `0 tokens` 直接恢复 2026-07-29 06:57 保存的候选。
- 候选再次证明四种结构不能同时通过拟合与可辨识性门禁，保存为 code v6。
- code 门禁返回稳定的 model 重做请求，托管器从第 5 阶段自动跳回第 4 阶段，
  Modeler 实际读取下游证据并产生 model v5～v7。
- v7 Coder 主动输出 `MODEL_REWORK_REQUIRED` 后再次保存 code v7 并回退 model，
  没有继续耗尽五轮普通代码反思。
