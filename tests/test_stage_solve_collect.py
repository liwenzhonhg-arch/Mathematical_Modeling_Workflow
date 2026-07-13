"""solve 阶段 JSON 产出收集测试：results.json / sensitivity.json 的收集与降级。"""

import json

from mmw.models import MetaData, StageID
from mmw.pipeline.stage_code import load_deliverables
from mmw.pipeline.stage_solve import (
    _check_deliverables,
    _cleanup_temp_script,
    _collect_changed_figures,
    _collect_json_output,
    _file_signature,
)
from mmw.utils.checkpoint import CheckpointManager


def test_collect_valid_json(tmp_path):
    p = tmp_path / "results.json"
    p.write_text('[{"name": "q1_最优值", "value": 1.5, "unit": ""}]', encoding="utf-8")
    out = _collect_json_output(p, default="[]", missing_msg="缺失")
    assert '"q1_最优值"' in out


def test_collect_missing_file_returns_default(tmp_path):
    out = _collect_json_output(tmp_path / "nope.json", default="[]", missing_msg="缺失")
    assert out == "[]"


def test_collect_invalid_json_returns_default(tmp_path):
    p = tmp_path / "sensitivity.json"
    p.write_text("{broken json", encoding="utf-8")
    out = _collect_json_output(p, default="{}", missing_msg="缺失")
    assert out == "{}"


def test_collect_unchanged_json_rejects_stale_output(tmp_path):
    path = tmp_path / "results.json"
    path.write_text('[{"name": "old", "value": 1}]', encoding="utf-8")
    previous = _file_signature(path)

    out = _collect_json_output(path, default="[]", missing_msg="缺失", previous=previous)

    assert out == "[]"


def _save_analyze(mgr: CheckpointManager, sub_problems: dict) -> None:
    mgr.save(
        StageID.ANALYZE,
        {"sub_problems.json": json.dumps(sub_problems, ensure_ascii=False)},
        MetaData(stage=StageID.ANALYZE.value, version=0),
    )


def test_load_deliverables_from_analyze(tmp_path):
    mgr = CheckpointManager(tmp_path)
    (tmp_path / "problem.md").write_text(
        "请提交 result1.xlsx 和 result2.xlsx。", encoding="utf-8"
    )
    _save_analyze(mgr, {
        "sub_problems": [],
        "deliverables": [
            {"file": "result1.xlsx", "desc": "问题1结果"},
            {"file": "result2.xlsx", "desc": "问题2结果"},
            {"desc": "缺 file 字段的脏数据应被过滤"},
        ],
    })
    files = [d["file"] for d in load_deliverables(mgr)]
    assert files == ["result1.xlsx", "result2.xlsx"]


def test_load_deliverables_missing_or_broken(tmp_path):
    mgr = CheckpointManager(tmp_path)
    assert load_deliverables(mgr) == []  # 无 analyze 检查点
    _save_analyze(mgr, {"sub_problems": []})
    assert load_deliverables(mgr) == []  # 无 deliverables 键


def test_check_deliverables_reports_missing(tmp_path):
    mgr = CheckpointManager(tmp_path)
    (tmp_path / "problem.md").write_text(
        "要求生成 result1.xlsx、result2.xlsx。", encoding="utf-8"
    )
    _save_analyze(mgr, {
        "sub_problems": [],
        "deliverables": [
            {"file": "result1.xlsx", "desc": "已生成"},
            {"file": "result2.xlsx", "desc": "未生成"},
        ],
    })
    (tmp_path / "result1.xlsx").write_bytes(b"fake xlsx")
    missing = _check_deliverables(tmp_path, mgr)
    assert missing == ["result2.xlsx"]


def test_check_deliverables_empty_list_noop(tmp_path):
    mgr = CheckpointManager(tmp_path)
    assert _check_deliverables(tmp_path, mgr) == []


def test_check_deliverables_rejects_unchanged_old_file(tmp_path):
    mgr = CheckpointManager(tmp_path)
    (tmp_path / "problem.md").write_text("要求 result1.xlsx。", encoding="utf-8")
    _save_analyze(mgr, {
        "sub_problems": [],
        "deliverables": [{"file": "result1.xlsx", "desc": "结果"}],
    })
    path = tmp_path / "result1.xlsx"
    path.write_bytes(b"old")

    assert _check_deliverables(
        tmp_path, mgr, previous={"result1.xlsx": _file_signature(path)}
    ) == ["result1.xlsx"]


def test_collect_changed_figures_excludes_old_files(tmp_path):
    old = tmp_path / "old.png"
    old.write_bytes(b"old")
    previous = {"old.png": _file_signature(old)}
    (tmp_path / "new.png").write_bytes(b"new")

    assert _collect_changed_figures(tmp_path, previous) == ["new.png"]


def test_load_deliverables_ignores_names_without_problem_evidence(tmp_path):
    mgr = CheckpointManager(tmp_path)
    (tmp_path / "problem.md").write_text("只要求 problem1.xlsx。", encoding="utf-8")
    _save_analyze(mgr, {
        "sub_problems": [],
        "deliverables": [
            {"file": "problem1.xlsx", "desc": "题面明确要求"},
            {"file": "result2.xlsx", "desc": "模型幻觉"},
            {"file": "../problem1.xlsx", "desc": "非法路径"},
        ],
    })

    assert [d["file"] for d in load_deliverables(mgr)] == ["problem1.xlsx"]


def test_cleanup_temp_script_ignores_permission_error(tmp_path, monkeypatch):
    script = tmp_path / "solution.py"
    script.write_text("print('ok')", encoding="utf-8")

    def raise_permission_error(*args, **kwargs):
        raise PermissionError("locked")

    monkeypatch.setattr(type(script), "unlink", raise_permission_error)
    _cleanup_temp_script(script)
