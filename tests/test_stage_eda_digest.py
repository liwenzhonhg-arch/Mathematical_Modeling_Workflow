"""EDA 数据结构摘要测试：pandas 真实读取，防 LLM 编造数据结构。"""

import pandas as pd

import mmw.pipeline.stage_eda as stage_eda
from mmw.pipeline.stage_eda import _file_digest, _read_delimited, _scan_data_files, _trend_note


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


def test_gbk_csv_digest_is_detected(tmp_path):
    path = tmp_path / "result.csv"
    path.write_text("时间,温度\n0,25\n", encoding="gbk")

    frame, encoding = _read_delimited(path, sep=",")

    assert encoding == "gb18030"
    assert list(frame.columns) == ["时间", "温度"]


def test_xlsx_digest_warns_about_merged_cells(tmp_path):
    from openpyxl import Workbook

    path = tmp_path / "merged.xlsx"
    book = Workbook()
    sheet = book.active
    sheet.append(["组别", "值"])
    sheet.append(["A", 1])
    sheet.append([None, 2])
    sheet.merge_cells("A2:A3")
    book.save(path)

    assert "分组标识列必须先前向填充" in _file_digest(path)


def test_trend_series_recommends_difference_not_raw_iqr():
    frame = pd.DataFrame({"时间(s)": range(20), "温度": range(30, 50)})

    note = _trend_note(frame)

    assert "一阶差分" in note
    assert "禁止用原始值全局 IQR" in note


def test_data_eda_without_generated_code_does_not_save_checkpoint(tmp_path, monkeypatch):
    raw = tmp_path / "data" / "raw"
    raw.mkdir(parents=True)
    pd.DataFrame({"x": [1]}).to_csv(raw / "d.csv", index=False)

    class Manager:
        def load_artifacts(self, stage):
            return {"analysis.md": "分析"}

        def save(self, *args, **kwargs):
            raise AssertionError("EDA 失败时不应保存检查点")

    class Settings:
        def get_llm_config(self, role):
            return type("Config", (), {"api_key": "dummy"})()

    class Agent:
        def __init__(self, llm):
            pass

        def generate_code(self, *args, **kwargs):
            return ""

    monkeypatch.setattr(stage_eda, "get_settings", lambda: Settings())
    monkeypatch.setattr(stage_eda, "LLMClient", lambda *args, **kwargs: object())
    monkeypatch.setattr(stage_eda, "EDAAgent", Agent)

    stage_eda.run_eda(tmp_path, Manager())


def test_docx_embedded_markdown_tables_are_not_reported_as_no_data(tmp_path):
    internal = tmp_path / ".mmw"
    internal.mkdir()
    (internal / "problem.md").write_text(
        "# A题\n\n| 地区 | 需求 |\n| --- | --- |\n| 1 | 28 |\n| 2 | 15 |\n",
        encoding="utf-8",
    )
    saved = {}

    class Manager:
        def save(self, stage, artifacts, meta):
            saved.update(artifacts)

    stage_eda.run_eda(tmp_path, Manager())

    assert "题面内嵌表格" in saved["data_summary.md"]
    assert "2 行 × 2 列" in saved["data_summary.md"]
    assert "本题未附带数据文件，无需 EDA" not in saved["data_summary.md"]
