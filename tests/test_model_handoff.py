"""建模假设、逻辑链和人工交接件回归测试。"""

from __future__ import annotations

import json

import pytest

import mmw.pipeline.stage_model as stage_model
from mmw.pipeline.stage_code import preferred_model_input
from mmw.utils.method_contract import build_model_contract
from mmw.utils.model_handoff import (
    build_model_handoff,
    model_structure_issues,
    normalize_assumption_artifacts,
    validate_assumptions_contract,
)


def _assumptions(count: int = 2) -> dict:
    return {
        "schema_version": 1,
        "assumptions": [
            {
                "id": f"ASM-{index}",
                "statement": f"假设 {index}",
                "basis": "题面未给出该动态过程，采用最小闭合简化",
                "scope": ["q1"],
                "model_effect": "决定状态转移形式",
                "relaxation": "放宽后需要随机或动态模型",
            }
            for index in range(1, count + 1)
        ],
        "classification_notes": [
            {
                "item": "任务必须在截止时间前完成",
                "kind": "hard_constraint",
                "destination": "analysis.md#题面硬约束",
            }
        ],
    }


def _equations_v2() -> dict:
    return {
        "schema_version": 2,
        "sub_problems": {
            "q1": {
                "title": "需求预测",
                "requirement": "预测未来需求并报告误差",
                "inputs": [
                    {"id": "DAT-Q1-1", "meaning": "历史需求", "source": "附件"}
                ],
                "outputs": [
                    {"id": "OUT-Q1-1", "meaning": "未来需求预测表"}
                ],
                "logic_chain": [
                    {
                        "id": "LOG-Q1-1",
                        "from": "历史需求",
                        "action": "提取时间依赖并滚动预测",
                        "to": "未来需求",
                        "reason": "预测时刻只能使用过去信息",
                    }
                ],
                "variables": [
                    {"symbol": "D_t", "meaning": "时刻 t 的需求", "unit": "GPU"}
                ],
                "formulas": [
                    {
                        "id": "EQ-Q1-1",
                        "meaning": "线性需求预测",
                        "expression": "D_t = beta^T x_t",
                    }
                ],
                "objective": {
                    "id": "OBJ-Q1",
                    "meaning": "最小化滚动验证误差",
                    "expression": "min RMSE",
                },
                "constraints": [
                    {
                        "id": "CON-Q1-1",
                        "meaning": "预测不得读取未来真值",
                        "expression": "train_time < forecast_time",
                        "hard": True,
                        "source_type": "hard_constraint",
                        "source_ref": "题目时间顺序",
                    }
                ],
                "assumption_refs": ["ASM-1"],
                "method": {
                    "name": "rolling-origin regression",
                    "rationale": "避免单窗口偶然性",
                    "termination": "完成预声明窗口和候选",
                },
                "validation": [
                    {"id": "VAL-Q1-1", "meaning": "滚动窗口 RMSE"},
                    {"id": "VAL-Q1-2", "meaning": "最终测试集一次评估"},
                ],
                "observability": "需求标签可观测",
            }
        },
    }


def test_assumption_contract_rejects_missing_relaxation_and_too_many_items():
    missing = _assumptions(1)
    del missing["assumptions"][0]["relaxation"]
    assert any("relaxation" in issue for issue in validate_assumptions_contract(
        json.dumps(missing, ensure_ascii=False)
    ))

    excessive = _assumptions(13)
    excessive["overflow_reason"] = "题目复杂"
    assert any("12" in issue for issue in validate_assumptions_contract(
        json.dumps(excessive, ensure_ascii=False)
    ))


def test_assumption_markdown_is_deterministic_and_excludes_classification_notes():
    artifacts = normalize_assumption_artifacts({
        "analysis.md": "# 分析",
        "assumptions.json": json.dumps(_assumptions(), ensure_ascii=False),
        "assumptions.md": "这段自由文本必须被覆盖",
    })

    assert artifacts["assumptions.md"].startswith("# 模型假设\n")
    assert "ASM-1" in artifacts["assumptions.md"]
    assert "放宽后" in artifacts["assumptions.md"]
    assert "任务必须在截止时间前完成" not in artifacts["assumptions.md"]


def test_assumption_normalization_rejects_missing_json():
    with pytest.raises(ValueError, match="assumptions.json"):
        normalize_assumption_artifacts({"assumptions.md": "# 模型假设"})


def test_schema_v2_builds_readable_handoff_and_validates_assumption_refs():
    equations = json.dumps(_equations_v2(), ensure_ascii=False)
    assumptions = json.dumps(_assumptions(), ensure_ascii=False)

    handoff = build_model_handoff(equations, json.dumps({
        "parameters": [{
            "id": "PAR-Q1-1",
            "name": "回归系数",
            "value": None,
            "unit": "无量纲",
            "source_ref": "附件待标定",
        }]
    }, ensure_ascii=False), assumptions)

    assert "# 模型交接摘要" in handoff
    assert "## q1：需求预测" in handoff
    assert "### 建模逻辑链" in handoff
    assert "历史需求 → 提取时间依赖并滚动预测 → 未来需求" in handoff
    assert "EQ-Q1-1" in handoff
    assert "D_t = beta^T x_t" in handoff
    assert "ASM-1" in handoff
    assert "PAR-Q1-1" in handoff
    assert "待代码标定" in handoff
    assert model_structure_issues("# 数学模型\n## 子问题 1：需求预测", equations, assumptions) == []


def test_schema_v2_rejects_missing_logic_and_unknown_assumption_reference():
    equations = _equations_v2()
    equations["sub_problems"]["q1"]["logic_chain"] = []
    equations["sub_problems"]["q1"]["assumption_refs"] = ["ASM-404"]

    issues = model_structure_issues(
        "# 数学模型\n## 子问题 1：需求预测",
        json.dumps(equations, ensure_ascii=False),
        json.dumps(_assumptions(), ensure_ascii=False),
    )

    assert any("logic_chain" in issue for issue in issues)
    assert any("ASM-404" in issue for issue in issues)


def test_legacy_equations_get_explicit_degraded_handoff():
    handoff = build_model_handoff(json.dumps({
        "sub_problems": {
            "q1": {
                "objective": "最小化成本",
                "constraints": ["容量约束"],
                "variables": ["x"],
                "method": "枚举",
            }
        }
    }, ensure_ascii=False))

    assert "兼容模式" in handoff
    assert "未提供结构化逻辑链" in handoff
    assert "最小化成本" in handoff


def test_revision_structure_rejects_version_appendices_and_duplicate_questions():
    model = (
        "# 数学模型\n"
        "## 子问题 1：预测\n正文\n"
        "## 子问题 1：预测\n重复正文\n"
        "## v48 修复合同\n追加内容\n"
    )

    issues = model_structure_issues(model, json.dumps(_equations_v2(), ensure_ascii=False))

    assert any("重复" in issue for issue in issues)
    assert any("历史版本" in issue for issue in issues)


def test_method_contract_accepts_structured_objective_constraint_and_method():
    contract = build_model_contract(json.dumps(_equations_v2(), ensure_ascii=False))

    assert contract["formulation"]["objectives"] == [{
        "id": "OBJ-Q1",
        "meaning": "最小化滚动验证误差",
        "unit": "",
    }]
    assert contract["formulation"]["constraints"][0]["id"] == "CON-Q1-1"
    assert contract["formulation"]["constraints"][0]["source_type"] == "hard_constraint"
    assert contract["formulation"]["model_family"] == "rolling-origin regression"


def test_model_stage_prepares_handoff_and_quality_report():
    assumptions = json.dumps(_assumptions(), ensure_ascii=False)
    prepared, blocking = stage_model._prepare_model_artifacts(
        {
            "model.md": "# 数学模型\n## 子问题 1：需求预测\n当前定义",
            "equations.json": json.dumps(_equations_v2(), ensure_ascii=False),
            "params.json": '{"parameters": []}',
        },
        assumptions,
        enforce_structure=True,
    )

    assert blocking == []
    assert "建模逻辑链" in prepared["model_handoff.md"]
    assert json.loads(prepared["model_quality_report.json"])["status"] == "pass"


def test_model_stage_blocks_incomplete_new_contract():
    equations = _equations_v2()
    equations["sub_problems"]["q1"]["outputs"] = []

    prepared, blocking = stage_model._prepare_model_artifacts(
        {
            "model.md": "# 数学模型\n## 子问题 1：需求预测",
            "equations.json": json.dumps(equations, ensure_ascii=False),
        },
        json.dumps(_assumptions(), ensure_ascii=False),
        enforce_structure=True,
    )

    assert any("outputs" in issue for issue in blocking)
    assert json.loads(prepared["model_quality_report.json"])["status"] == "fail"


def test_model_stage_requires_schema_v2_for_new_analyze_contract():
    _, blocking = stage_model._prepare_model_artifacts(
        {
            "model.md": "# 数学模型\n## 子问题 1：预测",
            "equations.json": '{"sub_problems": {"q1": {"method": "regression"}}}',
        },
        json.dumps(_assumptions(), ensure_ascii=False),
        enforce_structure=True,
    )

    assert any("schema_version=2" in issue for issue in blocking)


def test_coder_prefers_handoff_and_legacy_falls_back_to_full_model():
    assert preferred_model_input({
        "model.md": "完整模型",
        "model_handoff.md": "交接摘要",
    }) == "交接摘要"
    assert preferred_model_input({"model.md": "完整模型"}) == "完整模型"
