import importlib.util
import json
from pathlib import Path


CASE_DIR = Path(__file__).parents[1] / "test_cases" / "2020A_炉温曲线"


def test_2020a_reference_solver_stays_within_cross_checked_ranges():
    spec = importlib.util.spec_from_file_location(
        "reference_2020a",
        CASE_DIR / "reference_solver.py",
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    results = module.solve_reference()
    expected = json.loads(
        (CASE_DIR / "reference_expected.json").read_text(encoding="utf-8")
    )

    for item in expected["results"]:
        assert item["min"] <= results[item["name"]] <= item["max"]
