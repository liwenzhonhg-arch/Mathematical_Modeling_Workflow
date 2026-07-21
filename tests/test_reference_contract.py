import json

import pytest

from mmw.utils.reference_contract import (
    load_reference_contract,
    reference_result_failures,
    validate_reference_results,
)


CONTRACT = {
    "schema_version": 1,
    "results": [{"name": "q2_最大允许速度", "min": 76.0, "max": 80.0}],
}


def test_reference_contract_accepts_expected_result(tmp_path):
    (tmp_path / "reference_expected.json").write_text(
        json.dumps(CONTRACT, ensure_ascii=False),
        encoding="utf-8",
    )

    loaded = load_reference_contract(tmp_path)

    assert loaded == CONTRACT
    assert validate_reference_results(
        loaded,
        [{"name": "q2_最大允许速度", "value": 77.06}],
    ) == ""


def test_reference_contract_rejects_missing_or_out_of_range_result():
    assert "缺少" in validate_reference_results(CONTRACT, [])
    assert "越界" in validate_reference_results(
        CONTRACT,
        [{"name": "q2_最大允许速度", "value": 99.29}],
    )
    assert reference_result_failures(CONTRACT, [{
        "name": "q2_最大允许速度", "value": 99.29,
    }]) == [{
        "name": "q2_最大允许速度", "actual": 99.29, "category": "out_of_range",
    }]


def test_reference_contract_accepts_explicit_alias():
    contract = {
        "schema_version": 1,
        "results": [{
            "name": "q2_最大允许速度",
            "aliases": ["q2_最大速度"],
            "min": 76.0,
            "max": 80.0,
        }],
    }

    assert validate_reference_results(
        contract, [{"name": "q2_最大速度", "value": 77.0}],
    ) == ""


def test_invalid_reference_contract_is_not_silently_ignored(tmp_path):
    (tmp_path / "reference_expected.json").write_text("{broken", encoding="utf-8")

    with pytest.raises(ValueError, match="读取失败"):
        load_reference_contract(tmp_path)
