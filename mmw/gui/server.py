"""仅监听本机的 MMW 浏览器 GUI 服务。"""

from __future__ import annotations

import json
import os
import re
import secrets
import subprocess
import sys
import threading
import time
import webbrowser
from dataclasses import asdict, dataclass, field
from datetime import datetime
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse
from uuid import uuid4

from mmw import __version__
from mmw.config import LLMConfig, get_settings
from mmw.gui.providers import (
    activate_codex,
    activate_profile,
    get_profile_secret,
    public_profiles,
    save_profile,
)
from mmw.managed_run import load_managed_run, run_managed_pipeline
from mmw.models import STAGE_META, STAGE_ORDER, StageID
from mmw.update import check_for_update, install_latest_update
from mmw.pipeline.state_machine import PipelineStateMachine
from mmw.project import ProjectPaths, initialize_project, scan_project
from mmw.utils.checkpoint import CheckpointManager
from mmw.utils.file_io import read_json, read_yaml, write_json, write_yaml

STAGE_CHECKLISTS = {
    "analyze": ["子问题完整", "目标与约束正确", "硬性交付物无遗漏"],
    "eda": ["表头与单位正确", "缺失/异常值处理合理", "图表与原始数据一致"],
    "research": ["方法适用于题目", "来源真实可追溯", "没有把近似结论当作事实"],
    "model": ["假设可接受", "公式与量纲正确", "参数可标定且覆盖全部子问题"],
    "code": ["只读取真实附件", "没有默认值或占位结果", "运行历史与结构化输出完整"],
    "solve": ["数量级合理", "全部硬约束复算通过", "重复性与灵敏度可信"],
    "paper": ["摘要回答全部问题", "数值都有出处", "图表与引用完整"],
    "review": ["清单无失败项", "数值审计通过", "最终 benchmark 与当前版本绑定"],
}


@dataclass
class Job:
    id: str
    workspace: str
    stage: str
    kind: str = "stage"
    status: str = "running"
    message: str = "任务已启动"
    progress_mode: str = "indeterminate"
    progress: float | None = None
    current_step: str = "准备任务"
    step_index: int = 1
    step_total: int = 1
    started_at: str = field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))
    updated_at: str = field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))
    finished_at: str | None = None
    result: dict[str, Any] | None = None


class GuiApplication:
    def __init__(
        self,
        workspace_root: Path | None = None,
        env_path: Path | None = None,
        picker=None,
        recent_path: Path | None = None,
    ):
        self.workspace_root = (workspace_root or get_settings().workspace_dir).resolve()
        self.env_path = (env_path or Path(".env")).resolve()
        local_state = (
            Path(os.environ["APPDATA"]) / "MMW"
            if os.environ.get("APPDATA")
            else Path.home() / ".mmw"
        )
        self.recent_path = (recent_path or local_state / "recent-projects.json").resolve()
        self.picker = picker or _native_folder_picker
        self.token = secrets.token_urlsafe(24)
        self.projects: dict[str, Path] = {}
        self.jobs: dict[str, Job] = {}
        self._workspace_jobs: dict[str, str] = {}
        self._last_jobs: dict[str, Job] = {}
        self._lock = threading.Lock()
        self._picker_lock = threading.Lock()
        self._restore_recent_projects()

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
        summary = scan_project(path)
        project_id = next((key for key, value in self.projects.items() if value == path), uuid4().hex)
        self.projects.pop(project_id, None)
        self.projects[project_id] = path
        while len(self.projects) > 10:
            self.projects.pop(next(iter(self.projects)))
        self._save_recent_projects()
        return {"project_id": project_id, **summary}

    def list_projects(self) -> list[dict[str, Any]]:
        result = []
        for project_id, path in self.projects.items():
            try:
                result.append({"project_id": project_id, **scan_project(path)})
            except (OSError, ValueError):
                continue
        return result

    def _restore_recent_projects(self) -> None:
        if not self.recent_path.is_file():
            return
        try:
            data = read_json(self.recent_path)
        except (OSError, ValueError):
            return
        if not isinstance(data, dict) or not isinstance(data.get("projects"), list):
            return
        entries = data["projects"]
        for entry in entries[-10:]:
            if not isinstance(entry, dict):
                continue
            raw_path = entry.get("path")
            if not isinstance(raw_path, str) or not raw_path.strip():
                continue
            candidate = Path(raw_path)
            if not candidate.is_absolute() or str(candidate).startswith("\\\\"):
                continue
            try:
                path = candidate.resolve()
            except (OSError, ValueError):
                continue
            if path.is_dir() and ProjectPaths(path).config.is_file():
                self.projects[uuid4().hex] = path

    def _save_recent_projects(self) -> None:
        write_json(
            self.recent_path,
            {
                "projects": [
                    {"path": str(path), "last_opened": datetime.now().isoformat(timespec="seconds")}
                    for path in self.projects.values()
                ]
            },
        )

    def initialize(self, project_id: str, problem_file: str) -> dict[str, Any]:
        initialize_project(self.workspace(project_id), problem_file)
        return self.workspace_summary(project_id)

    def list_workspaces(self) -> list[dict[str, Any]]:
        if not self.workspace_root.is_dir():
            return []
        result = []
        for path in sorted(self.workspace_root.iterdir(), key=lambda item: item.name.casefold()):
            if path.is_dir() and (path / "config.yaml").is_file():
                result.append(self.workspace_summary(path.name, compact=True))
        return result

    def update_status(self) -> dict[str, Any]:
        active = next(
            (
                asdict(job)
                for job in self.jobs.values()
                if job.kind == "update" and job.status == "running"
            ),
            None,
        )
        if active:
            return {
                "current": __version__,
                "latest": "",
                "available": True,
                "installable": True,
                "release_url": "",
                "active_job": active,
            }
        try:
            return {**check_for_update(), "active_job": None}
        except (OSError, ValueError):
            return {
                "current": __version__,
                "latest": "",
                "available": False,
                "installable": False,
                "release_url": "",
                "error": "暂时无法检查更新",
                "active_job": None,
            }

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
                "figure_backends": self.figure_backends(name),
                "stages": stages,
                "warnings": sm.get_warnings(),
                "running_job": self._workspace_jobs.get(name),
                "active_job": self._active_job(name),
                "last_job": self._last_job(name),
                "outputs": self._file_listing(workspace),
                "logs": self._logs(workspace),
                "validation": self.validation_summary(name),
                "managed_run": self.managed_run_summary(name),
            }
        )
        return base

    def figure_backends(self, name: str) -> dict[str, Any]:
        from mmw.utils.origin_renderer import origin_status

        config = read_yaml(ProjectPaths(self.workspace(name)).config)
        status = origin_status()
        return {
            "selected": config.get("figure_backend", "matplotlib"),
            "origin": {
                "available": status["available"],
                "originpro_version": status["originpro_version"],
                "reason": status["reason"],
            },
        }

    def set_figure_backend(self, name: str, backend: str) -> dict[str, Any]:
        if backend not in {"matplotlib", "origin"}:
            raise ValueError("绘图后端只支持 matplotlib 或 origin")
        paths = ProjectPaths(self.workspace(name))
        config = read_yaml(paths.config)
        if backend == "origin":
            from mmw.utils.origin_renderer import origin_status

            if not origin_status()["available"]:
                raise ValueError("Origin 后端不可用，请确认已安装 Origin 2024")
        config["figure_backend"] = backend
        write_yaml(paths.config, config)
        return {"figure_backend": backend}

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
        quality_error = sm.quality_error(stage, selected) if selected else ""
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
            "quality_error": quality_error,
            "checklist": STAGE_CHECKLISTS[stage.value],
            "recommendation": self._rework_recommendation(stage, quality_error),
            "active_job": self._active_job(name),
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
            job = self._new_job_locked(name, stage_value, "stage", "阶段任务已启动")
        self._launch_job(job, self._run_job)
        return job

    def start_managed_run(
        self,
        name: str,
        max_stage_reworks: int = 2,
        max_total_reworks: int = 8,
        max_total_tokens: int = 0,
        max_total_minutes: int = 0,
        resume: bool = False,
    ) -> Job:
        if (
            not 0 <= max_stage_reworks <= 10
            or not 0 <= max_total_reworks <= 40
            or not 0 <= max_total_tokens <= 100_000_000
            or not 0 <= max_total_minutes <= 10_080
        ):
            raise ValueError("托管重做预算超出允许范围")
        workspace = self.workspace(name)
        previous = self.managed_run_summary(name)
        if resume and previous.get("status") != "waiting_user":
            raise ValueError("没有可恢复的托管任务")
        with self._lock:
            job = self._new_job_locked(name, "managed-run", "managed", "托管任务已启动")
            job.step_total = len(STAGE_ORDER) + 1
            job.result = {
                "max_stage_reworks": max_stage_reworks,
                "max_total_reworks": max_total_reworks,
                "max_total_tokens": max_total_tokens,
                "max_total_minutes": max_total_minutes,
                "run_id": previous.get("run_id") if resume else None,
            }
        self._launch_job(job, self._run_managed_job)
        return job

    def managed_run_summary(self, name: str) -> dict[str, Any]:
        workspace = self.workspace(name)
        state = load_managed_run(workspace)
        if state.get("status") == "running" and not self._active_job(name):
            state.update({
                "status": "waiting_user",
                "last_action": "interrupted",
                "last_error": "上次进程已中断，请确认后恢复托管",
                "finished_at": datetime.now().astimezone().isoformat(timespec="seconds"),
            })
            write_json(ProjectPaths(workspace).internal / "managed-run.json", state)
        return state

    def _run_managed_job(self, job: Job) -> None:
        workspace: Path | None = None
        try:
            workspace = self.workspace(job.workspace)
            mgr = CheckpointManager(workspace)
            options = job.result or {}

            def report(
                stage: StageID | None,
                status: str,
                message: str,
                index: int,
                total: int,
            ) -> None:
                self._update_job(
                    job,
                    stage=stage.value if stage else "finalize",
                    current_step=message,
                    step_index=index,
                    step_total=total,
                )

            def finalize() -> None:
                for command in ("compile", "export"):
                    result = subprocess.run(
                        [
                            sys.executable,
                            "-m",
                            "mmw.cli",
                            command,
                            "--workspace",
                            str(workspace),
                        ],
                        cwd=Path(__file__).resolve().parent.parent.parent,
                        capture_output=True,
                        text=True,
                        encoding="utf-8",
                        errors="replace",
                        timeout=600,
                    )
                    if result.returncode:
                        lines = (result.stdout + "\n" + result.stderr).strip().splitlines()
                        raise ValueError(lines[-1] if lines else f"{command} 执行失败")

            from mmw.cli import _run_stage

            state = run_managed_pipeline(
                workspace,
                mgr,
                _run_stage,
                self._record_decision,
                report,
                finalize,
                max_stage_reworks=int(options.get("max_stage_reworks", 2)),
                max_total_reworks=int(options.get("max_total_reworks", 8)),
                max_total_tokens=int(options.get("max_total_tokens", 0)),
                max_total_minutes=int(options.get("max_total_minutes", 0)),
                run_id=options.get("run_id"),
            )
            job.result = state
            job.status = state["status"]
            job.message = (
                "托管运行完成，已生成论文和提交包"
                if job.status == "completed"
                else f"托管运行已暂停：{state['last_error']}"
            )
        except subprocess.TimeoutExpired:
            job.status = "timed_out"
            job.message = "最终工具超过 10 分钟，已停止"
            if workspace:
                self._persist_managed_failure(workspace, job.status, job.message)
        except (ValueError, OSError, subprocess.SubprocessError) as exc:
            job.status = "failed"
            job.message = str(exc)
            if workspace:
                self._persist_managed_failure(workspace, job.status, job.message)
        except Exception as exc:
            job.status = "failed"
            job.message = f"{exc.__class__.__name__}，请查看工作区日志"
            if workspace:
                self._persist_managed_failure(workspace, job.status, job.message)
        finally:
            self._finish_job(job)

    @staticmethod
    def _persist_managed_failure(workspace: Path, status: str, message: str) -> None:
        state = load_managed_run(workspace)
        state.update({
            "status": status,
            "last_action": "failed",
            "last_error": message,
            "finished_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        })
        write_json(ProjectPaths(workspace).internal / "managed-run.json", state)

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
            self._update_job(
                job,
                current_step=f"执行{STAGE_META[stage]['label']} Agent 与质量检查",
                step_index=2,
                step_total=3,
            )
            from mmw.cli import _run_stage

            if _run_stage(stage, workspace, mgr) is False:
                raise RuntimeError("阶段执行失败，请查看工作区日志")
            self._update_job(job, current_step="保存检查点并刷新状态", step_index=3, step_total=3)
            job.status = "completed"
            job.message = f"{STAGE_META[stage]['label']}执行完成，等待审批"
        except ValueError as exc:
            job.status = "failed"
            job.message = str(exc)
        except Exception as exc:  # 不把供应商响应、prompt 或密钥带回浏览器
            job.status = "failed"
            job.message = f"{exc.__class__.__name__}，请查看工作区日志"
        finally:
            self._finish_job(job)

    def approve(self, name: str, stage_value: str, version: int | None, reason: str) -> dict[str, Any]:
        decision_reason = self._decision_reason(reason)
        workspace = self.workspace(name)
        self._ensure_idle(name)
        stage = StageID(stage_value)
        mgr = CheckpointManager(workspace)
        sm = PipelineStateMachine(mgr)
        if version is not None and mgr.is_approved(stage, version):
            mgr.set_active_version(stage, version)
            self._record_decision(workspace, stage, version, "activate", decision_reason)
            return {"message": f"{stage.value} 已切换到 v{version}"}
        can_approve, gate_reason = sm.can_approve(stage, version)
        if not can_approve:
            raise ValueError(gate_reason)
        mgr.approve(stage, version=version)
        selected = version or mgr.get_latest_version(stage)
        self._record_decision(workspace, stage, selected, "approve", decision_reason)
        return {"message": f"{stage.value} v{selected} 已审批并激活"}

    def rework(
        self,
        name: str,
        stage_value: str,
        reason: str,
        run_immediately: bool = False,
    ) -> dict[str, Any]:
        reason = self._decision_reason(reason)
        workspace = self.workspace(name)
        stage = StageID(stage_value)
        mgr = CheckpointManager(workspace)
        sm = PipelineStateMachine(mgr)
        if not mgr.get_latest_version(stage):
            raise ValueError(f"阶段 '{stage.value}' 尚未运行")
        can_run, run_reason = sm.can_run(stage)
        if run_immediately and not can_run:
            raise ValueError(run_reason)
        with self._lock:
            self._ensure_idle_locked(name)
            affected = sm.apply_rework(stage)
            job = (
                self._new_job_locked(name, stage.value, "stage", "重做任务已启动")
                if run_immediately
                else None
            )
        self._record_decision(
            workspace,
            stage,
            mgr.get_latest_version(stage),
            "rework",
            reason,
            run_requested=run_immediately,
            job_id=job.id if job else None,
        )
        if job:
            self._launch_job(job, self._run_job)
        return {
            "message": f"{stage.value} 已标记重做" + ("并开始运行" if job else ""),
            "affected": affected,
            "job": asdict(job) if job else None,
        }

    def ack(self, name: str, stage_value: str) -> dict[str, Any]:
        workspace = self.workspace(name)
        stage = StageID(stage_value)
        if not CheckpointManager(workspace).ack_upstream(stage):
            raise ValueError("该阶段没有可确认的上游变更")
        return {"message": f"{stage.value} 的上游变更警告已清除"}

    def validation_summary(self, name: str) -> dict[str, Any]:
        workspace = self.workspace(name)
        paths = ProjectPaths(workspace)
        mgr = CheckpointManager(workspace)
        benchmark_path = paths.output / "benchmark.json"
        benchmark = {}
        if benchmark_path.is_file():
            try:
                benchmark = read_json(benchmark_path)
            except (OSError, ValueError):
                benchmark = {}
        certification_error = ""
        if benchmark:
            from mmw.benchmark import final_certification_error

            certification_error = final_certification_error(
                workspace,
                mgr.get_active_version(StageID.SOLVE),
                mgr.get_active_version(StageID.REVIEW),
            )
        level = (
            benchmark.get("certification", {}).get("level", "unverified")
            if benchmark and not certification_error
            else "unverified"
        )
        layout_quality = {}
        layout_path = paths.output / "layout_quality.json"
        if layout_path.is_file():
            try:
                layout_quality = read_json(layout_path)
            except (OSError, ValueError):
                layout_quality = {}
        return {
            "certification": level,
            "certification_error": certification_error or (
                "" if benchmark else "尚未生成最终 benchmark"
            ),
            "benchmark": benchmark,
            "numeric_audit": (paths.output / "numeric_audit.md").is_file()
            or bool(mgr.load_artifacts(StageID.REVIEW).get("numeric_audit.md")),
            "paper_pdf": (paths.output / "paper.pdf").is_file(),
            "submission_zip": (paths.output / "submission.zip").is_file(),
            "layout_quality": layout_quality,
            "decisions": self._decisions(workspace),
        }

    def start_tool(self, name: str, action: str) -> Job:
        if action not in {
            "audit", "benchmark", "compile", "export",
            "polish-figures", "typeset", "layout-check",
        }:
            raise ValueError("未知验证操作")
        self.workspace(name)
        with self._lock:
            job = self._new_job_locked(name, action, "tool", f"{action} 已启动")
        self._launch_job(job, self._run_tool_job)
        return job

    def _run_tool_job(self, job: Job) -> None:
        try:
            workspace = self.workspace(job.workspace)
            mgr = CheckpointManager(workspace)
            if job.stage == "audit":
                self._update_job(job, current_step="读取论文与结构化数值", step_index=1, step_total=2)
                from mmw.pipeline.stage_review import build_numeric_audit

                report, markdown = build_numeric_audit(workspace, mgr)
                self._update_job(job, current_step="保存审计报告", step_index=2, step_total=2)
                output = ProjectPaths(workspace).output
                output.mkdir(parents=True, exist_ok=True)
                (output / "numeric_audit.md").write_text(markdown, encoding="utf-8")
                if report.unmatched_high:
                    raise ValueError(f"数值审计发现 {len(report.unmatched_high)} 个高置信问题")
                job.message = "数值审计通过"
            elif job.stage == "benchmark":
                self._update_job(job, current_step="执行独立 Benchmark", step_index=1, step_total=2)
                from mmw.benchmark import run_final_certification

                review_version = mgr.get_active_version(StageID.REVIEW) or mgr.get_latest_version(StageID.REVIEW)
                if not review_version:
                    raise ValueError("请先完成 review")
                cases_root = Path(__file__).resolve().parent.parent.parent / "test_cases"
                report = run_final_certification(mgr, cases_root, review_version)
                self._update_job(job, current_step="核对版本绑定与可信等级", step_index=2, step_total=2)
                if not report["overall_passed"]:
                    raise ValueError("最终 benchmark 未通过")
                job.message = f"benchmark 通过：{report['certification']['level']}"
            else:
                labels = {
                    "compile": ("编译论文并检查版式", "论文 PDF 已生成"),
                    "export": ("收集并打包提交物", "submission.zip 已生成"),
                    "polish-figures": ("调用图表 Agent 并重制图表", "图表重制完成，请审批新 solve 版本"),
                    "typeset": ("调用排版 Agent 整理论文", "自动排版完成，请审批新 paper 版本"),
                    "layout-check": ("检查 PDF、日志与图表质量", "论文视觉质量检查通过"),
                }
                self._update_job(
                    job,
                    current_step=labels[job.stage][0],
                )
                result = subprocess.run(
                    [
                        sys.executable,
                        "-m",
                        "mmw.cli",
                        job.stage,
                        "--workspace",
                        str(workspace),
                    ],
                    cwd=Path(__file__).resolve().parent.parent.parent,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=600,
                )
                if result.returncode:
                    detail = (result.stdout + "\n" + result.stderr).strip().splitlines()
                    raise ValueError(detail[-1] if detail else f"{job.stage} 执行失败")
                job.message = labels[job.stage][1]
                self._update_job(job, current_step=job.message, step_index=2, step_total=2)
            job.status = "completed"
        except subprocess.TimeoutExpired:
            job.status = "timed_out"
            job.message = f"{job.stage} 超过 10 分钟，已停止"
        except (ValueError, OSError, subprocess.SubprocessError) as exc:
            job.status = "failed"
            job.message = str(exc)
        except Exception as exc:  # 不向浏览器泄露供应商响应、prompt 或完整异常
            job.status = "failed"
            job.message = f"{exc.__class__.__name__}，请查看工作区日志"
        finally:
            self._finish_job(job)

    def start_update(self, restart_callback) -> Job:
        with self._lock:
            active = next(
                (item for item in self.jobs.values() if item.kind == "update" and item.status == "running"),
                None,
            )
            if active:
                raise ValueError("更新任务已在运行")
            job = Job(
                id=uuid4().hex,
                workspace="__app__",
                stage="update",
                kind="update",
                message="更新任务已启动",
                current_step="检查发布版本",
                step_total=4,
            )
            self.jobs[job.id] = job
        self._launch_job(job, lambda current: self._run_update_job(current, restart_callback))
        return job

    def _run_update_job(self, job: Job, restart_callback) -> None:
        try:
            step_indexes = {
                "检查发布版本": 1,
                "下载更新包": 2,
                "校验并解压更新包": 3,
                "安装新版本": 4,
                "安装完成": 4,
            }

            def report(step: str, progress: float | None = None) -> None:
                self._update_job(
                    job,
                    current_step=step,
                    step_index=step_indexes.get(step, job.step_index),
                    progress=progress,
                    progress_mode="determinate" if progress is not None else "indeterminate",
                )

            result = install_latest_update(progress_callback=report)
            executable = Path(str(result.pop("_executable")))
            job.result = result
            job.status = "completed"
            job.message = str(result.get("message", "更新安装完成，即将重启"))
            self._update_job(job, current_step="安装完成，即将重启", progress=100, progress_mode="determinate")
        except (ValueError, OSError) as exc:
            job.status = "failed"
            job.message = str(exc)
            executable = None
        except Exception as exc:
            job.status = "failed"
            job.message = f"{exc.__class__.__name__}，更新失败"
            executable = None
        finally:
            self._finish_job(job)
        if executable:
            time.sleep(2)
            restart_callback(executable)

    def _new_job_locked(self, name: str, stage: str, kind: str, message: str) -> Job:
        self._ensure_idle_locked(name)
        job = Job(
            id=uuid4().hex,
            workspace=name,
            stage=stage,
            kind=kind,
            message=message,
            current_step="检查运行条件",
            step_total=3 if kind == "stage" else 2,
        )
        self.jobs[job.id] = job
        self._workspace_jobs[name] = job.id
        return job

    @staticmethod
    def _launch_job(job: Job, target) -> None:
        threading.Thread(target=target, args=(job,), daemon=True).start()

    def _update_job(self, job: Job, **changes: Any) -> None:
        with self._lock:
            for key, value in changes.items():
                setattr(job, key, value)
            job.updated_at = datetime.now().isoformat(timespec="seconds")

    def _finish_job(self, job: Job) -> None:
        now = datetime.now().isoformat(timespec="seconds")
        with self._lock:
            job.updated_at = now
            job.finished_at = now
            if job.status == "completed":
                job.progress_mode = "determinate"
                job.progress = 100
            self._workspace_jobs.pop(job.workspace, None)
            self._last_jobs[job.workspace] = job
        try:
            self._persist_job(job)
        except OSError:
            pass

    def _ensure_idle(self, name: str) -> None:
        with self._lock:
            self._ensure_idle_locked(name)

    def _ensure_idle_locked(self, name: str) -> None:
        active_id = self._workspace_jobs.get(name)
        if active_id and self.jobs.get(active_id) and self.jobs[active_id].status == "running":
            raise ValueError("该工作区已有任务正在运行")

    def _active_job(self, name: str) -> dict[str, Any] | None:
        active_id = self._workspace_jobs.get(name)
        job = self.jobs.get(active_id) if active_id else None
        return asdict(job) if job and job.status == "running" else None

    def _last_job(self, name: str) -> dict[str, Any] | None:
        job = self._last_jobs.get(name)
        if job:
            return asdict(job)
        path = self._job_log_path(name)
        if not path.is_file():
            return None
        try:
            item = json.loads(path.read_text(encoding="utf-8").splitlines()[-1])
        except (OSError, ValueError, IndexError):
            return None
        return item if isinstance(item, dict) else None

    def _persist_job(self, job: Job) -> None:
        path = self._job_log_path(job.workspace)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(asdict(job), ensure_ascii=False) + "\n")

    def _job_log_path(self, name: str) -> Path:
        if name == "__app__":
            return self.recent_path.parent / "jobs.jsonl"
        return ProjectPaths(self.workspace(name)).logs / "jobs.jsonl"

    @staticmethod
    def _decision_reason(reason: str) -> str:
        reason = reason.strip()
        if len(reason) < 4:
            raise ValueError("请填写至少 4 个字的人工判断理由")
        if len(reason) > 2000:
            raise ValueError("人工判断理由不能超过 2000 字")
        return reason

    @staticmethod
    def _record_decision(
        workspace: Path,
        stage: StageID,
        version: int,
        action: str,
        reason: str,
        **extra: Any,
    ) -> None:
        path = ProjectPaths(workspace).internal / "decisions.jsonl"
        actor = extra.pop("actor", "human")
        entry = {
            "timestamp": datetime.now().astimezone().isoformat(timespec="seconds"),
            "actor": actor,
            "stage": stage.value,
            "version": version,
            "action": action,
            "reason": reason,
            **{key: value for key, value in extra.items() if value is not None},
        }
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry, ensure_ascii=False) + "\n")

    @staticmethod
    def _decisions(workspace: Path) -> list[dict[str, Any]]:
        path = ProjectPaths(workspace).internal / "decisions.jsonl"
        if not path.is_file():
            return []
        result = []
        for line in path.read_text(encoding="utf-8").splitlines()[-30:]:
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(item, dict):
                result.append(item)
        return list(reversed(result))

    @staticmethod
    def _rework_recommendation(stage: StageID, error: str) -> str:
        if not error:
            return "机器门禁通过，仍需完成人工检查清单"
        lowered = error.casefold()
        if any(token in lowered for token in ("拟合", "r2", "nrmse", "无可行")):
            return "优先检查 model；模型无误后再重做 code"
        if any(token in lowered for token in ("results.json", "sensitivity", "约束", "运行")):
            return "重做 code 并根据失败证据定向修订"
        if stage in {StageID.PAPER, StageID.REVIEW}:
            return f"定向重做 {stage.value}，不要改动已验证求解结果"
        return f"重做 {stage.value}"

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
            elif parts == ["api", "projects"]:
                self._send_json({"projects": app.list_projects()})
            elif len(parts) == 3 and parts[:2] == ["api", "projects"]:
                self._send_json(app.workspace_summary(parts[2]))
            elif len(parts) == 5 and parts[:2] == ["api", "projects"] and parts[3] == "stages":
                query = dict(item.split("=", 1) for item in parsed.query.split("&") if "=" in item)
                version = int(query["version"]) if query.get("version") else None
                self._send_json(app.stage_detail(parts[2], parts[4], version))
            elif len(parts) == 4 and parts[:2] == ["api", "projects"] and parts[3] == "validation":
                self._send_json(app.validation_summary(parts[2]))
            elif len(parts) == 4 and parts[:2] == ["api", "projects"] and parts[3] == "managed-run":
                self._send_json(app.managed_run_summary(parts[2]))
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
            elif parts == ["api", "update"]:
                self._send_json(app.update_status())
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
                        app.initialize(name, str(body.get("problem_file") or body.get("problem_pdf", "")))
                    result = asdict(app.start_run(name, str(body.get("stage", "next"))))
                elif action == "initialize":
                    result = app.initialize(
                        name, str(body.get("problem_file") or body.get("problem_pdf", ""))
                    )
                elif action == "approve":
                    version = int(body["version"]) if body.get("version") is not None else None
                    result = app.approve(
                        name, str(body.get("stage", "")), version, str(body.get("reason", ""))
                    )
                elif action == "rework":
                    result = app.rework(
                        name,
                        str(body.get("stage", "")),
                        str(body.get("reason", "")),
                        self._boolean(body, "run_immediately"),
                    )
                elif action == "ack":
                    result = app.ack(name, str(body.get("stage", "")))
                elif action == "tool":
                    result = asdict(app.start_tool(name, str(body.get("tool", ""))))
                elif action == "managed-run":
                    result = asdict(
                        app.start_managed_run(
                            name,
                            int(body.get("max_stage_reworks", 2)),
                            int(body.get("max_total_reworks", 8)),
                            int(body.get("max_total_tokens", 0)),
                            int(body.get("max_total_minutes", 0)),
                            self._boolean(body, "resume"),
                        )
                    )
                elif action == "figure-backend":
                    result = app.set_figure_backend(name, str(body.get("backend", "")))
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
                    result = app.approve(
                        name, str(body.get("stage", "")), version, str(body.get("reason", ""))
                    )
                elif action == "rework":
                    result = app.rework(
                        name,
                        str(body.get("stage", "")),
                        str(body.get("reason", "")),
                        self._boolean(body, "run_immediately"),
                    )
                elif action == "ack":
                    result = app.ack(name, str(body.get("stage", "")))
                else:
                    raise ValueError("未知工作区操作")
            elif parts == ["api", "providers", "save"]:
                result = save_profile(app.env_path, body)
            elif parts == ["api", "providers", "activate"]:
                result = activate_profile(app.env_path, str(body.get("id", "")))
            elif parts == ["api", "providers", "codex", "activate"]:
                result = activate_codex(app.env_path)
            elif parts == ["api", "providers", "codex", "test"]:
                from mmw.cli import _probe_llm_config

                ok, detail = _probe_llm_config(LLMConfig(api_key="", backend="codex"))
                if not ok:
                    raise ValueError(detail)
                result = {"ok": True, "message": "Codex CLI 调用成功"}
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
            elif parts == ["api", "update", "install"]:
                result = asdict(app.start_update(self.server.restart_into))
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

    @staticmethod
    def _boolean(body: dict[str, Any], key: str) -> bool:
        value = body.get(key, False)
        if not isinstance(value, bool):
            raise ValueError(f"{key} 必须是布尔值")
        return value


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

    def restart_into(self, executable: Path) -> None:
        self.shutdown()
        time.sleep(0.5)
        subprocess.Popen([str(executable)], cwd=executable.parent)


def serve_gui(
    port: int = 8765,
    open_browser: bool = True,
    env_path: Path | None = None,
) -> None:
    app = GuiApplication(env_path=env_path)
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
