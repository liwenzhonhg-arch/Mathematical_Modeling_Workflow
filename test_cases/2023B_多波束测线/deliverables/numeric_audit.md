# 数值一致性审计报告

程序化比对论文数值与求解产出（results.json / sensitivity.json / params.json）。

统计：共提取 150 个数值，匹配 148 个，缩放匹配 0 个，高置信缺出处 2 个，低置信可疑 0 个，忽略 115 个（编号/年份/小整数）。

## [严重] 高置信缺出处数值（极可能是编造的，必须逐一核实）

- `20.62` 出自 sections/model_solution.tex：…线数量$N$最少）。  水深函数由西边界基准水深$D(0)=20.62$m和坡度$\alpha$确定：   D(x) = D(0)…
- `0.0262` 出自 sections/model_solution.tex：…ha) = \tan(1.5^\circ) \approx 0.0262$。  目标函数为最小化测线总长度$T$，等价于最小化测线数…
