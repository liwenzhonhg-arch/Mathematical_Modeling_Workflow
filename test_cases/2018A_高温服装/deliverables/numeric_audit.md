# 数值一致性审计报告

程序化比对论文数值与求解产出（results.json / sensitivity.json / params.json）。

统计：共提取 182 个数值，匹配 178 个，缩放匹配 2 个，高置信缺出处 0 个，低置信可疑 2 个，忽略 153 个（编号/年份/小整数）。

## [提示] 缩放匹配（疑似单位换算，建议核对单位）

- `100` 出自 sections/model_solution.tex：…确施加。总网格点数$M$的选取兼顾计算精度与效率，每层约分配100个网格点，时间步长取$\Delta t = 1$ s。在每个…
- `100` 出自 sections/model_solution.tex：…K)}$、$h_{\text{skin}} \in [1, 100]\ \mathrm{W/(m^2\cdot K)}$范围内…

## [警示] 低置信可疑数值（精度低，可能是合理表述，人工判断）

- `95` 出自 references.bib：… journal={Proceedings of ICNN'95 - International Conference on…
- `6.4` 出自 sections/model_solution.tex：…V层的厚度标注为范围值（分别为0.6--25 mm和0.6--6.4 mm），表明这两个参数为可调的设计变量。  附件2提供了在…
