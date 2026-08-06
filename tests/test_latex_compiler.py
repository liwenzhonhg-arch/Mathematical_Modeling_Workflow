from mmw.latex.compiler import _layout_warnings


def test_layout_warnings_reject_large_float_and_material_overflow():
    log = "\n".join([
        "Overfull \\hbox (0.4pt too wide) in paragraph at lines 1--2",
        "Overfull \\hbox (12.5pt too wide) in paragraph at lines 3--4",
        "LaTeX Warning: Float too large for page by 29.62508pt on input line 99.",
    ])

    warnings = _layout_warnings(log)

    assert len(warnings) == 2
    assert any("12.5pt" in item for item in warnings)
    assert any("Float too large" in item for item in warnings)
