"""code 阶段门禁：缺少 solution.py 时不能保存 completed 检查点。"""

import json
from pathlib import Path

import mmw.pipeline.stage_code as stage_code
from mmw.models import MetaData, StageID
from mmw.pipeline.stage_code import (
    _has_solution_py,
    _review_feedback,
    _runtime_summary,
    _solve_feedback,
    run_code,
)
from mmw.utils.checkpoint import CheckpointManager


def test_has_solution_py_requires_non_empty_code():
    assert _has_solution_py({"solution.py": "print('ok')"}) is True
    assert _has_solution_py({"solution.py": "   \n"}) is False
    assert _has_solution_py({"code_explanation.md": "只有解释"}) is False


class DummyMgr:
    workspace = Path(".")
    saved = False

    def get_latest_version(self, stage):
        return 0

    def load_artifacts(self, stage):
        if stage == StageID.MODEL:
            return {"model.md": "模型"}
        if stage == StageID.EDA:
            return {"data_summary.md": "数据摘要"}
        if stage == StageID.ANALYZE:
            return {"sub_problems.json": "{}"}
        return {}

    def save(self, *args, **kwargs):
        self.saved = True
        raise AssertionError("缺少 solution.py 时不应保存检查点")


class DummySettings:
    def get_llm_config(self, role):
        class Config:
            api_key = "dummy"
        return Config()


class DummyLLM:
    model = "dummy"
    total_input_tokens = 0
    total_output_tokens = 0

    def __init__(self, *args, **kwargs):
        pass


class DummyCoder:
    def __init__(self, llm):
        pass

    def implement_with_retry(self, **kwargs):
        return {"code_explanation.md": "没有代码"}, None


def test_run_code_refuses_to_save_without_solution(monkeypatch):
    mgr = DummyMgr()
    workspace = Path(".")
    mgr.workspace = workspace

    monkeypatch.setattr(stage_code, "get_settings", lambda: DummySettings())
    monkeypatch.setattr(stage_code, "LLMClient", DummyLLM)
    monkeypatch.setattr(stage_code, "CoderAgent", DummyCoder)

    run_code(workspace, mgr)

    assert mgr.saved is False


def test_runtime_summary_contains_installed_versions():
    summary = _runtime_summary()
    assert "Python " in summary
    assert "numpy " in summary


def test_failed_review_becomes_code_feedback(tmp_path):
    mgr = CheckpointManager(tmp_path)
    mgr.save(StageID.CODE, {
        "solution.py": "print('ok')", "run_log.txt": "STDOUT:\nok",
    }, MetaData(stage=StageID.CODE.value, version=0))
    mgr.approve(StageID.CODE)
    mgr.save(StageID.REVIEW, {
        "review.md": "h_skin 灵敏度边界不一致",
        "checklist.json": json.dumps({
            "rework_stage": "code",
            "items": [{"check": "数值", "status": "fail"}]
        }, ensure_ascii=False),
    }, MetaData(stage=StageID.REVIEW.value, version=0))

    feedback = _review_feedback(mgr)

    assert "h_skin" in feedback
    assert "review v1" in feedback


def test_failed_solve_from_latest_code_becomes_code_feedback(tmp_path):
    mgr = CheckpointManager(tmp_path)
    mgr.save(StageID.CODE, {
        "solution.py": "print('ok')", "run_log.txt": "STDOUT:\nok",
    }, MetaData(stage=StageID.CODE.value, version=0))
    mgr.approve(StageID.CODE)
    mgr.save(StageID.SOLVE, {
        "run_log.txt": "STDOUT:\nok",
        "results.json": json.dumps([
            {"name": "q1_value", "value": 1.0, "unit": "", "desc": "结果"},
        ]),
        "sensitivity.json": json.dumps({
            "baseline": {"objective": 1.0},
            "experiments": [
                {"param": "alpha", "delta_pct": -10, "T_max": 0.9, "change_pct": -10},
                {"param": "beta", "delta_pct": 10, "T_max": 1.1, "change_pct": 10},
            ],
        }),
    }, MetaData(stage=StageID.SOLVE.value, version=0))

    feedback = _solve_feedback(mgr)

    assert "objective 必须是有限数值" in feedback
    assert '"T_max"' in feedback
    assert "solve v1" in feedback


def test_paper_upstream_data_gap_becomes_code_feedback(tmp_path):
    mgr = CheckpointManager(tmp_path)
    mgr.save(StageID.CODE, {
        "solution.py": "print('ok')", "run_log.txt": "STDOUT:\nok",
    }, MetaData(stage=StageID.CODE.value, version=0))
    mgr.approve(StageID.CODE)
    mgr.save(StageID.PAPER, {
        "abstract_score.json": json.dumps({
            "score": 60,
            "needs_upstream_data": True,
            "issues": ["q2 缺少量化验证指标"],
            "suggestions": ["补充代理验证结果"],
        }, ensure_ascii=False),
    }, MetaData(stage=StageID.PAPER.value, version=0))

    feedback = stage_code._paper_feedback(mgr)

    assert "q2 缺少量化验证指标" in feedback
    assert "paper v1" in feedback
