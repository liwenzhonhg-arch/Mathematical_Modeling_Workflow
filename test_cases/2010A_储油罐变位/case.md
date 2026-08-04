# 案例：2010 国赛 A 题“储油罐的变位识别与罐容表标定”

## 来源与性质

- 题目来源：https://www.mcm.edu.cn/html_cn/node/d5ae730f57dea3208cae73f7635aeee8.html
- 官方压缩包：https://www.mcm.edu.cn/upload_cn/node/70/rd4LEPmmd1095c70a7fb9d0898a08495837d8c93.rar
- 测试性质：双工作区清洁盲测；隐藏 Oracle 与工作区隔离。
- 输入：官方题面转换为 DOCX，两个 XLS 附件转换为 XLSX；转换仅改变容器格式。
- 运行 SPEC：`../2010a_clean_room_validation_spec.md`。

## 冻结快照

- commit：`0ae471c8039ca8b4b4108685f19ba5fe95201cba`
- 题面 DOCX SHA-256：`89154A219BF4A03007F6762E017D5467543B5BA488C1171BC5AB605229602FFC`
- 附件 1 SHA-256：`D8C7C50E0FE3C4B6C239E0E1FF90109667C14D8F9FAD8B1D717E1384D994A7EC`
- 附件 2 SHA-256：`0DD4A74C966804C5C1FFB9A0CBE53C0D7F04A4A7FF2B0142A71281917B6E0600`
- 每轮预算：1,000,000 tokens、180 活跃分钟、每阶段最多重做 2 次、总重做最多 8 次。
- 两个工作区启动前均只含上述三个官方输入；隐藏 Oracle 未复制到工作区。

## r1

- 时间：2026-08-03 00:18:38–01:56:45，活跃约 98.1 分钟。
- 结果：`waiting_user`，停在 model；analyze/eda/research 已审批，model 最新 v4 为 Verifier block，code v1 未审批，未进入 solve/paper/review。
- token：826,169。
- 关键证据：DOCX 文字提取丢失题图空间关系，模型把实际罐圆柱段误作 6 m，code 得到总容量约 50.527 m³；独立几何基线约 64.664 m³。Verifier 还发现空罐边界极值方向、协方差二次型和探针坐标证据错误。
- 成品：无论文 PDF、无 submission.zip，不满足完整产品要求。

## r2

- 时间：2026-08-03 20:26:32–21:05:13，活跃约 38.7 分钟。
- 结果：`waiting_user`，停在 model；analyze/eda/research 已审批，model 最新 v5 为 Verifier block，未进入 code/solve/paper/review。
- token：706,999。
- 关键证据：Verifier 无法从扁平题面确认小罐倾斜方向和实际罐探针位置；模型还留下未固定的稳健损失/近最优容差/起点数，并设计约 3.3 万角度候选的超预算搜索。
- 成品：无论文 PDF、无 submission.zip，不满足完整产品要求。

## 跨轮重复性

两轮都在 model 前后失败，未产生可比较的 solve 数值和罐容表。共同根因是题图空间信息没有进入 Agent 输入；失败阶段和 token 消耗不稳定，不能视为可重复完成。

## 结论

冻结基线判定为 **FAIL / unverified**。当前版本不能仅凭官方 DOCX 与附件独立产出完整合格作品；质量门禁诚实阻止了错误模型，但输入提取、模型最小可执行性、错误可见性和完整表格 Oracle 需要修复。修复方案见 `../2010a_standalone_reliability_fix_spec.md`。

## post-fix 探索轮（不计入最终双轮验收）

### postfix4_r1

- 冻结提交：`80f72ce`；工作区：`benchmark_2010A_postfix4_r1`。
- 时间：2026-08-04 00:06:40–01:01:44，活跃约 55.1 分钟。
- 结果：`waiting_user`，停在 code；token 请求边界累计 1,034,185，超过 1,000,000 后不再发起请求。
- 已确认进展：analyze 只保留官方 q1/q2；model v5 正确使用实际罐总长 10 m、圆柱段 8 m、探针距左端 3 m，并获 Verifier pass。
- 新缺陷：EDA/Coder 都把附件名全角冒号归一化为半角冒号；结果门禁误把 `NRMSE可用` 状态项当成 NRMSE 数值；model 只拟合相邻流量增量并自行增加探针零偏，使 q2 得到纵倾 0°、横偏约 7.04° 的错误条件解，尚未进入隐藏 Oracle。
- 成品：无 PDF、无提交包，本轮判定 FAIL / unverified；其工作区只保留作失败证据。

### postfix5_r1

- 冻结提交：`1f0850b`；工作区：`benchmark_2010A_postfix5_r1`。
- 结果：code v1、solve v1 已审批，停在 paper；累计 1,015,821 tokens 后暂停。
- 正向证据：附件路径首次执行成功；问题二识别为纵倾约 2.120°、横偏绝对值约 4.239°，落入隐藏范围；q2 罐容表抽样值与独立基线一致。
- 失败证据：问题一把截面 `1.2 m`/`1.78 m` 横竖方向颠倒，1.2 m 高度处罐容约 3106 L，隐藏基线约 4013 L；paper 追踪还因 L1–L4 注释缺失和否定性全局最优语句误判而停止。
- 结论：FAIL / unverified；未生成 PDF 和提交包，不计入最终双轮验收。

### postfix6_r1

- 冻结提交：`acf232e`；工作区：`benchmark_2010A_postfix6_r1`。
- 时间：2026-08-04 08:47:41–09:25:02，活跃约 37.3 分钟；累计 698,593 tokens。
- 结果：`waiting_user`，停在 code v3；三次候选均结构化返回 `MODEL_REWORK_REQUIRED`，未进入 solve/paper/review。
- 正向证据：问题一椭圆横竖半轴已正确取 `0.89 m`、`0.60 m`；Coder 没有靠零偏、比例系数或放宽容量边界掩盖矛盾。
- 失败证据：模型把图中探针右侧单段 `2.05 m` 当作小罐总长，遗漏左侧 `0.4 m`，导致几何容量 `3.439101 m³` 小于附件累计进油跨度 `3.656910 m³`。原图尺寸链应为 `0.4 + 2.05 = 2.45 m`；DOCX 定位文本的溢出后缀还被提取成 `2.05mcm`。
- 结论：FAIL / unverified；修复提取归一化与相邻段总长规则后重新冻结双跑。

### postfix8_r1

- 冻结提交：`ba2cce3`；工作区：`benchmark_2010A_postfix8_r1`；`postfix7` 仅完成初始化预检，未启动 LLM。
- 结果：analyze/eda/research/model/code/solve 已审批；累计 1,030,882 tokens 后停在 paper 摘要迭代，未进入 review/compile/export。
- 正向证据：小罐总长 `2.45 m`、半轴 `0.89 m/0.60 m` 和总容积 `4.110146 m³` 正确；问题二得到纵倾 `-2.119490°`、横偏幅值 `4.237820°`，问题二数值抽样与隐藏基线一致。
- 失败证据：模型忽略附件备注中明确的初始油量，把实验首行重新归零并重估初值，问题一选择了错误倾斜方向；两张表又从物理空端起步，未对齐题面要求的 `0–1.2 m` / `0–3.0 m` 主网格。隐藏表格 Oracle 因覆盖、网格和抽样失败而判定 FAIL。
- evaluator 诊断同时确认：有符号角需要按契约 `abs` 比较，“横向倾角幅值”和 `capacity_L` 是合法语义别名；只扩展别名/变换，不调整数值容差。
- 结论：FAIL / unverified；修复已知初值、必答网格和 evaluator 语义后，新双轮预算为 1,500,000 tokens、180 活跃分钟。

### postfix9_r1

- 冻结提交：`8f031f1`；工作区：`benchmark_2010A_postfix9_r1`；预算 1,500,000 tokens、180 活跃分钟。
- 结果：完成到 solve v1；paper 因外层一小时进程上限中断后暂停，累计 1,336,079 tokens。
- 正向证据：q1 主表五个隐藏抽样点和 q2 主表七个隐藏抽样点均落入冻结数值范围；纵倾角度制 `-2.119908°`、横偏幅值角度制 `4.222917°`；code/solve 同轮一致。
- 交付缺陷：等价表格使用 `油位_m`、`*_体积_m3`，旧 evaluator 未按显式单位换算；角度 alias 先命中 rad 字段。修复只扩展等价名称和 `m³→L` 换算，不改变范围或容差。
- 质量缺陷：`q2_物理空端容量=37.540265 m³` 明显不为零，却被旧状态机放行。已新增空端容量确定性门禁和端点复算提示。
- 结论：FAIL / unverified；本轮不计最终双轮，下一对以修复后的 evaluator 和物理门禁重新冻结。
