# 移动热运行契约 Spec

状态：**已实现并经 r8 code 续跑验证（2026-07-29）**

## 问题

2020A r8 已通过 model，但 code 的第二个候选使用 `scheme="implicit"` 后，仍按
显式格式的 `diffusion_number <= 0.5` 条件主动终止。现有 Coder 运行摘要和反思提示
先无条件要求该条件，下一行又要求薄层刚性问题使用隐式格式，契约相互矛盾。

同一候选还把 `assess_multistart_identifiability` 返回值包在 `diagnostic` 字段内。
code 门禁会从 `identifiability.json` 顶层重算诊断，因此这种包装即使运行完成也会
被拒绝。

## 规则

1. `diffusion_number <= 0.5` 只约束 `scheme="explicit"`；显式格式通过增加
   `substeps` 满足条件。
2. `scheme="implicit"` 不得被显式稳定性条件阻断；仍须用网格或时间步收敛检查验证
   数值精度。
3. `assess_multistart_identifiability(...)` 的原始返回对象必须直接、无包装地写入
   `identifiability.json` 顶层。
4. 标定过程的其他元数据写入独立文件，不得改变 `identifiability.json` 的门禁
   schema。
5. 可辨识性失败继续 `raise`，不得放宽阈值、伪造通过状态或绕过门禁。
6. 多个优化子问题共享 Coder 的单次执行总上限。模型必须先扣除标定、固定扫描、
   输出和验证开销，再给 q3、q4 分配共同截止时间；不得给每个子问题分别设置完整
   300 秒默认预算。每个候选开始前检查剩余总预算，只允许已开始的一次仿真越界。

## 验收

- 初次生成、错误反思、系统提示和运行摘要使用同一稳定性规则与文件契约。
- 自动测试锁定“显式才检查扩散数”和“报告直接写入顶层”两条提示。
- 门禁测试证明把诊断包装在 `diagnostic` 下会失败。
- 真实 code 续跑不再因隐式格式的显式稳定性条件终止；若仍失败，应暴露下一个真实
  问题而不是绕过。
- 模型修订与 Verifier 提示能识别“q3=300 秒且 q4=300 秒，但整个执行器仅
  300 秒”的不可执行预算合同，并要求重做 model 而不是在 code 内静默缩短。
