"""paper 阶段图片引用门禁：LaTeX 中引用的图片必须真实存在。"""

from pathlib import Path

from mmw.pipeline.stage_paper import _find_missing_graphics


def test_find_missing_graphics_accepts_figures_list_with_path():
    artifacts = {
        "sections/model_solution.tex": r"\includegraphics[width=0.8\textwidth]{figures/fig_q4.png}"
    }

    assert _find_missing_graphics(artifacts, ["fig_q4.png"], Path("not_a_workspace")) == []


def test_find_missing_graphics_accepts_figures_list_without_extension():
    artifacts = {
        "sections/model_solution.tex": r"\includegraphics{fig_q3_transect_layout}"
    }

    assert _find_missing_graphics(
        artifacts,
        ["figures/fig_q3_transect_layout.png"],
        Path("not_a_workspace"),
    ) == []


def test_find_missing_graphics_reports_unknown_reference():
    artifacts = {
        "sections/model_solution.tex": r"\includegraphics{figures/missing_plot.png}",
        "abstract_score.json": r"\includegraphics{not_tex.png}",
    }

    missing = _find_missing_graphics(artifacts, [], Path("not_a_workspace"))

    assert missing == ["sections/model_solution.tex: figures/missing_plot.png"]
