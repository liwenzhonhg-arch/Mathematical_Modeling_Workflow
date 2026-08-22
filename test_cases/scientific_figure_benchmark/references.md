# 权威来源与图型规则矩阵

检索日期：2026-08-11。只记录出版社、原始论文和软件官方文档；搜索摘要不作为
最终规则证据。

## A. 出版技术规范

| 来源 | 等级 | 提取规则 | 适用范围 |
|---|---|---|---|
| [Nature Research Figure Guide](https://research-figure-guide.nature.com/figures/preparing-figures-our-specifications/) | S | 轴与单位、可访问色板、可编辑文字、矢量优先、照片至少 300 DPI | 全部 |
| [Science/AAAS Figure Preparation](https://www.science.org/content/page/information-authors-research-articles) | S | 最终尺寸、线宽、符号、多子图、SI 单位、数据范围 | 全部 |
| [IEEE Create Graphics](https://journals.ieeeauthorcenter.ieee.org/create-your-ieee-journal-article/create-graphics-for-your-article/) | S | 颜色与线型/点形双重编码、灰度检查 | 多序列图 |
| [IEEE Resolution and Size](https://journals.ieeeauthorcenter.ieee.org/create-your-ieee-journal-article/create-graphics-for-your-article/resolution-and-size/) | S | 彩色/灰度图大于 300 DPI，黑白线稿大于 600 DPI | 导出 |
| [PLOS Figure Guidelines](https://journals.plos.org/plosone/s/figures) | S | 300--600 DPI、最终尺寸、分图、图注、图片完整性 | 全部 |
| [Elsevier Artwork Instructions](https://www.elsevier.com/about/policies-and-standards/author/artwork-and-media-instructions) | S | EPS/PDF/TIFF 等正式交付格式 | 导出 |

说明：不同出版社字号和文件要求不完全一致。本实验提取共同原则，不把某一期刊
的绝对字号直接写成 CUMCM 全局规则。

## B. 通用可视化研究

| 来源 | 等级 | 提取规则 |
|---|---|---|
| [Ten Simple Rules for Better Figures](https://journals.plos.org/ploscompbiol/article?id=10.1371%2Fjournal.pcbi.1003833) | A | 先确定信息；不信任默认值；避免误导、饼图式比较、无理由 3D 和 chartjunk |
| [Design of Data Figures](https://www.nature.com/articles/nmeth0910-665) | A | 优先使用更易准确比较的位置和长度编码 |
| [The Misuse of Colour in Science Communication](https://www.nature.com/articles/s41467-020-19160-7) | A | 使用感知均匀色图；禁止彩虹色谱；颜色轴按数据语义选择 |
| [Cividis](https://journals.plos.org/plosone/article?id=10.1371%2Fjournal.pone.0199239) | A | 顺序色图亮度单调并兼顾色觉缺陷 |
| [Beyond Bar and Line Graphs](https://journals.plos.org/plosbiology/article?id=10.1371%2Fjournal.pbio.1002128) | A | 小样本连续数据展示原始点和分布，不以均值柱图遮蔽数据 |
| [Raincloud Plots](https://wellcomeopenresearch.org/articles/4-63/v2) | A | 组合原始点、密度和统计摘要，避免单一摘要掩盖结构 |
| [ggdist](https://ieeexplore.ieee.org/document/10297592) | A | 用分位点、区间、密度和扇形图表达不确定性 |
| [Visualization in Bayesian Workflow](https://academic.oup.com/jrsssa/article/182/2/389/7070184) | A | 图用于 EDA、计算诊断、预测检查和模型比较，不只装饰最终结果 |

## C. 第一批八类图

| 序号 | 图型 | 主要参考 | 本实验提取的结构 |
|---|---|---|---|
| 01 | 时间序列与不确定性带 | [ggdist](https://ieeexplore.ieee.org/document/10297592)、[Bayesian workflow](https://academic.oup.com/jrsssa/article/182/2/389/7070184) | 观测实线、预测虚线、区间半透明带，图注明确区间含义 |
| 02 | 散点与拟合 | [Design of Data Figures](https://www.nature.com/articles/nmeth0910-665) | 原始点、拟合线和必要的区间；不以拟合线遮蔽点 |
| 03 | 分布组合图 | [Beyond Bar and Line Graphs](https://journals.plos.org/plosbiology/article?id=10.1371%2Fjournal.pbio.1002128)、[Raincloud Plots](https://wellcomeopenresearch.org/articles/4-63/v2) | 密度、原始点、中位数和四分位信息同时可见 |
| 04 | 分组比较 | [Ten Simple Rules for Better Figures](https://journals.plos.org/ploscompbiol/article?id=10.1371%2Fjournal.pcbi.1003833) | 零基线、同单位、直接比较，系列使用颜色和纹理/位置双重区分 |
| 05 | 热力图 | [Misuse of Colour](https://www.nature.com/articles/s41467-020-19160-7)、[Cividis](https://journals.plos.org/plosone/article?id=10.1371%2Fjournal.pone.0199239) | 发散量以零为中心；必须显示色条及单位 |
| 06 | 敏感性 Tornado | [Sensitivity Analysis of Environmental Models](https://www.sciencedirect.com/science/article/pii/S1364815216300287) | 低/高扰动围绕零基线，按影响范围排序 |
| 07 | Pareto 前沿 | [METRADE](https://www.nature.com/articles/srep15147)、[Multivariate Visualizations](https://link.springer.com/chapter/10.1007/978-3-642-40483-2_29) | 前沿和被支配解视觉分层，不把有限搜索声明为全局前沿 |
| 08 | 甘特图 | [Multi-Robot Scheduling](https://www.nature.com/articles/s41598-024-84240-3) | 横轴时间、纵轴资源、任务区段和任务 ID，可观察空闲与冲突 |

## D. 软件官方文档

| 后端 | 来源 | 用途 |
|---|---|---|
| Origin | [Origin Python graph export](https://www.originlab.com/doc/python/Sample-Projects-with-attached-Python-Code) | `originpro` 自动化和批量导出 |
| Origin | [LabTalk Layer.Plotn](https://docs.originlab.com/labtalk/ref/layer-plotn-obj/) | 单数据图颜色、线宽和透明度属性 |
| Origin | [LabTalk layer command](https://docs.originlab.com/labtalk/ref/layer-cmd/) | 分组/取消分组和图层重缩放；实际 COM 返回仍须单独验证 |
| MATLAB | [Export figures](https://www.mathworks.com/help/matlab/creating_plots/save-figure-at-specific-size-and-resolution.html) | `exportgraphics` 尺寸、分辨率和矢量导出 |
| MATLAB | [colororder](https://www.mathworks.com/help/matlab/ref/colororder.html) | 显式色板 |
| MATLAB | [tiledlayout](https://www.mathworks.com/help/matlab/ref/tiledlayout.html) | 多子图布局 |
| Matplotlib | [Style sheets and rcParams](https://matplotlib.org/stable/users/explain/customizing.html) | 可移植样式合同 |
| Matplotlib | [savefig](https://matplotlib.org/stable/api/_as_gen/matplotlib.pyplot.savefig.html) | PNG/PDF/SVG 导出 |
| PGFPlots | [Scientific data analysis](https://tikz.dev/pgfplots/tutorial2) | 论文内确定性矢量图和回归示例 |

## E. 不得直接推导的规则

- 论文发表级别不等于图片的每个设计选择都正确。
- 搜索结果、博客、视频和软件默认主题不能单独成为硬规则。
- 不从参考图片估读数值，不复制论文配色和面板布局。
- 不把期刊特定格式误当作 CUMCM 固定格式。
