"""research 证据清单必须区分已有资料与待搜索项。"""

import json
from importlib.resources import files
from pathlib import Path

from mmw.pipeline.stage_research import _build_evidence, _load_knowledge


def test_build_evidence_marks_external_search_as_unperformed():
    evidence = json.loads(_build_evidence(
        ["paper.pdf（当前仅记录文件名，未解析二进制内容）", "notes.md\n正文内容不应写入证据清单"],
        "可用方法域：优化",
        "[需要搜索: 空气层热导率]\n[需要搜索: PDE 示例]",
    ))

    assert evidence == {
        "local_references": ["paper.pdf（当前仅记录文件名，未解析二进制内容）", "notes.md"],
        "hmml_index_loaded": True,
        "external_search_performed": False,
        "unresolved_searches": ["空气层热导率", "PDE 示例"],
    }


def test_packaged_knowledge_does_not_depend_on_current_directory(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    context = _load_knowledge(Path(str(files("knowledge"))), "优化")

    assert context


def test_furnace_query_loads_generic_moving_heat_structure():
    context = _load_knowledge(
        Path(str(files("knowledge"))),
        "移动物体经过分区炉温场，需要建立热传导和传热系数模型",
    )

    assert "一维瞬态导热模型" in context
    assert "Robin" in context
    assert "结构选择门" in context
    assert all(
        forbidden not in context
        for forbidden in ("reference_solver", "reference_expected", "2020A", "HK =")
    )
