# 缺陷与待改进清单 — 2023A

分类：[工具] mmw 代码 / [提示词] prompts/ / [人工] 赛时人脑攻坚。修复后打勾并注明方式。

## 严重（影响得分）

- [ ] **[人工] q2/q3 镜场设计优化未产出完整数值结果**：吸收塔位置、镜面尺寸、镜数、布局的优化只走了粗粒度搜索，未输出最终设计参数和对应功率到 results.json，导致摘要只能写「详见正文」（摘要数值具体性 10/25）。与 2023B q4 同型——**布局/设计优化是 LLM 系统性弱项，赛时必须人工主攻**
- [ ] **[人工] 问题 1 结果偏低约 20%**（30.09 MW vs 参考 36~39 MW）：疑似阴影遮挡或截断效率计算偏保守（如未区分阴影与遮挡的去重、光斑模型过粗）。需人工对照 Verifier 指出的三处实现细节逐一复核
- [x] **[提示词] result2.xlsx / result3.xlsx 交付物仍未生成**（与 2023B 的 result1/2.xlsx 同型缺陷，二次出现）→ 已打通交付物全链：analyst.j2 输出 deliverables 清单 → code.j2/coder.j2 铁律强制生成 → stage_solve 校验缺失警告 → export 打包（待下次实测验证端到端效果）

## 中等（影响质量）

- [ ] **[人工] 数值审计 7 个高置信缺出处**待逐一核实（详见 deliverables/numeric_audit.md）
- [x] **[工具] 摘要不达标时缺「上游数据不足」的归因提示**：→ critic 输出新增 needs_upstream_data 字段（abstract_critic.j2 归因判断节），_refine_abstract 检测到即提前退出并提示 rework code（+ 测试）
- [x] **[提示词] 全角标点又出现在代码里**（v1 第 1 轮 SyntaxError: '。'）：→ coder.j2 规则 8 补充「代码语法部分只允许半角字符，语句末尾一个全角句号就是 SyntaxError」（'。'→'.' 自动转换有误伤风险，维持提示词强调方案）

## 轻微

- [ ] **[工具] 链式 approve 放行了残缺检查点**（paper v1 缺 4 章节仍被审批）：关键章节守卫已补在 stage 层，但 approve 命令本身可考虑对 paper 阶段做章节完整性检查
- [ ] **[人工] 摘要 59 分版本仍超字数**（689 字 > 600），需赛时人工精修

## 已修复（本次实测中）

- [x] **[工具] writer 批次输出格式漂移导致章节全丢**：_run_batch 格式重试一次（writer.py）
- [x] **[工具] 残缺论文检查点被静默保存**：stage_paper 关键章节守卫，缺 abstract/model_solution 中止（stage_paper.py）
- [x] **[工具] 摘要迭代保留最后版而非最佳版**：keep-best 跟踪历史最高分（stage_paper.py，2022C 已记录、本案例实证伤害后修复）
- [x] **[工具] 关键词硬指标不认 \keywords{} 命令**（abstract_critic.py）
- [x] **[人工→已演示] 从迭代历史手工回滚最佳摘要**：python 一行脚本从 abstract_iterations.json 取最高分版本替换检查点
