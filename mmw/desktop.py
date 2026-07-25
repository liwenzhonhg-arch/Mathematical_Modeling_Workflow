"""Windows 便携版入口：双击启动 GUI，内部子进程仍可复用 CLI。"""

from __future__ import annotations

import os
import runpy
import sys
from pathlib import Path


def runtime_dir() -> Path:
    """源码运行沿用当前目录；冻结版把配置放到用户目录。"""
    if getattr(sys, "frozen", False):
        return Path(os.environ.get("APPDATA") or Path.home()) / "MMW"
    return Path.cwd()


def _dispatch_embedded_script() -> bool:
    args = sys.argv[1:]
    if args[:1] != ["--mmw-run-script"]:
        return False
    if len(args) != 3:
        raise ValueError("无效的内部脚本执行参数")
    work_dir, script = Path(args[1]).resolve(), Path(args[2]).resolve()
    if not script.is_file() or script.suffix != ".py" or not script.is_relative_to(work_dir):
        raise ValueError("内部脚本必须是工作目录内的 Python 文件")
    os.chdir(work_dir)
    sys.path.insert(0, str(work_dir))
    runpy.run_path(str(script), run_name="__main__")
    return True


def main() -> None:
    if _dispatch_embedded_script():
        return

    root = runtime_dir().resolve()
    root.mkdir(parents=True, exist_ok=True)
    os.chdir(root)

    if sys.argv[1:3] == ["-m", "mmw.cli"]:
        del sys.argv[1:3]
        from mmw.cli import main as cli_main

        cli_main()
        return

    from mmw.gui.server import serve_gui

    serve_gui(env_path=root / ".env")


if __name__ == "__main__":
    main()
