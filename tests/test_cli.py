import json

from typer.testing import CliRunner

from mmw import cli
from mmw.models import MetaData, StageID
from mmw.pipeline.state_machine import PipelineStateMachine
from mmw.utils.checkpoint import CheckpointManager


def test_cli_historical_activation_reports_and_records_stale_version(tmp_path, monkeypatch):
    mgr = CheckpointManager(tmp_path)
    for stage in (StageID.ANALYZE, StageID.EDA):
        mgr.save(stage, {"artifact.txt": stage.value}, MetaData(stage=stage.value, version=0))
        mgr.approve(stage)
    mgr.save(StageID.ANALYZE, {"artifact.txt": "new"}, MetaData(stage="analyze", version=0))
    mgr.approve(StageID.ANALYZE)
    monkeypatch.setattr(cli, "_get_mgr", lambda _workspace=None: (mgr, PipelineStateMachine(mgr)))

    result = CliRunner().invoke(cli.app, ["approve", "eda", "--version", "1"])

    assert result.exit_code == 0
    assert "上游已变更" in result.stdout
    decision = json.loads((tmp_path / "decisions.jsonl").read_text("utf-8"))
    assert decision["action"] == "activate"
    assert decision["actor"] == "human-cli"
    assert decision["stale"] is True
