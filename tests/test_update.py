import hashlib
import io
import json
import sys
import tomllib
import zipfile
from pathlib import Path

import pytest

from mmw import __version__
from mmw.update import (
    check_for_update,
    install_latest_update,
    preflight_candidate,
    switch_gui_version,
)


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


def test_install_update_reports_download_and_install_steps(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    events = []

    install_latest_update(
        tmp_path,
        _release_opener(_bundle()),
        lambda step, progress=None: events.append((step, progress)),
    )

    download = [progress for step, progress in events if step == "下载更新包"]
    assert download[0] == 0
    assert download[-1] == 100
    assert ("校验并解压更新包", None) in events
    assert events[-1] == ("安装完成", 100)


class _Process:
    def __init__(self):
        self.terminated = False

    def poll(self):
        return None

    def terminate(self):
        self.terminated = True

    def wait(self, timeout=None):
        return 0


def test_candidate_preflight_requires_matching_http_version(monkeypatch):
    process = _Process()
    monkeypatch.setattr("mmw.update._free_port", lambda: 43210)
    monkeypatch.setattr("mmw.update._wait_for_gui_health", lambda *args, **kwargs: False)

    assert preflight_candidate(Path("new.exe"), "9.9.9", popen=lambda *args, **kwargs: process) is False
    assert process.terminated is True


def test_final_health_failure_restores_old_version_and_writes_status(tmp_path: Path, monkeypatch):
    processes = [_Process(), _Process()]
    health = iter([False, True])
    monkeypatch.setattr("mmw.update._wait_for_port_free", lambda *args, **kwargs: True)
    monkeypatch.setattr("mmw.update._wait_for_gui_health", lambda *args, **kwargs: next(health))
    status = tmp_path / "update-status.json"

    switched = switch_gui_version(
        Path("new.exe"),
        Path("old.exe"),
        "9.9.9",
        __version__,
        8765,
        status,
        popen=lambda *args, **kwargs: processes.pop(0),
    )

    assert switched is False
    assert json.loads(status.read_text("utf-8"))["status"] == "rolled_back"


def test_install_update_rejects_https_redirect_to_http(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    base = _release_opener(_bundle())

    class Downgraded(io.BytesIO):
        def geturl(self):
            return "http://github.com/insecure.zip"

    def opener(request, timeout):
        response = base(request, timeout)
        return Downgraded(response.read()) if request.full_url.endswith(".zip") else response

    with pytest.raises(ValueError, match="HTTPS"):
        install_latest_update(tmp_path, opener)


def test_tampered_installed_version_is_not_reused(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    first = install_latest_update(tmp_path, _release_opener(_bundle()))
    Path(str(first["_executable"])).write_bytes(b"tampered")

    second = install_latest_update(tmp_path, _release_opener(_bundle()))

    assert Path(str(second["_executable"])).parent != Path(str(first["_executable"])).parent
    assert Path(str(second["_executable"])).read_bytes() == b"exe"
