"""research 证据清单必须区分已有资料与待搜索项。"""

import json
from importlib.resources import files
from pathlib import Path

from mmw.pipeline.stage_research import (
    _build_evidence,
    _load_knowledge,
    _normalize_method_candidates,
    _search_queries,
)
from mmw.utils.research_sources import search_literature


def test_build_evidence_marks_external_search_as_unperformed():
    evidence = json.loads(_build_evidence(
        ["paper.pdf（当前仅记录文件名，未解析二进制内容）", "notes.md\n正文内容不应写入证据清单"],
        "可用方法域：优化",
        "[需要搜索: 空气层热导率]\n[需要搜索: PDE 示例]",
    ))

    assert evidence == {
        "schema_version": 1,
        "local_references": ["paper.pdf（当前仅记录文件名，未解析二进制内容）", "notes.md"],
        "hmml_index_loaded": True,
        "external_search_performed": False,
        "external_queries": [],
        "external_sources": [],
        "external_errors": [],
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


def _candidate(candidate_id: str, kind: str = "enhanced", budget: int = 30) -> dict:
    return {
        "id": candidate_id,
        "name": "候选方法",
        "kind": kind,
        "required_data": [],
        "assumptions": [],
        "failure_conditions": ["硬约束失败"],
        "pilot": {
            "metric": "有限输出",
            "pass_rule": "全部有限",
            "budget_seconds": budget,
        },
    }


def test_method_candidates_are_bounded_and_require_one_baseline():
    normalized = _normalize_method_candidates(json.dumps({
        "schema_version": 1,
        "subproblems": [{
            "id": "q1",
            "candidates": [
                _candidate("q1_base", "baseline"),
                _candidate("q1_better"),
            ],
        }],
    }, ensure_ascii=False), ["q1"])

    assert len(normalized["subproblems"][0]["candidates"]) == 2


def test_method_candidates_reject_unbounded_or_missing_baseline():
    import pytest

    with pytest.raises(ValueError, match="1～3"):
        _normalize_method_candidates(json.dumps({
            "schema_version": 1,
            "subproblems": [{
                "id": "q1",
                "candidates": [_candidate(f"q1_{index}", "baseline" if index == 0 else "enhanced") for index in range(4)],
            }],
        }), ["q1"])
    with pytest.raises(ValueError, match="baseline"):
        _normalize_method_candidates(json.dumps({
            "schema_version": 1,
            "subproblems": [{"id": "q1", "candidates": [_candidate("q1_only")]}],
        }), ["q1"])


def test_search_queries_are_deduplicated_and_bounded():
    approach = "\n".join(f"[需要搜索: query {index % 5}]" for index in range(8))

    assert _search_queries(approach) == ["query 0", "query 1", "query 2", "query 3"]


def test_literature_search_uses_fixed_sources_and_deduplicates_doi():
    urls = []

    def fake_fetch(url: str, timeout: float) -> dict:
        urls.append(url)
        if "openalex" in url:
            return {"results": [{
                "id": "https://openalex.org/W1",
                "doi": "https://doi.org/10.1/example",
                "display_name": "A useful model",
                "publication_year": 2024,
                "authorships": [],
                "abstract_inverted_index": {"Useful": [0], "abstract": [1]},
            }]}
        return {"message": {"items": [{
            "DOI": "10.1/example",
            "title": ["A useful model"],
            "author": [],
            "URL": "https://doi.org/10.1/example",
        }]}}

    result = search_literature(["heat model"], fetch_json=fake_fetch)

    assert len(urls) == 2
    assert all(url.startswith(("https://api.openalex.org/", "https://api.crossref.org/")) for url in urls)
    assert result["requests_succeeded"] == 2
    assert len(result["sources"]) == 1
    assert result["sources"][0]["evidence_level"] == "abstract"
