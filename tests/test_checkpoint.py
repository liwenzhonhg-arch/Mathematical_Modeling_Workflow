"""检查点版本树测试：保存、加载、审批、上游变更检测。"""

from pathlib import Path

import pytest

from mmw.models import CheckpointStatus, MetaData, StageID, StageResult
from mmw.utils.checkpoint import CheckpointManager


@pytest.fixture
def mgr(tmp_path):
    return CheckpointManager(tmp_path)


def _meta(stage: StageID) -> MetaData:
    return MetaData(stage=stage.value, version=0)


def test_version_tree_increments(mgr):
    assert mgr.get_latest_version(StageID.ANALYZE) == 0

    vdir1 = mgr.save(StageID.ANALYZE, {"analysis.md": "v1 内容"}, _meta(StageID.ANALYZE))
    assert vdir1.name == "v1"
    assert mgr.get_latest_version(StageID.ANALYZE) == 1

    vdir2 = mgr.save(StageID.ANALYZE, {"analysis.md": "v2 内容"}, _meta(StageID.ANALYZE))
    assert vdir2.name == "v2"
    assert mgr.get_latest_version(StageID.ANALYZE) == 2

    # 旧版本仍然可读
    assert mgr.load_artifacts(StageID.ANALYZE, version=1)["analysis.md"] == "v1 内容"
    assert mgr.load_artifacts(StageID.ANALYZE)["analysis.md"] == "v2 内容"


def test_save_writes_meta_and_status(mgr):
    mgr.save(StageID.ANALYZE, {"a.md": "x"}, _meta(StageID.ANALYZE))

    meta = mgr.load_meta(StageID.ANALYZE)
    assert meta is not None
    assert meta.version == 1
    assert meta.stage == "analyze"


def test_save_retries_transient_windows_replace_error(mgr, monkeypatch):
    original_replace = Path.replace
    attempts = 0

    def flaky_replace(path, target):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise PermissionError("temporarily locked")
        return original_replace(path, target)

    monkeypatch.setattr(Path, "replace", flaky_replace)

    vdir = mgr.save(StageID.ANALYZE, {"a.md": "x"}, _meta(StageID.ANALYZE))

    assert vdir.is_dir()
    assert attempts == 2

    status = mgr.load_status(StageID.ANALYZE)
    assert status is not None
    assert status.status == CheckpointStatus.COMPLETED


def test_load_artifacts_includes_subdirectories(mgr):
    # paper 阶段产出含 sections/ 子目录，rglob 必须能读到
    mgr.save(
        StageID.PAPER,
        {"sections/abstract.tex": "摘要", "references.bib": "@book{}"},
        _meta(StageID.PAPER),
    )
    artifacts = mgr.load_artifacts(StageID.PAPER)
    assert artifacts["sections/abstract.tex"] == "摘要"
    assert artifacts["references.bib"] == "@book{}"
    assert "meta.json" not in artifacts
    assert "status.json" not in artifacts


def test_save_rejects_path_traversal(mgr):
    with pytest.raises(ValueError):
        mgr.save(StageID.ANALYZE, {"../evil.txt": "x"}, _meta(StageID.ANALYZE))


def test_approve_flow(mgr):
    mgr.save(StageID.ANALYZE, {"a.md": "x"}, _meta(StageID.ANALYZE))
    assert not mgr.is_approved(StageID.ANALYZE)

    mgr.approve(StageID.ANALYZE, result=StageResult.PROCEED)
    assert mgr.is_approved(StageID.ANALYZE)

    status = mgr.load_status(StageID.ANALYZE)
    assert status.result == StageResult.PROCEED
    assert status.approved_at is not None


def test_upstream_change_detection(mgr):
    mgr.save(StageID.ANALYZE, {"a.md": "原始"}, _meta(StageID.ANALYZE))
    mgr.approve(StageID.ANALYZE)
    mgr.save(StageID.EDA, {"summary.md": "eda"}, _meta(StageID.EDA))
    mgr.approve(StageID.EDA)

    # 上游未变时不报变更
    assert not mgr.check_upstream_changed(StageID.EDA)

    # 上游 analyze 重跑出 v2，eda 应检测到变更
    mgr.save(StageID.ANALYZE, {"a.md": "重做后的内容"}, _meta(StageID.ANALYZE))
    mgr.approve(StageID.ANALYZE)
    assert mgr.check_upstream_changed(StageID.EDA)

    changes = mgr.refresh_upstream_flags()
    assert changes["eda"] is True
    status = mgr.load_status(StageID.EDA)
    assert status.upstream_changed is True


def _init_config(workspace):
    """造一个带 config.yaml 的工作空间（激活版本机制需要）。"""
    from mmw.utils.file_io import write_yaml

    write_yaml(workspace / "config.yaml", {"name": "test", "active_versions": {}})


def test_active_version_fallback_without_config(mgr):
    # 测试夹具无 config.yaml：激活版本回退最新版
    mgr.save(StageID.ANALYZE, {"a.md": "v1"}, _meta(StageID.ANALYZE))
    mgr.save(StageID.ANALYZE, {"a.md": "v2"}, _meta(StageID.ANALYZE))
    assert mgr.get_active_version(StageID.ANALYZE) == 2


def test_missing_config_prefers_latest_approved_over_unapproved(mgr):
    mgr.save(StageID.MODEL, {"model.md": "v1"}, _meta(StageID.MODEL))
    mgr.approve(StageID.MODEL)
    mgr.save(StageID.MODEL, {"model.md": "v2"}, _meta(StageID.MODEL))
    assert mgr.get_active_version(StageID.MODEL) == 1


def test_artifact_cannot_escape_into_sibling_version(mgr):
    with pytest.raises(ValueError):
        mgr.save(StageID.CODE, {"../v10/evil.txt": "x"}, _meta(StageID.CODE))
    assert not mgr._version_dir(StageID.CODE, 10).exists()


def test_set_active_version_pins_old_version(mgr, tmp_path):
    _init_config(tmp_path)
    mgr.save(StageID.MODEL, {"model.md": "方案A"}, _meta(StageID.MODEL))
    mgr.save(StageID.MODEL, {"model.md": "方案B"}, _meta(StageID.MODEL))

    mgr.set_active_version(StageID.MODEL, 1)
    assert mgr.get_active_version(StageID.MODEL) == 1
    # version=None 的加载读激活版而非最新版
    assert mgr.load_artifacts(StageID.MODEL)["model.md"] == "方案A"


def test_approve_activates_version(mgr, tmp_path):
    _init_config(tmp_path)
    mgr.save(StageID.MODEL, {"model.md": "方案A"}, _meta(StageID.MODEL))
    mgr.approve(StageID.MODEL, version=1)
    mgr.save(StageID.MODEL, {"model.md": "方案B"}, _meta(StageID.MODEL))

    # v1 已审批且激活：is_approved（按激活版）为 True
    assert mgr.get_active_version(StageID.MODEL) == 1
    assert mgr.is_approved(StageID.MODEL)


def test_active_version_invalid_falls_back_to_latest(mgr, tmp_path):
    _init_config(tmp_path)
    mgr.save(StageID.MODEL, {"model.md": "v1"}, _meta(StageID.MODEL))
    mgr.set_active_version(StageID.MODEL, 99)  # 指向不存在的版本
    assert mgr.get_active_version(StageID.MODEL) == 1


def test_branch_new_version_does_not_trigger_upstream_changed(mgr, tmp_path):
    _init_config(tmp_path)
    mgr.save(StageID.MODEL, {"model.md": "方案A"}, _meta(StageID.MODEL))
    mgr.approve(StageID.MODEL)  # 激活 v1
    mgr.save(StageID.CODE, {"solution.py": "code"}, _meta(StageID.CODE))
    mgr.approve(StageID.CODE)

    # branch 出 model v2 但不激活：下游 code 不应报上游变更
    mgr.save(StageID.MODEL, {"model.md": "方案B"}, _meta(StageID.MODEL))
    assert not mgr.check_upstream_changed(StageID.CODE)

    # 切换激活到 v2 后才触发变更
    mgr.set_active_version(StageID.MODEL, 2)
    assert mgr.check_upstream_changed(StageID.CODE)


def test_ack_upstream_clears_changed_flag(mgr):
    mgr.save(StageID.ANALYZE, {"a.md": "v1"}, _meta(StageID.ANALYZE))
    mgr.approve(StageID.ANALYZE)
    mgr.save(StageID.EDA, {"data_summary.md": "摘要"}, _meta(StageID.EDA))
    mgr.approve(StageID.EDA)

    # 人工编辑上游检查点内容 → 下游检测到变更
    vdir = mgr._version_dir(StageID.ANALYZE, 1)
    (vdir / "a.md").write_text("人工修订", encoding="utf-8")
    assert mgr.check_upstream_changed(StageID.EDA)
    mgr.refresh_upstream_flags()
    assert mgr.load_status(StageID.EDA).upstream_changed

    # ack 后：hash 刷新、标记清除、refresh 不再标记
    assert mgr.ack_upstream(StageID.EDA)
    assert not mgr.check_upstream_changed(StageID.EDA)
    status = mgr.load_status(StageID.EDA)
    assert not status.upstream_changed
    mgr.refresh_upstream_flags()
    assert not mgr.load_status(StageID.EDA).upstream_changed


def test_ack_upstream_no_checkpoint_returns_false(mgr):
    assert not mgr.ack_upstream(StageID.EDA)


def test_load_artifacts_skips_pycache_and_binary(mgr):
    # 误入检查点的 __pycache__/*.pyc 和非 UTF-8 文件不应让加载崩溃
    vdir = mgr.save(StageID.CODE, {"solution.py": "print(1)"}, _meta(StageID.CODE))
    cache = vdir / "__pycache__"
    cache.mkdir()
    (cache / "solution.cpython-314.pyc").write_bytes(b"\xca\xfe\xba\xbe")
    (vdir / "legacy.txt").write_bytes("GBK 中文".encode("gbk"))

    artifacts = mgr.load_artifacts(StageID.CODE)
    assert artifacts["solution.py"] == "print(1)"
    assert all("__pycache__" not in name for name in artifacts)
    assert "legacy.txt" not in artifacts


def test_pipeline_status_overview(mgr):
    mgr.save(StageID.ANALYZE, {"a.md": "x"}, _meta(StageID.ANALYZE))
    mgr.approve(StageID.ANALYZE)

    overview = mgr.get_pipeline_status()
    assert len(overview) == 8
    assert overview[0]["stage"] == "analyze"
    assert overview[0]["status"] == "approved"
    assert overview[0]["version"] == 1
    assert overview[1]["status"] == "pending"
    assert overview[1]["version"] == 0
