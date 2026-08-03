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
