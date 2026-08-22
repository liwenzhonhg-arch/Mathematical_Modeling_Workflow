import json

from mmw.utils.domain_contracts import validate_optional_domain_contracts
from mmw.utils.method_contract import validate_model_contract


def test_optional_domain_contracts_are_disabled_by_default():
    assert validate_optional_domain_contracts(None) == []
    assert validate_optional_domain_contracts({}) == []


def test_prediction_contract_requires_rolling_origin_and_wape_variants():
    issues = validate_optional_domain_contracts({
        "prediction": {
            "validation": {"strategy": "random_split"},
            "metrics": ["micro_wape"],
            "provenance": [],
        }
    })
    assert any("rolling_origin" in issue for issue in issues)
    assert any("macro_wape" in issue for issue in issues)


def test_scheduling_and_energy_contracts_require_closure():
    issues = validate_optional_domain_contracts({
        "scheduling": {
            "candidate_key_fields": ["route", "schedule"],
            "source_refs": ["q1"],
            "closure": {"all_required_tasks_covered": False, "feasible": True},
        },
        "energy": {
            "balance_tolerance": 1e-6,
            "flows": ["in", "out"],
            "recomputed_outputs": ["carbon"],
            "closure_passed": False,
        },
    })
    assert any("all_required_tasks_covered" in issue for issue in issues)
    assert any("closure_passed" in issue for issue in issues)


def test_method_contract_runs_optional_domain_gate_only_when_present():
    contract = {
        "schema_version": 1,
        "problem_scope": [],
        "formulation": {"objectives": [], "constraints": []},
        "implementation": {"class": "simulation", "algorithm": "demo"},
        "domain_contracts": {
            "prediction": {
                "validation": {"strategy": "rolling_origin"},
                "metrics": ["macro_wape", "micro_wape", "system_aggregate_wape"],
                "provenance": ["data.csv"],
            }
        },
    }
    assert validate_model_contract(json.dumps(contract, ensure_ascii=False)) == []
