# 缺陷与待改进清单 — 2023B

分类：[工具] mmw 代码 / [提示词] prompts/ / [人工] 赛时人脑攻坚。修复后打勾并注明方式。

## 严重（影响得分）

- [ ] **[人工] q4 真实地形布线算法失效**：漏测率 88%，LLM 给的「按方向角枚举 + 贪心」对复杂地形不收敛。需要人工设计算法（候选：沿等深线分段布线、按最浅深度分区、动态间距规划）。这是本题拿奖的核心难点
- [x] **[提示词] 题目硬性要求未满足**：题目要求产出 result1.xlsx / result2.xlsx 并在正文放规定格式的表 1/表 2，solution.py 没有生成 xlsx。→ 已打通交付物全链：analyst.j2 让 sub_problems.json 输出 deliverables 清单 → code.j2/coder.j2 铁律强制生成 → stage_solve 运行后校验缺失警告 → export 打包（待下次实测验证端到端效果）
- [ ] **[人工] q3 重叠率违反约束**：最大重叠率 24.92% 超出题目 10%~20% 区间，贪心策略对约束上界处理不严格。需人工修正算法（从深端起步或双向夹逼）

## 中等（影响质量）

- [x] **[工具] EDA 统计量是 LLM 估算而非真实计算**：→ 2022C 期间 EDA 全面重构为「真实结构摘要→生成代码→沙箱执行→按真实输出写报告」（stage_eda.py）
- [x] **[工具] EDA 未产出 notebook 和图表**：→ 重构后产出 eda_code.py + eda_output.txt + figures/eda_*.png（以可执行脚本+真实图表替代 notebook 设计）
- [x] **[提示词] 摘要遗留矛盾表述**：→ abstract_critic.j2 增加否决条款——结论与 results.json 数据矛盾时总分不得高于 60，issues 首条必须指明矛盾点
- [ ] **[人工] research 的 [需要搜索:] 未走人工检索中继**：本次 references/ 为空，文献支撑薄弱

## 轻微（体验/健壮性）

- [x] **[工具] 论文未引用图片**：→ 2022C 期间修复 `\graphicspath{{figures/}{./}}` + PDF 完整性校验（compiler.py），图片路径对接问题已根治
- [ ] **[工具] branch / compare 命令未在本案例演练**（已有单元测试覆盖，缺实战验证）
- [x] **[工具] 审计对派生值的提示可更友好**：→ 高置信标题措辞改为「编造或派生计算值，须逐一核实出处」（numeric_audit.py）

## 已修复（本次实测中）

- [x] **[工具] 推理模型输出截断**：max_tokens 可配置，MiMo 设 32768（mmw/config.py + .env）
- [x] **[工具] 代码生成截断**：全局 max_tokens 8192（.env LLM_MAX_TOKENS）
- [x] **[工具] 网络断流崩溃**：run_stream 3 次重试递增退避（mmw/agents/base.py）
- [x] **[工具] 数值审计误报 38 个**：run_log 纳入候选集 + 符号不敏感匹配（mmw/utils/numeric_audit.py）
- [x] **[人工→已演示] model 公式错误**：Verifier 抓出 + 人工编辑检查点修正（流程按设计工作）
