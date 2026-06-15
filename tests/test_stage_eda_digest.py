"""EDA 数据结构摘要测试：pandas 真实读取，防 LLM 编造数据结构。"""

import pandas as pd

from mmw.pipeline.stage_eda import _file_digest, _scan_data_files


def test_csv_digest_reflects_real_structure(tmp_path):
    p = tmp_path / "data.csv"
    pd.DataFrame({"深度": [70.0, 71.5], "坡度": [1.5, None]}).to_csv(p, index=False)
    digest = _file_digest(p)
    assert "2 行 × 2 列" in digest
    assert "深度" in digest
    assert "坡度: 1" in digest  # 缺失值计数


def test_xlsx_digest_lists_all_sheets(tmp_path):
    p = tmp_path / "data.xlsx"
    with pd.ExcelWriter(p) as w:
        pd.DataFrame({"a": [1]}).to_excel(w, sheet_name="表单1", index=False)
        pd.DataFrame({"b": [1, 2]}).to_excel(w, sheet_name="表单2", index=False)
    digest = _file_digest(p)
    assert "共 2 个表单" in digest
    assert "表单1" in digest and "表单2" in digest
    assert "2 行 × 1 列" in digest


def test_scan_includes_digest_as_preview(tmp_path):
    raw = tmp_path / "data" / "raw"
    raw.mkdir(parents=True)
    pd.DataFrame({"x": [1, 2, 3]}).to_csv(raw / "d.csv", index=False)
    files = _scan_data_files(tmp_path)
    assert len(files) == 1
    assert "3 行 × 1 列" in files[0]["preview"]


def test_unsupported_suffix_no_preview(tmp_path):
    raw = tmp_path / "data" / "raw"
    raw.mkdir(parents=True)
    (raw / "blob.bin").write_bytes(b"\x00\x01")
    files = _scan_data_files(tmp_path)
    assert files[0]["preview"] is None
