import json

from mmw.utils.method_contract import (
    build_model_contract,
    build_paper_traceability,
    build_review_consistency,
    build_solve_contract,
    finalize_code_contract,
    validate_code_contract,
    validate_paper_method_language,
    validate_paper_traceability,
    validate_result_contract,
    validate_solve_contract,
)


def _model_contract() -> dict:
    return build_model_contract(json.dumps({
        "sub_problems": {
            "q1": {
                "objective": "最小化总成本",
                "constraints": ["容量不超过上限", "每个客户服务一次"],
                "method": "VRPTW",
            },
        },
    }, ensure_ascii=False))


def _code_contract(solution: str = "print('ok')") -> dict:
    model = _model_contract()
    candidate = {
        "implementation": {
            "algorithm": "完整路线枚举",
            "class": "exact",
            "solver": "python",
            "randomized": False,
            "seed": None,
            "covers": ["OBJ-Q1", "CON-Q1-1", "CON-Q1-2"],
            "deviations": [],
        },
        "claims": {
            "optimality": "global-within-enumerated-feasible-space",
            "approximation": None,
            "limitations": [],
        },
    }
    return finalize_code_contract(
        json.dumps(model, ensure_ascii=False),
        json.dumps(candidate, ensure_ascii=False),
        solution=solution,
        model_version=1,
        code_version=1,
    )


def test_result_contract_rejects_nonzero_fixed_alignment_offset():
    model = {
        "formulation": {
            "constraints": [{
                "id": "CON-Q1-1",
                "meaning": "x(t)=vt/60，delta_t_obs=0",
                "hard": True,
            }],
        },
    }
    result = [{
        "name": "q1_观测时间偏移",
        "value": -20.872426,
        "unit": "s",
        "desc": "联合标定",
    }]

    assert "固定对齐偏移为 0" in validate_result_contract(
        json.dumps(model), result,
    )[0]
    result[0]["value"] = 0
    assert validate_result_contract(json.dumps(model), result) == []
    model["formulation"]["constraints"][0]["meaning"] = "观测时间偏移待标定"
    result[0]["value"] = -20.872426
    assert validate_result_contract(json.dumps(model), result) == []


def _runtime() -> str:
    return json.dumps({
        "schema_version": 1,
        "algorithm_class": "exact",
        "termination_status": "optimal",
        "feasible": True,
        "constraints_checked": ["CON-Q1-1", "CON-Q1-2"],
        "seed": None,
        "objective_value": 1.0,
        "optimality_certificate": {
            "type": "exhaustive_enumeration",
            "search_space_size": 10,
            "evaluated_candidates": 10,
        },
    }, ensure_ascii=False)


def test_model_contract_assigns_stable_ids():
    contract = _model_contract()
    assert contract["problem_scope"] == ["q1"]
    assert [item["id"] for item in contract["formulation"]["objectives"]] == ["OBJ-Q1"]
    assert [item["id"] for item in contract["formulation"]["constraints"]] == [
        "CON-Q1-1", "CON-Q1-2",
    ]


def test_code_may_use_different_exact_algorithm_without_changing_formulation():
    model = _model_contract()
    code = _code_contract()
    assert validate_code_contract(
        json.dumps(model, ensure_ascii=False),
        json.dumps(code, ensure_ascii=False),
        "print('ok')",
    ) == []


def test_code_contract_rejects_undisclosed_top_k_and_stale_hash():
    model = _model_contract()
    solution = "top_k = 10\nprint('ok')"
    code = _code_contract(solution)
    failures = validate_code_contract(
        json.dumps(model, ensure_ascii=False),
        json.dumps(code, ensure_ascii=False),
        solution,
    )
    assert any("top-k" in item for item in failures)
    failures = validate_code_contract(
        json.dumps(model, ensure_ascii=False),
        json.dumps(code, ensure_ascii=False),
        solution + "\nprint('changed')",
    )
    assert any("哈希" in item for item in failures)


def test_code_contract_rejects_exact_heuristic_and_missing_seed():
    model = _model_contract()
    solution = "def greedy_penalty_search():\n    pass\n"
    code = _code_contract(solution)
    code["implementation"]["randomized"] = True
    failures = validate_code_contract(
        json.dumps(model, ensure_ascii=False),
        json.dumps(code, ensure_ascii=False),
        solution,
    )
    assert any("启发式" in item for item in failures)
    assert any("seed" in item for item in failures)


def test_exact_contract_allows_legitimate_penalty_cost_objective():
    model = _model_contract()
    solution = "penalty_cost = early_count * early_fee\nprint(penalty_cost)\n"
    code = _code_contract(solution)

    assert validate_code_contract(
        json.dumps(model, ensure_ascii=False),
        json.dumps(code, ensure_ascii=False),
        solution,
    ) == []


def test_solve_contract_binds_results_and_validation():
    solution = "print('ok')"
    results = '[{"name":"q1_cost","value":1,"unit":"","desc":"x"}]'
    contract, report = build_solve_contract(
        json.dumps(_code_contract(solution), ensure_ascii=False),
        solution=solution,
        results=results,
        runtime=_runtime(),
        solve_version=1,
    )
    assert report["passed"]
    assert validate_solve_contract(
        json.dumps(contract, ensure_ascii=False),
        json.dumps(report, ensure_ascii=False),
        results=results,
        runtime=_runtime(),
    ) == []
    assert validate_solve_contract(
        json.dumps(contract, ensure_ascii=False),
        json.dumps(report, ensure_ascii=False),
        results=results + " ",
        runtime=_runtime(),
    )
    _, stale_report = build_solve_contract(
        json.dumps(_code_contract(solution), ensure_ascii=False),
        solution=solution + "\n# changed",
        results=results,
        runtime=_runtime(),
        solve_version=1,
    )
    assert not stale_report["passed"]


def test_paper_traceability_and_review_bind_same_contract():
    contract, _ = build_solve_contract(
        json.dumps(_code_contract(), ensure_ascii=False),
        solution="print('ok')",
        results="[]",
        runtime=_runtime(),
        solve_version=1,
    )
    raw = json.dumps(contract, ensure_ascii=False)
    tex, trace = build_paper_traceability(
        raw,
        "% MMW-ALGORITHM: 完整路线枚举\n"
        "% MMW-ID: OBJ-Q1\n% MMW-ID: CON-Q1-1\n% MMW-ID: CON-Q1-2\n"
        "\\section{模型求解}\n正文\n",
    )
    assert validate_paper_traceability(
        raw, json.dumps(trace, ensure_ascii=False), tex,
    ) == []
    review = build_review_consistency(
        raw,
        raw,
        json.dumps(trace, ensure_ascii=False),
        tex,
    )
    assert review["passed"]


def test_paper_traceability_rejects_missing_ids_and_global_overclaim():
    contract, _ = build_solve_contract(
        json.dumps(_code_contract(), ensure_ascii=False),
        solution="print('ok')",
        results="[]",
        runtime=_runtime(),
        solve_version=1,
    )
    raw = json.dumps(contract, ensure_ascii=False)
    _, trace = build_paper_traceability(
        raw,
        "% MMW-ALGORITHM: 完整路线枚举\n本文得到无条件全局最优解。\n",
    )
    assert not trace["passed"]
    assert any("ID" in item for item in trace["failures"])
    assert any("全局最优" in item for item in trace["failures"])


def test_paper_traceability_allows_negative_global_certificate_disclosure():
    contract = _code_contract()
    contract["implementation"]["class"] = "heuristic"
    contract["claims"]["optimality"] = "unverified"
    raw = json.dumps(contract, ensure_ascii=False)
    _, trace = build_paper_traceability(
        raw,
        "% MMW-ALGORITHM: 完整路线枚举\n"
        "% MMW-ID: OBJ-Q1\n% MMW-ID: CON-Q1-1\n% MMW-ID: CON-Q1-2\n"
        "该有限候选方法不具有连续决策域全局最优证书，"
        "也未获得全局最优证明，不构成连续决策域全局最优，"
        "没有连续域全局最优证书。\n",
    )

    assert trace["passed"]


def test_paper_traceability_adds_contract_limitations_and_accepts_cannot_prove():
    contract = _code_contract()
    contract["implementation"]["deviations"] = ["网格步长为 1%"]
    contract["claims"]["limitations"] = ["不能证明全局最优"]
    raw = json.dumps(contract, ensure_ascii=False)

    tex, trace = build_paper_traceability(
        raw,
        "% MMW-ALGORITHM: 完整路线枚举\n"
        "% MMW-ID: OBJ-Q1\n% MMW-ID: CON-Q1-1\n% MMW-ID: CON-Q1-2\n"
        "当前算法不能证明全局最优。\n",
    )

    assert trace["passed"]
    assert "% MMW-LIMITATION: D1" in tex
    assert "% MMW-LIMITATION: L1" in tex
    assert r"网格步长为 1\%" in tex


def test_paper_traceability_hash_binds_solve_results():
    contract, _ = build_solve_contract(
        json.dumps(_code_contract(), ensure_ascii=False),
        solution="print('ok')",
        results="[]",
        runtime=_runtime(),
        solve_version=1,
    )
    raw = json.dumps(contract, ensure_ascii=False)
    tex, trace = build_paper_traceability(
        raw,
        "% MMW-ALGORITHM: 完整路线枚举\n"
        "% MMW-ID: OBJ-Q1\n% MMW-ID: CON-Q1-1\n% MMW-ID: CON-Q1-2\n正文\n",
    )
    contract["bindings"]["results_sha256"] = "changed"

    failures = validate_paper_traceability(
        json.dumps(contract, ensure_ascii=False),
        json.dumps(trace, ensure_ascii=False),
        tex,
    )

    assert any("当前契约" in item for item in failures)


def test_global_claim_rejects_incomplete_runtime_certificate():
    solution = "print('ok')"
    runtime = json.loads(_runtime())
    runtime["optimality_certificate"]["evaluated_candidates"] = 9

    _, report = build_solve_contract(
        json.dumps(_code_contract(solution), ensure_ascii=False),
        solution=solution,
        results="[]",
        runtime=json.dumps(runtime, ensure_ascii=False),
        solve_version=1,
    )

    assert not report["passed"]
    assert any("完整搜索空间" in item for item in report["failures"])


def test_optimizer_runtime_requires_success_and_non_boundary_parameters():
    solution = "from scipy.optimize import minimize\nminimize(lambda x: x[0] ** 2, [0.4])"
    runtime = json.loads(_runtime())
    _, missing_report = build_solve_contract(
        json.dumps(_code_contract(solution), ensure_ascii=False),
        solution=solution,
        results="[]",
        runtime=json.dumps(runtime, ensure_ascii=False),
        solve_version=1,
    )
    assert any("缺少 optimizer" in item for item in missing_report["failures"])

    runtime["optimizer"] = {
        "used": True,
        "success": True,
        "status": "converged",
        "parameters": [{
            "name": "alpha", "value": 0.4, "lower": 0.0, "upper": 1.0,
            "boundary_hit": False,
        }],
    }

    _, report = build_solve_contract(
        json.dumps(_code_contract(solution), ensure_ascii=False),
        solution=solution,
        results="[]",
        runtime=json.dumps(runtime, ensure_ascii=False),
        solve_version=1,
    )
    assert report["passed"], report["failures"]

    runtime["optimizer"]["parameters"][0].update(value=0.0, boundary_hit=True)
    _, boundary_report = build_solve_contract(
        json.dumps(_code_contract(solution), ensure_ascii=False),
        solution=solution,
        results="[]",
        runtime=json.dumps(runtime, ensure_ascii=False),
        solve_version=1,
    )
    assert any("触及边界" in item for item in boundary_report["failures"])

    runtime["optimizer"].update(success=False, status="maxfev")
    _, failed_report = build_solve_contract(
        json.dumps(_code_contract(solution), ensure_ascii=False),
        solution=solution,
        results="[]",
        runtime=json.dumps(runtime, ensure_ascii=False),
        solve_version=1,
    )
    assert any("未成功" in item for item in failed_report["failures"])
    assert any("预算耗尽" in item for item in failed_report["failures"])


def test_optimizer_allows_predeclared_non_failure_termination():
    solution = "from scipy.optimize import minimize\nminimize(lambda x: x[0] ** 2, [0.4])"
    contract = _code_contract(solution)
    contract["implementation"].update(
        {"class": "heuristic", "acceptable_termination_statuses": ["local_optimal"]}
    )
    contract["claims"]["optimality"] = "unverified"
    runtime = json.loads(_runtime())
    runtime.update(
        algorithm_class="heuristic",
        termination_status="completed",
        optimizer={
            "used": True,
            "success": False,
            "status": "local_optimal",
            "parameters": [{
                "name": "alpha", "value": 0.4, "lower": 0.0, "upper": 1.0,
                "boundary_hit": False,
            }],
        },
    )

    _, report = build_solve_contract(
        json.dumps(contract, ensure_ascii=False),
        solution=solution,
        results="[]",
        runtime=json.dumps(runtime, ensure_ascii=False),
        solve_version=1,
    )

    assert report["passed"], report["failures"]


def test_optimizer_final_fit_reuses_declared_training_endpoints():
    solution = "print('ok')"
    contract = _code_contract(solution)
    contract["implementation"].update({
        "minimum_successful_starts": 3,
        "reuse_training_starts_for_final_fit": True,
    })
    runtime = json.loads(_runtime())
    runtime["optimizer"] = {
        "used": True,
        "success": True,
        "status": "converged",
        "parameters": [{
            "name": "alpha", "value": 0.4, "lower": 0.0, "upper": 1.0,
            "boundary_hit": False,
        }],
        "training_successful_endpoints": [[0.2], [0.4], [0.6]],
        "final_fit_initial_points": [[0.2], [0.4], [0.6]],
        "coarse_search_repeated_for_final_fit": False,
    }

    _, report = build_solve_contract(
        json.dumps(contract, ensure_ascii=False),
        solution=solution,
        results="[]",
        runtime=json.dumps(runtime, ensure_ascii=False),
        solve_version=1,
    )
    assert report["passed"], report["failures"]

    runtime["optimizer"]["coarse_search_repeated_for_final_fit"] = True
    _, repeated_report = build_solve_contract(
        json.dumps(contract, ensure_ascii=False),
        solution=solution,
        results="[]",
        runtime=json.dumps(runtime, ensure_ascii=False),
        solve_version=1,
    )
    assert any("重复了已完成的粗搜索" in item for item in repeated_report["failures"])


def test_paper_method_language_requires_honest_heuristic_wording_and_symbols():
    contract = _code_contract()
    contract["formulation"]["model_family"] = "混合整数线性规划 (MILP)"
    contract["formulation"]["objectives"][0]["meaning"] = (
        r"\min \sum_{k=1}^{K} c x_k"
    )
    contract["implementation"]["class"] = "heuristic"
    raw = json.dumps(contract, ensure_ascii=False)

    failures = validate_paper_method_language(
        raw,
        "利用求解器获得方案。",
        r"$x_k$ 为决策变量。",
        "建立 MILP 模型并求解。",
    )

    assert any("摘要" in item for item in failures)
    assert any("formulation" in item for item in failures)
    assert any("K" in item for item in failures)
    assert validate_paper_method_language(
        raw,
        "采用完整路线枚举启发式获得方案。",
        r"$K$ 为车辆数上界，$x_k$ 为决策变量。",
        "数学 formulation 为 MILP，但实际 implementation 采用启发式枚举。",
    ) == []


def test_paper_method_language_ignores_equation_label_letters():
    contract = _code_contract()
    contract["formulation"]["constraints"][0]["meaning"] = (
        "几何按(G1)-(G3)，换热率按(K0)-(K1)"
    )

    assert validate_paper_method_language(
        json.dumps(contract, ensure_ascii=False),
        "采用完整路线枚举获得方案。",
        "无额外单字母变量。",
        "按公式编号实现。",
    ) == []
