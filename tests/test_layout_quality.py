from pypdf import PdfWriter

from mmw.utils.layout_quality import inspect_layout


def _blank_pdf(path, pages=1):
    writer = PdfWriter()
    for _ in range(pages):
        writer.add_blank_page(width=595, height=842)
    with path.open("wb") as handle:
        writer.write(handle)


def test_layout_gate_detects_blank_body_page_and_log_failures(tmp_path):
    pdf = tmp_path / "paper.pdf"
    log = tmp_path / "main.log"
    _blank_pdf(pdf, 2)
    log.write_text("Missing character: x\nOverfull \\hbox\n", encoding="utf-8")

    report = inspect_layout(pdf, log, render_preview=False)

    assert not report["passed"]
    assert any("第 2 页为空白页" in item for item in report["failures"])
    assert any("缺失字符" in item for item in report["failures"])
    assert any("Overfull" in item for item in report["warnings"])


def test_layout_gate_detects_page_limit_and_damaged_pdf(tmp_path):
    pdf = tmp_path / "paper.pdf"
    _blank_pdf(pdf, 2)
    assert not inspect_layout(pdf, max_pages=1, render_preview=False)["passed"]
    pdf.write_bytes(b"not a pdf")
    assert any("损坏" in item for item in inspect_layout(pdf, render_preview=False)["failures"])


def test_layout_report_is_bound_to_pdf_and_version(tmp_path):
    pdf = tmp_path / "paper.pdf"
    _blank_pdf(pdf)
    report = inspect_layout(
        pdf,
        paper_version=3,
        output_dir=tmp_path / "output",
        render_preview=False,
    )
    assert report["paper_version"] == 3
    assert report["pdf_sha256"]
    assert (tmp_path / "output" / "layout_quality.json").is_file()


def test_layout_gate_detects_missing_manifest_figure(tmp_path):
    pdf = tmp_path / "paper.pdf"
    _blank_pdf(pdf)
    report = inspect_layout(
        pdf,
        manifest={"figures": [{"file": "missing.png"}]},
        figures_dir=tmp_path,
        render_preview=False,
    )
    assert any("图表文件缺失" in item for item in report["failures"])


def test_layout_gate_can_warn_instead_of_blocking_test_placeholders(tmp_path, monkeypatch):
    pdf = tmp_path / "paper.pdf"
    _blank_pdf(pdf)
    monkeypatch.setattr(
        "mmw.utils.layout_quality.PdfReader",
        lambda path: type("Reader", (), {"pages": [
            type("Page", (), {
                "extract_text": lambda self: "mmw-test TEST-RUN",
                "mediabox": type("Box", (), {"width": 595, "height": 842})(),
            })()
        ]})(),
    )

    report = inspect_layout(pdf, allow_test_placeholders=True, render_preview=False)

    assert report["passed"] is True
    assert len([item for item in report["warnings"] if "测试占位" in item]) == 2
