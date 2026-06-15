"""数值一致性审计：论文 .tex 中的数值必须能在求解产出中找到出处。

纯代码实现，零 LLM 调用。防止 LLM 写论文时编造数字。
"""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass, field


@dataclass
class ExtractedNumber:
    """从论文中提取的一个数值。"""

    value: float
    raw: str  # 原始文本形式，用于推断精度
    source_file: str
    context: str  # 前后各 30 字符


@dataclass
class AuditReport:
    """审计报告。"""

    unmatched_high: list[ExtractedNumber] = field(default_factory=list)  # 高置信缺出处
    unmatched_low: list[ExtractedNumber] = field(default_factory=list)  # 低置信可疑
    scaled: list[ExtractedNumber] = field(default_factory=list)  # 缩放匹配（单位换算）
    matched: int = 0
    ignored: int = 0
    total: int = 0


# ── TeX 清洗 ──────────────────────────────────────────────

_TEX_NOISE_PATTERNS = [
    re.compile(r"(?<!\\)%.*$", re.MULTILINE),  # 行注释
    re.compile(r"\\(?:ref|eqref|cite|label|pageref)\{[^}]*\}"),
    re.compile(r"\\includegraphics(?:\[[^\]]*\])?\{[^}]*\}"),
    re.compile(r"\\(?:begin|end)\{[^}]*\}(?:\{[^}]*\})?(?:\[[^\]]*\])?"),
    re.compile(r"\\(?:documentclass|usepackage|bibliographystyle|bibliography)(?:\[[^\]]*\])?\{[^}]*\}"),
]


def strip_tex_noise(tex: str) -> str:
    """删除不应参与数值提取的 LaTeX 结构（引用、注释、环境参数等）。"""
    for pat in _TEX_NOISE_PATTERNS:
        tex = pat.sub(" ", tex)
    return tex


# ── 数值提取 ──────────────────────────────────────────────

# 科学计数：3.2 \times 10^{4} / 3.2\times10^4
_SCI_RE = re.compile(r"(\d+(?:\.\d+)?)\s*\\times\s*10\^\{?(-?\d+)\}?")

# 普通数字：千分位 / 小数（含 e 记法）/ 整数
_NUM_RE = re.compile(
    r"[-+]?\d{1,3}(?:,\d{3})+(?:\.\d+)?"  # 1,234,567.89
    r"|[-+]?\d+\.\d+(?:[eE][-+]?\d+)?"     # 12.34 / 1.2e-3
    r"|[-+]?\d+"                            # 整数
)

# 紧邻这些字符的数字是编号而非数值结果
_LABEL_CHARS = "第图表式章节问题"

# 疑似章节号：1.2 / 3.1.4（各段都很小）
_SECTION_RE = re.compile(r"^\d{1,2}\.\d{1,2}(\.\d{1,2})?$")


def _is_ignorable(raw: str, value: float, text: str, start: int, end: int) -> bool:
    """判断数字是否应忽略（编号、年份、小整数等）。"""
    # 小整数（公式系数、序号）
    if "." not in raw and "," not in raw and abs(value) <= 10:
        return True
    # 年份
    if "." not in raw and 1900 <= value <= 2100:
        return True
    # 紧邻"第/图/表/式/章/节/问题"（前后 2 字符内）
    before = text[max(0, start - 2):start]
    after = text[end:end + 2]
    if any(c in _LABEL_CHARS for c in before + after):
        return True
    # 疑似章节号：仅当出现在行首（"3.1 模型建立"），避免误伤"误差为 3.2"这类正文数值
    at_line_start = start == 0 or text[start - 1] == "\n"
    if at_line_start and _SECTION_RE.match(raw) and all(int(p) <= 30 for p in raw.split(".")):
        return True
    return False


def extract_numbers(tex: str, source_file: str) -> tuple[list[ExtractedNumber], int]:
    """从清洗后的 TeX 文本提取待审计数值。返回 (数值列表, 忽略数)。"""
    text = strip_tex_noise(tex)
    numbers: list[ExtractedNumber] = []
    ignored = 0

    # 先提取科学计数（并从文本中移除，避免底数被普通正则重复提取）
    def _sci_sub(m: re.Match) -> str:
        nonlocal numbers
        value = float(m.group(1)) * (10 ** int(m.group(2)))
        ctx_start = max(0, m.start() - 30)
        numbers.append(ExtractedNumber(
            value=value, raw=m.group(0), source_file=source_file,
            context=text[ctx_start:m.end() + 30].replace("\n", " "),
        ))
        return " "

    cleaned = _SCI_RE.sub(_sci_sub, text)

    for m in _NUM_RE.finditer(cleaned):
        raw = m.group(0).lstrip("+-")
        value = float(raw.replace(",", ""))
        if _is_ignorable(raw, value, cleaned, m.start(), m.end()):
            ignored += 1
            continue
        ctx_start = max(0, m.start() - 30)
        numbers.append(ExtractedNumber(
            value=value, raw=raw, source_file=source_file,
            context=cleaned[ctx_start:m.end() + 30].replace("\n", " "),
        ))
    return numbers, ignored


# ── 匹配 ──────────────────────────────────────────────────

_SCALES = (100, 0.01, 1e4, 1e-4, 1e8, 1e-8)


def _decimal_places(raw: str) -> int:
    if "." in raw:
        return len(raw.split(".")[1].rstrip())
    return 0


def _sig_figs(raw: str) -> int:
    digits = raw.replace(",", "").replace(".", "").lstrip("0")
    return len(digits) if digits else 1


def _direct_match(raw: str, p: float, r: float) -> bool:
    """单候选直接匹配：相对误差 / 小数位舍入 / 有效数字舍入。"""
    if math.isclose(p, r, rel_tol=1e-3, abs_tol=1e-12):
        return True
    # 小数位舍入：1234.56 → 1234.6
    if round(r, _decimal_places(raw)) == p:
        return True
    # 有效数字舍入
    sig = _sig_figs(raw)
    if r != 0:
        try:
            if float(f"%.{sig}g" % r) == p:
                return True
        except (ValueError, OverflowError):
            pass
    return False


def value_matches(raw: str, value: float, candidates: list[float]) -> str:
    """返回 'exact'（直接匹配）/'scaled'（缩放匹配）/''（不匹配）。

    匹配忽略符号：论文行文常用"减少 43.75%"（正数）表述数据中的 -43.75。
    """
    abs_value = abs(value)
    for r in candidates:
        if _direct_match(raw, abs_value, abs(r)):
            return "exact"
    for r in candidates:
        for scale in _SCALES:
            if _direct_match(raw, abs_value, abs(r) * scale):
                return "scaled"
    return ""


# ── 候选集构建 ────────────────────────────────────────────

def _collect_candidate_values(obj) -> list[float]:
    """递归收集 JSON 结构中的所有数值。"""
    values: list[float] = []
    if isinstance(obj, bool):
        return values
    if isinstance(obj, (int, float)):
        values.append(float(obj))
    elif isinstance(obj, dict):
        for v in obj.values():
            values.extend(_collect_candidate_values(v))
    elif isinstance(obj, list):
        for v in obj:
            values.extend(_collect_candidate_values(v))
    elif isinstance(obj, str):
        # params.json 的 value 可能是字符串形式的数字
        try:
            values.append(float(obj))
        except ValueError:
            pass
    return values


def build_candidates(*json_texts: str) -> list[float]:
    """从若干 JSON 文本构建数值候选集，非法 JSON 跳过。"""
    values: list[float] = []
    for text in json_texts:
        if not text:
            continue
        try:
            values.extend(_collect_candidate_values(json.loads(text)))
        except json.JSONDecodeError:
            continue
    return values


def extract_candidates_from_text(text: str) -> list[float]:
    """从自由文本（如求解 stdout 日志）中提取数值作为候选。

    论文中的明细数字（逐测线表格等）往往来自求解程序的打印输出而非
    results.json 摘要，这些是真实数值，应计入出处。
    """
    values: list[float] = []
    for m in _SCI_RE.finditer(text):
        values.append(float(m.group(1)) * (10 ** int(m.group(2))))
    for m in _NUM_RE.finditer(text):
        values.append(float(m.group(0).replace(",", "")))
    return values


# ── 审计入口 ──────────────────────────────────────────────

def _is_high_confidence(num: ExtractedNumber) -> bool:
    return _sig_figs(num.raw) >= 3 or abs(num.value) >= 1000


def audit_paper(
    sections: dict[str, str],
    results_json: str,
    sensitivity_json: str = "",
    params_json: str = "",
    raw_output: str = "",
) -> AuditReport:
    """审计论文所有章节的数值出处。

    raw_output: 求解程序的原始输出（run_log/interpretation），其中的数值
    也算合法出处——论文明细表格常引用 stdout 打印的逐项数值。
    """
    candidates = build_candidates(results_json, sensitivity_json, params_json)
    if raw_output:
        candidates.extend(extract_candidates_from_text(raw_output))
    report = AuditReport()

    for name, content in sections.items():
        numbers, ignored = extract_numbers(content, name)
        report.ignored += ignored
        for num in numbers:
            report.total += 1
            kind = value_matches(num.raw, num.value, candidates)
            if kind == "exact":
                report.matched += 1
            elif kind == "scaled":
                report.scaled.append(num)
            elif _is_high_confidence(num):
                report.unmatched_high.append(num)
            else:
                report.unmatched_low.append(num)
    return report


def render_audit_md(report: AuditReport) -> str:
    """渲染审计报告为 Markdown。"""
    lines = [
        "# 数值一致性审计报告",
        "",
        "程序化比对论文数值与求解产出（results.json / sensitivity.json / params.json）。",
        "",
        f"统计：共提取 {report.total} 个数值，匹配 {report.matched} 个，"
        f"缩放匹配 {len(report.scaled)} 个，高置信缺出处 {len(report.unmatched_high)} 个，"
        f"低置信可疑 {len(report.unmatched_low)} 个，忽略 {report.ignored} 个（编号/年份/小整数）。",
        "",
    ]

    if report.unmatched_high:
        lines.append("## [严重] 高置信缺出处数值（编造或派生计算值，须逐一核实出处）")
        lines.append("")
        for n in report.unmatched_high:
            lines.append(f"- `{n.raw}` 出自 {n.source_file}：…{n.context}…")
        lines.append("")

    if report.scaled:
        lines.append("## [提示] 缩放匹配（疑似单位换算，建议核对单位）")
        lines.append("")
        for n in report.scaled:
            lines.append(f"- `{n.raw}` 出自 {n.source_file}：…{n.context}…")
        lines.append("")

    if report.unmatched_low:
        lines.append("## [警示] 低置信可疑数值（精度低，可能是合理表述，人工判断）")
        lines.append("")
        for n in report.unmatched_low[:20]:
            lines.append(f"- `{n.raw}` 出自 {n.source_file}：…{n.context}…")
        if len(report.unmatched_low) > 20:
            lines.append(f"- …（共 {len(report.unmatched_low)} 个，仅列前 20）")
        lines.append("")

    if not report.unmatched_high and not report.unmatched_low and not report.scaled:
        lines.append("所有提取数值均能在求解产出中找到出处。")
        lines.append("")

    return "\n".join(lines)
