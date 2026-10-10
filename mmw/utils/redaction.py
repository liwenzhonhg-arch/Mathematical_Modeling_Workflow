"""Shared secret naming and redaction rules for local public outputs."""

from __future__ import annotations

import re


_SENSITIVE_KEY = r"(?:[A-Za-z0-9]+[_-])*(?:api[_-]?key|token|secret|password|cookie|authorization)"
_SENSITIVE_KEY_RE = re.compile(_SENSITIVE_KEY, re.IGNORECASE)


def is_sensitive_key(key: str) -> bool:
    return _SENSITIVE_KEY_RE.fullmatch(key) is not None


_RULES = (
    (
        re.compile(r"(?is)-----BEGIN ([^-]*PRIVATE KEY)-----.*?-----END \1-----"),
        "<redacted-private-key>",
    ),
    (re.compile(r"(?i)(\b(?:authorization\s*:\s*)?(?:bearer|basic)\s+)[A-Za-z0-9._~+/=-]+"), r"\1<redacted>"),
    (re.compile(r"(?i)(\bcookie\s*:\s*)[^\r\n]+"), r"\1<redacted>"),
    (
        re.compile(
            rf"(?i)((?<![A-Za-z0-9_])[\"']?{_SENSITIVE_KEY}[\"']?\s*[:=]\s*)"
            r'''(?:"(?:\\.|[^"\\])+"|'(?:\\.|[^'\\])+'|[^\s"',;&}\]]+)'''
        ),
        r"\1<redacted>",
    ),
    (re.compile(r"(?i)(https?://[^\s/@]+:)[^\s/@]+(@)"), r"\1<redacted>\2"),
    (re.compile(r"(?i)\bsk-[A-Za-z0-9_-]{8,}\b"), "<redacted>"),
    (re.compile(r"(?is)-----BEGIN [^-]*PRIVATE KEY-----"), "<redacted-private-key>"),
)


def contains_secret(text: str) -> bool:
    return any(pattern.search(text) for pattern, _replacement in _RULES)


def redact_secrets(text: str) -> str:
    for pattern, replacement in _RULES:
        text = pattern.sub(replacement, text)
    return text
