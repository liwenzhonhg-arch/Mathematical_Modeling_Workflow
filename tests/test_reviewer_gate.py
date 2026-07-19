"""Reviewer artifact 恢复与程序化数值门禁测试。"""

import json

import pytest
import typer

import mmw.cli as cli
from mmw.agents.reviewer import ReviewerAgent, _markdown_check_status, get_review_rework_stage
from mmw.models import MetaData, StageID
from mmw.pipeline.stage_review import _add_numeric_audit_check, build_numeric_audit
from mmw.pipeline.state_machine import PipelineStateMachine
from mmw.utils.checkpoint import CheckpointManager


class DummyLLM:
    pass


def test_reviewer_recovers_fenced_checklist(monkeypatch):
    agent = ReviewerAgent(DummyLLM())
    response = '''# 评审报告

# checklist.json
```json
{"items": [{"check": "结果", "status": "pass"}]}
```
'''
    monkeypatch.setattr(agent, "render_prompt", lambda *args, **kwargs: "prompt")
    monkeypatch.setattr(agent, "run_stream", lambda prompt: response)

    artifacts = agent.review({"a.tex": "论文"})

    assert json.loads(artifacts["checklist.json"])["items"][0]["status"] == "pass"


def test_reviewer_keeps_response_when_review_artifact_is_missing(monkeypatch):
    agent = ReviewerAgent(DummyLLM())
    response = '''<artifact name="checklist.json">
{"items": [{"check": "模型", "status": "fail"}]}
</artifact>
# 论文评审报告
输出在此处截断'''
    monkeypatch.setattr(agent, "render_prompt", lambda *args, **kwargs: "prompt")
    monkeypatch.setattr(agent, "run_stream", lambda prompt: response)

    artifacts = agent.review({"a.tex": "论文"})

    assert "# 论文评审报告" in artifacts["review.md"]


def test_numeric_audit_failure_is_appended_to_checklist():
    artifacts = {"checklist.json": '{"items": []}'}

    _add_numeric_audit_check(artifacts, 2)

    item = json.loads(artifacts["checklist.json"])["items"][-1]
    assert item["status"] == "fail"
    assert "2" in item["note"]


def test_local_numeric_audit_command_does_not_need_llm(tmp_path, monkeypatch):
    mgr = CheckpointManager(tmp_path)
    mgr.save(StageID.SOLVE, {
        "results.json": '[{"name":"q1_value","value":12.34,"unit":"","desc":"结果"}]',
    }, MetaData(stage=StageID.SOLVE.value, version=0))
    mgr.save(StageID.PAPER, {
        "sections/abstract.tex": "结果为 12.34。",
    }, MetaData(stage=StageID.PAPER.value, version=0))
    monkeypatch.setattr(cli, "_get_mgr", lambda workspace: (mgr, PipelineStateMachine(mgr)))

    report, audit_md = build_numeric_audit(tmp_path, mgr)
    cli.audit(workspace="test")

    assert report.matched == 1
    assert "高置信缺出处 0 个" in audit_md


def test_local_numeric_audit_command_exits_nonzero_on_unmatched(tmp_path, monkeypatch):
    mgr = CheckpointManager(tmp_path)
    mgr.save(StageID.PAPER, {
        "sections/abstract.tex": "结果为 1234.56。",
    }, MetaData(stage=StageID.PAPER.value, version=0))
    monkeypatch.setattr(cli, "_get_mgr", lambda workspace: (mgr, PipelineStateMachine(mgr)))

    with pytest.raises(typer.Exit) as exc:
        cli.audit(workspace="test")

    assert exc.value.exit_code == 1


def test_reviewer_recovers_markdown_checkboxes(monkeypatch):
    agent = ReviewerAgent(DummyLLM())
    response = "# 评审\n- [x] 摘要独立成页\n- [ ] 附录代码完整"
    monkeypatch.setattr(agent, "render_prompt", lambda *args, **kwargs: "prompt")
    monkeypatch.setattr(agent, "run_stream", lambda prompt: response)

    items = json.loads(agent.review({"a.tex": "论文"})["checklist.json"])["items"]

    assert [item["status"] for item in items] == ["pass", "warning"]


def test_reviewer_prefers_unnamed_json_over_markdown(monkeypatch):
    agent = ReviewerAgent(DummyLLM())
    response = '''- [x] 参考文献完整
```json
{"items": [{"check": "参考文献", "status": "warning"}]}
```'''
    monkeypatch.setattr(agent, "render_prompt", lambda *args, **kwargs: "prompt")
    monkeypatch.setattr(agent, "run_stream", lambda prompt: response)

    items = json.loads(agent.review({"a.tex": "论文"})["checklist.json"])["items"]

    assert items[0]["status"] == "warning"


def test_markdown_check_status_uses_text_evidence():
    assert _markdown_check_status(" ", "摘要是否独立成页——是") == "pass"
    assert _markdown_check_status(" ", "图表缺失") == "fail"
    assert _markdown_check_status(" ", "页数需确认") == "warning"
    assert _markdown_check_status("x", "附录代码是否完整（否，仅提及文件名）") == "fail"
    assert _markdown_check_status("x", "论文页数（未提供总页数，需自行检查）") == "warning"


def test_reviewer_routes_model_logic_failure_to_model(monkeypatch):
    agent = ReviewerAgent(DummyLLM())
    response = '''<artifact name="checklist.json">
{"items": [{"check": "模型验证逻辑", "status": "fail", "note": "负相关不能证明一致"}]}
</artifact>'''
    monkeypatch.setattr(agent, "render_prompt", lambda *args, **kwargs: "prompt")
    monkeypatch.setattr(agent, "run_stream", lambda prompt: response)

    artifacts = agent.review({"a.tex": "论文"})

    assert get_review_rework_stage(artifacts) == "model"


def test_reviewer_overrides_wrong_model_route_for_numeric_audit(monkeypatch):
    agent = ReviewerAgent(DummyLLM())
    response = '''<artifact name="checklist.json">
{"rework_stage": "model", "items": [{"check": "数值审计", "status": "fail", "note": "14.8 缺出处，应写入 results.json"}]}
</artifact>'''
    monkeypatch.setattr(agent, "render_prompt", lambda *args, **kwargs: "prompt")
    monkeypatch.setattr(agent, "run_stream", lambda prompt: response)

    artifacts = agent.review({"a.tex": "论文"})

    assert get_review_rework_stage(artifacts) == "code"


def test_reviewer_routes_paper_only_missing_number_to_paper(monkeypatch):
    agent = ReviewerAgent(DummyLLM())
    response = '''<artifact name="checklist.json">
{"rework_stage": "code", "items": [{"check": "数值审计", "status": "fail", "note": "14.76 缺出处，需核实或删除"}]}
</artifact>'''
    monkeypatch.setattr(agent, "render_prompt", lambda *args, **kwargs: "prompt")
    monkeypatch.setattr(agent, "run_stream", lambda prompt: response)

    artifacts = agent.review({"a.tex": "论文"})

    assert get_review_rework_stage(artifacts) == "paper"


def test_reviewer_routes_mixed_model_and_numeric_failures_to_model(monkeypatch):
    agent = ReviewerAgent(DummyLLM())
    response = '''<artifact name="checklist.json">
{"items": [
  {"check": "决策模型", "status": "fail", "note": "等待时间方程口径矛盾"},
  {"check": "数值审计", "status": "fail", "note": "41.21 缺出处"}
]}
</artifact>'''
    monkeypatch.setattr(agent, "render_prompt", lambda *args, **kwargs: "prompt")
    monkeypatch.setattr(agent, "run_stream", lambda prompt: response)

    artifacts = agent.review({"a.tex": "论文"})

    assert get_review_rework_stage(artifacts) == "model"


def test_reviewer_uses_none_when_no_fail(monkeypatch):
    agent = ReviewerAgent(DummyLLM())
    response = '''<artifact name="checklist.json">
{"rework_stage": "paper", "items": [{"check": "结果", "status": "warning"}]}
</artifact>'''
    monkeypatch.setattr(agent, "render_prompt", lambda *args, **kwargs: "prompt")
    monkeypatch.setattr(agent, "run_stream", lambda prompt: response)

    assert get_review_rework_stage(agent.review({"a.tex": "论文"})) == "none"
