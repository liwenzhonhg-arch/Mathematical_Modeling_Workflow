"""Reviewer artifact 恢复与程序化数值门禁测试。"""

import json

from mmw.agents.reviewer import ReviewerAgent, _markdown_check_status, get_review_rework_stage
from mmw.pipeline.stage_review import _add_numeric_audit_check


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


def test_numeric_audit_failure_is_appended_to_checklist():
    artifacts = {"checklist.json": '{"items": []}'}

    _add_numeric_audit_check(artifacts, 2)

    item = json.loads(artifacts["checklist.json"])["items"][-1]
    assert item["status"] == "fail"
    assert "2" in item["note"]


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


def test_reviewer_routes_model_logic_failure_to_model(monkeypatch):
    agent = ReviewerAgent(DummyLLM())
    response = '''<artifact name="checklist.json">
{"items": [{"check": "模型验证逻辑", "status": "fail", "note": "负相关不能证明一致"}]}
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
