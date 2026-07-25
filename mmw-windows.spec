# -*- mode: python ; coding: utf-8 -*-

from PyInstaller.utils.hooks import collect_data_files


datas = collect_data_files("mmw") + collect_data_files("knowledge")
datas.append(("mmw/utils/moving_heat.py", "mmw/utils"))

a = Analysis(
    ["mmw/desktop.py"],
    pathex=["."],
    binaries=[],
    datas=datas,
    hiddenimports=["knowledge"],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["pytest", "_pytest"],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="MMW",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="MMW",
)
