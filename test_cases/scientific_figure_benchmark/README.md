# Scientific Figure Benchmark

## 用途

本目录保存科研绘图 Skill 的前置基准：权威来源矩阵、确定性测试数据、三后端
渲染脚本、生成图片和验证报告。它不属于正式八阶段运行，不得读取真实比赛
Oracle，也不得向比赛 `output/` 或 `.mmw/` 写入文件。

## 结构约定

- `references.md`：来源、证据等级、适用图型和提取规则。
- `manifest.json`：八类图的数据字段、单位和后端期望。
- `style_contract.json`：三后端共用的语义色值和图型角色映射。
- `data/`：由 `scripts/generate_data.py` 生成的标准 CSV。
- `scripts/`：数据生成、三后端渲染和独立验证脚本。
  - `render_origin.py` 是当前已验证的 Origin COM/LabTalk 入口。
  - `render_origin_embedded.py` 是保留的内置 Python 实验入口；当前 COM 会话未能稳定
    触发它，不能作为验证通过的正式入口。
- `outputs/matplotlib/`：Matplotlib PNG/PDF。
- `outputs/matlab/`：MATLAB PNG/PDF。
- `outputs/origin/`：Origin 实际生成的图片；不支持项不得放替代图。
- `reports/`：输入哈希、后端状态、图像质量和差异报告。

## 命名

文件使用两位序号加小写下划线名称，例如 `01_time_series.csv` 和
`01_time_series.png`。同一序号在数据、图片和报告中表示同一图型合同。

## 生成与清理

- 数据和输出必须由本目录脚本生成，不手工改图中正式数值。
- 重跑可覆盖本目录由脚本生成的同名输出，但不得删除历史或目录外文件。
- 产物在用户完成视觉评审前保留；清理、归档或删除必须另行获得明确授权。
- 不提交 Origin 许可证、用户模板、本机安装路径或 MATLAB 用户配置。
