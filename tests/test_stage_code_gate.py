"""code 阶段门禁：缺少 solution.py 时不能保存 completed 检查点。"""

import json
from pathlib import Path
from types import SimpleNamespace

import mmw.pipeline.stage_code as stage_code
from mmw.models import MetaData, StageID
from mmw.pipeline.state_machine import PipelineStateMachine
from mmw.pipeline.stage_code import (
    _candidate_quality_error,
    _code_uses_active_model,
    _file_signature,
    _has_solution_py,
    _load_newer_recovery,
    _review_feedback,
    _save_recovery,
    _runtime_summary,
    _solve_feedback,
    run_code,
)
from mmw.utils.moving_heat import assess_multistart_identifiability
from mmw.utils.checkpoint import CheckpointManager


def test_has_solution_py_requires_non_empty_code():
    assert _has_solution_py({"solution.py": "print('ok')"}) is True
    assert _has_solution_py({"solution.py": "   \n"}) is False
    assert _has_solution_py({"code_explanation.md": "只有解释"}) is False


def test_moving_heat_candidate_requires_identifiability_status(tmp_path):
    path = tmp_path / "results.json"
    report_path = tmp_path / "identifiability.json"
    result = SimpleNamespace(stdout="ok", stderr="")
    common = {"unit": "", "desc": "多起点诊断"}
    report_path.write_text(json.dumps(assess_multistart_identifiability(
        [[1.0], [1.01], [0.99]],
        [1.0, 1.0, 1.0],
        initial_parameter_sets=[[0.5], [1.5], [2.5]],
        outcome_sets=[[100.0], [101.0], [99.5]],
    )), encoding="utf-8")
    report_args = {
        "identifiability_path": report_path,
        "identifiability_before": None,
    }

    path.write_text(json.dumps([
        {"name": "q1_拟合误差", "value": 1.0, **common},
    ], ensure_ascii=False), encoding="utf-8")
    assert "缺少参数可辨识性" in _candidate_quality_error(
        result, path, None, require_identifiability=True, **report_args,
    )

    path.write_text(json.dumps([
        {"name": "q1_参数可辨识性", "value": 0, **common},
    ], ensure_ascii=False), encoding="utf-8")
    assert "未通过参数可辨识性" in _candidate_quality_error(
        result, path, None, require_identifiability=True, **report_args,
    )

    path.write_text(json.dumps([
        {"name": "q1_参数可辨识性", "value": 1, **common},
    ], ensure_ascii=False), encoding="utf-8")
    assert _candidate_quality_error(
        result, path, None, require_identifiability=True, **report_args,
    ) == ""

    valid_report = json.loads(report_path.read_text(encoding="utf-8"))
    report_path.write_text(json.dumps({"diagnostic": valid_report}), encoding="utf-8")
    assert "schema_version" in _candidate_quality_error(
        result, path, None, require_identifiability=True, **report_args,
    )

    report_path.write_text(json.dumps(valid_report), encoding="utf-8")
    report_path.write_text(json.dumps({
        **json.loads(report_path.read_text(encoding="utf-8")),
        "parameter_relative_spans": [0.5],
    }), encoding="utf-8")
    assert "不一致" in _candidate_quality_error(
        result, path, None, require_identifiability=True, **report_args,
    )


def test_candidate_requires_result_for_each_numeric_subproblem(tmp_path):
    path = tmp_path / "results.json"
    path.write_text(json.dumps([
        {"name": "q1_value", "value": 1, "unit": "", "desc": "ok"},
    ]), encoding="utf-8")
    result = SimpleNamespace(stdout="ok", stderr="")

    error = _candidate_quality_error(
        result,
        path,
        None,
        sub_problems=[
            {"id": "q1", "title": "建立模型并预测"},
            {"id": "q2", "title": "优化方案"},
            {"id": "q_model", "title": "建立评价方法"},
        ],
    )

    assert error == "results.json 缺少子问题结果: q2"


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


def test_run_code_keeps_oracle_out_and_saves_only_fresh_results(tmp_path, monkeypatch):
    sentinel = "SECRET_ORACLE_RANGE"
    references = tmp_path / "references"
    references.mkdir()
    (references / "reference_expected.json").write_text(sentinel, encoding="utf-8")

    class CapturingMgr(DummyMgr):
        def __init__(self):
            self.workspace = tmp_path
            self.artifacts = None

        def save(self, stage, artifacts, meta):
            self.artifacts = artifacts
            return tmp_path / "checkpoints" / "code" / "v1"

    captured = {}

    class FreshCoder:
        def __init__(self, llm):
            pass

        def implement_with_retry(self, **kwargs):
            captured.update(kwargs)
            (kwargs["work_dir"] / "results.json").write_text('[{"name":"q1","value":1}]', encoding="utf-8")
            return {"solution.py": "print('ok')"}, SimpleNamespace(
                success=True, stdout="ok", stderr="", error_summary="",
            )

    mgr = CapturingMgr()
    monkeypatch.setattr(stage_code, "get_settings", lambda: DummySettings())
    monkeypatch.setattr(stage_code, "LLMClient", DummyLLM)
    monkeypatch.setattr(stage_code, "CoderAgent", FreshCoder)

    run_code(tmp_path, mgr)

    assert sentinel not in json.dumps(captured, ensure_ascii=False, default=str)
    assert "reference_contract.json" not in mgr.artifacts
    assert json.loads(mgr.artifacts["results_preview.json"])[0]["value"] == 1


def test_run_code_does_not_snapshot_old_results(tmp_path, monkeypatch):
    (tmp_path / "results.json").write_text('[{"name":"old","value":1}]', encoding="utf-8")

    class CapturingMgr(DummyMgr):
        def __init__(self):
            self.workspace = tmp_path
            self.artifacts = None

        def save(self, stage, artifacts, meta):
            self.artifacts = artifacts
            return tmp_path / "checkpoints" / "code" / "v1"

    class NoRewriteCoder:
        def __init__(self, llm):
            pass

        def implement_with_retry(self, **kwargs):
            return {"solution.py": "print('ok')"}, SimpleNamespace(
                success=True, stdout="ok", stderr="", error_summary="",
            )

    mgr = CapturingMgr()
    monkeypatch.setattr(stage_code, "get_settings", lambda: DummySettings())
    monkeypatch.setattr(stage_code, "LLMClient", DummyLLM)
    monkeypatch.setattr(stage_code, "CoderAgent", NoRewriteCoder)

    run_code(tmp_path, mgr)

    assert "results_preview.json" not in mgr.artifacts


def test_run_code_preserves_failed_stdout(tmp_path, monkeypatch):
    class CapturingMgr(DummyMgr):
        def __init__(self):
            self.workspace = tmp_path
            self.artifacts = None

        def save(self, stage, artifacts, meta):
            self.artifacts = artifacts
            return tmp_path / "checkpoints" / "code" / "v1"

    class FailedCoder:
        def __init__(self, llm):
            pass

        def implement_with_retry(self, **kwargs):
            return {"solution.py": "raise RuntimeError"}, SimpleNamespace(
                success=False,
                stdout="R2=0.76, peak=230.7",
                stderr="RuntimeError: 无可行解",
                error_summary="RuntimeError: 无可行解",
            )

    mgr = CapturingMgr()
    monkeypatch.setattr(stage_code, "get_settings", lambda: DummySettings())
    monkeypatch.setattr(stage_code, "LLMClient", DummyLLM)
    monkeypatch.setattr(stage_code, "CoderAgent", FailedCoder)

    run_code(tmp_path, mgr)

    assert "R2=0.76" in mgr.artifacts["run_log.txt"]


def test_run_code_records_normalized_model_rework_request(tmp_path, monkeypatch):
    class CapturingMgr(DummyMgr):
        def __init__(self):
            self.workspace = tmp_path
            self.artifacts = None

        def save(self, stage, artifacts, meta):
            self.artifacts = artifacts
            return tmp_path / "checkpoints" / "code" / "v1"

    class FailedCoder:
        def __init__(self, llm):
            pass

        def implement_with_retry(self, **kwargs):
            return {"solution.py": "raise RuntimeError"}, SimpleNamespace(
                success=False,
                stdout="diagnostic",
                stderr="",
                error_summary=(
                    "RuntimeError: MODEL_REWORK_REQUIRED: provider raw details"
                ),
            )

    mgr = CapturingMgr()
    monkeypatch.setattr(stage_code, "get_settings", lambda: DummySettings())
    monkeypatch.setattr(stage_code, "LLMClient", DummyLLM)
    monkeypatch.setattr(stage_code, "CoderAgent", FailedCoder)

    run_code(tmp_path, mgr)

    request = json.loads(mgr.artifacts["rework_request.json"])
    assert request["target"] == "model"
    assert "provider raw details" not in request["reason"]


def test_newer_recovery_precedes_failed_checkpoint(tmp_path):
    mgr = CheckpointManager(tmp_path)
    mgr.save(
        StageID.MODEL,
        {"model.md": "model"},
        MetaData(stage=StageID.MODEL.value, version=0),
    )
    mgr.approve(StageID.MODEL)
    checkpoint = mgr.save(
        StageID.CODE,
        {"solution.py": "print('checkpoint')"},
        MetaData(stage=StageID.CODE.value, version=0),
    )
    _save_recovery(mgr, "print('recovery')")

    assert _load_newer_recovery(mgr, 1) == "print('recovery')"

    solution = checkpoint / "solution.py"
    solution.touch()
    assert _load_newer_recovery(mgr, 1) == ""


def test_code_model_rework_request_precedes_secondary_gate_errors(tmp_path):
    mgr = CheckpointManager(tmp_path)
    mgr.save(StageID.CODE, {
        "solution.py": "raise RuntimeError",
        "run_log.txt": "[执行失败]",
        "rework_request.json": json.dumps({
            "schema_version": 1,
            "target": "model",
            "reason": "normalized",
        }),
    }, MetaData(stage=StageID.CODE.value, version=0))

    assert PipelineStateMachine(mgr).quality_error(StageID.CODE, 1).startswith(
        "代码实证要求重做 model"
    )


def test_runtime_summary_contains_installed_versions():
    summary = _runtime_summary()
    assert "Python " in summary
    assert "numpy " in summary
    assert "MovingSlabConfig(thickness, grid_points" in summary
    assert "返回值仅为一维中心温度 ndarray" in summary
    assert "只有 scheme='explicit' 才检查 config.diffusion_number <= 0.5" in summary
    assert "隐式格式不得被显式扩散数条件阻断" in summary
    assert "原始返回对象直接、无包装地写入" in summary
    assert "Robin 系数 gamma=h/lambda" in summary
    assert "speed/60（cm/s）" in summary


def test_file_signature_changes_when_results_are_rewritten(tmp_path):
    results = tmp_path / "results.json"
    assert _file_signature(results) is None
    results.write_text("[]", encoding="utf-8")
    before = _file_signature(results)
    results.write_text("[1]", encoding="utf-8")
    assert _file_signature(results) != before


def test_failed_code_is_not_reused_after_active_model_changes(tmp_path):
    mgr = CheckpointManager(tmp_path)
    mgr.save(
        StageID.MODEL,
        {"model.md": "v1"},
        MetaData(stage=StageID.MODEL.value, version=0),
    )
    mgr.approve(StageID.MODEL)
    mgr.save(
        StageID.CODE,
        {"solution.py": "print('v1')", "run_log.txt": "[执行失败]"},
        MetaData(stage=StageID.CODE.value, version=0),
    )

    assert _code_uses_active_model(mgr, 1)

    mgr.save(
        StageID.MODEL,
        {"model.md": "v2"},
        MetaData(stage=StageID.MODEL.value, version=0),
    )
    mgr.approve(StageID.MODEL, version=2)

    assert not _code_uses_active_model(mgr, 1)


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
    assert "不得新增题目、场景或参数" in feedback
    assert "q3/q4" not in feedback
    assert "两车道" not in feedback


def test_latest_gui_rework_reason_becomes_code_feedback(tmp_path):
    mgr = CheckpointManager(tmp_path)
    mgr.save(
        StageID.CODE,
        {"solution.py": "print('ok')"},
        MetaData(stage=StageID.CODE.value, version=0),
    )
    decisions = tmp_path / "decisions.jsonl"
    decisions.write_text(
        "\n".join([
            json.dumps({
                "stage": "code",
                "version": 1,
                "action": "approve",
                "reason": "旧审批理由",
            }, ensure_ascii=False),
            "{broken",
            json.dumps({
                "stage": "code",
                "version": 1,
                "action": "rework",
                "reason": "删除虚构的问题四",
            }, ensure_ascii=False),
        ]),
        encoding="utf-8",
    )

    assert mgr.latest_rework_reason(StageID.CODE, 1) == "删除虚构的问题四"
