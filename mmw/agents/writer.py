"""Writer Agent：论文写作（分节 LaTeX），分两批生成避免截断。"""

from __future__ import annotations

from mmw.agents.base import BaseAgent
from mmw.llm import LLMClient
from mmw.utils.display import print_info

BATCH1_PROMPT = """请撰写论文的 **前半部分**，包括以下章节：
1. 摘要（含关键词）
2. 问题重述
3. 模型假设
4. 符号说明

## 问题分析
{analysis}

## 模型假设
{assumptions}

## 数学模型（供参考，本批次不需要写模型求解）
{model_brief}

## 关键数值结果（results.json，求解程序真实运行产出）
{results_json}

**铁律：摘要中出现的所有数值结果必须出自上表，禁止编造或改写任何数字。**摘要必须包含具体数值结论（如最优值、误差、百分比）。

请为每个章节输出独立的 artifact：
- <artifact name="sections/abstract.tex">
- <artifact name="sections/problem_restatement.tex">
- <artifact name="sections/assumptions.tex">
- <artifact name="sections/symbols.tex">
"""

BATCH2_PROMPT = """请撰写论文的 **后半部分**，包括以下章节：
5. 模型的建立与求解（这是最重要的部分，应占全文 50-60%）
6. 模型的检验（灵敏度分析）
7. 模型的评价与推广
8. 参考文献

## 数学模型
{model}

## 求解结果
{results}

{eda_section}

## 关键数值结果（results.json，求解程序真实运行产出）
{results_json}

## 灵敏度实验数据（sensitivity.json，真实运行结果）
{sensitivity_json}

{figures_section}

**铁律：论文中出现的所有数值结果必须出自上述 results.json 或 sensitivity.json，禁止编造或改写任何数字。**
灵敏度章节必须基于灵敏度实验数据撰写：逐参数引用 change_pct，给出"模型对参数 X 敏感/稳健"的定量结论，并引用对应灵敏度图（figures 中 sensitivity_ 开头的图）。

请为每个章节输出独立的 artifact：
- <artifact name="sections/model_solution.tex">
- <artifact name="sections/sensitivity.tex">
- <artifact name="sections/evaluation.tex">
- <artifact name="references.bib">
"""


REVISE_ABSTRACT_PROMPT = """请根据评审意见修订以下论文摘要。

## 原摘要
{abstract}

## 评审意见（abstract_score.json）
{critique_json}

## 关键数值结果（results.json，求解程序真实运行产出）
{results_json}

修订要求：
1. 逐条落实评审意见中的 issues 和 suggestions
2. **铁律：修订后摘要中出现的一切数值必须能在上方 results.json 中找到，禁止新增任何编造数字**
3. 保持 400-600 字、段落化表达、含关键词行（5-7 个）
4. 保持 LaTeX 格式不变

只输出修订后的完整摘要：
<artifact name="sections/abstract.tex">
（修订后内容）
</artifact>
"""


FORMAT_RETRY_PROMPT = """你刚才的输出没有使用 <artifact> 标签，系统无法解析为文件，内容已丢弃。

请把刚才的内容**严格按 artifact 标签格式**重新完整输出，每个章节一个标签，标签外不要有任何文字：

{expected}
"""


class WriterAgent(BaseAgent):

    role = "writer"
    system_prompt_template = "system/writer.j2"

    def _run_batch(self, prompt: str, expected: list[str]) -> dict[str, str]:
        """执行一个批次，产出为空时带格式提醒重试一次。"""
        response = self.run_stream(prompt)
        artifacts = self.parse_artifacts(response)
        if not artifacts:
            print_info("批次输出未含 artifact 标签，按格式要求重试一次...")
            expected_str = "\n".join(f'- <artifact name="{name}">' for name in expected)
            response = self.run_stream(FORMAT_RETRY_PROMPT.format(expected=expected_str))
            artifacts = self.parse_artifacts(response)
        return artifacts

    def write_paper(
        self,
        analysis: str,
        assumptions: str,
        model: str,
        results: str,
        interpretation: str = "",
        figures: list[str] | None = None,
        results_json: str = "[]",
        sensitivity_json: str = "{}",
        eda_summary: str = "",
    ) -> dict[str, str]:
        all_artifacts: dict[str, str] = {}

        # 第一批：前半部分
        print_info("生成论文前半部分（摘要/重述/假设/符号）...")
        prompt1 = BATCH1_PROMPT.format(
            analysis=analysis,
            assumptions=assumptions,
            model_brief=model[:2000],
            results_json=results_json,
        )
        arts1 = self._run_batch(prompt1, [
            "sections/abstract.tex",
            "sections/problem_restatement.tex",
            "sections/assumptions.tex",
            "sections/symbols.tex",
        ])
        all_artifacts.update(arts1)

        # 第二批：后半部分
        print_info("生成论文后半部分（模型求解/灵敏度/评价/参考文献）...")
        figures_section = ""
        if figures:
            figures_section = "## 生成的图表\n" + "\n".join(f"- {f}" for f in figures)

        eda_section = ""
        if eda_summary:
            eda_section = (
                "## 数据探索摘要（EDA 真实执行结果）\n"
                f"{eda_summary}\n\n"
                "数据预处理小节应基于此摘要撰写，并引用 figures 中 eda_ 开头的图。"
            )

        prompt2 = BATCH2_PROMPT.format(
            model=model,
            results=results,
            results_json=results_json,
            sensitivity_json=sensitivity_json,
            figures_section=figures_section,
            eda_section=eda_section,
        )
        arts2 = self._run_batch(prompt2, [
            "sections/model_solution.tex",
            "sections/sensitivity.tex",
            "sections/evaluation.tex",
            "references.bib",
        ])
        all_artifacts.update(arts2)

        return all_artifacts

    def revise_abstract(
        self, abstract: str, critique_json: str, results_json: str
    ) -> str:
        """根据评审意见修订摘要。解析失败时返回原摘要。"""
        prompt = REVISE_ABSTRACT_PROMPT.format(
            abstract=abstract,
            critique_json=critique_json,
            results_json=results_json,
        )
        response = self.run_stream(prompt)
        artifacts = self.parse_artifacts(response)
        return artifacts.get("sections/abstract.tex", abstract)
