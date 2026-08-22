"""Writer 提示词模板回归测试。"""

from pathlib import Path

from mmw.agents.writer import BATCH2_PROMPT, WriterAgent, _latex_fragment


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
    assert "不得猜测区域名称" in prompt
    assert "不得猜测仿真重复次数" in prompt


def test_latex_fragment_strips_document_wrapper():
    wrapped = (
        r"\documentclass{article}" "\n"
        r"\usepackage{ctex}" "\n"
        r"\begin{document}" "\n"
        r"\section{模型}" "\n"
        "正文\n"
        r"\end{document}"
    )

    fragment = _latex_fragment(wrapped)

    assert fragment == "\\section{模型}\n正文"
    assert r"\documentclass" not in fragment
    assert r"\begin{document}" not in fragment


def test_writer_prompt_avoids_forbidden_global_phrase():
    prompt = (
        Path(__file__).parents[1] / "mmw" / "prompts" / "system" / "writer.j2"
    ).read_text(encoding="utf-8")

    assert "连否定句也不要使用“全局最优”" in prompt


def test_writer_uses_model_handoff_as_primary_model(monkeypatch):
    prompts: list[str] = []
    responses = iter([
        "".join(
            f'<artifact name="{name}">正文</artifact>'
            for name in (
                "sections/abstract.tex",
                "sections/problem_restatement.tex",
                "sections/problem_analysis.tex",
                "sections/assumptions.tex",
                "sections/symbols.tex",
            )
        ),
        "".join(
            f'<artifact name="{name}">正文</artifact>'
            for name in (
                "sections/model_solution.tex",
                "sections/sensitivity.tex",
                "sections/evaluation.tex",
                "references.bib",
            )
        ),
    ])
    agent = WriterAgent.__new__(WriterAgent)

    def run_stream(prompt, **kwargs):
        prompts.append(prompt)
        return next(responses)

    monkeypatch.setattr(agent, "run_stream", run_stream)

    agent.write_paper(
        analysis="分析",
        assumptions="精简假设",
        model="完整模型中的历史追加不应进入 prompt",
        model_handoff="现役模型交接摘要",
        results="结果",
    )

    assert all("现役模型交接摘要" in prompt for prompt in prompts)
    assert all("完整模型中的历史追加" not in prompt for prompt in prompts)


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


def test_revise_sections_receives_original_problem_evidence(monkeypatch):
    prompts: list[str] = []
    agent = WriterAgent.__new__(WriterAgent)

    def run_stream(prompt, **kwargs):
        prompts.append(prompt)
        return '<artifact name="sections/model_solution.tex">已补原始参数表</artifact>'

    monkeypatch.setattr(agent, "run_stream", run_stream)

    agent.revise_sections(
        {"sections/model_solution.tex": "旧正文"},
        "补充原始数据",
        "[]",
        "{}",
        source_evidence="节点0坐标为(0,0)，速度35 km/h",
    )

    assert "节点0坐标为(0,0)，速度35 km/h" in prompts[0]
