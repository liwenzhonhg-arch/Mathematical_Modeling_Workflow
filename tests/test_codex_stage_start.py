from pathlib import Path

from mmw.config import Settings
from mmw.pipeline import stage_analyze


def test_analyze_stage_accepts_codex_without_api_key(tmp_path: Path, monkeypatch):
    internal = tmp_path / ".mmw"
    internal.mkdir()
    (internal / "problem.md").write_text("测试题目", encoding="utf-8")
    saved = {}

    class FakeLLM:
        def __init__(self, config, log_dir):
            assert config.backend == "codex"
            assert config.api_key == ""
            self.model = "codex"
            self.total_input_tokens = 0
            self.total_output_tokens = 0

    class FakeAgent:
        def __init__(self, llm):
            self.llm = llm

        def analyze(self, problem_text, data_files, input_evidence=""):
            assert problem_text == "测试题目"
            return {"analysis.md": "完成"}

    class FakeManager:
        def save(self, stage, artifacts, meta):
            saved["artifacts"] = artifacts
            return tmp_path / "checkpoint"

    settings = Settings(_env_file=None, llm_backend="codex")
    monkeypatch.setattr(stage_analyze, "get_settings", lambda: settings)
    monkeypatch.setattr(stage_analyze, "LLMClient", FakeLLM)
    monkeypatch.setattr(stage_analyze, "AnalystAgent", FakeAgent)

    stage_analyze.run_analyze(tmp_path, FakeManager())

    assert saved["artifacts"] == {"analysis.md": "完成"}
