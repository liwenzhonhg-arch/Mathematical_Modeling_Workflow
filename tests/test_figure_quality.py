import json
import struct
import zlib

import pytest

from mmw.utils.figure_quality import (
    inspect_figure,
    inspect_manifest_figures,
    load_figure_manifest,
)


def _png(path, width=1200, height=700, dpi=300):
    def chunk(kind, payload):
        return (
            struct.pack(">I", len(payload))
            + kind
            + payload
            + struct.pack(">I", zlib.crc32(kind + payload))
        )

    ppm = round(dpi / 0.0254)
    path.write_bytes(
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
        + chunk(b"pHYs", struct.pack(">IIB", ppm, ppm, 1))
        + chunk(b"IEND", b"")
    )


def test_manifest_rejects_paths_and_duplicates(tmp_path):
    path = tmp_path / "manifest.json"
    path.write_text(
        json.dumps({"figures": [{"file": "../x.png"}, {"file": "../x.png"}]}),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="file 非法"):
        load_figure_manifest(path)


def test_manifest_normalizes_legacy_list_and_figures_prefix(tmp_path):
    path = tmp_path / "manifest.json"
    path.write_text(
        json.dumps([{"file": "../figures/route.png"}]),
        encoding="utf-8",
    )

    assert load_figure_manifest(path) == {
        "schema_version": 1,
        "figures": [{"file": "route.png"}],
    }


def test_figure_quality_checks_pixels_dpi_and_aspect_ratio(tmp_path):
    good = tmp_path / "good.png"
    bad = tmp_path / "bad.png"
    _png(good)
    _png(bad, width=400, height=2000, dpi=96)

    assert inspect_figure(good)["passed"] is True
    report = inspect_figure(bad)
    assert report["passed"] is False
    assert any("像素不足" in item for item in report["failures"])
    assert any("宽高比异常" in item for item in report["failures"])
    assert any("DPI 过低" in item for item in report["failures"])


def test_manifest_report_marks_missing_figure(tmp_path):
    report = inspect_manifest_figures(
        tmp_path,
        {"figures": [{"file": "missing.png"}]},
    )
    assert report["passed"] is False
    assert report["figures"][0]["failures"] == ["图表文件缺失"]
