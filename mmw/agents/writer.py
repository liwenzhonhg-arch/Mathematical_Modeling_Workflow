"""Writer Agent：论文写作（分节 LaTeX），分两批生成避免截断。"""

from __future__ import annotations

from mmw.agents.base import BaseAgent
from mmw.llm import LLMClient
from mmw.utils.display import print_info
from mmw.utils.figure_quality import load_paper_style

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

## 已验证的实际方法契约
{method_contract}

## 关键数值结果（results.json，求解程序真实运行产出）
{results_json}

**铁律：摘要中出现的所有数值结果必须出自上表，禁止编造或改写任何数字。**摘要必须包含具体数值结论（如最优值、误差、百分比）。
摘要必须按方法契约写明实际 implementation；若实际为 heuristic，不得笼统称为“利用求解器”，必须点明启发式、贪心、枚举或实际算法名。
符号表必须覆盖 formulation 目标与约束中使用的全部大写单字母符号（例如车辆数上界 $K$）。

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

## 已验证的实际方法契约
{method_contract}

## 求解结果
{results}

{eda_section}

## 关键数值结果（results.json，求解程序真实运行产出）
{results_json}

## 灵敏度实验数据（sensitivity.json，真实运行结果）
{sensitivity_json}

{figures_section}

**铁律：论文中出现的所有数值结果必须出自上述 results.json 或 sensitivity.json，禁止编造或改写任何数字。**
**图表铁律：只能使用“生成的图表”列表中逐字出现的文件名；列表外的 EDA 图、示意图或猜测文件名一律不得写 `\\includegraphics`。**
参考文献条目必须在正文中用 `\\cite{{key}}` 实际引用；不得只生成未被引用的 references.bib。
如果“数学模型”中的拟采用方法与“求解结果”或 results.json 的实际运行产物不一致，必须以实际求解产物为准；不得把未运行的算法、未生成的帕累托前沿、未出现的参数设置写成已经完成的求解过程。
论文必须区分数学 formulation 与实际 implementation，并按方法契约如实说明 exact/heuristic、截断、近似、随机种子、deviations 和 limitations；不得使用高于契约 `claims.optimality` 的结论。
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
3. 去除 LaTeX 命令与空白后必须保持 400-600 字；若是最后一次修订仍超长，优先压缩方法过程和重复结论，不得牺牲数值真实性
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

REVISE_SECTIONS_PROMPT = """请只修订下列论文小节，消除评审指出的问题。

## 待修订小节
{sections}

## 评审证据
{feedback}

## results.json
{results_json}

## sensitivity.json
{sensitivity_json}

## 已验证的实际方法契约
{method_contract}

铁律：删除或改写没有直接出现在结构化结果中的数值，不得自行推导新的阈值、差值或整数近似。
如果评审指出缺少文献引用，待修订内容会包含 references.bib；必须从其中读取真实 BibTeX key，
在相关正文中加入至少一个 `\\cite{{真实key}}`，不得虚构 key，也不得只改 references.bib。
如果评审指出缺少核心图表引用，必须按反馈列出的真实文件名加入 `\\includegraphics`，
并为每张图添加标题、编号、正文引用和结果分析，不得只写“图表已保存”。
每个修订后小节必须使用原文件名的 `<artifact name="...">` 输出；标签外不要写说明。
"""


class WriterAgent(BaseAgent):

    role = "writer"
    system_prompt_template = "system/writer.j2"

    def _run_batch(self, prompt: str, expected: list[str]) -> dict[str, str]:
        """执行一个批次，缺少预期产物时带格式提醒补齐一次。"""
        response = self.run_stream(prompt, system_kwargs={"paper_style": load_paper_style()})
        artifacts = self.parse_artifacts(response)
        missing = [name for name in expected if not artifacts.get(name)]
        if missing:
            reason = "输出被截断且" if getattr(self, "last_finish_reason", None) == "length" else ""
            print_info(f"批次{reason}缺少预期 artifact，按格式要求补齐一次...")
            expected_str = "\n".join(f'- <artifact name="{name}">' for name in missing)
            response = self.run_stream(FORMAT_RETRY_PROMPT.format(expected=expected_str))
            artifacts.update(self.parse_artifacts(response))
        missing = [name for name in expected if not artifacts.get(name)]
        if missing:
            raise RuntimeError("LLM 输出不完整，仍缺少 artifact: " + ", ".join(missing))
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
        method_contract: str = "{}",
    ) -> dict[str, str]:
        all_artifacts: dict[str, str] = {}

        # 第一批：前半部分
        print_info("生成论文前半部分（摘要/重述/假设/符号）...")
        prompt1 = BATCH1_PROMPT.format(
            analysis=analysis,
            assumptions=assumptions,
            model_brief=model[:2000],
            method_contract=method_contract,
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
                "数据预处理小节应基于此摘要撰写；只有“生成的图表”列表明确列出的图才能引用。"
            )

        prompt2 = BATCH2_PROMPT.format(
            model=model,
            results=results,
            results_json=results_json,
            sensitivity_json=sensitivity_json,
            figures_section=figures_section,
            eda_section=eda_section,
            method_contract=method_contract,
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
        response = self.run_stream(prompt, system_kwargs={"paper_style": load_paper_style()})
        artifacts = self.parse_artifacts(response)
        return artifacts.get("sections/abstract.tex", abstract)

    def revise_sections(
        self,
        sections: dict[str, str],
        feedback: str,
        results_json: str,
        sensitivity_json: str,
        method_contract: str = "{}",
    ) -> dict[str, str]:
        rendered = "\n\n".join(f"### {name}\n{content}" for name, content in sections.items())
        return self._run_batch(
            REVISE_SECTIONS_PROMPT.format(
                sections=rendered,
                feedback=feedback,
                results_json=results_json,
                sensitivity_json=sensitivity_json,
                method_contract=method_contract,
            ),
            list(sections),
        )
