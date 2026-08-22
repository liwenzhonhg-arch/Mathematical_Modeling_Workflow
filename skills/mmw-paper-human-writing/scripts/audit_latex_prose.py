#!/usr/bin/env python3
"""Audit Chinese academic prose without treating LaTeX syntax as prose.

The audit command emits warnings only.  The compare command is a narrow
protected-content gate for rewrites and fails when covered tokens change.
"""

from __future__ import annotations

import argparse
import collections
import difflib
import json
import re
import sys
import unicodedata
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable


MATH_ENVIRONMENTS = (
    "equation",
    "align",
    "alignat",
    "gather",
    "multline",
    "displaymath",
    "math",
    "cases",
    "split",
    "array",
    "matrix",
    "pmatrix",
    "bmatrix",
    "vmatrix",
    "Vmatrix",
    "tikzpicture",
)

NON_PROSE_ENVIRONMENTS = (
    "verbatim",
    "Verbatim",
    "lstlisting",
    "minted",
    "tabular",
    "tabularx",
    "longtable",
    "thebibliography",
)

MMW_TRACE_RE = re.compile(
    r"(?m)^\s*%\s*MMW-(?:ALGORITHM|ID|LIMITATION)\s*:[^\n]*$"
)

MACHINE_COMMAND_RE = re.compile(
    r"\\(?:cite\w*|ref|eqref|pageref|label|url|href|includegraphics|input|include)"
    r"\*?(?:\[[^\]\n]*\])?\{[^{}\n]*\}(?:\{[^{}\n]*\})?"
)

TEXT_COMMAND_RE = re.compile(
    r"\\(?:section|subsection|subsubsection|paragraph|subparagraph|caption|"
    r"textbf|textit|emph|underline|keywords|text)\*?"
    r"(?:\[[^\]\n]*\])?\{([^{}\n]*)\}"
)

NUMBER_RE = re.compile(
    r"(?<![A-Za-z_])[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?%?"
)

URL_RE = re.compile(r"https?://[^\s)>}\]]+")

UNIT_RE = re.compile(
    r"(?<![A-Za-z])(?:MW|MWh|kW|kWh|GW|GWh|GPU(?:-hour)?|tCO2|kgCO2|"
    r"ms|min|km|kg|元|万元|小时|分钟|秒|百分点)(?![A-Za-z])",
    re.IGNORECASE,
)

META_SIGNPOSTS = (
    "值得注意的是",
    "需要指出的是",
    "不难发现",
    "显而易见",
    "毋庸置疑",
    "从某种意义上说",
    "更深层次",
    "归根结底",
)

SEQUENCE_WORDS = ("首先", "其次", "再次", "最后")

SEQUENCE_ACTION_WORDS = (
    "分析",
    "建立",
    "构建",
    "求解",
    "计算",
    "验证",
    "比较",
    "处理",
    "更新",
    "依赖",
    "基于",
    "得到",
    "输出",
    "输入",
    "设定",
    "选择",
    "拟合",
    "预测",
    "优化",
    "拆分",
    "说明",
    "报告",
    "定义",
    "读取",
    "筛选",
    "随后",
    "之后",
)

CONNECTORS = (
    "因此",
    "所以",
    "同时",
    "此外",
    "然而",
    "并且",
    "而且",
    "进一步",
    "从而",
)

GENERIC_CLAIM_PATTERNS = (
    re.compile(r"具有(?:较强|良好|一定|重要|广泛)?的?(?:科学性|合理性|适用性|推广价值|现实意义|参考价值)"),
    re.compile(r"为[^。！？\n]{0,24}(?:提供了?|开辟了?)(?:新的?)?(?:思路|路径|方向)"),
    re.compile(r"具有(?:广阔|良好|较大)的?(?:应用|推广)?前景"),
)

NOMINALIZATION_PATTERNS = (
    re.compile(r"进行(?:了|着)?[^，。；！？\n]{0,14}(?:分析|研究|计算|求解|优化|验证|比较|评估|讨论)"),
    re.compile(r"实现(?:了)?[^，。；！？\n]{0,14}(?:提升|降低|增长|优化|改善)"),
    re.compile(r"完成(?:了)?对[^，。；！？\n]{1,20}的(?:分析|求解|优化|验证|计算)"),
    re.compile(r"起到(?:了)?[^，。；！？\n]{0,12}(?:作用|效果)"),
)

VAGUE_EFFECT_WORDS = (
    "显著提升",
    "显著降低",
    "明显改善",
    "有效提高",
    "有效降低",
    "良好效果",
    "较好效果",
)

FIGURE_OPENERS = ("由图可知", "从图中可以看出", "由表可知", "从表中可以看出")

LATEX_HEADING_RE = re.compile(
    r"(?m)^[ \t]*\\(?P<kind>section|subsection|subsubsection|paragraph|subparagraph)"
    r"\*?(?:\[[^\]\n]*\])?\{(?P<title>[^{}\n]*)\}"
)
MARKDOWN_HEADING_RE = re.compile(
    r"(?m)^[ \t]{0,3}(?P<marks>#{1,6})[ \t]+(?P<title>[^\n]+)$"
)

EVIDENCE_MARKER_RE = re.compile(
    r"\d|图\s*\d|表\s*\d|式\s*\(?\d|公式|指标|误差|残差|约束|区间|"
    r"方案比较|结构化结果|results?\.json|sensitivity\.json|params\.json|"
    r"\\(?:cite|ref|eqref)\b"
)

EVALUATION_TERMS = ("优点", "缺点", "不足", "局限", "推广", "前景")
EVALUATION_SPECIFICITY_MARKERS = (
    "变量",
    "参数",
    "约束",
    "假设",
    "数据",
    "样本",
    "误差",
    "指标",
    "场景",
    "条件",
    "机制",
    "计算",
    "时间",
    "区域",
    "精度",
    "可观测",
)


@dataclass(frozen=True)
class WarningItem:
    category: str
    line: int
    excerpt: str
    message: str


def _mask_value(value: str) -> str:
    return "".join("\n" if char == "\n" else " " for char in value)


def _mask_matches(text: str, pattern: re.Pattern[str]) -> str:
    return pattern.sub(lambda match: _mask_value(match.group()), text)


def _environment_pattern(names: Iterable[str]) -> re.Pattern[str]:
    joined = "|".join(re.escape(name) for name in names)
    return re.compile(
        rf"\\begin\{{((?:{joined})\*?)\}}.*?\\end\{{\1\}}", re.DOTALL
    )


MATH_ENV_RE = _environment_pattern(MATH_ENVIRONMENTS)
NON_PROSE_ENV_RE = _environment_pattern(NON_PROSE_ENVIRONMENTS)

MATH_PATTERNS = (
    MATH_ENV_RE,
    re.compile(r"\\\[.*?\\\]", re.DOTALL),
    re.compile(r"\\\(.*?\\\)", re.DOTALL),
    re.compile(r"(?<!\\)\$\$.*?(?<!\\)\$\$", re.DOTALL),
    re.compile(r"(?<!\\)\$(?!\$).*?(?<!\\)\$", re.DOTALL),
)


def _keep_text_argument(match: re.Match[str]) -> str:
    value = list(_mask_value(match.group()))
    start = match.start(1) - match.start()
    argument = match.group(1)
    value[start : start + len(argument)] = argument
    return "".join(value)


def mask_non_prose(text: str) -> str:
    """Mask markup and machine content while preserving positions and lines."""

    masked = text
    patterns = (
        re.compile(r"```.*?```", re.DOTALL),
        re.compile(r"~~~.*?~~~", re.DOTALL),
        NON_PROSE_ENV_RE,
        *MATH_PATTERNS,
        MMW_TRACE_RE,
        re.compile(r"(?<!\\)%[^\n]*"),
        re.compile(r"`[^`\n]*`"),
        re.compile(r"\]\([^\n)]*\)"),
        URL_RE,
        re.compile(r"<[^>\n]+>"),
        MACHINE_COMMAND_RE,
    )
    for pattern in patterns:
        masked = _mask_matches(masked, pattern)

    masked = TEXT_COMMAND_RE.sub(_keep_text_argument, masked)
    masked = _mask_matches(
        masked,
        re.compile(r"\\[A-Za-z@]+\*?(?:\[[^\]\n]*\])?"),
    )
    masked = re.sub(r"[{}&]", " ", masked)
    return masked


def han_count(text: str) -> int:
    return len(re.findall(r"[\u4e00-\u9fff]", text))


def line_number(text: str, position: int) -> int:
    return text.count("\n", 0, position) + 1


def excerpt(value: str, width: int = 72) -> str:
    clean = re.sub(r"\s+", " ", value).strip()
    return clean if len(clean) <= width else clean[: width - 1] + "…"


def _sentences(text: str) -> list[re.Match[str]]:
    return list(re.finditer(r"[^。！？!?\n]+(?:[。！？!?]|$)", text))


def _paragraphs(text: str) -> list[tuple[int, str]]:
    return [(start, clean) for start, _, clean in _paragraph_spans(text)]


def _paragraph_spans(text: str) -> list[tuple[int, int, str]]:
    """Return paragraph offsets while preserving the source coordinate system."""

    paragraphs: list[tuple[int, int, str]] = []
    cursor = 0
    for block in re.split(r"\n\s*\n", text):
        position = text.find(block, cursor)
        if position < 0:
            continue
        cursor = position + len(block)
        clean = re.sub(r"^[#>*+\-\d.、\s]+", "", block).strip()
        if han_count(clean) >= 8:
            paragraphs.append((position, position + len(block), clean))
    return paragraphs


def _section_spans(text: str) -> list[tuple[int, int, str]]:
    """Split prose into heading-bounded regions without interpreting semantics."""

    matches = list(LATEX_HEADING_RE.finditer(text)) + list(
        MARKDOWN_HEADING_RE.finditer(text)
    )
    matches.sort(key=lambda match: match.start())
    if not matches:
        return [(0, len(text), "<document>")]

    spans: list[tuple[int, int, str]] = []
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        title = match.groupdict().get("title") or "<section>"
        spans.append((match.start(), end, title.strip()))
    return spans


def _ngrams(value: str, size: int = 3) -> set[str]:
    clean = re.sub(r"[^\u4e00-\u9fffA-Za-z0-9]", "", value)
    return {clean[index : index + size] for index in range(len(clean) - size + 1)}


def _similarity(left: str, right: str) -> float:
    clean_left = re.sub(r"[^\u4e00-\u9fffA-Za-z0-9]", "", left)
    clean_right = re.sub(r"[^\u4e00-\u9fffA-Za-z0-9]", "", right)
    sequence_ratio = difflib.SequenceMatcher(
        None, clean_left, clean_right, autojunk=False
    ).ratio()
    a, b = _ngrams(clean_left), _ngrams(clean_right)
    if not a or not b:
        return sequence_ratio
    return max(sequence_ratio, len(a & b) / len(a | b))


def _sentence_for_position(text: str, position: int) -> str:
    for match in _sentences(text):
        if match.start() <= position < match.end():
            return match.group()
    return ""


def _sequence_template_position(text: str) -> tuple[int, str] | None:
    """Return a warning position only for empty or repeated sequence templates."""

    hits = [
        (match.start(), word)
        for word in SEQUENCE_WORDS
        for match in re.finditer(re.escape(word), text)
    ]
    if len(hits) < 3 or len({word for _, word in hits}) < 3:
        return None

    weak_hits = [
        (position, word)
        for position, word in hits
        if not any(action in _sentence_for_position(text, position) for action in SEQUENCE_ACTION_WORDS)
    ]
    if len(weak_hits) >= 2:
        return min(position for position, _ in weak_hits), "顺序词附近缺少可识别的研究动作或依赖"

    repeated_paragraphs = 0
    for _, paragraph in _paragraphs(text):
        paragraph_words = {
            word for word in SEQUENCE_WORDS if word in paragraph
        }
        if len(paragraph_words) >= 3:
            repeated_paragraphs += 1
    if repeated_paragraphs >= 2:
        return min(position for position, _ in hits), "多个段落重复使用完整顺序词模板"
    return None


def _is_problem_locator(paragraph: str) -> bool:
    prefix = re.sub(r"\s+", "", paragraph[:24])
    return bool(
        re.match(
            r"^(?:问题[一二三四五六七八九十\d]+|(?:对于|针对|围绕)问题[一二三四五六七八九十\d]+)",
            prefix,
        )
    )


def _has_evidence(
    text: str, start: int, end: int, section_start: int, section_end: int
) -> bool:
    """Look only at the current sentence and its previous sentence in one paragraph."""

    paragraph_start, paragraph_end = section_start, section_end
    for candidate_start, candidate_end, _ in _paragraph_spans(
        text[section_start:section_end]
    ):
        candidate_start += section_start
        candidate_end += section_start
        if candidate_start <= start < candidate_end:
            paragraph_start, paragraph_end = candidate_start, candidate_end
            break

    paragraph = text[paragraph_start:paragraph_end]
    sentence_matches = list(_sentences(paragraph))
    current_index = next(
        (
            index
            for index, match in enumerate(sentence_matches)
            if paragraph_start + match.start() <= start < paragraph_start + match.end()
        ),
        None,
    )
    context_start = paragraph_start
    if current_index is not None and current_index > 0:
        context_start = paragraph_start + sentence_matches[current_index - 1].start()
    return bool(EVIDENCE_MARKER_RE.search(text[context_start:end]))


def _find_term(text: str, term: str) -> list[re.Match[str]]:
    term = str(term).strip()
    if not term:
        return []
    if re.fullmatch(r"[A-Za-z0-9_.-]+", term):
        pattern = re.compile(
            rf"(?<![A-Za-z0-9_]){re.escape(term)}(?![A-Za-z0-9_])",
            re.IGNORECASE,
        )
    else:
        pattern = re.compile(re.escape(term), re.IGNORECASE)
    return list(pattern.finditer(text))


def _find_numeric_term(text: str, value: str) -> list[re.Match[str]]:
    value = str(value).strip()
    if not value:
        return []
    pattern = re.compile(rf"(?<![\d.]){re.escape(value)}(?![\d.])")
    return list(pattern.finditer(text))


def _evidence(kind: str, term: str, match: re.Match[str], source: str) -> dict[str, object]:
    return {
        "kind": kind,
        "text": term,
        "line": line_number(source, match.start()),
    }


def _result_specs(raw: dict[str, object]) -> list[dict[str, object]]:
    specs: list[dict[str, object]] = []
    for value in raw.get("results", []) or []:  # type: ignore[union-attr]
        if isinstance(value, dict) and value.get("name"):
            specs.append(value)
    for name in raw.get("result_names", []) or []:  # type: ignore[union-attr]
        specs.append({"name": str(name)})
    return specs


def coverage_report(text: str, expectations: dict[str, object]) -> dict[str, object]:
    """Check task, method and result evidence without treating absence as a semantic verdict."""

    prose = mask_non_prose(text)
    items: list[dict[str, object]] = []
    for raw in expectations.get("subproblems", []):  # type: ignore[union-attr]
        if not isinstance(raw, dict) or not raw.get("id"):
            continue

        problem_id = str(raw["id"])
        task_terms = [problem_id]
        if raw.get("title"):
            task_terms.append(str(raw["title"]))
        task_terms.extend(str(value) for value in raw.get("aliases", []) or [])
        task_matches: list[tuple[str, re.Match[str]]] = []
        for term in task_terms:
            task_matches.extend((term, match) for match in _find_term(prose, term))

        method_terms = [str(value) for value in raw.get("method_terms", []) or []]
        method_matches: list[tuple[str, re.Match[str]]] = []
        for term in method_terms:
            method_matches.extend((term, match) for match in _find_term(prose, term))

        evidence: list[dict[str, object]] = []
        for term, match in task_matches:
            kind = "task_id" if term == problem_id else (
                "task_title" if term == str(raw.get("title", "")) else "task_alias"
            )
            evidence.append(_evidence(kind, term, match, text))
        for term, match in method_matches:
            evidence.append(_evidence("method_term", term, match, text))

        result_name_matches: list[str] = []
        result_value_matches: list[dict[str, object]] = []
        for result in _result_specs(raw):
            result_name = str(result["name"])
            result_terms = [result_name]
            result_terms.extend(str(value) for value in result.get("aliases", []) or [])
            for term in result_terms:
                for match in _find_term(prose, term):
                    result_name_matches.append(result_name)
                    evidence.append(_evidence("result_name", term, match, text))

            unit = str(result.get("unit", "")).strip()
            for display_value in result.get("display_values", []) or []:
                for match in _find_numeric_term(prose, str(display_value)):
                    context_start = max(0, match.start() - 80)
                    context_end = min(len(prose), match.end() + 80)
                    context = prose[context_start:context_end]
                    if unit and not _find_term(context, unit):
                        continue
                    nearby_task = any(
                        abs(task_match.start() - match.start()) <= 160
                        for _, task_match in task_matches
                    )
                    nearby_alias = any(
                        abs(alias_match.start() - match.start()) <= 160
                        for alias in result.get("aliases", []) or []
                        for alias_match in _find_term(prose, str(alias))
                    )
                    if not (nearby_task or nearby_alias):
                        continue
                    result_value_matches.append(
                        {"name": result_name, "value": str(display_value)}
                    )
                    evidence.append(
                        _evidence("result_value", f"{display_value}{unit}", match, text)
                    )

        task_present = bool(task_matches)
        method_present = not method_terms or bool(method_matches)
        result_present = not _result_specs(raw) or bool(
            result_name_matches or result_value_matches
        )
        item = {
            "id": problem_id,
            "task_present": task_present,
            "method_present": method_present,
            "result_present": result_present,
            "id_present": any(term == problem_id for term, _ in task_matches),
            "result_names_present": sorted(set(result_name_matches)),
            "method_terms_present": sorted({term for term, _ in method_matches}),
            "evidence": evidence,
            "missing_evidence": [
                kind
                for kind, present in (
                    ("task", task_present),
                    ("method", method_present),
                    ("result", result_present),
                )
                if not present
            ],
        }
        item["complete"] = bool(task_present and method_present and result_present)
        items.append(item)
    return {
        "complete": bool(items) and all(item["complete"] for item in items),
        "items": items,
        "missing_ids": [item["id"] for item in items if not item["task_present"]],
        "missing_results": [
            item["id"] for item in items if not item["result_present"]
        ],
        "missing_methods": [
            item["id"] for item in items if not item["method_present"]
        ],
    }


def audit_text(
    text: str, expectations: dict[str, object] | None = None
) -> dict[str, object]:
    prose = mask_non_prose(text)
    sections = _section_spans(text)
    total_han = han_count(prose)
    warnings: list[WarningItem] = []

    def add(category: str, position: int, value: str, message: str) -> None:
        warnings.append(
            WarningItem(category, line_number(text, position), excerpt(value), message)
        )

    for phrase in META_SIGNPOSTS:
        for match in re.finditer(re.escape(phrase), prose):
            add(
                "meta_signpost",
                match.start(),
                match.group(),
                "确认该短语后是否紧跟新证据；若只负责抬高语气，直接写判断。",
            )

    for pattern in GENERIC_CLAIM_PATTERNS:
        for match in pattern.finditer(prose):
            add(
                "generic_claim",
                match.start(),
                match.group(),
                "把评价落到具体能力、代价、适用条件或失败方式。",
            )

    for pattern in NOMINALIZATION_PATTERNS:
        for match in pattern.finditer(prose):
            add(
                "nominalization",
                match.start(),
                match.group(),
                "检查能否恢复直接动词，并写清分析或改变的对象。",
            )

    for section_start, section_end, _ in sections:
        section_prose = prose[section_start:section_end]
        sequence_warning = _sequence_template_position(section_prose)
        if sequence_warning is None:
            continue
        position, reason = sequence_warning
        sequence_terms = [
            word
            for _, word in sorted(
                [
                    (match.start(), word)
                    for word in SEQUENCE_WORDS
                    for match in re.finditer(re.escape(word), section_prose)
                ],
                key=lambda item: item[0],
            )[:8]
        ]
        add(
            "sequence_template",
            section_start + position,
            "、".join(sequence_terms),
            f"{reason}；确认顺序来自真实依赖，而不是覆盖章节内容。",
        )

    connector_hits = [
        (match.start(), word)
        for word in CONNECTORS
        for match in re.finditer(re.escape(word), prose)
    ]
    connector_density = len(connector_hits) * 1000 / max(total_han, 1)
    if total_han >= 500 and connector_density > 10:
        counts = collections.Counter(word for _, word in connector_hits)
        position = min(item[0] for item in connector_hits)
        sample = "、".join(f"{word} {count} 次" for word, count in counts.most_common(5))
        add(
            "connector_density",
            position,
            sample,
            f"连接词密度约为每千字 {connector_density:.1f} 个；检查逻辑是否可由事理直接衔接。",
        )

    for section_start, section_end, _ in sections:
        section_prose = prose[section_start:section_end]
        for match in _sentences(section_prose):
            sentence = match.group()
            start = section_start + match.start()
            end = section_start + match.end()
            raw_sentence = text[start:end]
            if any(marker in sentence for marker in ("可知", "可以看出", "表明", "说明")):
                if not _has_evidence(text, start, end, section_start, section_end):
                    add(
                        "result_evidence_chain",
                        start,
                        sentence,
                        "结果判断附近没有可见图表、数值、公式或结构化结果；补充证据或收窄结论。",
                    )
            if any(word in sentence for word in VAGUE_EFFECT_WORDS):
                has_evidence_marker = bool(
                    re.search(r"\d|\\(?:cite|ref|eqref)\b|图\s*\d|表\s*\d", raw_sentence)
                )
                if not has_evidence_marker:
                    add(
                        "vague_effect",
                        start,
                        sentence,
                        "效果形容词附近没有可见数字或引用；检查前文证据，必要时改成具体结果。",
                    )

            if any(term in sentence for term in EVALUATION_TERMS):
                has_specificity = any(
                    marker in sentence for marker in EVALUATION_SPECIFICITY_MARKERS
                )
                has_generic_evaluation = bool(
                    re.search(
                        r"(?:较强|良好|较好|广泛|较大|明显|有效|重要|一定|方便|简便|可靠|"
                        r"可行性|科学性|合理性|适用性|推广价值|应用前景)",
                        sentence,
                    )
                )
                if has_generic_evaluation and not has_specificity:
                    add(
                        "evaluation_specificity",
                        start,
                        sentence,
                        "评价只使用通用形容词；补充模型对象、数据条件、参数、影响或适用场景。",
                    )

    for section_start, section_end, _ in sections:
        section_prose = prose[section_start:section_end]
        figure_hits = [
            match
            for phrase in FIGURE_OPENERS
            for match in re.finditer(re.escape(phrase), section_prose)
        ]
        if len(figure_hits) >= 3:
            add(
                "figure_template",
                section_start + min(match.start() for match in figure_hits),
                f"机械读图开场共 {len(figure_hits)} 处",
                "保留必要定位，删去坐标轴可直接读出的复述，补比较、机制或边界。",
            )

        opener_counts: collections.Counter[str] = collections.Counter()
        opener_positions: dict[str, int] = {}
        for position, paragraph in _paragraphs(section_prose):
            if _is_problem_locator(paragraph):
                continue
            opener = "".join(re.findall(r"[\u4e00-\u9fff]", paragraph[:12]))[:4]
            if len(opener) == 4:
                opener_counts[opener] += 1
                opener_positions.setdefault(opener, position)
        for opener, count in opener_counts.items():
            if count >= 3:
                add(
                    "repeated_paragraph_opener",
                    section_start + opener_positions[opener],
                    f"{opener}… 共 {count} 段",
                    "检查是否使用同一段落模具；术语所需的正常重复可以保留。",
                )

    duplicate_pairs = 0
    all_sentence_matches: list[re.Match[str]] = []
    first_sentence_position: int | None = None
    for section_start, section_end, _ in sections:
        section_prose = prose[section_start:section_end]
        sentence_matches = [
            match for match in _sentences(section_prose) if han_count(match.group()) >= 20
        ]
        if first_sentence_position is None and sentence_matches:
            first_sentence_position = section_start + sentence_matches[0].start()
        all_sentence_matches.extend(sentence_matches)
        for index, left in enumerate(sentence_matches):
            for right in sentence_matches[index + 1 :]:
                if abs(han_count(left.group()) - han_count(right.group())) > 18:
                    continue
                similarity = _similarity(left.group(), right.group())
                if similarity >= 0.78:
                    duplicate_pairs += 1
                    add(
                        "near_duplicate",
                        section_start + right.start(),
                        right.group(),
                        f"与第 {line_number(text, section_start + left.start())} 行句子相似度 {similarity:.2f}；检查是否重复结论。",
                    )
                    if duplicate_pairs >= 8:
                        break
            if duplicate_pairs >= 8:
                break
        if duplicate_pairs >= 8:
            break

    lengths = [han_count(match.group()) for match in all_sentence_matches]
    sentence_cv: float | None = None
    if len(lengths) >= 12:
        mean = sum(lengths) / len(lengths)
        variance = sum((value - mean) ** 2 for value in lengths) / len(lengths)
        sentence_cv = variance**0.5 / mean if mean else None
        if sentence_cv is not None and sentence_cv < 0.35:
            add(
                "uniform_sentence_length",
                first_sentence_position or 0,
                f"{len(lengths)} 个句子的长度变异系数为 {sentence_cv:.2f}",
                "句长可能过于整齐；只在论证需要时合并或拆分，不要随机改句长。",
            )

    warnings.sort(key=lambda item: (item.line, item.category, item.excerpt))
    report: dict[str, object] = {
        "han_count": total_han,
        "warning_count": len(warnings),
        "connector_density_per_1000_han": round(connector_density, 2),
        "sentence_length_cv": None if sentence_cv is None else round(sentence_cv, 3),
        "warnings": [asdict(item) for item in warnings],
    }
    if expectations is not None:
        report["abstract_coverage"] = coverage_report(text, expectations)
    report["section_count"] = len(sections)
    return report


def _collect_matches(text: str, patterns: Iterable[re.Pattern[str]]) -> list[str]:
    matches: list[tuple[int, str]] = []
    occupied: list[tuple[int, int]] = []
    for pattern in patterns:
        for match in pattern.finditer(text):
            start, end = match.span()
            if any(start < old_end and end > old_start for old_start, old_end in occupied):
                continue
            matches.append((start, match.group()))
            occupied.append((start, end))
    return [value for _, value in sorted(matches)]


def protected_inventory(text: str) -> dict[str, list[str]]:
    return {
        "math": _collect_matches(text, MATH_PATTERNS),
        "numbers": NUMBER_RE.findall(text),
        "references": MACHINE_COMMAND_RE.findall(text),
        "mmw_trace": MMW_TRACE_RE.findall(text),
        "urls": URL_RE.findall(text),
        "units": UNIT_RE.findall(text),
    }


def _counter_delta(before: list[str], after: list[str]) -> dict[str, list[str]]:
    old, new = collections.Counter(before), collections.Counter(after)
    removed = list((old - new).elements())
    added = list((new - old).elements())
    return {"removed": removed, "added": added}


def compare_texts(before: str, after: str) -> dict[str, object]:
    old = protected_inventory(before)
    new = protected_inventory(after)
    differences = {
        key: delta
        for key in old
        if any((delta := _counter_delta(old[key], new[key])).values())
    }
    return {
        "passed": not differences,
        "differences": differences,
        "before_counts": {key: len(value) for key, value in old.items()},
        "after_counts": {key: len(value) for key, value in new.items()},
    }


def _read(path: str) -> str:
    return Path(path).read_text(encoding="utf-8")


def _print_audit(report: dict[str, object]) -> None:
    print(f"汉字数 {report['han_count']}，warning {report['warning_count']}")
    print(f"连接词密度 {report['connector_density_per_1000_han']}/千字")
    if report["sentence_length_cv"] is not None:
        print(f"句长变异系数 {report['sentence_length_cv']}")
    coverage = report.get("abstract_coverage")
    if coverage is not None:
        print(f"摘要问题覆盖 {'通过' if coverage['complete'] else '需人工补项'}")
        for key in ("missing_ids", "missing_results", "missing_methods"):
            if coverage[key]:
                print(f"- {key}: {coverage[key]}")
    for item in report["warnings"]:  # type: ignore[index]
        print(
            f"- L{item['line']} [{item['category']}] {item['excerpt']} — {item['message']}"
        )


def _print_compare(report: dict[str, object]) -> None:
    if report["passed"]:
        print("受保护内容比较通过。")
        return
    print("受保护内容发生变化。")
    for category, delta in report["differences"].items():  # type: ignore[union-attr]
        if delta["removed"]:
            print(f"- {category} removed: {delta['removed']}")
        if delta["added"]:
            print(f"- {category} added: {delta['added']}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="审计数学建模论文表达并保护 LaTeX 内容")
    subparsers = parser.add_subparsers(dest="command", required=True)

    audit_parser = subparsers.add_parser("audit", help="只读审计正文表达")
    audit_parser.add_argument("path")
    audit_parser.add_argument("--json", action="store_true", dest="as_json")
    audit_parser.add_argument(
        "--expectations",
        help="可选 analyze 完成契约 JSON，用于摘要问题—方法—结果覆盖检查",
    )

    compare_parser = subparsers.add_parser("compare", help="比较改稿前后的受保护内容")
    compare_parser.add_argument("before")
    compare_parser.add_argument("after")
    compare_parser.add_argument("--json", action="store_true", dest="as_json")

    args = parser.parse_args(argv)
    try:
        if args.command == "audit":
            expectations = None
            if args.expectations:
                expectations = json.loads(_read(args.expectations))
            report = audit_text(_read(args.path), expectations)
            if args.as_json:
                print(json.dumps(report, ensure_ascii=False, indent=2))
            else:
                _print_audit(report)
            return 0

        report = compare_texts(_read(args.before), _read(args.after))
        if args.as_json:
            print(json.dumps(report, ensure_ascii=False, indent=2))
        else:
            _print_compare(report)
        return 0 if report["passed"] else 1
    except (OSError, UnicodeError, ValueError) as error:
        print(f"无法读取文件：{error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
