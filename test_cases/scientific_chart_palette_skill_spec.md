# 科研图表配色资源与 Skill Spec

状态：Spec 已冻结；配色资源、Skill 实现和安装均待执行。

## 1. 决策

采用两步方案：

1. 先建立经过人工筛选和验证的本地配色目录。
2. 再将“按图表语义选择配色”的确定性流程封装为项目 Skill。

首版不复刻 ColorSpace 的任意颜色生成器。`mycolor.space` 只作为候选配色来源之一；
运行期不访问该网站、不抓取页面、不调用未公开接口，也不复制其源码或算法。

## 2. 目标

- 为数学建模论文图表提供稳定、离线、可追溯的配色选择。
- 同一语义在 Matplotlib、MATLAB 和可用的 Origin 后端中保持同色。
- 让配色服从数据语义、灰度阅读和论文缩放要求，而不是只追求屏幕观感。
- 在不修改求解数据、模型和结论的前提下，为 FigurePolisher 提供颜色角色映射。

## 3. 非目标

- 不制作通用调色网站或 ColorSpace 克隆。
- 不承诺从任意种子色生成无限色板。
- 不替代图型选择、轴与单位、标注、线型、点型和版式质量门禁。
- 不从论文图片、PNG 或网页截图反推数值或精确配色。
- 不在本 Spec 阶段安装 Skill、插件或新增依赖。

## 4. 第一阶段：本地配色目录

首批目录必须包含 13 个 `approved` 配色组：

| 类型 | 数量 | 主要用途 |
|---|---:|---|
| categorical | 4 | 2–6 个无序系列、分组柱图、甘特图类别 |
| sequential | 4 | 连续曲线、有序强度、非负热力图、单向敏感性 |
| diverging | 3 | 围绕零值、基准值或目标值的双向偏差 |
| highlight | 1 | 一个重点系列加若干中性背景系列 |
| neutral | 1 | 观测点、基线、被支配解、辅助网格 |

现有 `muted-editorial-v1` 作为首个候选，并继续以
`scientific_figure_benchmark/style_contract.json` 为精确色值来源。其余候选可来自
ColorSpace 的配色结果、出版社规范或人工设计，但必须通过本 Spec 的验收后才能标记
为 `approved`。

`blue-teal-sun-v1` 是连续曲线和连续曲面专用色板，颜色从深蓝、蓝青、青绿过渡到
黄绿和暖黄。它表达有序连续变量，不用于无序类别；单条普通曲线不得为了装饰而强制
渐变，只有颜色确实绑定时间、参数或函数值时才使用颜色条。

### 4.1 目录记录格式

配色目录保存为一个 JSON 文件；每组只保留以下字段：

```json
{
  "id": "muted-editorial-v1",
  "kind": "categorical",
  "colors": ["#315A7D", "#C46A45", "#4F8A83", "#82789B"],
  "roles": {
    "primary": "#315A7D",
    "accent": "#C46A45",
    "neutral": "#B8BDC3",
    "text": "#30343B",
    "grid": "#E2E5E9",
    "paper": "#FFFFFF"
  },
  "use_for": ["line", "scatter", "bar", "pareto", "gantt"],
  "source": {
    "type": "project",
    "url": null,
    "seed": null,
    "accessed_at": null
  },
  "status": "approved"
}
```

约束：

- `id` 使用稳定的 kebab-case；已用于正式输出后不得改变其颜色含义。
- 颜色统一保存为大写六位 HEX；单组内不得有重复值。
- 来自 ColorSpace 的候选记录完整分享 URL、种子 HEX 和访问日期。
- `roles` 只写确有语义的颜色；不得为填满字段而制造角色。
- `candidate`、`rejected` 不进入运行时目录；筛选记录留在测试证据中。

## 5. 第二阶段：Skill 合同

Skill 名称固定为 `scientific-chart-palette`。它接收图表语义，返回已批准配色组及角色
映射；不直接绘图，不读取原始图片，不改变 CSV。

### 5.1 输入

必填：

- `chart_type`：`line | scatter | distribution | bar | heatmap | tornado | pareto | gantt`。
- `series_count`：需要区分的主要系列数，整数且大于零。
- `output_mode`：`screen | print | grayscale`。

可选：

- `roles`：如 `observed`、`forecast`、`baseline`、`front`、`dominated`。
- `scale_semantics`：`categorical | sequential | diverging`。
- `midpoint`：仅发散数据使用的有意义中点。
- `seed_color`：仅用于在已批准目录中排序，不生成新色板。

### 5.2 输出

```json
{
  "palette_id": "muted-editorial-v1",
  "colors": ["#315A7D", "#C46A45"],
  "role_map": {
    "front": "#315A7D",
    "dominated": "#B8BDC3"
  },
  "secondary_encodings": ["marker", "direct_label"],
  "backend_status": {
    "matplotlib": "supported",
    "matlab": "supported",
    "origin": "validate-before-use"
  },
  "warnings": []
}
```

相同输入和同一目录版本必须得到完全相同的输出，不使用随机数。

### 5.3 最小调用形式

```powershell
python skills/scientific-chart-palette/scripts/select_palette.py `
  --chart-type pareto `
  --series-count 2 `
  --roles dominated,front `
  --output-mode print
```

脚本只使用 Python 标准库。复杂度在实际需要前不扩展为服务、GUI 或独立包。

## 6. 选择规则

按以下顺序选择，后项不得覆盖前项：

1. **数据语义**：无序类别用 categorical；有序单向量用 sequential；只有存在明确
   零值、基准值或目标值时才用 diverging。
2. **角色稳定**：主方法/预测用 `primary`，对照/高扰动用 `accent`，观测/基线/被支配
   解用中性色；同一语义跨子图和后端保持一致。
3. **焦点限制**：单张图最多一个高显著性重点色；其余系列降低饱和度或转为中性。
4. **系列上限**：categorical 最多直接区分 6 个主要系列。超过 6 个时必须返回
   `secondary_encodings`，优先使用线型、点型、直接标注或分面，不继续堆颜色。
5. **不确定性**：区间使用对应主色的低透明度浅色，不新增独立类别色。
6. **热力图**：顺序数据不得使用发散色图；发散色图的中性色必须对齐 `midpoint`。
7. **甘特图**：颜色绑定任务类别，不绑定资源；同类任务跨资源同色。
8. **禁用项**：禁止彩虹色谱、3D 渐变、纯装饰性色块和仅靠红绿区分。

## 7. 可读性门禁

- 默认背景为 `#FFFFFF`。
- 正文和轴标签与背景的对比度至少为 4.5:1；关键图形标记与背景至少为 3:1。
- `grayscale` 模式下，主要系列必须同时使用线型、点型、纹理或直接标注区分。
- 300 DPI PNG 和论文实际栏宽缩放后，图例、标签和重点系列仍可辨认。
- 每个 `approved` 配色组必须生成彩色、灰度两份接触表供人工复核。
- 自动门禁只检查 HEX、数量、对比度、重复值和确定性；色觉缺陷模拟及论文缩放由
  人工复核，不用新依赖伪造“自动通过”。

## 8. 后端合同

- Matplotlib 是默认和回退后端，必须接受目录中的精确 HEX。
- MATLAB 必须映射相同 HEX，不得替换为默认 `ColorOrder`。
- Origin 是 Windows 可选后端；只有实测精确颜色、透明度和导出成功后才标记
  `supported`。
- Origin 自动化失败或颜色能力不足时记录 `degraded`，并回退到 Matplotlib；不得把
  回退图片声明为 Origin 输出。

## 9. 来源与离线边界

- ColorSpace 候选入口：<https://mycolor.space/?hex=%23845EC2&sub=1>。
- 只人工保存最终候选 HEX 和来源元数据，不保存网站 HTML、JavaScript、Cookie 或
  原始响应。
- 运行时只读取本地已批准目录；来源网站下线、改版或无法访问不得影响绘图。
- 参考配色只作为表达灵感，不复制论文数据、整图布局或受保护源代码。

## 10. 与现有流程的集成

- 本 Skill 由 FigurePolisher 在读取当前 `figure_manifest.json` 和对应 CSV 后调用。
- FigurePolisher 仍负责图型、线型、标记、字体、布局、轴、单位和导出；本 Skill 只
  返回配色决策。
- 每张成图的质量报告增加 `palette_id`、角色映射、配色目录 SHA-256 和后端状态。
- 数值来源继续遵守 `scientific_figure_skill_experiment_spec.md`：仅使用当前 solve 的
  CSV/manifest，不读取历史图或参考图数据。

## 11. 计划目录

实现阶段只新增以下最小结构：

```text
skills/scientific-chart-palette/
├── SKILL.md
├── references/
│   └── palettes.json
└── scripts/
    └── select_palette.py
```

不创建 README、GUI、服务端、缓存、数据库或多层配置。评测输入和接触表放在
`test_cases/scientific_chart_palette/`，临时输出不得进入 `skills/`。

## 12. 验收

### 12.1 配色目录

- 13 个 `approved` 配色组，类型数量符合第 4 节。
- 所有颜色、ID、来源字段和用途通过结构校验；重复执行校验结果一致。
- 每组均有彩色/灰度接触表和人工结论，失败候选不得混入运行目录。
- 至少保留一个来自当前项目的配色组；来自 ColorSpace 的组均能追溯到分享 URL 和
  种子色。

### 12.2 选择器

- 对 line uncertainty、grouped bar、heatmap、Pareto、Gantt 各有一个确定性样例。
- `series_count > 6` 时返回二级编码建议，不生成第七个类别色。
- `scale_semantics=diverging` 且无 `midpoint` 时明确失败，不静默选择发散色图。
- 非法 HEX、未知图型、空目录和缺失角色给出可定位错误。
- 来源网站不可访问时，本地选择和成图不受影响。

### 12.3 Skill 与流程

- 使用项目实际 Skill validator 校验 `SKILL.md` 和目录结构。
- Matplotlib、MATLAB 使用相同角色 HEX；Origin 的成功、降级或回退均有真实记录。
- 质量报告包含目录哈希和 `palette_id`，可从成图追溯到具体配色版本。
- 安装前必须运行 `/skill-vetter`，报告结果并等待用户确认；未确认不得安装。

## 13. 实施顺序

1. 收集 12 组候选并生成接触表。
2. 人工筛选后冻结 `palettes.json`。
3. 实现单文件确定性选择器及最小样例。
4. 编写 `SKILL.md`，运行 validator 和范围测试。
5. 接入 FigurePolisher 的质量报告，但不改变数值链。
6. 运行 `/skill-vetter`；用户确认后才安装或启用。
