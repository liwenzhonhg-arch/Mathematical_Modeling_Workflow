"""LaTeX 编译器：xelatex 编译 + 错误解析 + main.tex 组装。"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path

from mmw.utils.display import print_error, print_info, print_success

MAIN_TEX_TEMPLATE = r"""\documentclass[withoutpreface,bwprint]{cumcmthesis}

\usepackage{amsmath,amssymb}
\usepackage{graphicx}
\graphicspath{{figures/}{./}}
\usepackage{booktabs}
\usepackage{float}
\usepackage{subcaption}
\usepackage{url}
\usepackage{listings}

\title{%(title)s}
\author{参赛队号：%(team_number)s\quad 题号：%(problem)s}
\date{}

\begin{document}

\maketitle

%(abstract_content)s

\clearpage

%(body_content)s

\bibliographystyle{plain}
\bibliography{references}

\end{document}
"""

UNSAFE_TEX_RE = re.compile(
    r"\\(?:input|include|openin|openout|write|immediate|verbatiminput|usepackage|documentclass)\b"
)


def find_unsafe_tex(paper_dir: Path) -> list[str]:
    """拒绝章节从编译目录外读取文件或改写编译环境。"""
    issues: list[str] = []
    for path in paper_dir.rglob("*"):
        if not path.is_file() or path.suffix not in {".tex", ".bib"}:
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        if UNSAFE_TEX_RE.search(text):
            issues.append(path.relative_to(paper_dir).as_posix())
        for match in re.finditer(r"\\lstinputlisting(?:\[[^\]]*\])?\{([^{}]+)\}", text):
            if match.group(1).replace("\\", "/") != "solution.py":
                issues.append(path.relative_to(paper_dir).as_posix())
    return sorted(set(issues))


def _escape_latex_text(text: str) -> str:
    """转义普通文本进入 LaTeX 命令参数时的特殊字符。"""
    replacements = {
        "\\": r"\textbackslash{}",
        "&": r"\&",
        "%": r"\%",
        "$": r"\$",
        "#": r"\#",
        "_": r"\_",
        "{": r"\{",
        "}": r"\}",
        "~": r"\textasciitilde{}",
        "^": r"\textasciicircum{}",
    }
    return "".join(replacements.get(ch, ch) for ch in text)


def assemble_main_tex(
    paper_dir: Path,
    title: str = "题目",
    team_number: str = "",
    problem: str = "A",
    workspace: Path | None = None,
) -> str:
    """从分节文件组装 main.tex 内容。"""
    sections_dir = paper_dir / "sections"

    section_order = [
        "abstract.tex",
        "problem_restatement.tex",
        "assumptions.tex",
        "symbols.tex",
        "model_solution.tex",
        "sensitivity.tex",
        "evaluation.tex",
        "appendix.tex",
    ]

    abstract_content = ""
    body_parts: list[str] = []

    for sec_name in section_order:
        candidates = [sections_dir / sec_name, paper_dir / sec_name]
        sec_path = next((p for p in candidates if p.exists()), None)
        if sec_path is None:
            continue

        content = sec_path.read_text(encoding="utf-8").strip()
        if sec_name == "abstract.tex":
            abstract_content = content
        else:
            body_parts.append(content)

    body_content = "\n\n".join(body_parts)

    return MAIN_TEX_TEMPLATE % {
        "title": _escape_latex_text(title),
        "team_number": _escape_latex_text(team_number),
        "problem": _escape_latex_text(problem),
        "abstract_content": abstract_content,
        "body_content": body_content,
    }


def compile_latex(
    work_dir: Path,
    main_tex: str = "main.tex",
    engine: str = "xelatex",
    runs: int = 2,
    max_pages: int | None = None,
) -> tuple[bool, str]:
    """编译 LaTeX 文档。返回 (成功与否, 错误/信息消息)。"""
    if not re.match(r'^[\w\-. ]+\.tex$', main_tex):
        return False, f"非法的 tex 文件名: {main_tex}"

    if not shutil.which(engine):
        return False, f"未找到 {engine}，请安装 TeX Live 或 MiKTeX"

    tex_path = (work_dir / main_tex).resolve()
    if not str(tex_path).startswith(str(work_dir.resolve())):
        return False, f"路径越界: {main_tex}"
    if not tex_path.exists():
        return False, f"未找到 {tex_path}"

    env = {**os.environ, "TEXINPUTS": f".{os.pathsep}{work_dir}{os.pathsep}"}

    pdf_path = work_dir / main_tex.replace(".tex", ".pdf")
    pdf_path.unlink(missing_ok=True)

    def _run_xelatex(label: str):
        print_info(label)
        try:
            return subprocess.run(
                [engine, "-interaction=nonstopmode", main_tex],
                cwd=str(work_dir),
                capture_output=True,
                text=True,
                timeout=120,
                encoding="utf-8",
                errors="replace",
                env=env,
            )
        except subprocess.TimeoutExpired:
            return None
        except FileNotFoundError:
            return None

    proc = _run_xelatex("编译第 1 轮...")
    if proc is None:
        return False, f"{engine} 不存在或编译超时"
    if proc.returncode != 0:
        return False, _format_compile_failure(proc.stderr, work_dir, main_tex)

    bib_path = work_dir / "references.bib"
    if bib_path.exists():
        aux_name = main_tex.replace(".tex", "")
        aux_path = work_dir / f"{aux_name}.aux"
        aux_text = aux_path.read_text(encoding="utf-8", errors="replace") if aux_path.exists() else ""
        if "\\citation" not in aux_text:
            return False, "论文存在 references.bib，但正文没有任何 \\cite 引用"
        bib_proc = subprocess.run(
            ["bibtex", aux_name],
            cwd=str(work_dir),
            capture_output=True,
            text=True,
            timeout=30,
            encoding="utf-8",
            errors="replace",
        )
        if bib_proc.returncode != 0:
            return False, "bibtex 执行失败，请检查 references.bib 和引用键"

    for i in range(1, runs + 1):
        proc = _run_xelatex(f"解析引用第 {i}/{runs} 轮...")
        if proc is None or proc.returncode != 0:
            return False, f"{engine} 最终编译失败"

    pdf_name = main_tex.replace(".tex", ".pdf")
    if pdf_path.exists() and _pdf_is_valid(pdf_path):
        log_path = work_dir / main_tex.replace(".tex", ".log")
        errors = []
        if log_path.exists():
            log_text = log_path.read_text(encoding="utf-8", errors="replace")
            errors = [l.strip() for l in log_text.splitlines() if l.startswith("!")]
            page_match = re.search(r"Output written on .*?\((\d+) pages?", log_text)
            if max_pages is not None and page_match and int(page_match.group(1)) > max_pages:
                return False, f"论文共 {page_match.group(1)} 页，超过配置上限 {max_pages} 页"
        msg = str(pdf_path)
        if errors:
            msg += f"\n编译有 {len(errors)} 个错误（PDF 已生成但可能有排版问题）"
        return True, msg
    if pdf_path.exists():
        return False, f"PDF 文件损坏（无 EOF 标记，xelatex 中途失败）: {pdf_path}，请查看 .log"
    return False, "编译完成但未生成 PDF 文件"


def _format_compile_failure(stderr: str, work_dir: Path, main_tex: str) -> str:
    log_path = work_dir / main_tex.replace(".tex", ".log")
    if log_path.exists():
        return "；".join(_extract_errors(log_path.read_text(encoding="utf-8", errors="replace"))[:5])
    return stderr[-1000:] or "LaTeX 编译失败"


def _pdf_is_valid(pdf_path: Path) -> bool:
    """校验 PDF 完整性：尾部必须有 %%EOF 标记（xelatex 崩溃会留下截断文件）。"""
    try:
        with open(pdf_path, "rb") as f:
            f.seek(max(0, pdf_path.stat().st_size - 1024))
            return b"%%EOF" in f.read()
    except OSError:
        return False


def _extract_errors(log_text: str) -> list[str]:
    """从 LaTeX 日志中提取错误信息。"""
    errors: list[str] = []
    for line in log_text.splitlines():
        if line.startswith("!") or "Error" in line or "Fatal" in line:
            errors.append(line.strip())
    if not errors:
        errors.append("未知编译错误，请查看完整日志")
    return errors


def prepare_compile_dir(
    workspace: Path, paper_version_dir: Path, build_key: str | None = None
) -> Path:
    """准备编译目录：复制模板和章节文件到 output/。"""
    compile_dir = workspace / "output" / "latex_build"
    if build_key:
        compile_dir /= build_key
    compile_dir.mkdir(parents=True, exist_ok=True)

    # 复制模板文件
    template_dir = Path(__file__).parent / "templates" / "cumcm"
    if template_dir.exists():
        for f in template_dir.iterdir():
            if f.is_file():
                shutil.copy2(f, compile_dir / f.name)

    # 复制章节文件（展平到编译目录）
    sections_dir = paper_version_dir / "sections"
    src_dir = sections_dir if sections_dir.exists() else paper_version_dir
    for f in src_dir.iterdir():
        if f.is_file() and f.suffix == ".tex":
            shutil.copy2(f, compile_dir / f.name)

    # 复制 references.bib
    bib_src = paper_version_dir / "references.bib"
    if bib_src.exists():
        shutil.copy2(bib_src, compile_dir / "references.bib")

    code_src = paper_version_dir / "solution.py"
    if code_src.exists():
        shutil.copy2(code_src, compile_dir / "solution.py")

    # 复制图表
    figures_src = workspace / "figures"
    if figures_src.exists():
        figures_dst = compile_dir / "figures"
        figures_dst.mkdir(exist_ok=True)
        for src in figures_src.iterdir():
            if not src.is_file():
                continue
            dst = figures_dst / src.name
            if dst.exists() and dst.stat().st_size == src.stat().st_size:
                continue
            shutil.copy2(src, dst)

    return compile_dir
