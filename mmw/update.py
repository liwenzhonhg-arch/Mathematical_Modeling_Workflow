"""Windows 便携版更新：检查 GitHub Release，校验后安装到新目录。"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import socket
import stat
import subprocess
import sys
import tempfile
import time
import zipfile
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from mmw import __version__

RELEASE_API = (
    "https://api.github.com/repos/"
    "liwenzhonhg-arch/Mathematical_Modeling_Workflow/releases/latest"
)
MAX_METADATA_BYTES = 2 * 1024 * 1024
MAX_DOWNLOAD_BYTES = 500 * 1024 * 1024
MAX_EXTRACTED_BYTES = 1024 * 1024 * 1024
HEALTH_TIMEOUT_SECONDS = 15


def _version_tuple(value: str) -> tuple[int, int, int]:
    value = value.removeprefix("v")
    parts = value.split(".")
    if len(parts) != 3 or any(not part.isdigit() for part in parts):
        raise ValueError("GitHub Release 版本号格式无效")
    return int(parts[0]), int(parts[1]), int(parts[2])


def fetch_latest_release(opener=urlopen) -> dict[str, object]:
    request = Request(
        RELEASE_API,
        headers={
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": f"MMW/{__version__}",
        },
    )
    with opener(request, timeout=5) as response:
        payload = response.read(MAX_METADATA_BYTES + 1)
    if len(payload) > MAX_METADATA_BYTES:
        raise ValueError("GitHub Release 响应过大")
    data = json.loads(payload)
    if not isinstance(data, dict) or not isinstance(data.get("assets"), list):
        raise ValueError("GitHub Release 响应格式无效")
    latest = str(data.get("tag_name", "")).removeprefix("v")
    _version_tuple(latest)
    asset_name = f"MMW-Windows-x64-v{latest}.zip"
    asset = next(
        (
            item for item in data.get("assets", [])
            if isinstance(item, dict)
            and item.get("name") == asset_name
            and item.get("state") == "uploaded"
        ),
        None,
    )
    if not asset:
        raise ValueError("最新 Release 没有 Windows 发行包")
    try:
        size = int(asset.get("size", 0))
    except (TypeError, ValueError):
        raise ValueError("Windows 发行包大小异常") from None
    digest = str(asset.get("digest", ""))
    download_url = str(asset.get("browser_download_url", ""))
    release_url = str(data.get("html_url", ""))
    parsed = urlparse(download_url)
    release_parsed = urlparse(release_url)
    if not 0 < size <= MAX_DOWNLOAD_BYTES:
        raise ValueError("Windows 发行包大小异常")
    if (
        not digest.startswith("sha256:")
        or len(digest) != 71
        or any(character not in "0123456789abcdefABCDEF" for character in digest[7:])
    ):
        raise ValueError("Windows 发行包缺少有效 SHA256")
    if parsed.scheme != "https" or parsed.hostname != "github.com":
        raise ValueError("Windows 发行包下载地址无效")
    if release_parsed.scheme != "https" or release_parsed.hostname != "github.com":
        raise ValueError("GitHub Release 地址无效")
    return {
        "latest": latest,
        "release_url": release_url,
        "asset_name": asset_name,
        "download_url": download_url,
        "size": size,
        "sha256": digest.removeprefix("sha256:").lower(),
    }


def check_for_update(opener=urlopen) -> dict[str, object]:
    release = fetch_latest_release(opener)
    available = _version_tuple(str(release["latest"])) > _version_tuple(__version__)
    return {
        "current": __version__,
        "latest": release["latest"],
        "available": available,
        "installable": available and sys.platform == "win32" and bool(getattr(sys, "frozen", False)),
        "release_url": release["release_url"],
        "size": release["size"],
    }


def install_latest_update(
    install_root: Path | None = None,
    opener=urlopen,
    progress_callback=None,
) -> dict[str, object]:
    report = progress_callback or (lambda _step, _progress=None: None)
    if sys.platform != "win32" or not getattr(sys, "frozen", False):
        raise ValueError("一键更新只支持 Windows EXE")
    report("检查发布版本")
    release = fetch_latest_release(opener)
    latest = str(release["latest"])
    if _version_tuple(latest) <= _version_tuple(__version__):
        raise ValueError("当前已经是最新版本")

    root = install_root or (
        Path(os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA") or Path.home())
        / "MMW"
        / "versions"
    )
    root.mkdir(parents=True, exist_ok=True)
    digest = str(release["sha256"])
    target = root / f"v{latest}"
    if _installed_hash(target) == digest:
        report("已找到校验通过的版本", 100)
        return _installed_result(latest, target)
    if target.exists():
        target = root / f"v{latest}-{digest[:8]}"
        if _installed_hash(target) == digest:
            report("已找到校验通过的版本", 100)
            return _installed_result(latest, target)
        if target.exists():
            raise ValueError("目标版本目录已存在但校验信息不匹配")

    descriptor, archive_name = tempfile.mkstemp(prefix="mmw-update-", suffix=".zip", dir=root)
    os.close(descriptor)
    archive = Path(archive_name)
    staging = Path(tempfile.mkdtemp(prefix=f".v{latest}-", dir=root))
    try:
        report("下载更新包", 0)
        _download(
            str(release["download_url"]),
            archive,
            int(release["size"]),
            digest,
            opener,
            lambda total: report("下载更新包", total / int(release["size"]) * 100),
        )
        report("校验并解压更新包")
        _extract_verified(archive, staging)
        executable = staging / "MMW.exe"
        if not executable.is_file() or not staging.joinpath("_internal").is_dir():
            raise ValueError("更新包缺少 MMW.exe 或 _internal")
        (staging / ".mmw-update.json").write_text(
            json.dumps(
                {"version": latest, "sha256": digest, "files": _directory_manifest(staging)},
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        report("安装新版本")
        staging.replace(target)
        report("安装完成", 100)
        return _installed_result(latest, target)
    finally:
        archive.unlink(missing_ok=True)
        if staging.exists():
            shutil.rmtree(staging)


def _download(
    url: str,
    path: Path,
    expected_size: int,
    expected_hash: str,
    opener,
    progress_callback=None,
) -> None:
    request = Request(url, headers={"User-Agent": f"MMW/{__version__}"})
    digest = hashlib.sha256()
    total = 0
    with opener(request, timeout=60) as response, path.open("wb") as output:
        final_url = str(getattr(response, "geturl", lambda: url)())
        if urlparse(final_url).scheme != "https":
            raise ValueError("Windows 发行包下载重定向必须保持 HTTPS")
        while chunk := response.read(1024 * 1024):
            total += len(chunk)
            if total > MAX_DOWNLOAD_BYTES or total > expected_size:
                raise ValueError("更新包下载大小异常")
            digest.update(chunk)
            output.write(chunk)
            if progress_callback:
                progress_callback(total)
    if total != expected_size or digest.hexdigest() != expected_hash:
        raise ValueError("更新包 SHA256 校验失败")


def _extract_verified(archive: Path, target: Path) -> None:
    with zipfile.ZipFile(archive) as bundle:
        entries = bundle.infolist()
        if len(entries) > 10_000 or sum(item.file_size for item in entries) > MAX_EXTRACTED_BYTES:
            raise ValueError("更新包解压规模异常")
        seen: set[str] = set()
        for item in entries:
            destination = (target / item.filename).resolve()
            if not destination.is_relative_to(target.resolve()):
                raise ValueError("更新包包含非法路径")
            normalized = destination.relative_to(target.resolve()).as_posix().casefold()
            if normalized in seen:
                raise ValueError("更新包包含重复路径")
            seen.add(normalized)
            mode = (item.external_attr >> 16) & 0o170000
            if mode and mode != stat.S_IFREG and mode != stat.S_IFDIR:
                raise ValueError("更新包包含符号链接")
        bundle.extractall(target)


def _installed_result(version: str, target: Path) -> dict[str, object]:
    return {
        "ok": True,
        "version": version,
        "message": f"v{version} 已安装，正在重启",
        "_executable": str((target / "MMW.exe").resolve()),
    }


def _installed_hash(target: Path) -> str:
    marker = target / ".mmw-update.json"
    if not target.joinpath("MMW.exe").is_file() or not target.joinpath("_internal").is_dir() or not marker.is_file():
        return ""
    try:
        installed = json.loads(marker.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError):
        return ""
    if not isinstance(installed, dict) or not isinstance(installed.get("files"), dict):
        return ""
    if installed["files"] != _directory_manifest(target):
        return ""
    return str(installed.get("sha256", ""))


def _directory_manifest(root: Path) -> dict[str, str]:
    """验证已安装目录没有被替换；marker 本身不纳入清单。"""
    manifest: dict[str, str] = {}
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.name == ".mmw-update.json":
            continue
        relative = path.relative_to(root).as_posix()
        manifest[relative] = _file_sha256(path)
    return manifest


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _free_port() -> int:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


def _wait_for_gui_health(
    port: int,
    expected_version: str,
    process,
    *,
    timeout: float = HEALTH_TIMEOUT_SECONDS,
    opener=urlopen,
) -> bool:
    deadline = time.monotonic() + timeout
    request = Request(f"http://127.0.0.1:{port}/api/health")
    while time.monotonic() < deadline:
        if process.poll() is not None:
            return False
        try:
            with opener(request, timeout=1) as response:
                payload = json.loads(response.read(4096))
            if payload == {"status": "ok", "version": expected_version}:
                return True
        except (OSError, ValueError, json.JSONDecodeError):
            pass
        time.sleep(0.1)
    return False


def _wait_for_port_free(port: int, timeout: float = HEALTH_TIMEOUT_SECONDS) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        with socket.socket() as probe:
            if probe.connect_ex(("127.0.0.1", port)) != 0:
                return True
        time.sleep(0.1)
    return False


def _stop_process(process) -> None:
    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


def preflight_candidate(
    executable: Path,
    expected_version: str,
    *,
    popen=subprocess.Popen,
) -> bool:
    port = _free_port()
    process = popen(
        [str(executable), "--mmw-health-server", str(port)],
        cwd=executable.parent,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        return _wait_for_gui_health(port, expected_version, process)
    finally:
        _stop_process(process)


def _write_update_status(path: Path, status: str, message: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(
            {
                "status": status,
                "message": message,
                "updated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    temporary.replace(path)


def switch_gui_version(
    candidate: Path,
    previous: Path,
    candidate_version: str,
    previous_version: str,
    port: int,
    status_path: Path,
    *,
    popen=subprocess.Popen,
) -> bool:
    if not _wait_for_port_free(port):
        _write_update_status(status_path, "unavailable", "旧服务未释放监听端口")
        return False

    try:
        process = popen(
            [str(candidate), "--mmw-health-server", str(port)],
            cwd=candidate.parent,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except OSError:
        process = None
    if process is not None and _wait_for_gui_health(port, candidate_version, process):
        _write_update_status(status_path, "completed", f"v{candidate_version} 已通过健康检查")
        return True
    if process is not None:
        _stop_process(process)

    try:
        rollback = popen(
            [str(previous), "--mmw-health-server", str(port)],
            cwd=previous.parent,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except OSError:
        _write_update_status(status_path, "unavailable", "新旧版本健康检查均失败")
        return False
    restored = _wait_for_gui_health(port, previous_version, rollback)
    if not restored:
        _stop_process(rollback)
    _write_update_status(
        status_path,
        "rolled_back" if restored else "unavailable",
        "新版本健康检查失败，已恢复旧版本" if restored else "新旧版本健康检查均失败",
    )
    return False


def update_helper_main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("mode", choices=("preflight", "switch"))
    parser.add_argument("candidate", type=Path)
    parser.add_argument("candidate_version")
    parser.add_argument("status_path", type=Path)
    parser.add_argument("--previous", type=Path)
    parser.add_argument("--previous-version", default=__version__)
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args(argv)
    try:
        if not 1 <= args.port <= 65535:
            raise ValueError("更新 helper 端口无效")
        if args.mode == "preflight":
            ok = preflight_candidate(args.candidate, args.candidate_version)
            _write_update_status(
                args.status_path,
                "preflight_passed" if ok else "preflight_failed",
                "候选版本预检通过" if ok else "候选版本 HTTP 健康检查失败",
            )
            return 0 if ok else 1
        if args.previous is None:
            raise ValueError("切换 helper 缺少旧版本路径")
        return 0 if switch_gui_version(
            args.candidate,
            args.previous,
            args.candidate_version,
            args.previous_version,
            args.port,
            args.status_path,
        ) else 1
    except (OSError, ValueError, subprocess.SubprocessError):
        _write_update_status(args.status_path, "failed", "更新 helper 执行失败")
        return 1
