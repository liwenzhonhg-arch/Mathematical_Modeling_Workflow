import json

from matplotlib.axes import Axes
import pandas as pd
import pytest

from mmw.agents.figure_polisher import validate_polisher_plan
from mmw.models import MetaData, StageID
from mmw.pipeline.stage_solve import rerun_figure_polish
from mmw.utils.checkpoint import CheckpointManager
from mmw.utils.figure_renderer import render_matplotlib_manifest


@pytest.mark.parametrize("kind", ["line", "scatter", "bar"])
def test_renderer_supports_core_xy_charts(tmp_path, kind):
    data = tmp_path / "data"
    figures = tmp_path / "figures"
    data.mkdir()
    pd.DataFrame({"x": [1, 2, 3], "a": [2, 3, 5], "b": [1, 4, 2]}).to_csv(
        data / "xy.csv", index=False
    )
    report = render_matplotlib_manifest(
        {
            "figures": [{
                "file": f"{kind}.png",
                "kind": kind,
                "data_file": "xy.csv",
                "x": "x",
                "y": ["a", "b"],
                "title": "测试图",
                "x_label": "时间 / h",
                "y_label": "数量 / 次",
            }]
        },
        data,
        figures,
    )
    assert report["passed"] is True
    assert (figures / f"{kind}.png").is_file()


def test_renderer_supports_heatmap(tmp_path):
    data = tmp_path / "data"
    figures = tmp_path / "figures"
    data.mkdir()
    pd.DataFrame({
        "row": ["a", "a", "b", "b"],
        "col": ["x", "y", "x", "y"],
        "value": [1, 2, 3, 4],
    }).to_csv(data / "heat.csv", index=False)
    report = render_matplotlib_manifest(
        {"figures": [{
            "file": "heat.png",
            "kind": "heatmap",
            "data_file": "heat.csv",
            "x": "col",
            "y": "row",
            "value": "value",
        }]},
        data,
        figures,
    )
    assert report["passed"] is True


def test_renderer_rejects_csv_without_columns(tmp_path):
    data = tmp_path / "data"
    figures = tmp_path / "figures"
    data.mkdir()
    (data / "empty.csv").write_text("\ufeff\n", encoding="utf-8")

    with pytest.raises(ValueError, match="没有表头或数据"):
        render_matplotlib_manifest(
            {"figures": [{
                "file": "empty.png",
                "kind": "line",
                "data_file": "empty.csv",
                "x": "x",
                "y": ["y"],
            }]},
            data,
            figures,
        )


def test_route_line_chart_keeps_vehicle_groups_separate(tmp_path, monkeypatch):
    data = tmp_path / "data"
    figures = tmp_path / "figures"
    data.mkdir()
    pd.DataFrame({
        "vehicle": [1, 1, 2, 2],
        "order": [0, 1, 0, 1],
        "node": [0, 4, 0, 7],
        "x": [0, 8, 0, 14],
        "y": [0, 10, 0, 2],
    }).to_csv(data / "routes.csv", index=False)
    calls = []
    original_plot = Axes.plot

    def record_plot(self, *args, **kwargs):
        calls.append(kwargs.get("label"))
        return original_plot(self, *args, **kwargs)

    monkeypatch.setattr(Axes, "plot", record_plot)
    render_matplotlib_manifest(
        {"figures": [{
            "file": "routes.png",
            "kind": "line",
            "data_file": "routes.csv",
            "x": "x",
            "y": "y",
        }]},
        data,
        figures,
    )

    assert calls == ["车辆 1", "车辆 2"]


def test_route_scatter_with_sequence_draws_vehicle_paths(tmp_path, monkeypatch):
    data = tmp_path / "data"
    figures = tmp_path / "figures"
    data.mkdir()
    pd.DataFrame({
        "vehicle": [1, 1, 2, 2],
        "sequence": [0, 1, 0, 1],
        "node": [0, 4, 0, 7],
        "x": [0, 8, 0, 14],
        "y": [0, 10, 0, 2],
    }).to_csv(data / "routes.csv", index=False)
    calls = []
    original_plot = Axes.plot

    def record_plot(self, *args, **kwargs):
        calls.append(kwargs.get("label"))
        return original_plot(self, *args, **kwargs)

    monkeypatch.setattr(Axes, "plot", record_plot)
    render_matplotlib_manifest(
        {"figures": [{
            "file": "routes.png",
            "kind": "scatter",
            "data_file": "routes.csv",
            "x": "x",
            "y": "y",
        }]},
        data,
        figures,
    )

    assert calls == ["车辆 1", "车辆 2"]


def test_polisher_cannot_change_data_mapping():
    original = {
        "figures": [{
            "file": "x.png",
            "kind": "line",
            "data_file": "x.csv",
            "x": "time",
            "y": ["value"],
        }]
    }
    changed = json.loads(json.dumps(original))
    changed["figures"][0]["x"] = "other"
    with pytest.raises(ValueError, match="修改了数据映射"):
        validate_polisher_plan(original, changed)


def test_polisher_can_add_series_labels():
    original = {
        "figures": [{
            "file": "x.png",
            "kind": "line",
            "data_file": "x.csv",
            "x": "time",
            "y": ["objective", "baseline"],
        }]
    }
    candidate = json.loads(json.dumps(original))
    candidate["figures"][0]["series_labels"] = ["扰动后成本", "基准成本"]

    assert validate_polisher_plan(original, candidate)["figures"][0]["series_labels"] == [
        "扰动后成本",
        "基准成本",
    ]


def test_unknown_chart_type_preserves_existing_image(tmp_path):
    data = tmp_path / "data"
    figures = tmp_path / "figures"
    data.mkdir()
    pd.DataFrame({"x": [1, 2], "y": [2, 3]}).to_csv(data / "line.csv", index=False)
    item = {
        "file": "line.png", "kind": "line", "data_file": "line.csv",
        "x": "x", "y": ["y"],
    }
    render_matplotlib_manifest({"figures": [item]}, data, figures)
    before = (figures / "line.png").read_bytes()

    report = render_matplotlib_manifest(
        {"figures": [{**item, "kind": "network"}]}, data, figures
    )

    assert report["figures"][0]["renderer"] == "original"
    assert (figures / "line.png").read_bytes() == before


def test_rerun_figure_polish_uses_latest_unapproved_solve(tmp_path, monkeypatch):
    mgr = CheckpointManager(tmp_path)
    first = {"schema_version": 1, "figures": [{"file": "first.png"}]}
    latest = {"schema_version": 1, "figures": [{"file": "latest.png"}]}
    mgr.save(
        StageID.SOLVE,
        {"figure_manifest.json": json.dumps(first)},
        MetaData(stage=StageID.SOLVE.value, version=0),
    )
    mgr.approve(StageID.SOLVE, version=1)
    mgr.save(
        StageID.SOLVE,
        {"figure_manifest.json": json.dumps(latest)},
        MetaData(stage=StageID.SOLVE.value, version=0),
    )

    def fake_polish(workspace, manifest):
        return manifest, {"passed": True}, {"model": None, "input": 0, "output": 0}

    monkeypatch.setattr("mmw.pipeline.stage_solve.polish_figure_manifest", fake_polish)
    rerun_figure_polish(tmp_path, mgr)

    artifacts = mgr.load_artifacts(StageID.SOLVE, version=3)
    assert "latest.png" in artifacts["figure_manifest.json"]
