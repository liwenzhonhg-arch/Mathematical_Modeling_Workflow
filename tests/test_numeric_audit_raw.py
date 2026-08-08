"""数值审计 raw_output 候选集测试。"""

import hashlib
import json

from mmw.pipeline.stage_review import _bound_data_table_evidence
from mmw.utils.numeric_audit import audit_paper, extract_candidates_from_text


def test_extract_candidates_from_text():
    text = "测线 1: x = 0.0203 海里, 水深 = 21.60 m\n样本 3.2\\times 10^{4} 条"
    values = extract_candidates_from_text(text)
    assert 0.0203 in values
    assert 21.60 in values
    assert 32000.0 in values


def test_raw_output_numbers_count_as_sourced():
    sections = {"model_solution.tex": "测线 1 处水深为 21.60 m，覆盖宽度 75.01 m。"}
    # results.json 里没有这些明细，但 run_log 里有
    raw = "STDOUT:\n  测线 1: 水深 = 21.60 m, 覆盖宽度 = 75.01 m"
    report = audit_paper(sections, "[]", raw_output=raw)
    assert report.matched == 2
    assert not report.unmatched_high


def test_without_raw_output_still_flags():
    sections = {"model_solution.tex": "测线 1 处水深为 21.60 m，覆盖宽度 75.01 m。"}
    report = audit_paper(sections, "[]")
    assert len(report.unmatched_high) + len(report.unmatched_low) == 2


def test_bound_data_table_evidence_uses_only_hash_matched_current_csv(tmp_path):
    (tmp_path / ".mmw").mkdir()
    data = tmp_path / "output" / "data"
    data.mkdir(parents=True)
    current = data / "current.csv"
    current.write_text("value\n123.45\n", encoding="utf-8")
    stale = data / "stale.csv"
    stale.write_text("value\n999.0\n", encoding="utf-8")
    manifest = json.dumps({
        "current.csv": hashlib.sha256(current.read_bytes()).hexdigest(),
        "stale.csv": "0" * 64,
    })

    values = json.loads(_bound_data_table_evidence(tmp_path, manifest))

    assert 123.45 in values
    assert 999.0 not in values
