import hashlib
import io
import json
import sys
import tomllib
import zipfile
from pathlib import Path

import pytest

from mmw import __version__
from mmw.update import check_for_update, install_latest_update


def _release_opener(bundle: bytes, *, digest: str | None = None):
    metadata = json.dumps(
        {
            "tag_name": "v9.9.9",
            "html_url": "https://github.com/liwenzhonhg-arch/Mathematical_Modeling_Workflow/releases/tag/v9.9.9",
            "assets": [
                {
                    "name": "MMW-Windows-x64-v9.9.9.zip",
                    "state": "uploaded",
                    "size": len(bundle),
                    "digest": f"sha256:{digest or hashlib.sha256(bundle).hexdigest()}",
                    "browser_download_url": "https://github.com/liwenzhonhg-arch/Mathematical_Modeling_Workflow/releases/download/v9.9.9/MMW-Windows-x64-v9.9.9.zip",
                }
            ],
        }
    ).encode()

    def opener(request, timeout):
        return io.BytesIO(bundle if request.full_url.endswith(".zip") else metadata)

    return opener


def _bundle(*, unsafe: bool = False) -> bytes:
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as archive:
        archive.writestr("MMW.exe", b"exe")
        archive.writestr("_internal/", b"")
        archive.writestr("_internal/app.dat", b"data")
        if unsafe:
            archive.writestr("../outside.txt", b"bad")
    return stream.getvalue()


def test_version_is_synced_and_update_status_is_installable(monkeypatch):
    project = Path(__file__).resolve().parents[1] / "pyproject.toml"
    project_version = tomllib.loads(project.read_text(encoding="utf-8"))["project"]["version"]
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(sys, "frozen", True, raising=False)

    result = check_for_update(_release_opener(_bundle()))

    assert project_version == __version__
    assert result["available"] is True
    assert result["installable"] is True


def test_install_update_verifies_and_extracts(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(sys, "frozen", True, raising=False)

    result = install_latest_update(tmp_path, _release_opener(_bundle()))
    executable = Path(str(result["_executable"]))

    assert executable.read_bytes() == b"exe"
    assert executable.parent.joinpath("_internal/app.dat").read_bytes() == b"data"
    assert json.loads(executable.parent.joinpath(".mmw-update.json").read_text(encoding="utf-8"))[
        "version"
    ] == "9.9.9"


@pytest.mark.parametrize(
    ("opener", "message"),
    [
        (_release_opener(_bundle(), digest="0" * 64), "SHA256"),
        (_release_opener(_bundle(unsafe=True)), "非法路径"),
    ],
)
def test_install_update_rejects_untrusted_archive(
    tmp_path: Path, monkeypatch, opener, message: str
):
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(sys, "frozen", True, raising=False)

    with pytest.raises(ValueError, match=message):
        install_latest_update(tmp_path, opener)

    assert not list(tmp_path.glob("v9.9.9*"))
