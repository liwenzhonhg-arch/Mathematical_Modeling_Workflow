"""题目文件夹扫描、初始化和新旧项目路径兼容。"""

from __future__ import annotations

import hashlib
import json
import os
import re
import xml.etree.ElementTree as ET
import zipfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from mmw.models import CompetitionConfig
from mmw.utils.file_io import read_json, write_json, write_yaml


IGNORED_DIRS = {".git", ".mmw", "output", "__pycache__", "node_modules"}
PROBLEM_SUFFIXES = {".pdf", ".docx"}
DATA_SUFFIXES = {
    ".csv", ".xlsx", ".xls", ".json", ".txt", ".tsv", ".mat", ".zip",
    ".png", ".jpg", ".jpeg",
}


@dataclass(frozen=True)
class ProjectPaths:
    root: Path

    @property
    def internal(self) -> Path:
        return self.root / ".mmw" if (self.root / ".mmw").exists() else self.root

    @property
    def modern(self) -> bool:
        return self.internal.name == ".mmw"

    @property
    def config(self) -> Path:
        return self.internal / "config.yaml"

    @property
    def problem(self) -> Path:
        return self.internal / "problem.md"

    @property
    def manifest(self) -> Path:
        return self.internal / "input_manifest.json"

    @property
    def checkpoints(self) -> Path:
        return self.internal / "checkpoints"

    @property
    def logs(self) -> Path:
        return self.internal / "logs"

    @property
    def cache(self) -> Path:
        return self.internal / "cache" if self.modern else self.root

    @property
    def output(self) -> Path:
        return self.root / "output"

    @property
    def figures(self) -> Path:
        return self.output / "figures" if self.modern else self.root / "figures"

    @property
    def result_data(self) -> Path:
        return self.output / "data" if self.modern else self.root

    def data_files(self) -> list[Path]:
        if self.modern and self.manifest.is_file():
            try:
                entries = read_json(self.manifest).get("attachments", [])
            except (OSError, ValueError):
                return []
            files = []
            for entry in entries:
                relative = str(entry.get("path", ""))
                path = (self.root / relative).resolve()
                if relative and path.is_relative_to(self.root.resolve()) and path.is_file():
                    files.append(path)
            return sorted(files)
        raw = self.root / "data" / "raw"
        return sorted(path for path in raw.iterdir() if path.is_file()) if raw.is_dir() else []

    def relative(self, path: Path) -> str:
        return path.resolve().relative_to(self.root.resolve()).as_posix()

    def deliverable(self, name: str) -> Path:
        return self.result_data / name if self.modern else self.root / name


def scan_project(root: Path) -> dict[str, Any]:
    """只读扫描题目文件夹，不创建任何运行文件。"""
    root = root.resolve()
    if not root.is_dir():
        raise ValueError("所选路径不是文件夹")
    if str(root).startswith("\\\\"):
        raise ValueError("首版只支持本机文件夹，不支持网络路径")

    files = [
        path for path in root.rglob("*")
        if path.is_file()
        and path.resolve().is_relative_to(root)
        and not any(part.casefold() in IGNORED_DIRS for part in path.relative_to(root).parts[:-1])
        and not path.name.startswith(".")
    ]
    problem_files = [path for path in files if path.suffix.casefold() in PROBLEM_SUFFIXES]
    legacy_docs = [path for path in files if path.suffix.casefold() == ".doc"]
    attachments = [path for path in files if path.suffix.casefold() in DATA_SUFFIXES]
    paths = ProjectPaths(root)
    managed = paths.config.is_file()
    selected_problem = ""
    if managed and paths.manifest.is_file():
        try:
            manifest = read_json(paths.manifest)
            selected_problem = str(manifest.get("problem_file") or manifest.get("problem_pdf", ""))
        except (OSError, ValueError):
            pass
    return {
        "name": root.name,
        "path": str(root),
        "writable": os.access(root, os.W_OK),
        "initialized": managed,
        "legacy": managed and not paths.modern,
        "problem_file": selected_problem,
        "problem_files": [_file_info(root, path) for path in sorted(problem_files)],
        "problem_pdf": selected_problem,
        "pdfs": [_file_info(root, path) for path in sorted(problem_files) if path.suffix.casefold() == ".pdf"],
        "attachments": [_file_info(root, path) for path in sorted(attachments)],
        "ready": managed or (len(problem_files) == 1 and os.access(root, os.W_OK)),
        "blocked_reason": (
            "" if managed or len(problem_files) == 1
            else "检测到旧版 .doc，请用 Word 另存为 .docx" if legacy_docs and not problem_files
            else "未找到 PDF 或 DOCX 题目文件" if not problem_files
            else "检测到多个题目文件，请选择主问题文件"
        ),
    }


def initialize_project(root: Path, problem_file: str) -> ProjectPaths:
    """提取题目后创建 `.mmw/`；提取失败时不写入项目。"""
    root = root.resolve()
    scan = scan_project(root)
    if scan["initialized"]:
        return ProjectPaths(root)
    candidates = {item["path"] for item in scan["problem_files"]}
    if problem_file not in candidates:
        raise ValueError("请选择扫描结果中的主问题文件")
    problem_path = (root / problem_file).resolve()
    if not problem_path.is_relative_to(root) or not problem_path.is_file():
        raise ValueError("题目文件路径非法")
    if problem_path.stat().st_size > 100 * 1024 * 1024:
        raise ValueError("题目文件超过 100 MB，拒绝读取")

    problem_text = extract_problem_text(problem_path)
    if len(re.sub(r"\s+", "", problem_text)) < 200:
        raise ValueError("题目文件可提取文字过少，暂时无法可靠读取")

    year_match = re.search(r"20\d{2}", f"{root.name} {problem_path.name}")
    problem_match = re.search(r"(?<![A-Za-z])([ABC])(?:题)?(?![A-Za-z])", f"{root.name} {problem_path.stem}", re.I)
    config = CompetitionConfig(
        name=root.name,
        year=int(year_match.group()) if year_match else datetime.now().year,
        problem=problem_match.group(1).upper() if problem_match else "",
        title=root.name,
    ).model_dump()
    config["problem_file"] = problem_file
    config["problem_pdf"] = problem_file
    config["created_at"] = datetime.now().isoformat(timespec="seconds")

    attachments = []
    for item in scan["attachments"]:
        path = root / item["path"]
        attachments.append({
            **item,
            "sha256": _sha256_file(path),
        })
    manifest = {
        "problem_file": problem_file,
        "problem_pdf": problem_file,
        "problem_sha256": _sha256_file(problem_path),
        "attachments": attachments,
    }

    paths = ProjectPaths(root)
    (root / ".mmw" / "checkpoints").mkdir(parents=True)
    (root / ".mmw" / "logs").mkdir()
    (root / ".mmw" / "cache").mkdir()
    (root / "output" / "code").mkdir(parents=True, exist_ok=True)
    (root / "output" / "data").mkdir(exist_ok=True)
    (root / "output" / "figures").mkdir(exist_ok=True)
    write_yaml(paths.config, config)
    write_json(paths.manifest, manifest)
    paths.problem.write_text(problem_text, encoding="utf-8")
    return paths


def extract_problem_text(path: Path) -> str:
    suffix = path.suffix.casefold()
    if suffix == ".pdf":
        return extract_pdf_text(path)
    if suffix == ".docx":
        return extract_docx_text(path)
    raise ValueError(f"不支持的题目文件格式：{suffix or '无扩展名'}")


def extract_pdf_text(path: Path) -> str:
    """提取带文本层 PDF，并保留页码边界。"""
    try:
        from pypdf import PdfReader
    except ImportError as exc:
        raise RuntimeError("缺少 pypdf，无法读取题目 PDF") from exc
    try:
        reader = PdfReader(path)
        pages = [
            f"<!-- page:{index} -->\n\n{text.strip()}"
            for index, page in enumerate(reader.pages, start=1)
            if (text := (page.extract_text() or "")).strip()
        ]
    except Exception as exc:
        raise ValueError(f"PDF 读取失败：{exc.__class__.__name__}") from exc
    return f"# {path.stem}\n\n" + "\n\n---\n\n".join(pages) + "\n"


def extract_docx_text(path: Path) -> str:
    """使用标准库只读提取 DOCX 正文、表格和定位图形文字。"""
    namespace = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
    paragraph_tag = f"{{{namespace}}}p"
    text_tags = {
        f"{{{namespace}}}t",
        "{http://schemas.openxmlformats.org/officeDocument/2006/math}t",
    }
    break_tags = {f"{{{namespace}}}br", f"{{{namespace}}}cr"}
    tab_tag = f"{{{namespace}}}tab"
    shape_tag = "{urn:schemas-microsoft-com:vml}shape"
    page_break_tag = f"{{{namespace}}}lastRenderedPageBreak"
    try:
        with zipfile.ZipFile(path) as archive:
            info = archive.getinfo("word/document.xml")
            if info.file_size > 20 * 1024 * 1024:
                raise ValueError("DOCX 正文超过 20 MB，拒绝解压")
            document = ET.fromstring(archive.read(info))
    except ValueError:
        raise
    except (KeyError, OSError, zipfile.BadZipFile, ET.ParseError) as exc:
        raise ValueError(f"Word 读取失败：{exc.__class__.__name__}") from exc

    paragraphs = []
    for paragraph in document.iter(paragraph_tag):
        parts = []
        for node in paragraph.iter():
            if node.tag in text_tags and node.text:
                parts.append(node.text)
            elif node.tag == tab_tag:
                parts.append("\t")
            elif node.tag in break_tags:
                parts.append("\n")
        text = "".join(parts).strip()
        if text:
            paragraphs.append(text)

    positioned = []
    page = 1
    for node in document.iter():
        if node.tag == page_break_tag or (
            node.tag == f"{{{namespace}}}br" and node.get(f"{{{namespace}}}type") == "page"
        ):
            page += 1
        if node.tag != shape_tag:
            continue
        style = node.get("style", "")
        left_match = re.search(r"(?:^|;)\s*left\s*:\s*(-?\d+(?:\.\d+)?)", style)
        top_match = re.search(r"(?:^|;)\s*top\s*:\s*(-?\d+(?:\.\d+)?)", style)
        text = "".join(
            child.text or "" for child in node.iter() if child.tag in text_tags
        ).strip()
        if text and left_match and top_match:
            positioned.append((page, float(top_match.group(1)), float(left_match.group(1)), text))

    result = f"# {path.stem}\n\n" + "\n\n".join(paragraphs) + "\n"
    if positioned:
        lines = ["", "## 图形定位文本", "", "以下文本来自带绝对位置的题图标注，坐标仅用于恢复相对顺序："]
        for item_page, top, left, text in sorted(positioned):
            lines.append(f"- page={item_page}, top={top:g}, left={left:g}: {text}")
        result += "\n".join(lines) + "\n"
    return result


def _file_info(root: Path, path: Path) -> dict[str, Any]:
    return {
        "name": path.name,
        "path": path.relative_to(root).as_posix(),
        "size": path.stat().st_size,
        "type": path.suffix.casefold().lstrip("."),
    }


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
