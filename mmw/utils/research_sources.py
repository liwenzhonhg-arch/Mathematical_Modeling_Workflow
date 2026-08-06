"""有界学术元数据检索；默认由配置关闭，不下载全文。"""

from __future__ import annotations

import html
import json
import re
from collections.abc import Callable
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request, urlopen

MAX_RESPONSE_BYTES = 2 * 1024 * 1024


def _read_json(url: str, timeout: float = 8) -> dict[str, Any]:
    request = Request(url, headers={"User-Agent": "MMW/0.1.7 (academic metadata search)"})
    with urlopen(request, timeout=timeout) as response:
        declared = response.headers.get("Content-Length")
        if declared and int(declared) > MAX_RESPONSE_BYTES:
            raise ValueError("response too large")
        body = response.read(MAX_RESPONSE_BYTES + 1)
    if len(body) > MAX_RESPONSE_BYTES:
        raise ValueError("response too large")
    data = json.loads(body.decode("utf-8"))
    if not isinstance(data, dict):
        raise ValueError("response root is not an object")
    return data


def _clean_text(value: Any, limit: int = 1200) -> str:
    text = re.sub(r"<[^>]+>", " ", html.unescape(str(value or "")))
    return re.sub(r"\s+", " ", text).strip()[:limit]


def _openalex_abstract(inverted: Any) -> str:
    if not isinstance(inverted, dict):
        return ""
    positions: list[tuple[int, str]] = []
    for word, indexes in inverted.items():
        if not isinstance(indexes, list):
            continue
        for index in indexes:
            if isinstance(index, int) and not isinstance(index, bool) and index >= 0:
                positions.append((index, str(word)))
    return _clean_text(" ".join(word for _, word in sorted(positions)))


def _doi(value: Any) -> str:
    return re.sub(r"^https?://(?:dx\.)?doi\.org/", "", str(value or ""), flags=re.I).strip().lower()


def _openalex_records(data: dict[str, Any], query: str) -> list[dict[str, Any]]:
    records = []
    for item in data.get("results", []):
        if not isinstance(item, dict):
            continue
        authors = []
        for authorship in item.get("authorships", [])[:8]:
            author = authorship.get("author", {}) if isinstance(authorship, dict) else {}
            if isinstance(author, dict) and author.get("display_name"):
                authors.append(str(author["display_name"]))
        abstract = _openalex_abstract(item.get("abstract_inverted_index"))
        records.append({
            "source": "openalex",
            "query": query,
            "id": str(item.get("id") or ""),
            "doi": _doi(item.get("doi")),
            "title": _clean_text(item.get("display_name"), 500),
            "authors": authors,
            "year": item.get("publication_year"),
            "url": str(item.get("id") or ""),
            "abstract": abstract,
            "evidence_level": "abstract" if abstract else "metadata",
        })
    return [record for record in records if record["title"]]


def _crossref_year(item: dict[str, Any]) -> int | None:
    for field in ("published-print", "published-online", "published", "issued"):
        parts = item.get(field, {}).get("date-parts", []) if isinstance(item.get(field), dict) else []
        if parts and parts[0] and isinstance(parts[0][0], int):
            return parts[0][0]
    return None


def _crossref_records(data: dict[str, Any], query: str) -> list[dict[str, Any]]:
    message = data.get("message", {})
    items = message.get("items", []) if isinstance(message, dict) else []
    records = []
    for item in items:
        if not isinstance(item, dict):
            continue
        title = item.get("title", [])
        title = title[0] if isinstance(title, list) and title else title
        authors = []
        for author in item.get("author", [])[:8]:
            if not isinstance(author, dict):
                continue
            name = " ".join(str(author.get(part, "")).strip() for part in ("given", "family")).strip()
            if name:
                authors.append(name)
        abstract = _clean_text(item.get("abstract"))
        records.append({
            "source": "crossref",
            "query": query,
            "id": _doi(item.get("DOI")),
            "doi": _doi(item.get("DOI")),
            "title": _clean_text(title, 500),
            "authors": authors,
            "year": _crossref_year(item),
            "url": str(item.get("URL") or ""),
            "abstract": abstract,
            "evidence_level": "abstract" if abstract else "metadata",
        })
    return [record for record in records if record["title"]]


def _dedupe(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    selected: dict[str, dict[str, Any]] = {}
    for record in records:
        title_key = re.sub(r"\W+", "", record["title"].casefold())
        key = record.get("doi") or title_key
        if not key:
            continue
        current = selected.get(key)
        if current is None or (not current.get("abstract") and record.get("abstract")):
            selected[key] = record
    return list(selected.values())


def search_literature(
    queries: list[str],
    *,
    per_source: int = 3,
    timeout: float = 8,
    fetch_json: Callable[[str, float], dict[str, Any]] = _read_json,
) -> dict[str, Any]:
    """查询固定端点并返回精简、去重后的公开元数据。"""
    bounded_queries = list(dict.fromkeys(query.strip() for query in queries if query.strip()))[:4]
    rows = max(1, min(int(per_source), 3))
    records: list[dict[str, Any]] = []
    errors = []
    succeeded = 0
    for query in bounded_queries:
        endpoints = (
            (
                "openalex",
                "https://api.openalex.org/works?" + urlencode({"search": query, "per-page": rows}),
                _openalex_records,
            ),
            (
                "crossref",
                "https://api.crossref.org/works?" + urlencode({
                    "query.bibliographic": query,
                    "rows": rows,
                    "select": "DOI,title,author,published,published-print,published-online,issued,URL,abstract",
                }),
                _crossref_records,
            ),
        )
        for source, url, parser in endpoints:
            try:
                records.extend(parser(fetch_json(url, timeout), query))
                succeeded += 1
            except Exception as exc:
                errors.append({"query": query, "source": source, "error": type(exc).__name__})
    return {
        "queries": bounded_queries,
        "requests_succeeded": succeeded,
        "sources": _dedupe(records),
        "errors": errors,
    }
