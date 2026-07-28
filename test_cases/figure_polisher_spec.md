# FigurePolisherAgent Spec

状态：已实现

## 定位

FigurePolisherAgent 是 `solve → paper` 之间的受约束子步骤，不新增第九阶段。
它只决定图表表达方式，不重新求解，也不能改变数据。

## 输入

- 激活 `solve` 的 `figures_list.json`。
- `results.json`、`sensitivity.json`。
- Coder 生成的 `figure_manifest.json` 与每图 CSV。
- 原始 PNG，作为缺少结构化绘图数据时的回退。

## 输出

- 重制后的当前版本图表。
- `figure_manifest.json`：文件、类型、数据源、轴标签、单位、论文用途。
- `figure_quality_report.json`：逐图检查结果与失败原因。

## 支持范围

首版只支持 `line`、`scatter`、`bar`、`heatmap`。流程图不交给统计绘图器，
由 Typesetter 使用确定性 TikZ/LaTeX 处理。未知类型保留原图并报告 warning。

## 约束

- 只读取当前项目内、manifest 明确列出的相对路径。
- CSV 是图表数值的唯一来源；不得从 PNG 反推数据。
- 统一中文字体、色盲友好配色、线宽、网格和 300 DPI。
- 坐标轴必须有名称和单位；多序列必须有图例。
- 禁止饼图、3D 图、渐变背景、阴影和装饰性图片。
- 重制前后逐序列核对数值，不通过则保留原图并失败。

## 验收

- 四种图型各有一个自动化测试。
- 同一 manifest 重复运行产生相同尺寸和相同数据摘要。
- 当前运行未列出的历史图表不得进入新 manifest 或提交包。
