"""仅监听本机的 MMW 浏览器 GUI 服务。"""

from __future__ import annotations

import json
import os
import re
import secrets
import subprocess
import sys
import threading
import webbrowser
from dataclasses import asdict, dataclass, field
from datetime import datetime
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse
from uuid import uuid4

from mmw.config import LLMConfig, get_settings
from mmw.gui.providers import (
    activate_profile,
    get_profile_secret,
    public_profiles,
    save_profile,
)
from mmw.models import STAGE_META, STAGE_ORDER, StageID
from mmw.pipeline.state_machine import PipelineStateMachine
from mmw.project import ProjectPaths, initialize_project, scan_project
from mmw.utils.checkpoint import CheckpointManager
from mmw.utils.file_io import read_json, read_yaml


@dataclass
class Job:
    id: str
    workspace: str
    stage: str
    status: str = "running"
    message: str = "任务已启动"
    started_at: str = field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))
    finished_at: str | None = None


class GuiApplication:
    def __init__(
        self,
        workspace_root: Path | None = None,
        env_path: Path | None = None,
        picker=None,
    ):
        self.workspace_root = (workspace_root or get_settings().workspace_dir).resolve()
        self.env_path = (env_path or Path(".env")).resolve()
        self.picker = picker or _native_folder_picker
        self.token = secrets.token_urlsafe(24)
        self.projects: dict[str, Path] = {}
        self.jobs: dict[str, Job] = {}
        self._workspace_jobs: dict[str, str] = {}
        self._lock = threading.Lock()
        self._picker_lock = threading.Lock()

    def workspace(self, name: str) -> Path:
        if name in self.projects:
            return self.projects[name]
        # 兼容旧式 CLI workspace；新 GUI 不向浏览器暴露任意路径入口。
        if not name or Path(name).name != name:
            raise ValueError("工作区名称非法")
        path = (self.workspace_root / name).resolve()
        if path.parent != self.workspace_root or not (path / "config.yaml").is_file():
            raise ValueError("工作区不存在")
        return path

    def pick_project(self) -> dict[str, Any]:
        if not self._picker_lock.acquire(blocking=False):
            raise ValueError("文件夹选择窗口已经打开")
        try:
            selected = self.picker(self.workspace_root if self.workspace_root.is_dir() else Path.home())
            if not selected:
                return {"selected": False}
            return {"selected": True, "project": self.register_project(Path(selected))}
        finally:
            self._picker_lock.release()

    def register_project(self, path: Path) -> dict[str, Any]:
        path = path.resolve()
        if getattr(sys, "frozen", False) and path.is_relative_to(Path(sys.executable).resolve().parent):
            raise ValueError("不能把 MMW 安装目录作为题目文件夹")
        project_id = next((key for key, value in self.projects.items() if value == path), uuid4().hex)
        self.projects[project_id] = path
        return {"project_id": project_id, **scan_project(path)}

    def initialize(self, project_id: str, problem_pdf: str) -> dict[str, Any]:
        initialize_project(self.workspace(project_id), problem_pdf)
        return self.workspace_summary(project_id)

    def list_workspaces(self) -> list[dict[str, Any]]:
        if not self.workspace_root.is_dir():
            return []
        result = []
        for path in sorted(self.workspace_root.iterdir(), key=lambda item: item.name.casefold()):
            if path.is_dir() and (path / "config.yaml").is_file():
                result.append(self.workspace_summary(path.name, compact=True))
        return result

    def workspace_summary(self, name: str, compact: bool = False) -> dict[str, Any]:
        workspace = self.workspace(name)
        paths = ProjectPaths(workspace)
        config = read_yaml(paths.config)
        mgr = CheckpointManager(workspace)
        sm = PipelineStateMachine(mgr)
        stages = mgr.get_pipeline_status()
        approved = sum(item["status"] == "approved" for item in stages)
        completed = sum(item["status"] in {"completed", "approved"} for item in stages)
        next_stage = sm.get_next_runnable()
        data_files = len(paths.data_files())
        problem_text = (
            paths.problem.read_text(encoding="utf-8")
            if paths.problem.is_file()
            else ""
        )
        base = {
            "project_id": name,
            "name": workspace.name,
            "title": config.get("title") or name,
            "year": config.get("year"),
            "problem": config.get("problem"),
            "path": str(workspace),
            "approved": approved,
            "completed": completed,
            "total": len(STAGE_ORDER),
            "next_stage": next_stage.value if next_stage else None,
            "problem_ready": bool(re.sub(r"<!--.*?-->", "", problem_text, flags=re.DOTALL).strip()),
            "data_files": data_files,
        }
        if compact:
            return base
        base.update(
            {
                "config": config,
                "stages": stages,
                "warnings": sm.get_warnings(),
                "running_job": self._workspace_jobs.get(name),
                "outputs": self._file_listing(workspace),
                "logs": self._logs(workspace),
            }
        )
        return base

    def stage_detail(self, name: str, stage_value: str, version: int | None = None) -> dict[str, Any]:
        workspace = self.workspace(name)
        stage = StageID(stage_value)
        mgr = CheckpointManager(workspace)
        latest = mgr.get_latest_version(stage)
        selected = version or mgr.get_active_version(stage) or latest
        versions = []
        for current in range(1, latest + 1):
            status = mgr.load_status(stage, current)
            meta = mgr.load_meta(stage, current)
            versions.append(
                {
                    "version": current,
                    "active": current == mgr.get_active_version(stage),
                    "status": status.status.value if status else "missing",
                    "created_at": meta.created_at.isoformat(timespec="seconds") if meta else None,
                    "model": meta.model_used if meta else None,
                }
            )
        status = mgr.load_status(stage, selected) if selected else None
        meta = mgr.load_meta(stage, selected) if selected else None
        sm = PipelineStateMachine(mgr)
        return {
            "stage": stage.value,
            "label": STAGE_META[stage]["label"],
            "selected_version": selected,
            "latest_version": latest,
            "active_version": mgr.get_active_version(stage) if latest else 0,
            "versions": versions,
            "status": status.model_dump(mode="json") if status else None,
            "meta": meta.model_dump(mode="json") if meta else None,
            "artifacts": mgr.load_artifacts(stage, selected) if selected else {},
            "quality_error": sm.quality_error(stage, selected) if selected else "",
        }

    def _logs(self, workspace: Path) -> list[dict[str, Any]]:
        result = []
        log_dir = ProjectPaths(workspace).logs
        if not log_dir.is_dir():
            return result
        for path in sorted(log_dir.glob("*.json"), key=lambda item: item.stat().st_mtime, reverse=True)[:30]:
            try:
                entry = read_json(path)
            except (OSError, ValueError):
                continue
            result.append(
                {
                    "file": path.name,
                    "timestamp": entry.get("timestamp", ""),
                    "model": entry.get("model", ""),
                    "input_tokens": entry.get("input_tokens", 0),
                    "output_tokens": entry.get("output_tokens", 0),
                }
            )
        return result

    def _file_listing(self, workspace: Path) -> list[dict[str, Any]]:
        paths = ProjectPaths(workspace)
        allowed_roots = [paths.output]
        result = []
        for root in allowed_roots:
            if not root.is_dir():
                continue
            for path in root.rglob("*"):
                if path.is_file():
                    result.append(
                        {
                            "name": path.name,
                            "path": path.relative_to(workspace).as_posix(),
                            "size": path.stat().st_size,
                        }
                    )
        return sorted(result, key=lambda item: item["path"])

    def start_run(self, name: str, stage_value: str) -> Job:
        self.workspace(name)
        with self._lock:
            active_id = self._workspace_jobs.get(name)
            if active_id and self.jobs[active_id].status == "running":
                raise ValueError("该工作区已有任务正在运行")
            job = Job(id=uuid4().hex, workspace=name, stage=stage_value)
            self.jobs[job.id] = job
            self._workspace_jobs[name] = job.id
        threading.Thread(target=self._run_job, args=(job,), daemon=True).start()
        return job

    def _run_job(self, job: Job) -> None:
        try:
            workspace = self.workspace(job.workspace)
            mgr = CheckpointManager(workspace)
            sm = PipelineStateMachine(mgr)
            stage = sm.get_next_runnable() if job.stage == "next" else StageID(job.stage)
            if stage is None:
                raise ValueError("当前没有可运行阶段")
            can_run, reason = sm.can_run(stage)
            if not can_run:
                raise ValueError(reason)
            job.stage = stage.value
            from mmw.cli import _run_stage

            if _run_stage(stage, workspace, mgr) is False:
                raise RuntimeError("阶段执行失败，请查看工作区日志")
            job.status = "completed"
            job.message = f"{STAGE_META[stage]['label']}执行完成，等待审批"
        except ValueError as exc:
            job.status = "failed"
            job.message = str(exc)
        except Exception as exc:  # 不把供应商响应、prompt 或密钥带回浏览器
            job.status = "failed"
            job.message = f"{exc.__class__.__name__}，请查看工作区日志"
        finally:
            job.finished_at = datetime.now().isoformat(timespec="seconds")
            with self._lock:
                self._workspace_jobs.pop(job.workspace, None)

    def approve(self, name: str, stage_value: str, version: int | None) -> dict[str, Any]:
        workspace = self.workspace(name)
        stage = StageID(stage_value)
        mgr = CheckpointManager(workspace)
        sm = PipelineStateMachine(mgr)
        if version is not None and mgr.is_approved(stage, version):
            mgr.set_active_version(stage, version)
            return {"message": f"{stage.value} 已切换到 v{version}"}
        can_approve, reason = sm.can_approve(stage, version)
        if not can_approve:
            raise ValueError(reason)
        mgr.approve(stage, version=version)
        return {"message": f"{stage.value} v{version or mgr.get_latest_version(stage)} 已审批并激活"}

    def rework(self, name: str, stage_value: str) -> dict[str, Any]:
        workspace = self.workspace(name)
        stage = StageID(stage_value)
        affected = PipelineStateMachine(CheckpointManager(workspace)).apply_rework(stage)
        return {"message": f"{stage.value} 已标记重做", "affected": affected}

    def ack(self, name: str, stage_value: str) -> dict[str, Any]:
        workspace = self.workspace(name)
        stage = StageID(stage_value)
        if not CheckpointManager(workspace).ack_upstream(stage):
            raise ValueError("该阶段没有可确认的上游变更")
        return {"message": f"{stage.value} 的上游变更警告已清除"}

    def open_path(self, name: str, relative: str = "", folder: bool = False) -> dict[str, Any]:
        workspace = self.workspace(name)
        if relative:
            output = ProjectPaths(workspace).output.resolve()
            target = (workspace / relative).resolve()
            if not target.is_relative_to(output) or not target.is_file():
                raise ValueError("只能打开 output/ 中已有的文件")
            if folder:
                target = target.parent
        else:
            target = workspace
        if os.name == "nt":
            os.startfile(target)  # type: ignore[attr-defined]
        else:
            subprocess.Popen(["open" if sys.platform == "darwin" else "xdg-open", str(target)])
        return {"message": "已在本机打开"}


class GuiHandler(BaseHTTPRequestHandler):
    server: "GuiServer"

    def log_message(self, format: str, *args: object) -> None:
        return

    def _send_json(self, payload: Any, status: int = 200) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _error(self, exc: Exception, status: int = 400) -> None:
        self._send_json({"error": str(exc) or exc.__class__.__name__}, status)

    def _body(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0"))
        if length > 1_000_000:
            raise ValueError("请求体过大")
        data = json.loads(self.rfile.read(length) or b"{}")
        if not isinstance(data, dict):
            raise ValueError("请求体必须是 JSON 对象")
        return data

    def _authorized(self) -> bool:
        return secrets.compare_digest(self.headers.get("X-MMW-Token", ""), self.server.app.token)

    def do_GET(self) -> None:
        try:
            parsed = urlparse(self.path)
            parts = [unquote(part) for part in parsed.path.split("/") if part]
            app = self.server.app
            if parsed.path == "/":
                path = Path(__file__).parent / "static" / "index.html"
                body = path.read_text(encoding="utf-8").replace("__MMW_TOKEN__", app.token).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(body)
            elif parts == ["api", "workspaces"]:
                self._send_json({"root": str(app.workspace_root), "workspaces": app.list_workspaces()})
            elif len(parts) == 3 and parts[:2] == ["api", "projects"]:
                self._send_json(app.workspace_summary(parts[2]))
            elif len(parts) == 5 and parts[:2] == ["api", "projects"] and parts[3] == "stages":
                query = dict(item.split("=", 1) for item in parsed.query.split("&") if "=" in item)
                version = int(query["version"]) if query.get("version") else None
                self._send_json(app.stage_detail(parts[2], parts[4], version))
            elif len(parts) == 3 and parts[:2] == ["api", "workspaces"]:
                self._send_json(app.workspace_summary(parts[2]))
            elif len(parts) == 5 and parts[:2] == ["api", "workspaces"] and parts[3] == "stages":
                query = dict(item.split("=", 1) for item in parsed.query.split("&") if "=" in item)
                version = int(query["version"]) if query.get("version") else None
                self._send_json(app.stage_detail(parts[2], parts[4], version))
            elif len(parts) == 3 and parts[:2] == ["api", "jobs"]:
                job = app.jobs.get(parts[2])
                if not job:
                    raise ValueError("任务不存在")
                self._send_json(asdict(job))
            elif parts == ["api", "providers"]:
                self._send_json(public_profiles(app.env_path))
            else:
                self._send_json({"error": "Not found"}, 404)
        except (ValueError, OSError, KeyError) as exc:
            self._error(exc)

    def do_POST(self) -> None:
        if not self._authorized():
            self._send_json({"error": "无效会话令牌"}, HTTPStatus.FORBIDDEN)
            return
        try:
            parts = [unquote(part) for part in urlparse(self.path).path.split("/") if part]
            body = self._body()
            app = self.server.app
            if parts == ["api", "projects", "pick"]:
                result = app.pick_project()
            elif len(parts) == 4 and parts[:2] == ["api", "projects"]:
                name, action = parts[2], parts[3]
                if action == "start":
                    workspace = app.workspace(name)
                    if not ProjectPaths(workspace).config.is_file():
                        app.initialize(name, str(body.get("problem_pdf", "")))
                    result = asdict(app.start_run(name, str(body.get("stage", "next"))))
                elif action == "initialize":
                    result = app.initialize(name, str(body.get("problem_pdf", "")))
                elif action == "approve":
                    version = int(body["version"]) if body.get("version") is not None else None
                    result = app.approve(name, str(body.get("stage", "")), version)
                elif action == "rework":
                    result = app.rework(name, str(body.get("stage", "")))
                elif action == "ack":
                    result = app.ack(name, str(body.get("stage", "")))
                elif action == "open":
                    result = app.open_path(
                        name,
                        str(body.get("path", "")),
                        bool(body.get("folder", False)),
                    )
                else:
                    raise ValueError("未知项目操作")
            elif len(parts) == 4 and parts[:2] == ["api", "workspaces"]:
                name, action = parts[2], parts[3]
                if action == "run":
                    result = asdict(app.start_run(name, str(body.get("stage", "next"))))
                elif action == "approve":
                    version = int(body["version"]) if body.get("version") is not None else None
                    result = app.approve(name, str(body.get("stage", "")), version)
                elif action == "rework":
                    result = app.rework(name, str(body.get("stage", "")))
                elif action == "ack":
                    result = app.ack(name, str(body.get("stage", "")))
                else:
                    raise ValueError("未知工作区操作")
            elif parts == ["api", "providers", "save"]:
                result = save_profile(app.env_path, body)
            elif parts == ["api", "providers", "activate"]:
                result = activate_profile(app.env_path, str(body.get("id", "")))
            elif parts in (["api", "providers", "test"], ["api", "providers", "discover"]):
                profile = self._provider_payload(body)
                config = LLMConfig(
                    api_key=str(profile["api_key"]),
                    base_url=str(profile["base_url"]),
                    model=str(profile.get("default_model") or profile.get("model") or ""),
                )
                if parts[-1] == "test":
                    from mmw.cli import _probe_llm_config

                    ok, detail = _probe_llm_config(config)
                    if not ok:
                        raise ValueError(detail)
                    result = {"ok": True, "message": detail}
                else:
                    from openai import OpenAI

                    models = sorted(item.id for item in OpenAI(api_key=config.api_key, base_url=config.base_url).models.list())
                    result = {"models": models}
            else:
                raise ValueError("未知操作")
            self._send_json(result)
        except (ValueError, OSError, KeyError, json.JSONDecodeError) as exc:
            self._error(exc)
        except Exception as exc:
            status = getattr(exc, "status_code", None)
            detail = f"{exc.__class__.__name__}" + (f" (HTTP {status})" if status else "")
            self._error(ValueError(detail))

    def _provider_payload(self, body: dict[str, Any]) -> dict[str, Any]:
        if body.get("id") and not body.get("api_key"):
            saved = get_profile_secret(self.server.app.env_path, str(body["id"]))
            return {**saved, **body, "api_key": saved["api_key"]}
        if not body.get("api_key") or not body.get("base_url"):
            raise ValueError("API Key 和 Base URL 不能为空")
        return body


def _native_folder_picker(initial: Path) -> str:
    """由本机进程打开文件夹选择器，浏览器不接触绝对路径输入。"""
    import tkinter as tk
    from tkinter import filedialog

    root = tk.Tk()
    root.withdraw()
    root.attributes("-topmost", True)
    root.update()
    try:
        return filedialog.askdirectory(
            parent=root,
            initialdir=str(initial),
            title="选择数学建模题目文件夹",
            mustexist=True,
        )
    finally:
        root.destroy()


class GuiServer(ThreadingHTTPServer):
    def __init__(self, address: tuple[str, int], app: GuiApplication):
        super().__init__(address, GuiHandler)
        self.app = app


def serve_gui(port: int = 8765, open_browser: bool = True) -> None:
    app = GuiApplication()
    server = GuiServer(("127.0.0.1", port), app)
    url = f"http://127.0.0.1:{server.server_port}/"
    print(f"MMW GUI: {url}")
    if open_browser:
        threading.Timer(0.3, webbrowser.open, args=(url,)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
