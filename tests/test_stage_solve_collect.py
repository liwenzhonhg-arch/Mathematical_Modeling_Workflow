"""solve 阶段 JSON 产出收集测试：results.json / sensitivity.json 的收集与降级。"""

import json

from mmw.models import MetaData, StageID
from mmw.pipeline.stage_code import load_deliverables
from mmw.pipeline.stage_solve import _check_deliverables, _collect_json_output
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


def _save_analyze(mgr: CheckpointManager, sub_problems: dict) -> None:
    mgr.save(
        StageID.ANALYZE,
        {"sub_problems.json": json.dumps(sub_problems, ensure_ascii=False)},
        MetaData(stage=StageID.ANALYZE.value, version=0),
    )


def test_load_deliverables_from_analyze(tmp_path):
    mgr = CheckpointManager(tmp_path)
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
