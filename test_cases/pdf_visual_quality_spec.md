# PDF 视觉质量门禁 Spec

状态：已实现；A 题 16 页 PDF 实测识别两项测试占位并阻塞导出

## 目标

在“xelatex 返回 0”之外，自动发现影响提交的版式错误。检测失败项与 warning
分离；没有页面渲染器时仍执行日志和 PDF 结构检查。

## 输入与输出

- 输入：`main.log`、`main.pdf`、论文 LaTeX、图表 manifest。
- 输出：`output/layout_quality.json` 与 `output/layout_quality.md`。

## 硬失败

- PDF 不存在、损坏、超出页数上限。
- LaTeX error、未定义引用、`Missing character`。
- 空白正文页。
- 图表文件缺失、无效、低于 300 DPI 或宽高比超过 4:1。
- 正文仍含测试标题或 `TEST-RUN`。

## Warning

- `Overfull \hbox`。
- 单页文字过密或过少。
- 图表/表格标题未在正文引用。
- 页面渲染命令不可用。

## 页面预览

优先使用现有 `pdftocairo`/`pdftoppm` 渲染 110 DPI PNG；不可用时不新增大型
PDF 引擎依赖，只报告 warning。预览写入 `output/layout_preview/`，不进检查点。

## 验收

- 缺字、超页、空白页、低 DPI 和测试占位信息分别有测试。
- 质量报告绑定当前 paper 版本和 PDF SHA256。
- compile 成功但视觉硬失败时不得 export。
