import pandas as pd

from mmw.utils import origin_renderer


def _manifest() -> dict:
    return {
        "figures": [{
            "file": "trend.png",
            "kind": "line",
            "data_file": "trend.csv",
            "x": "x",
            "y": ["y"],
            "x_label": "时间",
            "y_label": "数值",
        }]
    }


def test_origin_unavailable_falls_back_without_changing_csv(tmp_path, monkeypatch):
    csv_path = tmp_path / "trend.csv"
    pd.DataFrame({"x": [1, 2], "y": [2, 3]}).to_csv(csv_path, index=False)
    before = csv_path.read_bytes()
    monkeypatch.setattr(
        origin_renderer,
        "origin_status",
        lambda: {"available": False, "executable": None, "originpro_version": None, "reason": "缺失"},
    )

    report = origin_renderer.render_origin_manifest(_manifest(), tmp_path, tmp_path / "figures")

    assert report["renderer"] == "matplotlib"
    assert report["figures"][0]["fallback_reason"] == "缺失"
    assert csv_path.read_bytes() == before
    assert (tmp_path / "figures" / "trend.png").is_file()


def test_safe_label_removes_labtalk_separators():
    assert origin_renderer._safe_label("标题; {exit}\n下一行") == "标题 exit下一行"
