from pathlib import Path
from types import SimpleNamespace

from mmw.agents.typesetter import TypesetterAgent, normalize_tex_artifacts, validate_typeset_revision
from mmw.pipeline import stage_paper


def test_typesetter_protects_numbers_references_and_files():
    before = {
        "sections/a.tex": r"结果为 12.5。\label{x}\cite{k}\includegraphics{a.png}",
        "references.bib": "@article{k, title={T}}",
    }
    assert validate_typeset_revision(before, dict(before)) == []
    assert validate_typeset_revision(before, {**before, "sections/a.tex": before["sections/a.tex"].replace("12.5", "13")})
    assert validate_typeset_revision(before, {**before, "extra.tex": "x"})


def test_typesetter_normalizes_only_whitespace():
    source = {"sections/a.tex": "正文  \n\n\n\n下一段", "notes.md": "不改"}
    result, changed = normalize_tex_artifacts(source)
    assert result["sections/a.tex"] == "正文\n\n\n下一段\n"
    assert result["notes.md"] == "不改"
    assert changed == ["sections/a.tex"]


def test_typesetter_accepts_partial_output_and_preserves_omitted_files(monkeypatch):
    agent = object.__new__(TypesetterAgent)
    monkeypatch.setattr(agent, "render_prompt", lambda *args, **kwargs: "first")
    monkeypatch.setattr(
        agent,
        "run_stream",
        lambda *args, **kwargs: '<artifact name="sections/a.tex">正文</artifact>',
    )

    revised, report = agent.typeset({
        "sections/a.tex": "正文",
        "sections/b.tex": "保留",
    })

    assert revised["sections/a.tex"] == "正文"
    assert revised["sections/b.tex"] == "保留\n"
    assert report["accepted"] is True
    assert report["rounds"] == 1


def test_rerun_typesetter_uses_latest_draft(tmp_path, monkeypatch):
    class Manager:
        def get_latest_version(self, stage):
            return 7

        def load_artifacts(self, stage, version):
            assert version == 7
            return {"sections/a.tex": "latest draft"}

        def save(self, stage, artifacts, meta):
            assert artifacts["sections/a.tex"] == "latest draft"
            return Path("v8")

    class DummyLLM:
        model = "dummy"
        total_input_tokens = 0
        total_output_tokens = 0

    monkeypatch.setattr(
        stage_paper,
        "get_settings",
        lambda: SimpleNamespace(
            get_llm_config=lambda role: SimpleNamespace(backend="codex", api_key="")
        ),
    )
    monkeypatch.setattr(stage_paper, "LLMClient", lambda *args, **kwargs: DummyLLM())
    monkeypatch.setattr(
        stage_paper,
        "TypesetterAgent",
        lambda llm: SimpleNamespace(
            typeset=lambda artifacts, feedback: (
                artifacts,
                {"accepted": True, "violations": []},
            )
        ),
    )

    assert stage_paper.rerun_typesetter(tmp_path, Manager()) == Path("v8")
