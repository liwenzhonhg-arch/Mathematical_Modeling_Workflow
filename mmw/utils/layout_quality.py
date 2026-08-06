"""编译后 PDF/LaTeX/图表的确定性视觉质量门禁。"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

from pypdf import PdfReader

from mmw.utils.figure_quality import inspect_manifest_figures, load_paper_style


def _page_has_image(page: Any) -> bool:
    try:
        resources = page.get("/Resources")
        if resources is None:
            return False
        resources = resources.get_object()
        xobjects = resources.get("/XObject")
        if xobjects is None:
            return False
        xobjects = xobjects.get_object()
        return any(obj.get_object().get("/Subtype") == "/Image" for obj in xobjects.values())
    except (AttributeError, KeyError, TypeError):
        return False


def _render_preview(pdf_path: Path, preview_dir: Path) -> str | None:
    preview_dir.mkdir(parents=True, exist_ok=True)
    cairo = shutil.which("pdftocairo")
    ppm = shutil.which("pdftoppm")
    if cairo:
        command = [cairo, "-png", "-r", "110", str(pdf_path), str(preview_dir / "page")]
    elif ppm:
        command = [ppm, "-png", "-r", "110", str(pdf_path), str(preview_dir / "page")]
    else:
        return "未找到 pdftocairo/pdftoppm，未生成页面预览"
    try:
        subprocess.run(command, check=True, capture_output=True, timeout=120)
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as error:
        return f"页面预览生成失败：{type(error).__name__}"
    return None


def inspect_layout(
    pdf_path: Path,
    log_path: Path | None = None,
    *,
    max_pages: int = 20,
    paper_version: int = 0,
    manifest: dict[str, Any] | None = None,
    figures_dir: Path | None = None,
    output_dir: Path | None = None,
    render_preview: bool = True,
    allow_test_placeholders: bool = False,
) -> dict[str, Any]:
    failures: list[str] = []
    warnings: list[str] = []
    pages = 0
    pdf_hash = ""
    texts: list[str] = []
    style = load_paper_style()

    if not pdf_path.is_file():
        failures.append("PDF 不存在")
    else:
        pdf_hash = hashlib.sha256(pdf_path.read_bytes()).hexdigest()
        try:
            reader = PdfReader(pdf_path)
            pages = len(reader.pages)
            for index, page in enumerate(reader.pages, 1):
                text = page.extract_text() or ""
                texts.append(text)
                clean_chars = len(re.sub(r"\s+", "", text))
                if index > 1 and not clean_chars and not _page_has_image(page):
                    failures.append(f"第 {index} 页为空白页")
                elif index > 1 and clean_chars < 20:
                    warnings.append(f"第 {index} 页文字过少")
                elif clean_chars > 4000:
                    warnings.append(f"第 {index} 页文字过密")
                width = float(page.mediabox.width)
                height = float(page.mediabox.height)
                expected = style["paper"]
                if (
                    abs(width - expected["page_width_pt"]) > expected["page_tolerance_pt"]
                    or abs(height - expected["page_height_pt"]) > expected["page_tolerance_pt"]
                ):
                    failures.append(f"第 {index} 页不是 A4 尺寸：{width:.1f}x{height:.1f}pt")
        except Exception as error:
            failures.append(f"PDF 损坏或不可读取：{type(error).__name__}")

    if pages > max_pages:
        failures.append(f"论文共 {pages} 页，超过上限 {max_pages} 页")
    all_text = "\n".join(texts)
    for placeholder in style["paper"]["forbidden_placeholders"]:
        if placeholder.casefold() in all_text.casefold():
            message = f"正文含测试占位信息：{placeholder}"
            (warnings if allow_test_placeholders else failures).append(message)

    log_text = ""
    if log_path and log_path.is_file():
        log_text = log_path.read_text(encoding="utf-8", errors="replace")
    if any(line.startswith("!") for line in log_text.splitlines()):
        failures.append("LaTeX 日志包含错误")
    if re.search(r"(undefined references|Reference .+ undefined)", log_text, re.IGNORECASE):
        failures.append("LaTeX 存在未定义引用")
    if "Missing character:" in log_text:
        failures.append("LaTeX 存在缺失字符")
    overfull = len(re.findall(r"Overfull \\hbox", log_text))
    if overfull:
        warnings.append(f"LaTeX 存在 {overfull} 处 Overfull hbox")

    figure_report: list[dict[str, Any]] = []
    if manifest is not None and figures_dir is not None:
        figure_bundle = inspect_manifest_figures(figures_dir, manifest, style)
        figure_report = figure_bundle["figures"]
        for item in figure_report:
            failures.extend(f"{item['file']}：{message}" for message in item["failures"])
            warnings.extend(f"{item['file']}：{message}" for message in item["warnings"])

    if render_preview and pdf_path.is_file() and output_dir is not None:
        preview_warning = _render_preview(pdf_path, output_dir / "layout_preview")
        if preview_warning:
            warnings.append(preview_warning)

    report = {
        "schema_version": 1,
        "passed": not failures,
        "paper_version": paper_version,
        "pdf_sha256": pdf_hash,
        "pages": pages,
        "failures": failures,
        "warnings": warnings,
        "figures": figure_report,
    }
    if output_dir is not None:
        output_dir.mkdir(parents=True, exist_ok=True)
        (output_dir / "layout_quality.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        lines = [
            "# 论文视觉质量报告",
            "",
            f"- 结论：{'通过' if report['passed'] else '阻塞'}",
            f"- 页数：{pages}/{max_pages}",
            f"- paper 版本：v{paper_version}",
            "",
            "## 失败项",
            *(f"- {item}" for item in failures),
            "",
            "## 警告",
            *(f"- {item}" for item in warnings),
        ]
        (output_dir / "layout_quality.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return report
