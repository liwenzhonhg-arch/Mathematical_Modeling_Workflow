"""Windows 发行物的离线完整性与安全边界检查。"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any


class ReleaseValidationError(RuntimeError):
    """发行物不满足公开分发门禁。"""


REQUIRED_PATHS = {
    "MMW.exe",
    "README-Windows.txt",
    "_internal/mmw/gui/static/index.html",
    "_internal/mmw/prompts/analyze.j2",
    "_internal/knowledge/hmml.json",
    "_internal/mmw/utils/moving_heat.py",
}
SENSITIVE_SEGMENTS = {".git", "workspace", "test_cases", "__pycache__", ".pytest_cache"}
SENSITIVE_NAMES = {".env", ".env.local", "id_rsa", "id_ed25519"}
SENSITIVE_SUFFIXES = {".key", ".pem", ".p12", ".pfx"}
SENSITIVE_NAME_RE = re.compile(
    r"(?i)(?:^|[._-])(?:credentials?|auth(?:entication)?|tokens?|cookies?|sessions?|login|browser[_-]?data)(?:[._-]|$)"
)
TEXT_SUFFIXES = {".json", ".txt", ".ini", ".cfg", ".yaml", ".yml", ".toml", ".py", ".ps1", ".bat"}
SECRET_CONTENT_RE = re.compile(
    r"(?is)(?:-----BEGIN [^-]*PRIVATE KEY-----|\bbearer\s+[A-Za-z0-9._~+/=-]{12,}|"
    r"\b(?:api[_-]?key|token|secret|password)\b\s*[:=]\s*[\"']?[A-Za-z0-9._~+/=-]{8,})"
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _normalized_archive_path(name: str) -> PurePosixPath:
    normalized = name.replace("\\", "/")
    path = PurePosixPath(normalized)
    if (
        path.is_absolute()
        or re.match(r"^[A-Za-z]:", normalized)
        or ".." in path.parts
        or not path.parts
    ):
        raise ReleaseValidationError(f"ZIP 包含路径穿越条目：{name}")
    return path


def _reject_sensitive_path(path: PurePosixPath) -> None:
    if path.as_posix().lower() == "_internal/certifi/cacert.pem":
        return
    parts = {part.lower() for part in path.parts}
    name = path.name.lower()
    if (
        parts & SENSITIVE_SEGMENTS
        or name in SENSITIVE_NAMES
        or name.startswith(".env.")
        or SENSITIVE_NAME_RE.search(name)
        or path.suffix.lower() in SENSITIVE_SUFFIXES
    ):
        raise ReleaseValidationError(f"发行物包含敏感路径：{path.as_posix()}")


def validate_release(
    bundle: Path,
    archive: Path,
    checksum: Path,
    *,
    max_archive_mb: int = 150,
    max_uncompressed_mb: int = 700,
    smoke_test: bool = True,
) -> dict[str, Any]:
    bundle = bundle.resolve()
    archive = archive.resolve()
    checksum = checksum.resolve()
    if not bundle.is_dir() or not archive.is_file() or not checksum.is_file():
        raise ReleaseValidationError("发行目录、ZIP 或 SHA256 文件不存在")
    if archive.stat().st_size > max_archive_mb * 1024 * 1024:
        raise ReleaseValidationError(f"ZIP 超过 {max_archive_mb} MiB 上限")

    expected_parts = checksum.read_text(encoding="ascii").strip().split()
    actual_digest = _sha256(archive)
    if len(expected_parts) != 2 or expected_parts[0].lower() != actual_digest:
        raise ReleaseValidationError("SHA256 文件与 ZIP 不一致")
    if Path(expected_parts[1]).name != archive.name:
        raise ReleaseValidationError("SHA256 文件中的发行物名称不一致")

    with zipfile.ZipFile(archive) as handle:
        if bad_file := handle.testzip():
            raise ReleaseValidationError(f"ZIP CRC 校验失败：{bad_file}")
        names: set[str] = set()
        normalized_names: set[str] = set()
        file_count = 0
        uncompressed_size = 0
        for info in handle.infolist():
            path = _normalized_archive_path(info.filename)
            _reject_sensitive_path(path)
            normalized_name = path.as_posix().casefold()
            if normalized_name in normalized_names:
                raise ReleaseValidationError(f"ZIP 包含重复路径：{path.as_posix()}")
            normalized_names.add(normalized_name)
            if info.is_dir():
                continue
            if info.file_size <= 2 * 1024 * 1024:
                _scan_sensitive_content(path, handle.read(info))
            names.add(path.as_posix())
            file_count += 1
            uncompressed_size += info.file_size
        if uncompressed_size > max_uncompressed_mb * 1024 * 1024:
            raise ReleaseValidationError(f"ZIP 解压后超过 {max_uncompressed_mb} MiB 上限")

    missing = sorted(REQUIRED_PATHS - names)
    if missing:
        raise ReleaseValidationError(f"发行物缺少必需文件：{', '.join(missing)}")

    for path in bundle.rglob("*"):
        if path.is_file():
            _reject_sensitive_path(PurePosixPath(path.relative_to(bundle).as_posix()))
            if path.stat().st_size <= 2 * 1024 * 1024:
                _scan_sensitive_content(path, path.read_bytes())

    if smoke_test:
        executable = bundle / "MMW.exe"
        try:
            result = subprocess.run(
                [str(executable), "-m", "mmw.cli", "--help"],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=60,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise ReleaseValidationError(f"冻结版冒烟测试无法完成：{type(exc).__name__}") from exc
        if result.returncode != 0:
            raise ReleaseValidationError(f"冻结版冒烟测试失败，退出码 {result.returncode}")

    return {
        "archive_sha256": actual_digest,
        "archive_bytes": archive.stat().st_size,
        "uncompressed_bytes": uncompressed_size,
        "file_count": file_count,
        "smoke_test": "passed" if smoke_test else "skipped",
    }


def _scan_sensitive_content(path: PurePosixPath | Path, data: bytes) -> None:
    """只报告路径和规则名，不把疑似秘密写入异常。"""
    suffix = Path(path).suffix.lower()
    if suffix not in TEXT_SUFFIXES or len(data) > 2 * 1024 * 1024 or b"\x00" in data:
        return
    text = data.decode("utf-8", errors="ignore")
    if SECRET_CONTENT_RE.search(text):
        raise ReleaseValidationError(f"发行物内容命中疑似秘密规则：{Path(path).as_posix()}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--checksum", type=Path, required=True)
    parser.add_argument("--max-archive-mb", type=int, default=150)
    parser.add_argument("--max-uncompressed-mb", type=int, default=700)
    args = parser.parse_args()
    report = validate_release(
        args.bundle,
        args.archive,
        args.checksum,
        max_archive_mb=args.max_archive_mb,
        max_uncompressed_mb=args.max_uncompressed_mb,
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
