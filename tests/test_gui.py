from pathlib import Path
import threading
import sys

from mmw.config import Settings
from mmw import desktop
from mmw.gui.providers import activate_codex, activate_profile, public_profiles, save_profile
from mmw.gui.server import GuiApplication, Job
from mmw.models import MetaData, StageID
from mmw.pipeline.stage_solve import run_solve
from mmw.project import ProjectPaths, initialize_project, scan_project
from mmw.utils.checkpoint import CheckpointManager
from mmw.utils.file_io import write_yaml


def test_provider_switch_is_atomic_and_masked(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(
        "mmw.gui.providers.codex_cli_status",
        lambda: {"installed": False, "logged_in": False, "message": "未安装 Codex CLI"},
    )
    env_path = tmp_path / ".env"
    env_path.write_text("# keep me\nWORKSPACE_DIR=workspace\n", encoding="utf-8")

    profile = save_profile(
        env_path,
        {
            "name": "Test API",
            "base_url": "https://example.test/v1",
            "api_key": "sk-test-super-secret",
            "default_model": "chat-model",
            "reasoning_model": "reason-model",
        },
    )
    activate_profile(env_path, profile["id"])

    text = env_path.read_text(encoding="utf-8")
    settings = Settings(_env_file=env_path)
    public = public_profiles(env_path)
    assert "# keep me" in text and "WORKSPACE_DIR=workspace" in text
    assert settings.llm_model == "chat-model"
    assert settings.modeler_model == "reason-model"
    assert settings.reviewer_model == "chat-model"
    assert settings.llm_backend == "openai"
    assert "sk-test-super-secret" not in str(public)
    assert public["active_id"] == profile["id"]
    assert public["backend"] == "openai"


def test_codex_switch_preserves_api_profile(tmp_path: Path, monkeypatch):
    env_path = tmp_path / ".env"
    env_path.write_text(
        'LLM_BACKEND="openai"\nLLM_API_KEY="sk-preserved"\nMMW_ACTIVE_PROVIDER="api-1"\n',
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "mmw.gui.providers.codex_cli_status",
        lambda: {"installed": True, "logged_in": True, "message": "Codex CLI 已登录"},
    )

    result = activate_codex(env_path)
    settings = Settings(_env_file=env_path)

    assert result["backend"] == "codex"
    assert settings.llm_backend == "codex"
    assert settings.llm_api_key == "sk-preserved"
    assert settings.mmw_active_provider == "api-1"


def test_codex_switch_requires_local_login(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(
        "mmw.gui.providers.codex_cli_status",
        lambda: {"installed": True, "logged_in": False, "message": "Codex CLI 未登录"},
    )

    try:
        activate_codex(tmp_path / ".env")
    except ValueError as exc:
        assert str(exc) == "Codex CLI 未登录，请先运行 codex login"
    else:
        raise AssertionError("未登录 Codex 时仍允许切换")


def test_frozen_desktop_uses_appdata_and_dispatches_cli(tmp_path: Path, monkeypatch):
    called = []
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setenv("APPDATA", str(tmp_path / "Roaming"))
    monkeypatch.setattr(sys, "argv", ["MMW.exe", "-m", "mmw.cli", "status"])
    monkeypatch.setattr("mmw.cli.main", lambda: called.append(list(sys.argv)))

    desktop.main()

    assert Path.cwd() == (tmp_path / "Roaming" / "MMW").resolve()
    assert called == [["MMW.exe", "status"]]


def test_frozen_desktop_starts_gui_with_private_env(tmp_path: Path, monkeypatch):
    captured = {}
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setenv("APPDATA", str(tmp_path / "Roaming"))
    monkeypatch.setattr(sys, "argv", ["MMW.exe"])
    monkeypatch.setattr(
        "mmw.gui.server.serve_gui",
        lambda **kwargs: captured.update(kwargs),
    )

    desktop.main()

    assert captured["env_path"] == (tmp_path / "Roaming" / "MMW" / ".env").resolve()


def test_frozen_desktop_dispatches_executor_bootstrap(tmp_path: Path, monkeypatch):
    script = tmp_path / "solution.py"
    output = tmp_path / "result.txt"
    script.write_text("from pathlib import Path\nPath('result.txt').write_text('ok')\n")
    monkeypatch.setattr(
        sys,
        "argv",
        ["MMW.exe", "--mmw-run-script", str(tmp_path), str(script)],
    )

    desktop.main()

    assert output.read_text() == "ok"


def test_gui_only_lists_valid_direct_workspaces(tmp_path: Path):
    root = tmp_path / "workspace"
    valid = root / "2026_A"
    (valid / "data" / "raw").mkdir(parents=True)
    (valid / "config.yaml").write_text("name: 2026_A\nyear: 2026\nproblem: A\n", encoding="utf-8")
    (valid / "problem.md").write_text("<!-- placeholder -->\n", encoding="utf-8")
    (root / "not-a-workspace").mkdir()

    app = GuiApplication(workspace_root=root, env_path=tmp_path / ".env")
    workspaces = app.list_workspaces()
    assert [item["name"] for item in workspaces] == ["2026_A"]
    assert workspaces[0]["problem_ready"] is False


def test_plain_pdf_folder_is_read_only_until_initialized(tmp_path: Path, monkeypatch):
    project = tmp_path / "2026_A题"
    project.mkdir()
    (project / "A题.pdf").write_bytes(b"%PDF fixture")
    (project / "附件.csv").write_text("x,y\n1,2\n", encoding="utf-8")

    scanned = scan_project(project)
    assert scanned["ready"] is True
    assert not (project / ".mmw").exists()

    monkeypatch.setattr(
        "mmw.project.extract_pdf_text",
        lambda _: "# A题\n\n" + "这是可提取的题目正文。" * 30,
    )
    paths = initialize_project(project, "A题.pdf")

    assert paths.problem.is_file()
    assert paths.checkpoints == project / ".mmw" / "checkpoints"
    assert [path.name for path in paths.data_files()] == ["附件.csv"]
    assert (project / "output" / "figures").is_dir()
    assert (project / "A题.pdf").read_bytes() == b"%PDF fixture"


def test_gui_registers_arbitrary_selected_folder(tmp_path: Path):
    project = tmp_path / "outside-workspace"
    project.mkdir()
    (project / "problem.pdf").write_bytes(b"%PDF fixture")
    app = GuiApplication(workspace_root=tmp_path / "unused", env_path=tmp_path / ".env")

    scanned = app.register_project(project)

    assert app.workspace(scanned["project_id"]) == project.resolve()
    assert scanned["path"] == str(project.resolve())


def test_folder_picker_rejects_duplicate_dialogs(tmp_path: Path):
    entered = threading.Event()
    release = threading.Event()

    def picker(_):
        entered.set()
        release.wait(2)
        return ""

    app = GuiApplication(workspace_root=tmp_path, env_path=tmp_path / ".env", picker=picker)
    thread = threading.Thread(target=app.pick_project)
    thread.start()
    assert entered.wait(1)
    try:
        try:
            app.pick_project()
        except ValueError as exc:
            assert "已经打开" in str(exc)
        else:
            raise AssertionError("重复文件夹选择窗口未被拒绝")
    finally:
        release.set()
        thread.join(2)


def test_modern_project_solve_uses_output_directories(tmp_path: Path):
    internal = tmp_path / ".mmw"
    (internal / "checkpoints").mkdir(parents=True)
    (internal / "cache").mkdir()
    write_yaml(internal / "config.yaml", {"name": "test", "active_versions": {}})
    mgr = CheckpointManager(tmp_path)
    code = """
from pathlib import Path
import json
out = Path("output/data")
out.mkdir(parents=True, exist_ok=True)
(Path("output/figures")).mkdir(parents=True, exist_ok=True)
(Path("output/figures") / "fig_result.png").write_bytes(b"png")
(out / "results.json").write_text(json.dumps([{"name":"q1_value","value":1.0,"unit":"","desc":"result"}]), encoding="utf-8")
(out / "sensitivity.json").write_text(json.dumps({"baseline":{"objective":1.0},"experiments":[{"param":"a","delta_pct":-10,"objective":0.9,"change_pct":-10},{"param":"b","delta_pct":10,"objective":1.1,"change_pct":10}]}), encoding="utf-8")
"""
    mgr.save(StageID.CODE, {"solution.py": code}, MetaData(stage="code", version=0))

    run_solve(tmp_path, mgr)

    assert (tmp_path / "output" / "data" / "results.json").is_file()
    assert (tmp_path / "output" / "figures" / "fig_result.png").is_file()
    assert "q1_value" in mgr.load_artifacts(StageID.SOLVE)["results.json"]


def test_gui_records_reasoned_human_decisions(tmp_path: Path):
    root = tmp_path / "workspace"
    project = root / "2026_A"
    project.mkdir(parents=True)
    write_yaml(project / "config.yaml", {"name": "2026_A", "active_versions": {}})
    mgr = CheckpointManager(project)
    mgr.save(StageID.ANALYZE, {"analysis.md": "完整分析"}, MetaData(stage="analyze", version=0))
    app = GuiApplication(workspace_root=root, env_path=tmp_path / ".env")

    try:
        app.approve("2026_A", "analyze", 1, "")
    except ValueError as exc:
        assert "人工判断理由" in str(exc)
    else:
        raise AssertionError("空人工判断理由未被拒绝")

    app.approve("2026_A", "analyze", 1, "题意、约束和交付物均已人工核对")

    decisions = app.validation_summary("2026_A")["decisions"]
    assert decisions[0]["action"] == "approve"
    assert decisions[0]["reason"] == "题意、约束和交付物均已人工核对"


def test_gui_stage_detail_exposes_human_checklist_and_rework_hint(tmp_path: Path):
    root = tmp_path / "workspace"
    project = root / "2026_A"
    project.mkdir(parents=True)
    write_yaml(project / "config.yaml", {"name": "2026_A", "active_versions": {}})
    CheckpointManager(project).save(
        StageID.ANALYZE,
        {"analysis.md": "完整分析"},
        MetaData(stage="analyze", version=0),
    )

    detail = GuiApplication(
        workspace_root=root, env_path=tmp_path / ".env"
    ).stage_detail("2026_A", "analyze")

    assert "子问题完整" in detail["checklist"]
    assert "人工检查清单" in detail["recommendation"]


def test_gui_compile_tool_uses_selected_project_path(tmp_path: Path, monkeypatch):
    project = tmp_path / "outside-workspace"
    project.mkdir()
    app = GuiApplication(workspace_root=tmp_path / "unused", env_path=tmp_path / ".env")
    selected = app.register_project(project)["project_id"]
    captured = {}

    def fake_run(command, **kwargs):
        captured["command"] = command
        return type("Result", (), {"returncode": 0, "stdout": "", "stderr": ""})()

    monkeypatch.setattr("mmw.gui.server.subprocess.run", fake_run)
    job = Job(id="compile-job", workspace=selected, stage="compile")

    app._run_tool_job(job)

    assert job.status == "completed"
    assert captured["command"][-1] == str(project.resolve())


def test_gui_tool_job_redacts_unexpected_errors(tmp_path: Path, monkeypatch):
    project = tmp_path / "project"
    project.mkdir()
    app = GuiApplication(workspace_root=tmp_path / "unused", env_path=tmp_path / ".env")
    selected = app.register_project(project)["project_id"]
    monkeypatch.setattr(
        "mmw.gui.server.subprocess.run",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("secret provider response")),
    )
    job = Job(id="export-job", workspace=selected, stage="export")

    app._run_tool_job(job)

    assert job.status == "failed"
    assert job.message == "RuntimeError，请查看工作区日志"
