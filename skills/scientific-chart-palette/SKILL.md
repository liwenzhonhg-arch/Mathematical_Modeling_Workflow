---
name: scientific-chart-palette
description: >-
  为数学建模论文图表按数据语义选择可追溯、离线的科学配色，并返回角色映射、二级编码建议
  和后端状态。用于 FigurePolisher 或需要统一 Matplotlib、MATLAB、Origin 配色的科研绘图；
  不用于生成任意颜色、网页调色器或从图片反推颜色。
---

# Scientific Chart Palette

## 任务边界

只做配色决策，不绘图、不修改 CSV/manifest 数值、不改变模型结果。运行期只读取本 Skill
目录中的已批准 `references/palettes.json`，不访问 ColorSpace 或其他外部网站。

## 使用流程

1. 先根据图表问题确定 `chart_type`、系列数和语义角色。
2. 调用 `scripts/select_palette.py`，优先使用 `scale_semantics`；发散配色必须提供
   有意义的 `midpoint`。
3. 将返回的 `palette_id`、`role_map` 和 `secondary_encodings` 写入图表质量报告。
4. Matplotlib、MATLAB 使用返回的精确 HEX；Origin 仅在真实验证通过时使用，否则回退
   Matplotlib 并记录 `degraded`。

## 硬约束

- categorical 最多直接区分 6 个主要系列；更多系列改用线型、点型、直接标注或分面。
- 不使用彩虹色谱、3D 渐变或仅靠红绿区分。
- 不确定性带使用主系列的浅色/透明度，不新增独立系列颜色。
- 同一语义跨子图和后端保持同色；观测、基线和被支配解优先使用中性色。
- 同一目录版本和相同输入必须得到相同输出。
- 连续曲线/曲面只有在颜色绑定时间、参数或函数值时才使用 `blue-teal-sun-v1` 和颜色条；
  普通单条曲线保持单色。

## 资源

- 配色目录：[references/palettes.json](references/palettes.json)
- 选择与校验：[scripts/select_palette.py](scripts/select_palette.py)
- 项目级合同：`test_cases/scientific_chart_palette_skill_spec.md`

安装或启用前，按项目规则运行 `/skill-vetter` 并等待用户确认；本文件不授予安装权限。
