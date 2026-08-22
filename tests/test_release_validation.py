from __future__ import annotations

import hashlib
import zipfile
from pathlib import Path

import pytest

from mmw.release_validation import ReleaseValidationError, validate_release


REQUIRED = {
    "MMW.exe": b"fake exe",
    "README-Windows.txt": b"readme",
    "_internal/mmw/gui/static/index.html": b"html",
    "_internal/mmw/prompts/analyze.j2": b"prompt",
    "_internal/knowledge/hmml.json": b"{}",
    "_internal/mmw/utils/moving_heat.py": b"module",
}


def _write_release(tmp_path: Path, files: dict[str, bytes]) -> tuple[Path, Path, Path]:
    bundle = tmp_path / "MMW"
    for name, content in files.items():
        target = bundle / Path(name)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
    archive = tmp_path / "MMW-Windows-x64-v0.0.0.zip"
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as handle:
        for path in bundle.rglob("*"):
            if path.is_file():
                handle.write(path, path.relative_to(bundle).as_posix())
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    checksum = Path(f"{archive}.sha256")
    checksum.write_text(f"{digest}  {archive.name}\n", encoding="ascii")
    return bundle, archive, checksum


def test_validate_release_accepts_complete_safe_bundle(tmp_path: Path) -> None:
    files = {**REQUIRED, "_internal/certifi/cacert.pem": b"public CA bundle"}
    bundle, archive, checksum = _write_release(tmp_path, files)

    report = validate_release(bundle, archive, checksum, smoke_test=False)

    assert report["archive_sha256"] == hashlib.sha256(archive.read_bytes()).hexdigest()
    assert report["file_count"] == len(files)


@pytest.mark.parametrize(
    "unsafe_name",
    [
        ".env",
        "workspace/private.json",
        "test_cases/case.json",
        ".git/config",
        "secret.key",
        "secret.pem",
        "credentials.json",
        "browser-data/profile.json",
    ],
)
def test_validate_release_rejects_sensitive_paths(tmp_path: Path, unsafe_name: str) -> None:
    bundle, archive, checksum = _write_release(tmp_path, {**REQUIRED, unsafe_name: b"secret"})

    with pytest.raises(ReleaseValidationError, match="敏感"):
        validate_release(bundle, archive, checksum, smoke_test=False)


@pytest.mark.parametrize(
    "payload",
    [
        b'api_key = "abcdefgh12345678"\n',
        b"Authorization: Bearer abcdefghijklmnop\n",
        b"-----BEGIN PRIVATE KEY-----\nredacted\n",
    ],
)
def test_validate_release_rejects_sensitive_text_content(
    tmp_path: Path, payload: bytes
) -> None:
    bundle, archive, checksum = _write_release(
        tmp_path, {**REQUIRED, "_internal/settings.txt": payload}
    )

    with pytest.raises(ReleaseValidationError, match="疑似秘密"):
        validate_release(bundle, archive, checksum, smoke_test=False)


@pytest.mark.parametrize("unsafe_name", ["../escape.txt", "C:/escape.txt"])
def test_validate_release_rejects_path_traversal(tmp_path: Path, unsafe_name: str) -> None:
    bundle, archive, checksum = _write_release(tmp_path, REQUIRED)
    with zipfile.ZipFile(archive, "a") as handle:
        handle.writestr(unsafe_name, "bad")
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    checksum.write_text(f"{digest}  {archive.name}\n", encoding="ascii")

    with pytest.raises(ReleaseValidationError, match="路径穿越"):
        validate_release(bundle, archive, checksum, smoke_test=False)


def test_validate_release_rejects_duplicate_casefolded_paths(tmp_path: Path) -> None:
    bundle, archive, checksum = _write_release(tmp_path, REQUIRED)
    with zipfile.ZipFile(archive, "a") as handle:
        handle.writestr("readme-windows.TXT", "duplicate on Windows")
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    checksum.write_text(f"{digest}  {archive.name}\n", encoding="ascii")

    with pytest.raises(ReleaseValidationError, match="重复路径"):
        validate_release(bundle, archive, checksum, smoke_test=False)


def test_build_script_uses_isolated_locked_environment() -> None:
    script = (Path(__file__).parents[1] / "build-windows.ps1").read_text(encoding="utf-8")

    assert "requirements-windows.lock" in script
    assert "-m venv" in script
    assert "mmw.release_validation" in script
