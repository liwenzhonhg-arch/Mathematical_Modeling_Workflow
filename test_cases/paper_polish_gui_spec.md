# 论文重制 GUI Spec

状态：已实现；真实浏览器冒烟检查通过，未安装 `originpro` 的开发环境会禁用 Origin 选项

## 目标

复用现有 Job 进度模型，在“论文与交付”页面提供图表重制、自动排版和视觉质量
检查，不增加新的页面路由和前端框架。

## 操作

- 绘图后端选择：Matplotlib / Origin。
- `重制当前图表`。
- `自动排版论文`。
- `检查 PDF 版式`。
- 查看当前质量报告和预览目录。

## 后端

继续使用 `/api/projects/<id>/tool`，增加：

- `polish-figures`
- `typeset`
- `layout-check`

每个任务必须返回现有 Job 字段：状态、当前步骤、开始/完成时间、百分比或
indeterminate、最终失败原因。

## 权限与安全

- 沿用本机会话令牌和不透明 `project_id`。
- 浏览器不得提交 Origin 路径或任意文件路径。
- 页面不显示 prompt、模型原始响应或完整异常。
- 任务运行期间禁用重复启动按钮。

## 验收

- 三个工具的 API、任务冲突、刷新恢复和失败消息有测试。
- 无 Origin 时选项显示“不可用”，Matplotlib 仍可运行。
- visual quality 硬失败时 export 按钮禁用并显示具体项目。
