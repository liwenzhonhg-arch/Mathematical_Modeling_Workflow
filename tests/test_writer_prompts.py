"""Writer 提示词模板回归测试。"""

from pathlib import Path

from mmw.agents.writer import BATCH2_PROMPT, WriterAgent


def test_batch2_prompt_can_format_citation_example():
    prompt = BATCH2_PROMPT.format(
        model="model",
        results="results",
        eda_section="eda",
        results_json="{}",
        sensitivity_json="{}",
        figures_section="figures",
        method_contract="{}",
    )

    assert r"\cite{key}" in prompt


def test_writer_prompt_avoids_forbidden_global_phrase():
    prompt = (
        Path(__file__).parents[1] / "mmw" / "prompts" / "system" / "writer.j2"
    ).read_text(encoding="utf-8")

    assert "连否定句也不要使用“全局最优”" in prompt


def test_run_batch_retries_only_missing_artifacts(monkeypatch):
    responses = iter([
        '<artifact name="sections/model_solution.tex">正文</artifact>',
        '<artifact name="references.bib">@book{key,title={Book}}</artifact>',
    ])
    agent = WriterAgent.__new__(WriterAgent)
    monkeypatch.setattr(agent, "run_stream", lambda *args, **kwargs: next(responses))

    artifacts = agent._run_batch("prompt", [
        "sections/model_solution.tex", "references.bib",
    ])

    assert set(artifacts) == {"sections/model_solution.tex", "references.bib"}


def test_revise_sections_retries_truncated_missing_artifact(monkeypatch):
    responses = iter([
        '<artifact name="sections/abstract.tex">新摘要</artifact>',
        '<artifact name="sections/symbols.tex">补全 K</artifact>',
    ])
    agent = WriterAgent.__new__(WriterAgent)

    def run_stream(*args, **kwargs):
        agent.last_finish_reason = "length"
        return next(responses)

    monkeypatch.setattr(agent, "run_stream", run_stream)

    revised = agent.revise_sections(
        {
            "sections/abstract.tex": "旧摘要",
            "sections/symbols.tex": "旧符号",
        },
        "修订",
        "[]",
        "{}",
    )

    assert revised == {
        "sections/abstract.tex": "新摘要",
        "sections/symbols.tex": "补全 K",
    }
