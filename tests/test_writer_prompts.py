"""Writer 提示词模板回归测试。"""

from mmw.agents.writer import BATCH2_PROMPT


def test_batch2_prompt_can_format_citation_example():
    prompt = BATCH2_PROMPT.format(
        model="model",
        results="results",
        eda_section="eda",
        results_json="{}",
        sensitivity_json="{}",
        figures_section="figures",
    )

    assert r"\cite{key}" in prompt
