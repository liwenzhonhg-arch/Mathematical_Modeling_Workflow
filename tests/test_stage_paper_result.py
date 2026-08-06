"""paper 阶段失败必须向 CLI 返回失败信号。"""

import json

from mmw.latex.compiler import assemble_main_tex, find_unsafe_tex, prepare_compile_dir
from mmw.models import MetaData, StageID
from mmw.pipeline.stage_paper import _add_code_appendix, _review_revision, run_paper
from mmw.pipeline.stage_review import _review_manifest
from mmw.utils.checkpoint import CheckpointManager


class EmptyManager:
    def load_artifacts(self, stage):
        return {}


def _complete_paper(**overrides):
    artifacts = {
        "sections/abstract.tex": "摘要",
        "sections/problem_restatement.tex": "问题重述",
        "sections/assumptions.tex": "假设",
        "sections/symbols.tex": "符号",
        "sections/model_solution.tex": "模型正文",
        "sections/sensitivity.tex": "灵敏度",
        "sections/evaluation.tex": "评价正文",
        "abstract_score.json": '{"score": 85}',
    }
    artifacts.update(overrides)
    return artifacts


def test_run_paper_returns_false_without_upstream(tmp_path):
    assert run_paper(tmp_path, EmptyManager()) is False


def test_code_appendix_is_assembled_and_copied(tmp_path):
    paper = tmp_path / "paper"
    (paper / "sections").mkdir(parents=True)
    artifacts = {}
    _add_code_appendix(artifacts, "print('ok')")
    for name, content in artifacts.items():
        path = paper / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    main = assemble_main_tex(paper)
    build = prepare_compile_dir(tmp_path, paper)

    assert "\\clearpage" in main
    assert "\\lstinputlisting" in main
    assert "\\usepackage{multirow}" in main
    assert "\\usepackage{longtable}" in main
    assert "\\usepackage{tabularx}" in main
    assert "\\hypersetup{hidelinks}" in main
    assert (build / "solution.py").read_text(encoding="utf-8") == "print('ok')"


def test_assemble_normalizes_only_tagged_display_math(tmp_path):
    paper = tmp_path / "paper"
    sections = paper / "sections"
    sections.mkdir(parents=True)
    (sections / "model_solution.tex").write_text(
        "$$x=1\\tag{1}$$\n$$y=2$$",
        encoding="utf-8",
    )

    main = assemble_main_tex(paper)

    assert "\\begin{equation}\nx=1\\tag{1}\n\\end{equation}" in main
    assert "$$y=2$$" in main


def test_review_manifest_uses_real_export_paths():
    manifest = _review_manifest(
        {"sections/abstract.tex": "摘要", "solution.py": "print('ok')"},
        {
            "results.json": "[]",
            "sensitivity.json": "{}",
            "figures_list.json": '["fig_q1.png"]',
            "data_tables.json": '{"q1_capacity_table.csv":"hash"}',
        },
    )

    assert "code/solution.py (export path)" in manifest
    assert "output/data/results.json" in manifest
    assert "output/data/sensitivity.json" in manifest
    assert "output/figures/fig_q1.png" in manifest
    assert "output/data/q1_capacity_table.csv" in manifest


def test_long_code_is_packaged_but_not_inlined_into_paper():
    artifacts = {}
    solution = "\n".join(f"print({index})" for index in range(201))

    _add_code_appendix(artifacts, solution)

    assert artifacts["solution.py"] == solution
    assert "lstinputlisting" not in artifacts["sections/appendix.tex"]
    assert "code/solution.py" in artifacts["sections/appendix.tex"]


def test_review_revision_targets_only_audited_section(tmp_path):
    mgr = CheckpointManager(tmp_path)
    mgr.save(StageID.PAPER, {
        "sections/abstract.tex": "摘要",
        "sections/sensitivity.tex": "含无出处数值270",
    }, MetaData(stage=StageID.PAPER.value, version=0))
    mgr.save(StageID.REVIEW, {
        "numeric_audit.md": "## [严重]\n- `270` 出自 sections/sensitivity.tex：无出处",
    }, MetaData(stage=StageID.REVIEW.value, version=0))

    sections, _ = _review_revision(mgr)

    assert sections == {"sections/sensitivity.tex": "含无出处数值270"}


def test_paper_citation_gate_revision_includes_bibliography(tmp_path):
    mgr = CheckpointManager(tmp_path)
    mgr.save(StageID.SOLVE, {
        "run_log.txt": "STDOUT:\nok",
        "results.json": '[{"name":"q1_value","value":1,"unit":"","desc":"结果"}]',
        "sensitivity.json": (
            '{"baseline":{"objective":1},"experiments":['
            '{"param":"a","delta_pct":-10,"objective":0.9,"change_pct":-10},'
            '{"param":"b","delta_pct":10,"objective":1.1,"change_pct":10}]}'
        ),
    }, MetaData(stage=StageID.SOLVE.value, version=0))
    mgr.approve(StageID.SOLVE)
    mgr.save(StageID.PAPER, _complete_paper(**{
        "references.bib": "@book{real_key, title={Book}}",
    }), MetaData(stage=StageID.PAPER.value, version=0))

    sections, feedback = _review_revision(mgr)

    assert "cite" in feedback
    assert sections["references.bib"].startswith("@book{real_key")
    assert "sections/model_solution.tex" in sections


def test_paper_figure_gate_revision_targets_model_solution(tmp_path):
    mgr = CheckpointManager(tmp_path)
    mgr.save(StageID.SOLVE, {
        "figures_list.json": '["fig_q3.png"]',
    }, MetaData(stage=StageID.SOLVE.value, version=0))
    mgr.approve(StageID.SOLVE)
    mgr.save(StageID.PAPER, _complete_paper(**{
        "sections/model_solution.tex": "正文没有图",
    }), MetaData(stage=StageID.PAPER.value, version=0))

    sections, feedback = _review_revision(mgr)

    assert sections == {"sections/model_solution.tex": "正文没有图"}
    assert "fig_q3.png" in feedback


def test_paper_method_gate_revision_combines_named_sections(tmp_path, monkeypatch):
    mgr = CheckpointManager(tmp_path)
    mgr.save(StageID.PAPER, _complete_paper(), MetaData(
        stage=StageID.PAPER.value, version=0,
    ))
    monkeypatch.setattr(
        "mmw.pipeline.state_machine.PipelineStateMachine.quality_error",
        lambda *args: (
            "paper 方法表述失败: 摘要未如实说明 heuristic 实现；"
            "符号说明缺少 formulation 使用的大写符号: K"
        ),
    )

    sections, feedback = _review_revision(mgr)

    assert set(sections) == {
        "sections/abstract.tex",
        "sections/symbols.tex",
    }
    assert "heuristic" in feedback
    assert "K" in feedback


def test_paper_gate_revision_includes_gui_rework_reason(tmp_path):
    mgr = CheckpointManager(tmp_path)
    mgr.save(
        StageID.PAPER,
        _complete_paper(**{
            "sections/abstract.tex": "摘" * 601,
            "abstract_score.json": '{"score": 90, "needs_upstream_data": false}',
        }),
        MetaData(stage=StageID.PAPER.value, version=0),
    )
    (tmp_path / "decisions.jsonl").write_text(
        json.dumps({
            "stage": "paper",
            "version": 1,
            "action": "rework",
            "reason": "核心数值保留两位小数",
        }, ensure_ascii=False),
        encoding="utf-8",
    )

    sections, feedback = _review_revision(mgr)

    assert sections == {"sections/abstract.tex": "摘" * 601}
    assert "摘要正文 601 字" in feedback
    assert "核心数值保留两位小数" in feedback


def test_gui_rework_reason_can_target_one_paper_section(tmp_path):
    mgr = CheckpointManager(tmp_path)
    mgr.save(
        StageID.PAPER,
        {
            "sections/abstract.tex": "摘要",
            "sections/model_solution.tex": "模型正文",
            "abstract_score.json": '{"score": 90, "needs_upstream_data": false}',
        },
        MetaData(stage=StageID.PAPER.value, version=0),
    )
    (tmp_path / "decisions.jsonl").write_text(
        json.dumps({
            "stage": "paper",
            "version": 1,
            "action": "rework",
            "reason": "只修订 sections/model_solution.tex",
        }, ensure_ascii=False),
        encoding="utf-8",
    )

    sections, feedback = _review_revision(mgr)

    assert sections == {"sections/model_solution.tex": "模型正文"}
    assert "sections/model_solution.tex" in feedback


def test_review_revision_is_not_reused_after_solve_changes(tmp_path):
    mgr = CheckpointManager(tmp_path)
    mgr.save(StageID.SOLVE, {"results.json": "[]"}, MetaData(stage="solve", version=0))
    mgr.approve(StageID.SOLVE)
    mgr.save(StageID.PAPER, {
        "sections/model_solution.tex": "旧求解结果 123.45",
        "abstract_score.json": '{"score": 85}',
    }, MetaData(stage="paper", version=0))
    mgr.save(StageID.REVIEW, {
        "numeric_audit.md": "## [严重]\n- `123.45` 出自 sections/model_solution.tex：无出处",
    }, MetaData(stage="review", version=0))
    mgr.save(StageID.SOLVE, {"results.json": "[]"}, MetaData(stage="solve", version=0))
    mgr.approve(StageID.SOLVE)

    sections, feedback = _review_revision(mgr)

    assert sections == {}
    assert feedback == ""


def test_paper_review_failure_revises_paper_not_upstream(tmp_path):
    mgr = CheckpointManager(tmp_path)
    mgr.save(StageID.PAPER, {
        "sections/abstract.tex": r"旧摘要\cite{key}",
        "references.bib": "@book{key,title={Book}}",
        "abstract_score.json": '{"score": 85}',
    }, MetaData(stage="paper", version=0))
    mgr.save(StageID.REVIEW, {
        "review.md": "参考文献格式需修订",
        "checklist.json": (
            '{"rework_stage":"paper","items":['
            '{"check":"参考文献格式","status":"fail"}]}'
        ),
    }, MetaData(stage="review", version=0))

    sections, feedback = _review_revision(mgr)

    assert sections["sections/abstract.tex"] == r"旧摘要\cite{key}"
    assert sections["references.bib"].startswith("@book")
    assert "参考文献" in feedback


def test_unsafe_tex_file_reads_are_rejected(tmp_path):
    paper = tmp_path / "paper"
    paper.mkdir()
    (paper / "bad.tex").write_text(r"\lstinputlisting{../../../../.env}", encoding="utf-8")
    assert find_unsafe_tex(paper) == ["bad.tex"]
