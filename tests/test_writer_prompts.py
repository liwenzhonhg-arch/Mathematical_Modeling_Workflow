"""Writer 提示词模板回归测试。"""

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
