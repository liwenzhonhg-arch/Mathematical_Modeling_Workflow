from pathlib import Path
from datetime import datetime, timedelta
import json
import threading
import sys
import time
import zipfile

from mmw.config import Settings
from mmw import desktop
from mmw.gui.providers import activate_codex, activate_profile, public_profiles, save_profile
from mmw.gui.server import GuiApplication, GuiHandler, Job
from mmw.models import MetaData, StageID
from mmw.pipeline.stage_solve import run_solve
from mmw.project import (
    ProjectPaths,
    initialize_project,
    restore_attachment_paths,
    scan_project,
)
from mmw.utils.checkpoint import CheckpointManager
from mmw.utils.file_io import read_yaml, write_yaml


def test_restore_attachment_paths_reverses_nfkc_filename_change():
    code = 'pd.read_excel("问题A附件1:实验采集数据表.xlsx")'
    assert restore_attachment_paths(
        code, ["问题A附件1：实验采集数据表.xlsx"],
    ) == 'pd.read_excel("问题A附件1：实验采集数据表.xlsx")'


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


def test_gui_paper_tools_save_backend_and_share_job_lock(tmp_path: Path, monkeypatch):
    project = tmp_path / "project"
    project.mkdir()
    write_yaml(project / "config.yaml", {"name": "project", "figure_backend": "matplotlib"})
    app = GuiApplication(
        workspace_root=tmp_path / "unused",
        env_path=tmp_path / ".env",
        recent_path=tmp_path / "recent-projects.json",
    )
    selected = app.register_project(project)["project_id"]
    monkeypatch.setattr(
        "mmw.utils.origin_renderer.origin_status",
        lambda: {"available": False, "reason": "缺失", "executable": None, "originpro_version": None},
    )
    monkeypatch.setattr(app, "_launch_job", lambda job, target: None)

    assert app.figure_backends(selected)["selected"] == "matplotlib"
    assert app.set_figure_backend(selected, "matplotlib") == {"figure_backend": "matplotlib"}
    assert read_yaml(project / "config.yaml")["figure_backend"] == "matplotlib"
    try:
        app.set_figure_backend(selected, "origin")
    except ValueError as error:
        assert "不可用" in str(error)
    else:
        raise AssertionError("Origin 不可用时仍允许选中")

    job = app.start_tool(selected, "polish-figures")
    assert job.kind == "tool"
    try:
        app.start_tool(selected, "typeset")
    except ValueError as error:
        assert "已有任务" in str(error)
    else:
        raise AssertionError("同一项目允许重复启动工具任务")


def test_gui_outputs_hide_figures_not_declared_by_current_solve(tmp_path: Path):
    project = tmp_path / "project"
    internal = project / ".mmw"
    internal.mkdir(parents=True)
    write_yaml(internal / "config.yaml", {
        "name": "project",
        "active_versions": {},
    })
    mgr = CheckpointManager(project)
    mgr.save(
        StageID.SOLVE,
        {"figures_list.json": '["current.png"]'},
        MetaData(stage=StageID.SOLVE.value, version=0),
    )
    mgr.approve(StageID.SOLVE)
    figures = project / "output" / "figures"
    figures.mkdir(parents=True)
    (figures / "current.png").write_bytes(b"current")
    (figures / "stale.png").write_bytes(b"stale")
    (project / "output" / "paper.pdf").write_bytes(b"paper")
    app = GuiApplication(
        workspace_root=tmp_path / "unused",
        env_path=tmp_path / ".env",
        recent_path=tmp_path / "recent-projects.json",
    )
    selected = app.register_project(project)["project_id"]

    paths = {
        item["path"] for item in app.workspace_summary(selected)["outputs"]
    }

    assert "output/figures/current.png" in paths
    assert "output/figures/stale.png" not in paths
    assert "output/paper.pdf" in paths


def test_gui_managed_run_uses_existing_job_lock_and_validates_budget(tmp_path: Path, monkeypatch):
    project = tmp_path / "project"
    project.mkdir()
    write_yaml(project / "config.yaml", {"name": "project", "active_versions": {}})
    app = GuiApplication(
        workspace_root=tmp_path / "unused",
        env_path=tmp_path / ".env",
        recent_path=tmp_path / "recent-projects.json",
    )
    selected = app.register_project(project)["project_id"]
    monkeypatch.setattr(app, "_launch_job", lambda job, target: None)

    job = app.start_managed_run(selected)

    assert job.kind == "managed"
    assert job.step_total == 9
    try:
        app.start_run(selected, "next")
    except ValueError as error:
        assert "已有任务" in str(error)
    else:
        raise AssertionError("托管运行没有占用现有项目任务锁")
    try:
        app.start_managed_run(selected, max_stage_reworks=11)
    except ValueError as error:
        assert "预算" in str(error)
    else:
        raise AssertionError("非法托管预算未被拒绝")
    try:
        app.start_managed_run(selected, max_total_tokens=100_000_001)
    except ValueError as error:
        assert "预算" in str(error)
    else:
        raise AssertionError("非法 token 预算未被拒绝")


def test_gui_managed_run_persists_redacted_unexpected_failure(tmp_path: Path, monkeypatch):
    project = tmp_path / "project"
    project.mkdir()
    write_yaml(project / "config.yaml", {"name": "project", "active_versions": {}})
    app = GuiApplication(
        workspace_root=tmp_path / "unused",
        env_path=tmp_path / ".env",
        recent_path=tmp_path / "recent-projects.json",
    )
    selected = app.register_project(project)["project_id"]
    monkeypatch.setattr(app, "_launch_job", lambda job, target: None)
    monkeypatch.setattr(
        "mmw.gui.server.run_managed_pipeline",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("provider secret")),
    )
    job = app.start_managed_run(selected)

    app._run_managed_job(job)

    state = json.loads((ProjectPaths(project).internal / "managed-run.json").read_text("utf-8"))
    assert job.status == "failed"
    assert state["status"] == "failed"
    assert "provider secret" not in state["last_error"]


def test_gui_marks_orphaned_managed_run_as_resumable(tmp_path: Path):
    project = tmp_path / "project"
    project.mkdir()
    write_yaml(project / "config.yaml", {"name": "project", "active_versions": {}})
    internal = ProjectPaths(project).internal
    (internal / "managed-run.json").write_text(
        json.dumps({"run_id": "old", "status": "running"}),
        encoding="utf-8",
    )
    app = GuiApplication(
        workspace_root=tmp_path / "unused",
        env_path=tmp_path / ".env",
        recent_path=tmp_path / "recent-projects.json",
    )
    selected = app.register_project(project)["project_id"]

    state = app.managed_run_summary(selected)

    assert state["status"] == "waiting_user"
    assert state["last_action"] == "interrupted"


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

    app = GuiApplication(
        workspace_root=root,
        env_path=tmp_path / ".env",
        recent_path=tmp_path / "recent-projects.json",
    )
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


def test_docx_problem_is_scanned_and_extracted(tmp_path: Path):
    project = tmp_path / "2026_B题"
    project.mkdir()
    docx = project / "B题.docx"
    text = "这是Word题目正文，包含模型目标、约束条件和数据说明。" * 20
    document = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" '
        'xmlns:m="http://schemas.openxmlformats.org/officeDocument/2006/math">'
        f"<w:body><w:p><w:r><w:t>{text}</w:t></w:r></w:p>"
        "<w:p><m:oMath><m:r><m:t>x+y=1</m:t></m:r></m:oMath></w:p>"
        "<w:tbl>"
        "<w:tr><w:tc><w:p><w:r><w:t>地区</w:t></w:r></w:p></w:tc>"
        "<w:tc><w:p><w:r><w:t>需求</w:t></w:r></w:p></w:tc></w:tr>"
        "<w:tr><w:tc><w:p><w:r><w:t>1</w:t></w:r></w:p></w:tc>"
        "<w:tc><w:p><w:r><w:t>28</w:t></w:r></w:p></w:tc></w:tr>"
        "</w:tbl>"
        "</w:body></w:document>"
    )
    with zipfile.ZipFile(docx, "w") as archive:
        archive.writestr("word/document.xml", document)
    original = docx.read_bytes()

    scanned = scan_project(project)
    assert scanned["ready"] is True
    assert scanned["problem_files"][0]["path"] == "B题.docx"
    assert scanned["problem_files"][0]["type"] == "docx"

    paths = initialize_project(project, "B题.docx")

    extracted = paths.problem.read_text(encoding="utf-8")
    evidence = json.loads(paths.evidence.read_text(encoding="utf-8"))
    assert text in extracted
    assert "x+y=1" in extracted
    assert "| 地区 | 需求 |" in extracted
    assert "| --- | --- |" in extracted
    assert "| 1 | 28 |" in extracted
    assert evidence["visual_assets"] == []
    assert evidence["visual_interpretation"]["status"] == "not_run"
    assert docx.read_bytes() == original


def test_docx_embedded_image_creates_uninterpreted_evidence_manifest(tmp_path: Path):
    project = tmp_path / "visual-docx"
    project.mkdir()
    docx = project / "A题.docx"
    document = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        f'<w:body><w:p><w:r><w:t>{"题目正文与约束。" * 30}</w:t></w:r></w:p></w:body></w:document>'
    )
    png = b"\x89PNG\r\n\x1a\n" + b"fixture"
    with zipfile.ZipFile(docx, "w") as archive:
        archive.writestr("word/document.xml", document)
        archive.writestr("word/media/image1.png", png)

    paths = initialize_project(project, docx.name)
    evidence = json.loads(paths.evidence.read_text(encoding="utf-8"))

    assert evidence["schema_version"] == 1
    assert evidence["visual_interpretation"]["status"] == "not_run"
    assert len(evidence["visual_assets"]) == 1
    asset = evidence["visual_assets"][0]
    assert asset["mime"] == "image/png"
    assert asset["interpretation_status"] == "not_run"
    assert (project / ".mmw" / asset["cache_path"]).read_bytes() == png


def test_pdf_embedded_image_creates_uninterpreted_evidence_manifest(tmp_path: Path, monkeypatch):
    project = tmp_path / "visual-pdf"
    project.mkdir()
    pdf = project / "A题.pdf"
    pdf.write_bytes(b"%PDF fixture")
    png = b"\x89PNG\r\n\x1a\n" + b"fixture"

    class Page:
        images = [type("Image", (), {"data": png})()]

        @staticmethod
        def extract_text():
            return "题目正文包含目标、约束和数据说明。" * 30

    monkeypatch.setattr("pypdf.PdfReader", lambda _: type("Reader", (), {"pages": [Page()]})())

    paths = initialize_project(project, pdf.name)
    evidence = json.loads(paths.evidence.read_text(encoding="utf-8"))

    assert evidence["visual_interpretation"]["status"] == "not_run"
    assert evidence["visual_assets"][0]["page"] == 1
    assert evidence["visual_assets"][0]["mime"] == "image/png"


def test_docx_positioned_shape_text_keeps_relative_order(tmp_path: Path):
    project = tmp_path / "positioned-docx"
    project.mkdir()
    docx = project / "A题.docx"
    labels = [(8438, "1m"), (2976, "1m"), (6098, "6m"), (3578, "2m"), (9000, "2.05mcm")]
    shapes = "".join(
        f'<v:shape style="position:absolute;left:{left};top:13429">'
        f'<v:textbox><w:txbxContent><w:p><w:r><w:t>{text}</w:t></w:r></w:p>'
        '</w:txbxContent></v:textbox></v:shape>'
        for left, text in labels
    )
    document = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" '
        'xmlns:v="urn:schemas-microsoft-com:vml">'
        f'<w:body><w:p><w:r><w:t>{"题目正文与约束条件。" * 20}</w:t></w:r></w:p>{shapes}</w:body></w:document>'
    )
    with zipfile.ZipFile(docx, "w") as archive:
        archive.writestr("word/document.xml", document)

    extracted = initialize_project(project, docx.name).problem.read_text(encoding="utf-8")
    layout = extracted.split("## 图形定位文本", 1)[1]

    assert layout.index("left=2976: 1m") < layout.index("left=3578: 2m")
    assert layout.index("left=3578: 2m") < layout.index("left=6098: 6m")
    assert layout.index("left=6098: 6m") < layout.index("left=8438: 1m")
    assert "top=13429: 1m | 2m | 6m | 1m" in layout
    assert "left=9000: 2.05m" in layout
    assert "2.05mcm" not in extracted


def test_legacy_doc_requires_conversion(tmp_path: Path):
    project = tmp_path / "legacy"
    project.mkdir()
    (project / "题目.doc").write_bytes(b"legacy word")

    scanned = scan_project(project)

    assert scanned["ready"] is False
    assert "另存为 .docx" in scanned["blocked_reason"]


def test_gui_registers_arbitrary_selected_folder(tmp_path: Path):
    project = tmp_path / "outside-workspace"
    project.mkdir()
    (project / "problem.pdf").write_bytes(b"%PDF fixture")
    app = GuiApplication(
        workspace_root=tmp_path / "unused",
        env_path=tmp_path / ".env",
        recent_path=tmp_path / "recent-projects.json",
    )

    scanned = app.register_project(project)

    assert app.workspace(scanned["project_id"]) == project.resolve()
    assert scanned["path"] == str(project.resolve())


def test_gui_restores_recent_initialized_project(tmp_path: Path):
    project = tmp_path / "outside-workspace"
    (project / ".mmw").mkdir(parents=True)
    write_yaml(project / ".mmw" / "config.yaml", {"name": "outside", "active_versions": {}})
    recent_path = tmp_path / "recent-projects.json"
    first = GuiApplication(
        workspace_root=tmp_path / "unused",
        env_path=tmp_path / ".env",
        recent_path=recent_path,
    )
    first_id = first.register_project(project)["project_id"]

    restored = GuiApplication(
        workspace_root=tmp_path / "unused",
        env_path=tmp_path / ".env",
        recent_path=recent_path,
    ).list_projects()

    assert len(restored) == 1
    assert restored[0]["path"] == str(project.resolve())
    assert restored[0]["project_id"] != first_id


def test_gui_ignores_invalid_recent_project_registry(tmp_path: Path):
    recent_path = tmp_path / "recent-projects.json"
    recent_path.write_text('{"projects": [{"path": "relative-project"}]}', encoding="utf-8")

    app = GuiApplication(
        workspace_root=tmp_path / "unused",
        env_path=tmp_path / ".env",
        recent_path=recent_path,
    )

    assert app.list_projects() == []


def test_folder_picker_rejects_duplicate_dialogs(tmp_path: Path):
    entered = threading.Event()
    release = threading.Event()

    def picker(_):
        entered.set()
        release.wait(2)
        return ""

    app = GuiApplication(
        workspace_root=tmp_path,
        env_path=tmp_path / ".env",
        picker=picker,
        recent_path=tmp_path / "recent-projects.json",
    )
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


def test_gui_hides_figures_not_listed_by_active_solve(tmp_path: Path):
    project = tmp_path / "project"
    (project / "output" / "figures").mkdir(parents=True)
    (project / ".mmw").mkdir()
    write_yaml(project / ".mmw" / "config.yaml", {"name": "test", "active_versions": {}})
    (project / "output" / "figures" / "current.png").write_bytes(b"current")
    (project / "output" / "figures" / "stale.png").write_bytes(b"stale")
    CheckpointManager(project).save(
        StageID.SOLVE,
        {"figures_list.json": '["current.png"]'},
        MetaData(stage="solve", version=0),
    )
    app = GuiApplication(
        workspace_root=tmp_path,
        env_path=tmp_path / ".env",
        recent_path=tmp_path / "recent-projects.json",
    )

    listed = {item["path"] for item in app._file_listing(project)}

    assert "output/figures/current.png" in listed
    assert "output/figures/stale.png" not in listed


def test_gui_records_reasoned_human_decisions(tmp_path: Path):
    root = tmp_path / "workspace"
    project = root / "2026_A"
    project.mkdir(parents=True)
    write_yaml(project / "config.yaml", {"name": "2026_A", "active_versions": {}})
    mgr = CheckpointManager(project)
    mgr.save(StageID.ANALYZE, {"analysis.md": "完整分析"}, MetaData(stage="analyze", version=0))
    app = GuiApplication(
        workspace_root=root,
        env_path=tmp_path / ".env",
        recent_path=tmp_path / "recent-projects.json",
    )

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
        workspace_root=root,
        env_path=tmp_path / ".env",
        recent_path=tmp_path / "recent-projects.json",
    ).stage_detail("2026_A", "analyze")

    assert "子问题完整" in detail["checklist"]
    assert "人工检查清单" in detail["recommendation"]


def test_gui_compile_tool_uses_selected_project_path(tmp_path: Path, monkeypatch):
    project = tmp_path / "outside-workspace"
    project.mkdir()
    app = GuiApplication(
        workspace_root=tmp_path / "unused",
        env_path=tmp_path / ".env",
        recent_path=tmp_path / "recent-projects.json",
    )
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
    app = GuiApplication(
        workspace_root=tmp_path / "unused",
        env_path=tmp_path / ".env",
        recent_path=tmp_path / "recent-projects.json",
    )
    selected = app.register_project(project)["project_id"]
    monkeypatch.setattr(
        "mmw.gui.server.subprocess.run",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("secret provider response")),
    )
    job = Job(id="export-job", workspace=selected, stage="export")

    app._run_tool_job(job)

    assert job.status == "failed"
    assert job.message == "RuntimeError，请查看工作区日志"


def test_gui_rework_can_register_immediate_run_atomically(tmp_path: Path, monkeypatch):
    root = tmp_path / "workspace"
    project = root / "2026_A"
    project.mkdir(parents=True)
    write_yaml(project / "config.yaml", {"name": "2026_A", "active_versions": {}})
    mgr = CheckpointManager(project)
    mgr.save(StageID.ANALYZE, {"analysis.md": "完整分析"}, MetaData(stage="analyze", version=0))
    app = GuiApplication(
        workspace_root=root,
        env_path=tmp_path / ".env",
        recent_path=tmp_path / "recent-projects.json",
    )
    monkeypatch.setattr(app, "_launch_job", lambda job, target: None)

    result = app.rework("2026_A", "analyze", "需要按审查意见修正分析", run_immediately=True)

    assert result["job"]["status"] == "running"
    assert result["job"]["stage"] == "analyze"
    assert app.workspace_summary("2026_A")["active_job"]["id"] == result["job"]["id"]
    decision = app.validation_summary("2026_A")["decisions"][0]
    assert decision["action"] == "rework"
    assert decision["run_requested"] is True
    assert decision["job_id"] == result["job"]["id"]


def test_gui_finished_job_is_persisted_without_raw_provider_data(tmp_path: Path):
    project = tmp_path / "project"
    project.mkdir()
    app = GuiApplication(
        workspace_root=tmp_path / "unused",
        env_path=tmp_path / ".env",
        recent_path=tmp_path / "recent-projects.json",
    )
    selected = app.register_project(project)["project_id"]
    job = Job(id="safe-job", workspace=selected, stage="audit", kind="tool")
    job.status = "failed"
    job.message = "RuntimeError，请查看工作区日志"

    app._finish_job(job)

    saved = (ProjectPaths(project).logs / "jobs.jsonl").read_text(encoding="utf-8")
    assert "RuntimeError，请查看工作区日志" in saved
    assert "provider response" not in saved
    assert app._last_job(selected)["status"] == "failed"


def test_gui_heartbeat_does_not_fake_step_progress(tmp_path: Path, monkeypatch):
    app = GuiApplication(recent_path=tmp_path / "recent-projects.json")
    job = Job(id="heartbeat-job", workspace="unused", stage="analyze")
    updated_at = job.updated_at
    job.heartbeat_at = (datetime.now() - timedelta(seconds=1)).isoformat(timespec="seconds")
    initial_heartbeat = job.heartbeat_at
    monkeypatch.setattr("mmw.gui.server.HEARTBEAT_INTERVAL_SECONDS", 0.01)

    app._launch_job(job, lambda _: time.sleep(0.05))
    time.sleep(0.03)

    assert job.heartbeat_at != initial_heartbeat
    assert job.updated_at == updated_at
    assert job.current_step == "准备任务"
    assert job.progress is None


def test_gui_reports_stalled_without_changing_running_status(tmp_path: Path):
    app = GuiApplication(recent_path=tmp_path / "recent-projects.json")
    job = Job(id="stalled-job", workspace="unused", stage="analyze")
    job.heartbeat_at = (datetime.now() - timedelta(seconds=21)).isoformat(timespec="seconds")

    payload = app.job_payload(job)

    assert payload["status"] == "running"
    assert payload["possible_stalled"] is True


def test_gui_restores_unfinished_ordinary_job_as_orphaned(tmp_path: Path):
    project = tmp_path / "project"
    project.mkdir()
    app = GuiApplication(recent_path=tmp_path / "recent-projects.json")
    selected = app.register_project(project)["project_id"]
    with app._lock:
        app._new_job_locked(selected, "analyze", "stage", "已启动")

    restarted = GuiApplication(recent_path=tmp_path / "recent-projects.json")
    restarted_id = restarted.register_project(project)["project_id"]
    summary = restarted._last_job(restarted_id)

    assert summary["status"] == "orphaned"
    assert "重新启动" in summary["message"]


def test_gui_update_status_reconnects_to_running_update(tmp_path: Path, monkeypatch):
    app = GuiApplication(
        workspace_root=tmp_path / "unused",
        env_path=tmp_path / ".env",
        recent_path=tmp_path / "recent-projects.json",
    )
    monkeypatch.setattr(app, "_launch_job", lambda job, target: None)

    job = app.start_update(lambda executable: None)

    assert app.update_status()["active_job"]["id"] == job.id


def test_gui_frontend_restores_one_polling_loop_and_retries_network_errors():
    html = (Path(__file__).parents[1] / "mmw" / "gui" / "static" / "index.html").read_text(
        encoding="utf-8"
    )
    poll_source = html.split("async function pollJob", 1)[1].split(
        "function renderStageList", 1
    )[0]

    assert "pollTimer:null" in html
    assert "clearTimeout(state.pollTimer)" in poll_source
    assert "scheduleJobPoll(id,1500)" in poll_source
    assert "scheduleJobPoll(id,pollDelay)" in poll_source
    assert "toast(error.message,true)" not in poll_source
    assert 'job.possible_stalled?"可能卡住"' in html
    assert "job.heartbeat_at||job.updated_at" in html
    assert '!["overview","outputs"].includes(target)' in html


def test_gui_rework_flag_requires_json_boolean():
    assert GuiHandler._boolean({}, "run_immediately") is False
    try:
        GuiHandler._boolean({"run_immediately": "false"}, "run_immediately")
    except ValueError as exc:
        assert "布尔值" in str(exc)
    else:
        raise AssertionError("字符串不能作为 run_immediately 布尔值")
