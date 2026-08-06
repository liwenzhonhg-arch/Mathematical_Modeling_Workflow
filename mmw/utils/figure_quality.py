"""共享图表规范、manifest 校验和 PNG 质量检查。"""

from __future__ import annotations

import json
import struct
from pathlib import Path
from typing import Any


STYLE_PATH = Path(__file__).parent.parent / "latex" / "templates" / "paper_style.json"


def load_paper_style() -> dict[str, Any]:
    return json.loads(STYLE_PATH.read_text(encoding="utf-8"))


def load_figure_manifest(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, list):
        data = {"schema_version": 1, "figures": data}
    figures = data.get("figures") if isinstance(data, dict) else None
    if not isinstance(figures, list):
        raise ValueError("figure_manifest.json 缺少 figures 数组")
    names: set[str] = set()
    for index, item in enumerate(figures, 1):
        if not isinstance(item, dict):
            raise ValueError(f"figure_manifest.json 第 {index} 项不是对象")
        name = item.get("file")
        if isinstance(name, str) and name.replace("\\", "/").startswith("../figures/"):
            legacy = Path(name.replace("\\", "/"))
            if legacy.parent.as_posix() == "../figures":
                name = legacy.name
                item["file"] = name
        if not isinstance(name, str) or Path(name).name != name or not name.endswith(".png"):
            raise ValueError(f"figure_manifest.json 第 {index} 项 file 非法")
        if name in names:
            raise ValueError(f"figure_manifest.json 图表重名：{name}")
        names.add(name)
    return data


def png_info(path: Path) -> dict[str, float | int | None]:
    """只读 PNG 头和 pHYs，不依赖 Pillow。"""
    with path.open("rb") as file:
        if file.read(8) != b"\x89PNG\r\n\x1a\n":
            raise ValueError("不是有效 PNG")
        width = height = 0
        dpi_x = dpi_y = None
        while True:
            raw_length = file.read(4)
            if len(raw_length) != 4:
                break
            length = struct.unpack(">I", raw_length)[0]
            kind = file.read(4)
            payload = file.read(length)
            file.read(4)
            if kind == b"IHDR" and len(payload) >= 8:
                width, height = struct.unpack(">II", payload[:8])
            elif kind == b"pHYs" and len(payload) == 9 and payload[8] == 1:
                x_ppm, y_ppm = struct.unpack(">II", payload[:8])
                dpi_x, dpi_y = x_ppm * 0.0254, y_ppm * 0.0254
            elif kind == b"IEND":
                break
    if not width or not height:
        raise ValueError("PNG 缺少 IHDR")
    return {"width": width, "height": height, "dpi_x": dpi_x, "dpi_y": dpi_y}


def inspect_figure(path: Path, style: dict[str, Any] | None = None) -> dict[str, Any]:
    limits = (style or load_paper_style())["figure"]
    failures: list[str] = []
    warnings: list[str] = []
    try:
        info = png_info(path)
    except (OSError, ValueError) as exc:
        return {"file": path.name, "passed": False, "failures": [str(exc)], "warnings": []}
    width, height = int(info["width"]), int(info["height"])
    if width < limits["width_px_min"] or height < limits["height_px_min"]:
        failures.append(f"像素不足：{width}x{height}")
    if max(width, height) / min(width, height) > limits["aspect_ratio_max"]:
        failures.append(f"宽高比异常：{width}x{height}")
    dpi_values = [value for value in (info["dpi_x"], info["dpi_y"]) if value is not None]
    if dpi_values and min(dpi_values) + 0.5 < limits["dpi_min"]:
        failures.append(f"DPI 过低：{min(dpi_values):.1f}")
    elif not dpi_values:
        warnings.append("PNG 未记录 DPI")
    return {
        "file": path.name,
        **info,
        "passed": not failures,
        "failures": failures,
        "warnings": warnings,
    }


def inspect_manifest_figures(
    figures_dir: Path,
    manifest: dict[str, Any],
    style: dict[str, Any] | None = None,
) -> dict[str, Any]:
    reports = []
    for item in manifest["figures"]:
        path = figures_dir / item["file"]
        if not path.is_file():
            reports.append({
                "file": item["file"],
                "passed": False,
                "failures": ["图表文件缺失"],
                "warnings": [],
            })
        else:
            reports.append(inspect_figure(path, style))
    return {
        "schema_version": 1,
        "passed": all(item["passed"] for item in reports),
        "figures": reports,
    }
