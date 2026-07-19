"""检查点版本树管理。

每个阶段的产出保存在 workspace/<竞赛>/checkpoints/<阶段目录>/v<N>/ 下。
每个版本目录包含产出文件 + meta.json + status.json。
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
import time
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

import yaml

from mmw.models import (
    STAGE_META,
    STAGE_ORDER,
    CheckpointStatus,
    MetaData,
    StageID,
    StageResult,
    StatusData,
)


class CheckpointManager:
    """管理检查点的保存、加载、审批和版本追踪。"""

    def __init__(self, workspace: Path):
        self.workspace = workspace
        self.checkpoint_dir = workspace / "checkpoints"

    def _stage_dir(self, stage: StageID) -> Path:
        return self.checkpoint_dir / STAGE_META[stage]["dir"]

    def _version_dir(self, stage: StageID, version: int) -> Path:
        return self._stage_dir(stage) / f"v{version}"

    # ── 版本管理 ───────────────────────────────────────────

    def get_latest_version(self, stage: StageID) -> int:
        """获取阶段的最新版本号，无版本返回 0。"""
        stage_dir = self._stage_dir(stage)
        if not stage_dir.exists():
            return 0
        versions = [
            int(d.name[1:])
            for d in stage_dir.iterdir()
            if d.is_dir() and d.name.startswith("v") and d.name[1:].isdigit()
        ]
        return max(versions) if versions else 0

    def get_next_version(self, stage: StageID) -> int:
        return self.get_latest_version(stage) + 1

    def get_latest_approved_version(self, stage: StageID) -> int:
        for version in range(self.get_latest_version(stage), 0, -1):
            status = self.load_status(stage, version)
            if status is not None and status.status == CheckpointStatus.APPROVED:
                return version
        return 0

    # ── 激活版本（branch 多方案支持）──────────────────────

    def get_active_version(self, stage: StageID) -> int:
        """获取阶段的激活版本：优先读 config.yaml 的 active_versions，无则用最新版。

        三重容错：config.yaml 缺失 / active_versions 键缺失 / 指定的版本目录已删，
        均回退到最新版本。
        """
        latest = self.get_latest_version(stage)
        fallback = self.get_latest_approved_version(stage) or latest
        config_path = self.workspace / "config.yaml"
        if not config_path.exists():
            return fallback
        try:
            from mmw.utils.file_io import read_yaml

            active = read_yaml(config_path).get("active_versions", {}) or {}
            version = int(active.get(stage.value, 0))
        except (OSError, yaml.YAMLError, TypeError, ValueError, AttributeError):
            return fallback
        if version <= 0 or not self._version_dir(stage, version).exists():
            return fallback
        return version

    def set_active_version(self, stage: StageID, version: int) -> None:
        """把阶段的激活版本写入 config.yaml 的 active_versions。"""
        from mmw.utils.file_io import read_yaml, write_yaml

        config_path = self.workspace / "config.yaml"
        if not config_path.exists():
            return  # 无配置文件（如测试环境）时静默跳过，激活语义回退 latest
        cfg = read_yaml(config_path)
        cfg.setdefault("active_versions", {})
        cfg["active_versions"][stage.value] = version
        write_yaml(config_path, cfg)

    # ── 保存 ──────────────────────────────────────────────

    def save(
        self,
        stage: StageID,
        artifacts: dict[str, str | bytes],
        meta: MetaData,
    ) -> Path:
        """保存阶段产出到新版本目录。返回版本目录路径。"""
        with self._version_lock():
            version = self.get_next_version(stage)
            meta.version = version
            meta.upstream_versions = self._active_upstream_versions(stage)
            stage_dir = self._stage_dir(stage)
            stage_dir.mkdir(parents=True, exist_ok=True)
            tmp = Path(tempfile.mkdtemp(prefix=f".v{version}-", dir=stage_dir))
            vdir = self._version_dir(stage, version)
            try:
                for name, content in artifacts.items():
                    fpath = (tmp / name).resolve()
                    if not fpath.is_relative_to(tmp.resolve()):
                        raise ValueError(f"非法的产出文件名: {name}")
                    fpath.parent.mkdir(parents=True, exist_ok=True)
                    if isinstance(content, bytes):
                        fpath.write_bytes(content)
                    else:
                        fpath.write_text(content, encoding="utf-8")
                (tmp / "meta.json").write_text(meta.model_dump_json(indent=2), encoding="utf-8")
                status = StatusData(
                    status=CheckpointStatus.COMPLETED,
                    upstream_hash=self._compute_upstream_hash(stage),
                )
                (tmp / "status.json").write_text(status.model_dump_json(indent=2), encoding="utf-8")
                for attempt in range(3):
                    try:
                        tmp.replace(vdir)
                        break
                    except PermissionError:
                        if attempt == 2:
                            raise
                        time.sleep(0.1)
            except Exception:
                import shutil
                shutil.rmtree(tmp, ignore_errors=True)
                raise
            return vdir

    @contextmanager
    def _version_lock(self):
        """ponytail: 单个 workspace 全局锁；并发量需要时再拆成按阶段锁。"""
        self.checkpoint_dir.mkdir(parents=True, exist_ok=True)
        lock_path = self.checkpoint_dir / ".version.lock"
        with lock_path.open("a+b") as lock:
            lock.seek(0)
            if os.name == "nt":
                import msvcrt
                lock.seek(0, 2)
                if lock.tell() == 0:
                    lock.write(b"0")
                    lock.flush()
                lock.seek(0)
                msvcrt.locking(lock.fileno(), msvcrt.LK_LOCK, 1)
                try:
                    yield
                finally:
                    lock.seek(0)
                    msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
                try:
                    yield
                finally:
                    fcntl.flock(lock.fileno(), fcntl.LOCK_UN)

    def _active_upstream_versions(self, stage: StageID) -> dict[str, int]:
        idx = STAGE_ORDER.index(stage)
        return {
            upstream.value: self.get_active_version(upstream)
            for upstream in STAGE_ORDER[:idx]
            if self.get_active_version(upstream) > 0
        }

    # ── 加载 ──────────────────────────────────────────────

    def load_artifacts(
        self, stage: StageID, version: int | None = None
    ) -> dict[str, str]:
        """加载阶段产出文件。version=None 时用激活版本（无激活记录则最新版）。"""
        if version is None:
            version = self.get_active_version(stage)
        if version == 0:
            return {}
        vdir = self._version_dir(stage, version)
        if not vdir.exists():
            return {}
        artifacts = {}
        for fpath in vdir.rglob("*"):
            if not fpath.is_file():
                continue
            if fpath.name in ("meta.json", "status.json"):
                continue
            # 跳过缓存目录与二进制文件（如误入检查点的 __pycache__/*.pyc）
            if "__pycache__" in fpath.parts:
                continue
            rel = fpath.relative_to(vdir).as_posix()
            try:
                artifacts[rel] = fpath.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                from mmw.utils.display import print_error

                print_error(f"检查点文件 {rel} 不是 UTF-8 文本，已跳过加载")
        return artifacts

    def load_status(
        self, stage: StageID, version: int | None = None
    ) -> StatusData | None:
        """加载阶段状态。version=None 时用激活版本。"""
        if version is None:
            version = self.get_active_version(stage)
        if version == 0:
            return None
        status_path = self._version_dir(stage, version) / "status.json"
        if not status_path.exists():
            return None
        return StatusData.model_validate_json(status_path.read_text(encoding="utf-8"))

    def load_meta(
        self, stage: StageID, version: int | None = None
    ) -> MetaData | None:
        """加载阶段元数据。version=None 时用激活版本。"""
        if version is None:
            version = self.get_active_version(stage)
        if version == 0:
            return None
        meta_path = self._version_dir(stage, version) / "meta.json"
        if not meta_path.exists():
            return None
        return MetaData.model_validate_json(meta_path.read_text(encoding="utf-8"))

    # ── 审批 ──────────────────────────────────────────────

    def approve(
        self,
        stage: StageID,
        result: StageResult = StageResult.PROCEED,
        rework_target: str | None = None,
        version: int | None = None,
    ) -> None:
        """审批阶段，标记状态为 approved。"""
        if version is None:
            version = self.get_latest_version(stage)
        status_path = self._version_dir(stage, version) / "status.json"
        status = StatusData(
            status=CheckpointStatus.APPROVED,
            result=result,
            rework_target=rework_target,
            upstream_hash=self._compute_upstream_hash(stage),
            upstream_changed=False,
            approved_by="手动",
            approved_at=datetime.now(),
        )
        old_status = status_path.read_text(encoding="utf-8")
        status_path.write_text(status.model_dump_json(indent=2), encoding="utf-8")
        try:
            self.set_active_version(stage, version)
        except (OSError, yaml.YAMLError):
            status_path.write_text(old_status, encoding="utf-8")
            raise
        self.refresh_upstream_flags()

    def is_approved(self, stage: StageID, version: int | None = None) -> bool:
        """检查阶段是否已审批。"""
        status = self.load_status(stage, version)
        if status is None:
            return False
        return status.status == CheckpointStatus.APPROVED

    def mark_pending(self, stage: StageID) -> bool:
        version = self.get_latest_version(stage)
        if not version:
            return False
        status = self.load_status(stage, version)
        if status is None:
            return False
        status.status = CheckpointStatus.PENDING
        status.result = StageResult.REWORK
        status.rework_target = stage.value
        self._version_dir(stage, version).joinpath("status.json").write_text(
            status.model_dump_json(indent=2), encoding="utf-8"
        )
        return True

    def mark_upstream_changed(self, stage: StageID) -> bool:
        version = self.get_latest_version(stage)
        status = self.load_status(stage, version) if version else None
        if status is None:
            return False
        status.upstream_changed = True
        self._version_dir(stage, version).joinpath("status.json").write_text(
            status.model_dump_json(indent=2), encoding="utf-8"
        )
        return True

    # ── 上游变更检测 ─────────────────────────────────────

    def _compute_upstream_hash(self, stage: StageID) -> str:
        """计算当前阶段所有上游检查点的内容 hash。"""
        from mmw.models import STAGE_ORDER

        idx = STAGE_ORDER.index(stage)
        hash_parts: list[str] = []
        for upstream_stage in STAGE_ORDER[:idx]:
            # 用激活版本而非最新版：branch 出新版但未激活时，不应触发下游 upstream_changed
            version = self.get_active_version(upstream_stage)
            if version == 0:
                continue
            vdir = self._version_dir(upstream_stage, version)
            for fpath in sorted(vdir.rglob("*")):
                if fpath.name == "status.json" or not fpath.is_file():
                    continue
                content = fpath.read_bytes()
                hash_parts.append(hashlib.md5(content).hexdigest())
        combined = ":".join(hash_parts)
        return hashlib.md5(combined.encode()).hexdigest()

    def check_upstream_changed(self, stage: StageID, version: int | None = None) -> bool:
        """检查上游是否在本阶段审批后发生了变更。"""
        status = self.load_status(stage, version)
        if status is None or status.upstream_hash is None:
            return False
        current_hash = self._compute_upstream_hash(stage)
        return current_hash != status.upstream_hash

    def ack_upstream(self, stage: StageID) -> bool:
        """人工确认上游变更对本阶段无影响：刷新 upstream_hash 并清除变更标记。

        作用于 active 版本（与流水线实际读取口径一致）。返回是否成功。
        """
        version = self.get_active_version(stage)
        if version == 0:
            return False
        status = self.load_status(stage, version)
        if status is None:
            return False
        status.upstream_hash = self._compute_upstream_hash(stage)
        status.upstream_changed = False
        status_path = self._version_dir(stage, version) / "status.json"
        status_path.write_text(status.model_dump_json(indent=2), encoding="utf-8")
        return True

    def refresh_upstream_flags(self) -> dict[str, bool]:
        """刷新所有阶段的 upstream_changed 标记，返回变更情况。"""
        from mmw.models import STAGE_ORDER

        changes: dict[str, bool] = {}
        for stage in STAGE_ORDER:
            version = self.get_active_version(stage)
            if version == 0:
                continue
            changed = self.check_upstream_changed(stage, version)
            changes[stage.value] = changed
            status_path = self._version_dir(stage, version) / "status.json"
            status = self.load_status(stage, version)
            if status is not None and status.upstream_changed != changed:
                status.upstream_changed = changed
                status_path.write_text(
                    status.model_dump_json(indent=2), encoding="utf-8"
                )
        return changes

    # ── 概览 ──────────────────────────────────────────────

    def get_pipeline_status(self) -> list[dict]:
        """返回所有阶段的状态概览。"""
        from mmw.models import STAGE_ORDER

        result = []
        for stage in STAGE_ORDER:
            version = self.get_latest_version(stage)
            meta = STAGE_META[stage]
            entry = {
                "stage": stage.value,
                "label": meta["label"],
                "index": meta["index"],
                "version": version,
                "active_version": self.get_active_version(stage) if version > 0 else 0,
                "status": "pending",
                "upstream_changed": False,
            }
            if version > 0:
                status = self.load_status(stage, version)
                if status is not None:
                    entry["status"] = status.status.value
                active_status = self.load_status(stage, entry["active_version"])
                if active_status is not None:
                    entry["upstream_changed"] = active_status.upstream_changed
            result.append(entry)
        return result
