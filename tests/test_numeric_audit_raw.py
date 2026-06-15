"""数值审计 raw_output 候选集测试。"""

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
