MMW Windows x64 便携版

1. 完整解压 ZIP，不要只从压缩包内直接运行。
2. 双击 MMW.exe，浏览器会打开本机审查台。
3. 先进入“模型与运行模式”：
   - API 模式：填写自己的 API Base URL、API Key 和模型。
   - Codex 模式：本机需另外安装 Codex CLI，并先运行 codex login。
4. 选择包含题目 PDF 和附件的文件夹，然后启动流程。

说明：
- 程序仅监听 127.0.0.1。
- 配置保存在当前 Windows 用户的 %APPDATA%\MMW\.env，不会写入安装目录。
- Codex 登录态、API Key、题目文件和工作区均不包含在发行包中。
- 生成最终论文 PDF 需要另外安装 MiKTeX 或 TeX Live（含 xelatex、bibtex）。
- 这是便携版，不需要安装 Python；不要删除同目录下的 _internal 文件夹。
