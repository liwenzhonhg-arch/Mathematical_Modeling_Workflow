"""export 门禁：审批与硬交付物必须在创建 zip 前通过。"""

import json
import hashlib
import zipfile

import pytest
import typer

import mmw.cli as cli
from mmw.models import MetaData, StageID
from mmw.pipeline.state_machine import PipelineStateMachine
from mmw.utils.checkpoint import CheckpointManager


def _meta(stage: StageID) -> MetaData:
    return MetaData(stage=stage.value, version=0)


def _ready_manager(tmp_path, with_deliverable: bool = False) -> CheckpointManager:
    mgr = CheckpointManager(tmp_path)
    (tmp_path / "problem.md").write_text("请提交 problem1.xlsx。", encoding="utf-8")
    (tmp_path / "output").mkdir()
    (tmp_path / "output" / "paper.pdf").write_bytes(b"pdf")
    if with_deliverable:
        (tmp_path / "problem1.xlsx").write_bytes(b"xlsx")
    deliverables_manifest = (
        {"problem1.xlsx": hashlib.sha256(b"xlsx").hexdigest()}
        if with_deliverable else {}
    )
    mgr.save(StageID.ANALYZE, {
        "sub_problems.json": json.dumps({
            "sub_problems": [],
            "deliverables": [{"file": "problem1.xlsx", "desc": "温度分布"}],
        }, ensure_ascii=False),
    }, _meta(StageID.ANALYZE))
    stages = {
        StageID.CODE: {
            "solution.py": "print('ok')",
            "run_log.txt": "STDOUT:\nok",
        },
        StageID.SOLVE: {
            "run_log.txt": "STDOUT:\nok",
            "results.json": '[{"name": "q1", "value": 1, "unit": "", "desc": "结果"}]',
            "sensitivity.json": '{"baseline": {"objective": 1}, "experiments": [{"param": "a", "delta_pct": -10, "objective": 0.9, "change_pct": -10}, {"param": "b", "delta_pct": 10, "objective": 2, "change_pct": 100}]}',
            "deliverables_manifest.json": json.dumps(deliverables_manifest),
        },
        StageID.PAPER: {
            "sections/abstract.tex": "摘要",
            "sections/problem_restatement.tex": "问题重述",
            "sections/assumptions.tex": "假设",
            "sections/symbols.tex": "符号",
            "sections/model_solution.tex": "模型",
            "sections/sensitivity.tex": "灵敏度",
            "sections/evaluation.tex": "评价",
            "abstract_score.json": '{"score": 90, "needs_upstream_data": false}',
        },
        StageID.REVIEW: {
            "checklist.json": '{"items": [{"check": "ok", "status": "pass"}]}',
        },
    }
    for stage, artifacts in stages.items():
        mgr.save(stage, artifacts, _meta(stage))
        mgr.approve(stage)
    versions = {
        stage.value: mgr.get_active_version(stage)
        for stage in (StageID.CODE, StageID.SOLVE, StageID.PAPER, StageID.REVIEW)
    }
    (tmp_path / "output" / "paper_manifest.json").write_text(json.dumps({
        "versions": versions,
        "pdf_sha256": hashlib.sha256(b"pdf").hexdigest(),
    }), encoding="utf-8")
    return mgr


def test_export_missing_deliverable_exits_before_creating_zip(tmp_path, monkeypatch):
    mgr = _ready_manager(tmp_path)
    sm = PipelineStateMachine(mgr)
    monkeypatch.setattr(cli, "_get_mgr", lambda workspace: (mgr, sm))

    with pytest.raises(typer.Exit) as exc:
        cli.export_submission(workspace="test")

    assert exc.value.exit_code == 1
    assert not (tmp_path / "output" / "submission.zip").exists()


def test_export_complete_submission_creates_zip(tmp_path, monkeypatch):
    mgr = _ready_manager(tmp_path, with_deliverable=True)
    sm = PipelineStateMachine(mgr)
    monkeypatch.setattr(cli, "_get_mgr", lambda workspace: (mgr, sm))

    cli.export_submission(workspace="test")

    with zipfile.ZipFile(tmp_path / "output" / "submission.zip") as archive:
        assert set(archive.namelist()) == {
            "paper.pdf", "code/solution.py", "problem1.xlsx",
        }
