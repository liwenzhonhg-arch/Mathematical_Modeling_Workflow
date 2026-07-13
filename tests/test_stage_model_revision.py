"""model block 自动修订：通过即停，连续 block 最多两轮。"""

import json

import mmw.pipeline.stage_model as stage_model
from mmw.models import MetaData, StageID
from mmw.utils.checkpoint import CheckpointManager


class DummyLLM:
    model = "dummy"
    total_input_tokens = 10
    total_output_tokens = 5


class DummyModeler:
    def __init__(self):
        self.revisions = 0

    def revise_model(self, current_artifacts, verify_status, verify_report):
        self.revisions += 1
        return {"model.md": f"model-v{self.revisions + 1}"}


def _verify_artifacts(severity: str) -> dict[str, str]:
    return {
        "verify_report.md": f"severity={severity}",
        "verify_status.json": json.dumps({
            "severity": severity,
            "issues": [{"category": "公式", "summary": "修正"}],
        }, ensure_ascii=False),
    }


def test_revision_stops_after_warning(tmp_path, monkeypatch):
    mgr = CheckpointManager(tmp_path)
    modeler = DummyModeler()
    sequence = iter(["block", "warning"])
    monkeypatch.setattr(
        stage_model,
        "_verify_model",
        lambda *args: (_verify_artifacts(next(sequence)), DummyLLM()),
    )

    stage_model._run_verified_versions(
        tmp_path, mgr, object(), modeler, DummyLLM(),
        "analysis", "assumptions", {"model.md": "model-v1", "params.json": "{}"},
    )

    assert mgr.get_latest_version(StageID.MODEL) == 2
    assert modeler.revisions == 1
    latest = mgr.load_artifacts(StageID.MODEL, 2)
    assert latest["model.md"] == "model-v2"
    assert latest["params.json"] == "{}"
    assert len(json.loads(latest["revision_history.json"])) == 2


def test_revision_stops_after_two_revisions(tmp_path, monkeypatch):
    mgr = CheckpointManager(tmp_path)
    modeler = DummyModeler()
    monkeypatch.setattr(
        stage_model,
        "_verify_model",
        lambda *args: (_verify_artifacts("block"), DummyLLM()),
    )

    stage_model._run_verified_versions(
        tmp_path, mgr, object(), modeler, DummyLLM(),
        "analysis", "assumptions", {"model.md": "model-v1"},
    )

    assert mgr.get_latest_version(StageID.MODEL) == 3
    assert modeler.revisions == 2
    assert json.loads(
        mgr.load_artifacts(StageID.MODEL, 3)["verify_status.json"]
    )["severity"] == "block"


def test_revision_history_can_include_blocked_source(tmp_path, monkeypatch):
    mgr = CheckpointManager(tmp_path)
    monkeypatch.setattr(
        stage_model,
        "_verify_model",
        lambda *args: (_verify_artifacts("warning"), DummyLLM()),
    )
    source = [{"round": 0, "source_version": 1, "severity": "block", "issues": []}]

    stage_model._run_verified_versions(
        tmp_path, mgr, object(), DummyModeler(), DummyLLM(),
        "analysis", "assumptions", {"model.md": "revised"},
        max_revisions=1,
        history=source,
    )

    history = json.loads(mgr.load_artifacts(StageID.MODEL, 1)["revision_history.json"])
    assert history[0]["source_version"] == 1
    assert history[-1]["severity"] == "warning"


def test_code_gate_failure_becomes_model_feedback(tmp_path):
    mgr = CheckpointManager(tmp_path)
    mgr.save(StageID.MODEL, {
        "model.md": "模型",
        "verify_status.json": '{"severity": "pass", "issues": []}',
    }, MetaData(stage=StageID.MODEL.value, version=0))
    mgr.approve(StageID.MODEL)
    mgr.save(StageID.CODE, {
        "solution.py": "print('done')",
        "run_log.txt": "未找到可行解，A_opt可能是罚函数值",
    }, MetaData(stage=StageID.CODE.value, version=0))

    feedback = stage_model._code_feedback(mgr)

    assert "罚函数值" in feedback
    assert "code v1" in feedback
