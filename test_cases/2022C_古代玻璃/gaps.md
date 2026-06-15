# 缺陷与待改进清单 — 2022C

分类：[工具] mmw 代码 / [提示词] prompts/ / [人工] 赛时人脑攻坚。修复后打勾并注明方式。

## 严重（影响得分）

- [ ] **[人工] q1 风化前成分预测的方法深度**：当前用线性回归做风化前预测，未处理成分数据的成分性约束（CoDA/ilr 变换是该题获奖论文的常见亮点）。Verifier 也指出了预测方向表述问题
- [ ] **[人工] 风化与类型关联结论（p=0.247 不显著）与多数参考论文相反**：可能是合并口径（按采样点 vs 按文物去重）造成，需人工复核统计单元的选择
- [x] **[提示词] 题目要求的亚类划分「敏感性分析」深度不足**：→ coder.j2 规则 11 新增 (c) 题型适配——统计/ML 题扰动超参数与数据口径（k±1/±2、特征子集留一、阈值±5%），全档零变化的实验必须换扰动对象重做

## 中等（影响质量）

- [x] **[工具] 摘要迭代应保留最高分版本**：→ 2023A 期间修复 keep-best 跟踪（stage_paper.py + 回归测试）
- [x] **[工具] 反思循环对「同一错误反复出现」缺乏感知**：→ implement_with_retry 检测连续两轮同 error_summary 提前终止并提示根因排查方向（coder.py + 测试）
- [x] **[工具] 输出截断无显式检测**：→ llm.py 在流结束与同步调用处检查 finish_reason=length，红色警告提示调大 max_tokens（+ 测试）
- [ ] **[人工] 数值审计剩 1 个高置信缺出处**：需人工核实（详见 deliverables/numeric_audit.md）

## 轻微

- [x] **[工具] 人工编辑上游检查点后 status 显示「上游已变更」警告残留**：→ 新增 `mmw ack <stage>` 命令（checkpoint.ack_upstream + cli），已在本工作空间实测清除 research/model 警告
- [x] **[提示词] EDA 图表未被论文引用**：→ stage_paper 把 eda 的 data_summary.md 传给 writer，BATCH2 注入 EDA 摘要并指示数据预处理小节引用 eda_ 开头的图

## 已修复（本次实测中）

- [x] **[工具] 图片路径不匹配导致 xelatex 崩溃出损坏 PDF**：论文用裸文件名引用图片而图片在 figures/ 子目录 → MAIN_TEX_TEMPLATE 加 `\graphicspath{{figures/}{./}}`（compiler.py）
- [x] **[工具] compile 把「PDF 文件存在」当成功**：xelatex 崩溃留下的截断 PDF 也被报告成功 → 加 `_pdf_is_valid()` 校验尾部 %%EOF 标记（compiler.py）

- [x] **[工具] EDA 报告凭空编造数据结构**：重构为「真实结构摘要→生成代码→执行→按真实输出写报告」（stage_eda.py + eda agent + 3 个提示词）
- [x] **[工具] coder 用合成数据兜底**：数据文件清单贯通 + 三处禁伪造铁律（stage_code.py + coder.j2 + code.j2 + reflection）
- [x] **[工具] deepseek-chat 8192 截断 C 类代码**：coder 切 MiMo 49152（.env），结论写入 .env.example
- [x] **[工具] 摘要评分 JSON 解析脆弱**：候选切片解析 + raw_response 留底（abstract_critic.py）
- [x] **[人工→已演示] 多表关联知识注入**：人工编辑 eda 检查点的数据访问说明 → coder 一次跑通
