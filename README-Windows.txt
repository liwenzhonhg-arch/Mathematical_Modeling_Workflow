MMW Windows x64 便携版

1. 完整解压 ZIP，不要只从压缩包内直接运行。
2. 双击 MMW.exe，浏览器会打开本机审查台。
3. 先进入“模型与运行模式”：
   - API 模式：填写自己的 API Base URL、API Key 和模型。
   - Codex 模式：本机需另外安装 Codex CLI，并先运行 codex login。
4. 选择包含题目 PDF 或 DOCX 及附件的文件夹，然后启动流程。

说明：
- 程序仅监听 127.0.0.1。
- 支持带文本层的 PDF 和现代 Word DOCX；旧版 DOC 请先另存为 DOCX。
- 配置保存在当前 Windows 用户的 %APPDATA%\MMW\.env，不会写入安装目录。
- 最近打开的项目记录在 %APPDATA%\MMW\recent-projects.json，刷新页面或重启后会自动恢复。
- Codex 登录态、API Key、题目文件和工作区均不包含在发行包中。
- 启动后会异步检查官方 GitHub Release；右上角出现更新按钮时可一键下载、校验并重启到新版。
- 新版安装在当前用户的 %LOCALAPPDATA%\MMW\versions，不覆盖正在运行的便携版。
- 生成最终论文 PDF 需要另外安装 MiKTeX 或 TeX Live（含 xelatex、bibtex）。
- “论文与交付”页可重制图表、自动排版和检查 PDF 版式；版式门禁未通过时不能导出。
- “流程总览”可选择逐阶段审查，或显式启动“托管运行到最终交付”；托管遇到缺数据、质量失败或预算耗尽会暂停，处理后可恢复。
- 绘图默认使用 Matplotlib；本机已安装 Origin 2024 时可在项目中切换 Origin 后端。
- 这是便携版，不需要安装 Python；不要删除同目录下的 _internal 文件夹。
