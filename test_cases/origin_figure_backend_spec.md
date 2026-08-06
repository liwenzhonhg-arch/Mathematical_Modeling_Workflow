# Origin 2024 可选绘图后端 Spec

状态：已实现并通过本机 Origin 2024 SR1 隐藏启动、CSV 导入、PNG 导出实测

## 定位

Origin 是 Windows 本机可选后端。Matplotlib 始终是开源版默认后端；未安装、
未授权或调用失败时必须明确回退，不能阻塞求解结果。

## 本机基线

- 已安装 Origin 2024 SR1。
- Automation Server 已注册；安装路径只在运行时从注册表读取，不写入仓库。
- 外部 Python 通过官方 `originpro` 包调用 Origin Automation Server。

## 接口

- 配置值：`figure_backend: matplotlib | origin`，默认 `matplotlib`。
- 后端消费与 FigurePolisher 相同的 manifest 和 CSV。
- 输出相同文件名的 PNG。首版不附加矢量图，避免同时维护未被论文装配消费的冗余产物。
- 输出 `renderer.json`，记录实际后端、Origin 版本和回退原因。

## 安全与兼容

- 不把 Origin 安装路径写入项目或提交；运行时从注册表/标准位置发现。
- 不把许可证、用户模板和 Origin 项目文件打进发行包。
- 只允许项目目录内的 CSV 输入和图表输出。
- Origin 调用异常时在 `finally` 中关闭本次实例；GUI 后台任务沿用现有超时与失败状态。
- Linux/macOS 或无 Origin 的 Windows 直接使用 Matplotlib。

## 首版范围

只验证折线、散点和柱状图。热力图首版继续使用 Matplotlib，避免同时维护
两套复杂模板。

## 验收

- 本机能隐藏启动 Origin、导入 CSV、套用模板并导出一张 PNG。
- Origin 不可用测试必须回退且不修改原始数据。
- 公共测试不要求安装 Origin。
