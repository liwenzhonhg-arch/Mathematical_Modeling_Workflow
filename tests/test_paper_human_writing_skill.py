"""数学建模论文自然表达 Skill 与审计器回归测试。"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


ROOT = Path(__file__).parents[1]
SKILL_DIR = ROOT / "skills" / "mmw-paper-human-writing"
SCRIPT_PATH = SKILL_DIR / "scripts" / "audit_latex_prose.py"


def _load_auditor():
    spec = importlib.util.spec_from_file_location("audit_latex_prose", SCRIPT_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    previous = sys.dont_write_bytecode
    sys.dont_write_bytecode = True
    try:
        spec.loader.exec_module(module)
    finally:
        sys.dont_write_bytecode = previous
    return module


def test_skill_has_triggering_metadata_and_bounded_resources():
    skill = (SKILL_DIR / "SKILL.md").read_text(encoding="utf-8")

    assert skill.startswith("---\nname: mmw-paper-human-writing\n")
    assert "去 AI 味" in skill
    assert "LaTeX 公式、数值、单位、引用" in skill
    assert len(skill.splitlines()) < 500
    assert (SKILL_DIR / "references" / "section-contracts.md").is_file()
    assert (SKILL_DIR / "references" / "protected-content.md").is_file()
    assert (SKILL_DIR / "evals" / "evals.json").is_file()


def test_audit_masks_latex_math_machine_fields_and_mmw_comments():
    auditor = _load_auditor()
    text = r"""% MMW-ID: OBJ-Q1
\section{结果分析}
集合写为 $S=\{i:x_i>0\}$，并由式~\eqref{eq:balance}约束。
\begin{align*}
x_t &= x_{t-1} - 2.5, \\ 
y_t &= 1--3.
\end{align*}
值得注意的是，模型具有良好的推广价值。
"""

    report = auditor.audit_text(text)
    categories = [item["category"] for item in report["warnings"]]

    assert categories.count("meta_signpost") == 1
    assert categories.count("generic_claim") == 1
    assert "MMW-ID" not in auditor.mask_non_prose(text)
    assert "x_t" not in auditor.mask_non_prose(text)


def test_compare_allows_prose_only_rewrite():
    auditor = _load_auditor()
    before = r"""% MMW-ID: OBJ-Q1
由式~\eqref{eq:cost}可知，成本为 $120.4$ 万元。详见 \cite{solver}。
"""
    after = r"""% MMW-ID: OBJ-Q1
式~\eqref{eq:cost}给出的方案成本为 $120.4$ 万元，算法来源见 \cite{solver}。
"""

    report = auditor.compare_texts(before, after)

    assert report["passed"] is True
    assert report["differences"] == {}


def test_compare_blocks_number_math_reference_and_trace_changes():
    auditor = _load_auditor()
    before = r"""% MMW-ID: OBJ-Q1
成本为 $120.4$ 万元，见式~\eqref{eq:cost}和 \cite{solver}。
"""
    after = r"""% MMW-ID: OBJ-Q2
成本为 $119.8$ 万元，见式~\eqref{eq:new_cost}和 \cite{other}。
"""

    report = auditor.compare_texts(before, after)

    assert report["passed"] is False
    assert {"math", "numbers", "references", "mmw_trace"} <= set(
        report["differences"]
    )


def test_cli_warning_is_non_blocking_but_protected_change_blocks(tmp_path):
    auditor = _load_auditor()
    before = tmp_path / "before.tex"
    after = tmp_path / "after.tex"
    before.write_text("值得注意的是，成本为 $120.4$ 万元。", encoding="utf-8")
    after.write_text("成本为 $119.8$ 万元。", encoding="utf-8")

    assert auditor.main(["audit", str(before)]) == 0
    assert auditor.main(["compare", str(before), str(after)]) == 1


def test_audit_detects_template_nominalization_and_near_duplicate():
    auditor = _load_auditor()
    text = """首先，我们进行了需求分析。其次，我们进行了模型求解。最后，我们进行了结果验证。

该方案能够有效降低系统成本，并且能够减少高峰时段的购电压力，从而提高整体运行水平。

该方案可以有效降低系统成本，同时可以减少高峰时段的购电压力，从而提升整体运行水平。
"""

    report = auditor.audit_text(text)
    categories = {item["category"] for item in report["warnings"]}

    # 顺序词与真实分析、求解、验证动作绑定时不应被机械判为模板。
    assert "sequence_template" not in categories
    assert "nominalization" in categories
    assert "near_duplicate" in categories


def test_audit_flags_empty_sequence_and_ignores_problem_locators():
    auditor = _load_auditor()
    dead_template = "首先是背景。其次是方法。最后是结果。"
    report = auditor.audit_text(dead_template)
    assert "sequence_template" in {item["category"] for item in report["warnings"]}

    locators = """对于问题一，建立成本模型并求解。

针对问题二，建立约束模型并验证。

对于问题三，比较两种方案并报告结果。
"""
    report = auditor.audit_text(locators)
    assert "repeated_paragraph_opener" not in {
        item["category"] for item in report["warnings"]
    }


def test_audit_flags_result_evidence_and_generic_evaluation():
    auditor = _load_auditor()
    text = "可以看出该方案有效。模型具有良好的推广价值。"
    categories = {item["category"] for item in auditor.audit_text(text)["warnings"]}
    assert "result_evidence_chain" in categories
    assert "evaluation_specificity" in categories


def test_abstract_coverage_uses_analyze_ids_and_result_names():
    auditor = _load_auditor()
    expectations = {
        "subproblems": [
            {"id": "Q1", "result_names": ["q1_cost"], "method_terms": ["线性规划"]},
            {"id": "Q2", "result_names": ["q2_route"], "method_terms": ["最短路"]},
        ]
    }
    abstract = "Q1采用线性规划，结果 q1_cost 已给出；Q2采用最短路，结果 q2_route 已给出。"
    report = auditor.coverage_report(abstract, expectations)
    assert report["complete"] is True
    assert all(item["method_present"] for item in report["items"])


def test_abstract_coverage_accepts_task_alias_and_display_value_with_unit():
    auditor = _load_auditor()
    expectations = {
        "subproblems": [
            {
                "id": "q1",
                "title": "司机决策模型",
                "aliases": ["排队等待与空载返回"],
                "method_terms": ["随机决策模型"],
                "results": [
                    {
                        "name": "q1_base_queue_profit",
                        "aliases": ["排队等待预期收益"],
                        "display_values": ["2.18"],
                        "unit": "元",
                    }
                ],
            }
        ]
    }
    text = "针对排队等待与空载返回，采用随机决策模型，排队等待预期收益为2.18元。"
    report = auditor.coverage_report(text, expectations)
    item = report["items"][0]
    assert report["complete"] is True
    assert item["task_present"] is True
    assert item["result_present"] is True
    assert {evidence["kind"] for evidence in item["evidence"]} >= {
        "task_alias",
        "method_term",
        "result_value",
    }


def test_abstract_coverage_rejects_wrong_unit_and_machine_id():
    auditor = _load_auditor()
    expectations = {
        "subproblems": [
            {
                "id": "q1",
                "title": "司机决策模型",
                "aliases": ["排队等待与空载返回"],
                "results": [
                    {
                        "name": "q1_profit",
                        "aliases": ["q1收益值"],
                        "display_values": ["2.18"],
                        "unit": "元",
                    }
                ],
            }
        ]
    }
    wrong_unit = "排队等待与空载返回的排队等待预期收益为2.18分钟。"
    assert auditor.coverage_report(wrong_unit, expectations)["complete"] is False

    machine_only = r"见 \cite{q1}，代码 `q1` 和公式 $q1$ 均未写出司机决策。"
    item = auditor.coverage_report(machine_only, expectations)["items"][0]
    assert item["task_present"] is False


def test_sequence_and_evidence_checks_respect_section_boundaries():
    auditor = _load_auditor()
    text = r"""\section{摘要}
首先介绍研究对象并建立模型，最后报告结果。

\section{结果分析}
首先比较两个方案并解释机制，最后限定适用边界。
"""
    categories = {item["category"] for item in auditor.audit_text(text)["warnings"]}
    assert "sequence_template" not in categories

    cross_section = r"""\section{结果一}
图1显示方案A优于方案B。

\section{结果二}
这表明模型有效。
"""
    categories = {
        item["category"]
        for item in auditor.audit_text(cross_section)["warnings"]
    }
    assert "result_evidence_chain" in categories


def test_cli_accepts_analyze_expectations_json(tmp_path, capsys):
    auditor = _load_auditor()
    abstract = tmp_path / "abstract.tex"
    expectations = tmp_path / "expectations.json"
    abstract.write_text("Q1采用线性规划，结果 q1_cost 已给出。", encoding="utf-8")
    expectations.write_text(
        '{"subproblems":[{"id":"Q1","result_names":["q1_cost"],'
        '"method_terms":["线性规划"]}]}',
        encoding="utf-8",
    )

    assert auditor.main(
        ["audit", str(abstract), "--expectations", str(expectations), "--json"]
    ) == 0
    assert '"complete": true' in capsys.readouterr().out


def test_deterministic_eval_tool_writes_gate_report(tmp_path):
    tool_path = ROOT / "tools" / "evaluate_paper_human_writing.py"
    spec = importlib.util.spec_from_file_location("evaluate_human_writing", tool_path)
    assert spec and spec.loader
    tool = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = tool
    spec.loader.exec_module(tool)

    source = tmp_path / "source"
    baseline = tmp_path / "baseline"
    candidate = tmp_path / "candidate"
    for directory in (source, baseline, candidate):
        directory.mkdir()
    (source / "document.tex").write_text("\u6458\u8981\u7ed3\u679c\u4e3a $120.4$ \u5143\u3002", encoding="utf-8")
    (baseline / "document.tex").write_text("\u6458\u8981\u7ed3\u679c\u4e3a $120.4$ \u5143\u3002", encoding="utf-8")
    (candidate / "document.tex").write_text("\u65b9\u6848\u6210\u672c\u4e3a $120.4$ \u5143\u3002", encoding="utf-8")
    output = tmp_path / "evaluation"

    report = tool.evaluate(source, baseline, candidate, output, None)

    assert report["status"] == "ready_for_blind_review"
    assert (output / "deterministic.json").is_file()
    assert (output / "source_hashes.json").is_file()


def test_writer_and_reviewer_prompts_use_natural_academic_contract():
    writer = (ROOT / "mmw" / "prompts" / "system" / "writer.j2").read_text(
        encoding="utf-8"
    )
    reviewer = (
        ROOT / "mmw" / "prompts" / "system" / "reviewer.j2"
    ).read_text(encoding="utf-8")

    assert "不把全文套进“首先—其次—最后”" in writer
    assert "不强制固定行数" in writer
    assert "任务—证据—判断—边界" in writer
    assert "证据—观察—机制—边界" in writer
    assert "预声明别名" in writer
    assert "同义改写式注水" in reviewer
    assert "冒号、破折号、必要对比" in reviewer
    assert "题目到 formulation" in reviewer
    assert "评价具体性" in reviewer
    assert "不跨章节累计" in reviewer
