"""model block 自动修订：通过即停，连续 block 最多两轮。"""

import json
from pathlib import Path

import mmw.pipeline.stage_model as stage_model
from mmw.models import MetaData, StageID
from mmw.utils.checkpoint import CheckpointManager


class DummyLLM:
    model = "dummy"
    total_input_tokens = 10
    total_output_tokens = 5


class DummyModeler:
    def __init__(self):
        self.revisions = 0
        self.context_resets = 0

    def reset_context(self):
        self.context_resets += 1

    def revise_model(self, current_artifacts, verify_status, verify_report, **kwargs):
        self.revisions += 1
        return {"model.md": f"model-v{self.revisions + 1}"}


class RecordingModeler(DummyModeler):
    def revise_model(self, current_artifacts, verify_status, verify_report, **kwargs):
        self.verify_status = verify_status
        self.verify_report = verify_report
        return super().revise_model(
            current_artifacts,
            verify_status,
            verify_report,
            **kwargs,
        )


def _verify_artifacts(severity: str) -> dict[str, str]:
    return {
        "verify_report.md": f"severity={severity}",
        "verify_status.json": json.dumps({
            "severity": severity,
            "issues": [{"category": "公式", "summary": "修正"}],
        }, ensure_ascii=False),
    }


def test_revision_stops_after_warning(tmp_path, monkeypatch):
    mgr = CheckpointManager(tmp_path)
    modeler = DummyModeler()
    sequence = iter(["block", "warning"])
    monkeypatch.setattr(
        stage_model,
        "_verify_model",
        lambda *args: (_verify_artifacts(next(sequence)), DummyLLM()),
    )

    stage_model._run_verified_versions(
        tmp_path, mgr, object(), modeler, DummyLLM(),
        "analysis", "assumptions", {"model.md": "model-v1", "params.json": "{}"},
    )

    assert mgr.get_latest_version(StageID.MODEL) == 2
    assert modeler.revisions == 1
    latest = mgr.load_artifacts(StageID.MODEL, 2)
    assert latest["model.md"] == "model-v2"
    assert latest["params.json"] == "{}"
    assert len(json.loads(latest["revision_history.json"])) == 2


def test_revision_stops_after_two_revisions(tmp_path, monkeypatch):
    mgr = CheckpointManager(tmp_path)
    modeler = DummyModeler()
    monkeypatch.setattr(
        stage_model,
        "_verify_model",
        lambda *args: (_verify_artifacts("block"), DummyLLM()),
    )

    stage_model._run_verified_versions(
        tmp_path, mgr, object(), modeler, DummyLLM(),
        "analysis", "assumptions", {"model.md": "model-v1"},
    )

    assert mgr.get_latest_version(StageID.MODEL) == 3
    assert modeler.revisions == 2
    assert modeler.context_resets == 2
    assert json.loads(
        mgr.load_artifacts(StageID.MODEL, 3)["verify_status.json"]
    )["severity"] == "block"


def test_verifier_does_not_require_solve_outputs_during_model_stage():
    prompt = (
        Path(stage_model.__file__).parents[1]
        / "prompts"
        / "system"
        / "verifier.j2"
    ).read_text(encoding="utf-8")

    assert "路线、数值结果、图表和最优性间隙由后续 code/solve 阶段产生" in prompt
    assert "不得仅因尚无这些结果判定 `block`" in prompt


def test_tank_geometry_and_symmetry_rules_are_explicit():
    prompts = Path(stage_model.__file__).parents[1] / "prompts"
    analyst = (prompts / "system" / "analyst.j2").read_text(encoding="utf-8")
    modeler = (prompts / "system" / "modeler.j2").read_text(encoding="utf-8")
    verifier = (prompts / "system" / "verifier.j2").read_text(encoding="utf-8")

    assert "同一水平链上的相邻段不得遗漏" in analyst
    assert "不得自行扩成新的 q 编号" in analyst
    assert "只拟合倾角绝对值" in modeler
    assert "不得要求全部训练区间端点均为部分充液" in modeler
    assert "不得把 `geometry_unconfirmed` 留给没有视觉输入的 Coder" in modeler
    assert "不得要求物理等价的正负解通过参数跨度门禁" in verifier


def test_modeler_prompts_require_minimal_moving_heat_structure():
    prompts = Path(stage_model.__file__).parents[1] / "prompts"
    system = (prompts / "system" / "modeler.j2").read_text(encoding="utf-8")
    revision = (prompts / "model_revision.j2").read_text(encoding="utf-8")

    assert "只写连续 PDE、Robin 边界和受测运行模块接口" in system
    assert "只加入题面明确的硬约束" in system
    assert "不得要求一个互斥尾窗同时覆盖多个炉程区域" in system
    assert "把速度换成 `cm/s`" in system
    assert "附件时间列就是物理时刻" in system
    assert "不同设定值的受控炉区组" in system
    assert "无设定温度的冷却通道" in system
    assert "无设定温度的冷却通道" in revision
    assert "小温区10与11之间的间隙中点" in system
    assert "规范结果名" in revision
    assert "不声称连续速度域最大值" in system
    assert "连续阈值平台" in revision
    assert "本版现役 formulation 只保留经验降阶结构" in system
    assert "不得用任意 `区域均值残差 / 全局 RMSE` 比例单独否决模型" in system
    assert "运行环境没有区间 ODE/Interval Newton API" in system
    assert "优先删除该结构并恢复题面可行域" in revision
    assert "题面为 `cm/min` 且时间为秒时须先把速度换成 `cm/s`" in revision
    assert "附件非零首时刻就是物理时刻" in revision
    assert "不再标定过渡形状参数" in revision
    assert "缺少被否决候选的运行实现不是硬约束缺失" in revision
    assert "不得用任意 `区域均值残差 / 全局 RMSE` 比例单独触发结构否决" in revision
    assert "删除该不可执行验证层和超出实际运行预算的固定次数" in revision
    assert "不得再引入全域样条、跨工况事件位置或连续置信域认证" in revision
    assert "多个优化子问题必须共享 Coder 单次执行的总墙钟上限" in system
    assert "多个优化子问题必须共享 Coder 单次执行的总墙钟上限" in revision
    assert "炉前区到炉后区的完整路径" in revision
    assert "全部受控区与真实间隙" in system
    assert "B_total_default=300 s" in revision
    assert "只精化实际发现的状态变化区间" in system
    assert "互易扩散耦合" in system
    assert "不先按参数去重" in system
    assert "不得叠加 SVD、条件数或逐参数剖面优化硬门禁" in revision
    assert "问题2可行速度升序序列的首项、中位索引项、末项" in revision
    verifier = (prompts / "system" / "verifier.j2").read_text(encoding="utf-8")
    assert "不得因模型没有重写该受测函数算法而判定 `block`" in verifier
    assert "即使 Verifier 建议“增加升级路线”" in revision
    assert "触边距离必须按对数搜索区间计算" in revision
    assert "不得以“强制工作完成后若有余量再追加”为由重新引入" in revision
    assert "用于建立耗时估计的前几个任务也必须在启动前" in revision
    assert "N_start * (1 + N_direction)" in revision


def test_retired_pde_cannot_reenter_structured_model_contract():
    evidence = "code v13-v15 已用真实运行证据淘汰 PDE-Robin 候选"
    methods = "主要方法：一维非稳态导热"
    issues = stage_model._model_evidence_issues(
        {
            "model.md": "现役经验一阶响应模型",
            "equations.json": '{"method":"PDE-Robin via _mmw_moving_heat"}',
        },
        "{}",
        methods,
        evidence,
    )

    assert "下游运行证据已淘汰 PDE，现役结构化合同不得重新引入" in issues
    assert not stage_model._model_evidence_issues(
        {
            "model.md": "现役经验一阶响应模型",
            "equations.json": '{"method":"分区经验一阶响应"}',
        },
        "{}",
        methods,
        evidence,
    )
    assert not stage_model._model_evidence_issues(
        {
            "model.md": "现役有效平板状态空间模型",
            "equations.json": '{"method":"simulate_effective_slab"}',
        },
        "{}",
        methods,
        evidence,
    )


def test_verifier_rejects_double_counting_sensor_start_time():
    prompt = (
        Path(stage_model.__file__).parents[1]
        / "prompts"
        / "system"
        / "verifier.j2"
    ).read_text(encoding="utf-8")

    assert "观测时钟语义" in prompt
    assert "把阈值穿越时刻再次加到附件时间" in prompt


def test_verifier_treats_unfounded_regional_residual_ratio_as_warning():
    prompt = (
        Path(stage_model.__file__).parents[1]
        / "prompts"
        / "system"
        / "verifier.j2"
    ).read_text(encoding="utf-8")

    assert "分区残差证据边界" in prompt
    assert "任意 `区域均值残差 / 全局 RMSE` 比例只能作为 warning" in prompt
    assert "当前受测移动热运行接口不提供区间 ODE 或 Interval Newton" in prompt


def test_verifier_blocks_per_subproblem_full_runtime_budgets():
    prompt = (
        Path(stage_model.__file__).parents[1]
        / "prompts"
        / "system"
        / "verifier.j2"
    ).read_text(encoding="utf-8")

    assert "共享总时长预算" in prompt
    assert "把完整执行上限分别赋给 q3、q4" in prompt
    assert "必须判定 `block`" in prompt
    assert "允许候选越过总截止" in prompt
    assert "响应率定义域" in prompt
    assert "单轮可执行预算" in prompt
    assert "要求先测时后停止" in prompt
    assert "诚实停止优先于复活淘汰模型" in prompt
    assert "不要求模型保证任意输入都能答完四问" in prompt
    assert "参数坐标一致性" in prompt
    assert "无控冷却几何" in prompt
    assert "有限检查集口径" in prompt
    assert "阈值等号与平台" in prompt
    assert "小温区10与11之间的间隙中点" in prompt
    assert "规范结果名" in prompt


def test_model_evidence_gate_rejects_claimed_fit_before_code_runs():
    issues = stage_model._model_evidence_issues(
        {
            "model.md": (
                "标定后得到 K=0.02，拟合 RMSE < 2°C，模型通过验证。"
            ),
        },
        json.dumps({
            "external_search_performed": False,
            "unresolved_searches": [],
        }),
    )

    assert any("尚未执行代码" in issue for issue in issues)


def test_model_evidence_gate_rejects_unresolved_bi_support():
    issues = stage_model._model_evidence_issues(
        {
            "model.md": (
                "查阅典型材料参数和换热系数范围，计算 Bi=0.02<0.1，"
                "因此满足集总参数法并选择集总模型。"
            ),
        },
        json.dumps({
            "external_search_performed": False,
            "unresolved_searches": [
                "材料热物理性质",
                "回焊炉换热系数范围",
            ],
        }, ensure_ascii=False),
    )

    assert any("未执行的外部搜索" in issue for issue in issues)
    assert any("不能据此选择集总模型" in issue for issue in issues)


def test_model_evidence_gate_allows_conditional_bi_candidate():
    issues = stage_model._model_evidence_issues(
        {
            "model.md": (
                "若 Bi<0.1，可采用集总模型作为候选；"
                "最终仅按真实数据的拟合质量选择结构。"
            ),
        },
        json.dumps({
            "external_search_performed": False,
            "unresolved_searches": ["材料热物理参数", "换热系数"],
        }, ensure_ascii=False),
    )

    assert not any("Bi" in issue for issue in issues)


def test_apply_evidence_gate_promotes_warning_to_block():
    gated = stage_model._apply_evidence_gate(
        _verify_artifacts("warning"),
        ["伪运行结论"],
    )

    status = json.loads(gated["verify_status.json"])
    assert status["severity"] == "block"
    assert any(item["summary"] == "伪运行结论" for item in status["issues"])
    assert "确定性证据门禁" in gated["verify_report.md"]


def test_model_evidence_gate_requires_primary_pde_blueprint():
    issues = stage_model._model_evidence_issues(
        {"model.md": "采用集总 ODE，拟合失败时再考虑一维模型。"},
        "{}",
        "### 子问题1\n- **主要方法**：一维非稳态导热模型",
    )

    assert any("PDE" in issue and "Robin" in issue for issue in issues)


def test_model_evidence_gate_rejects_primary_pde_as_fallback():
    issues = stage_model._model_evidence_issues(
        {
            "model.md": (
                r"移动坐标 x(t)。若集总模型 NRMSE 未通过，则启用一维非稳态导热升级结构："
                r"\frac{\partial T}{\partial t}=\alpha\frac{\partial^2T}{\partial y^2}，"
                "表面采用 Robin 边界。"
            ),
        },
        "{}",
        "### 子问题1\n- **主要方法**：一维非稳态导热模型",
    )

    assert any("备用路径" in issue for issue in issues)


def test_model_evidence_gate_rejects_transient_pde_as_fallback():
    issues = stage_model._model_evidence_issues(
        {
            "model.md": (
                r"移动坐标 x(t)，\frac{\partial T}{\partial t}，Robin 边界；"
                "优先采用集总模型，一维瞬态导热备用模型仅在拟合失败时启用。"
            ),
        },
        "{}",
        "### 子问题1\n- **主要方法**：一维非稳态导热模型",
    )

    assert any("备用路径" in issue for issue in issues)


def test_model_evidence_gate_rejects_unsearched_material_numbers():
    issues = stage_model._model_evidence_issues(
        {
            "model.md": (
                "取典型对流系数 h=50，并取 FR4 导热系数 k=0.3，"
                "据此计算 Bi。"
            ),
        },
        json.dumps({
            "external_search_performed": False,
            "unresolved_searches": ["材料热物理参数", "换热系数"],
        }, ensure_ascii=False),
    )

    assert any("材料或换热参数数值" in issue for issue in issues)


def test_revision_history_can_include_blocked_source(tmp_path, monkeypatch):
    mgr = CheckpointManager(tmp_path)
    monkeypatch.setattr(
        stage_model,
        "_verify_model",
        lambda *args: (_verify_artifacts("warning"), DummyLLM()),
    )
    source = [{"round": 0, "source_version": 1, "severity": "block", "issues": []}]

    stage_model._run_verified_versions(
        tmp_path, mgr, object(), DummyModeler(), DummyLLM(),
        "analysis", "assumptions", {"model.md": "revised"},
        max_revisions=1,
        history=source,
    )

    history = json.loads(mgr.load_artifacts(StageID.MODEL, 1)["revision_history.json"])
    assert history[0]["source_version"] == 1
    assert history[-1]["severity"] == "warning"


def test_blocked_model_prefers_verifier_report_over_generic_rework_reason(
    tmp_path,
    monkeypatch,
):
    mgr = CheckpointManager(tmp_path)
    for stage, artifacts in (
        (StageID.ANALYZE, {"analysis.md": "分析", "assumptions.md": "假设"}),
        (StageID.EDA, {"data_summary.md": "数据"}),
        (StageID.RESEARCH, {
            "methods.md": "方法",
            "approach.md": "路线",
            "research_evidence.json": "{}",
        }),
    ):
        mgr.save(stage, artifacts, MetaData(stage=stage.value, version=0))
        mgr.approve(stage)
    report = "具体问题：空气温度场端点必须固定为 25°C"
    mgr.save(StageID.MODEL, {
        "model.md": "待修订模型",
        "verify_status.json": json.dumps({
            "severity": "block",
            "issues": [{"category": "边界", "summary": report}],
        }, ensure_ascii=False),
        "verify_report.md": report,
    }, MetaData(stage=StageID.MODEL.value, version=0))
    (tmp_path / "decisions.jsonl").write_text(json.dumps({
        "stage": "model",
        "version": 1,
        "action": "rework",
        "reason": "Verifier 发现严重问题",
    }, ensure_ascii=False), encoding="utf-8")
    modeler = RecordingModeler()
    settings = type("Settings", (), {
        "get_llm_config": lambda self, role: type("Config", (), {
            "backend": "openai",
            "api_key": "test",
        })(),
    })()
    monkeypatch.setattr(stage_model, "get_settings", lambda: settings)
    monkeypatch.setattr(stage_model, "LLMClient", lambda *args, **kwargs: DummyLLM())
    monkeypatch.setattr(stage_model, "ModelerAgent", lambda llm: modeler)
    monkeypatch.setattr(
        stage_model,
        "_run_verified_versions",
        lambda *args, **kwargs: (
            tmp_path,
            _verify_artifacts("warning"),
        ),
    )

    assert stage_model.run_model(tmp_path, mgr) is True
    assert modeler.verify_report == report
    assert report in modeler.verify_status


def test_verification_does_not_reuse_stale_status(tmp_path, monkeypatch):
    mgr = CheckpointManager(tmp_path)
    monkeypatch.setattr(
        stage_model,
        "_verify_model",
        lambda *args: ({"verify_report.md": "本轮无法解析"}, DummyLLM()),
    )

    stage_model._run_verified_versions(
        tmp_path, mgr, object(), DummyModeler(), DummyLLM(),
        "analysis", "assumptions", {
            "model.md": "revised",
            "verify_status.json": '{"severity": "pass"}',
            "verify_report.md": "旧报告",
        },
        max_revisions=0,
    )

    latest = mgr.load_artifacts(StageID.MODEL, 1)
    assert "verify_status.json" not in latest
    assert json.loads(latest["revision_history.json"])[-1]["severity"] == "invalid"


def test_code_gate_failure_becomes_model_feedback(tmp_path):
    mgr = CheckpointManager(tmp_path)
    mgr.save(StageID.MODEL, {
        "model.md": "模型",
        "verify_status.json": '{"severity": "pass", "issues": []}',
    }, MetaData(stage=StageID.MODEL.value, version=0))
    mgr.approve(StageID.MODEL)
    mgr.save(StageID.CODE, {
        "solution.py": "print('done')",
        "run_log.txt": "未找到可行解，A_opt可能是罚函数值",
    }, MetaData(stage=StageID.CODE.value, version=0))

    feedback = stage_model._code_feedback(mgr)

    assert "罚函数值" in feedback
    assert "code v1" in feedback


def test_code_feedback_falls_back_to_active_model_and_includes_contract(tmp_path):
    mgr = CheckpointManager(tmp_path)
    mgr.save(StageID.MODEL, {
        "model.md": "现役降阶模型",
        "verify_status.json": '{"severity": "pass", "issues": []}',
    }, MetaData(stage=StageID.MODEL.value, version=0))
    mgr.approve(StageID.MODEL)
    mgr.save(StageID.CODE, {
        "solution.py": "print('done')",
        "run_log.txt": "未找到可行解，A_opt可能是罚函数值；区域残差诊断失败",
        "method_contract.json": json.dumps({
            "formulation": {"model_family": "PDE 已否决，只保留经验降阶"},
            "implementation": {"deviations": ["分区残差比例没有独立依据"]},
        }, ensure_ascii=False),
        "method_runtime.json": json.dumps({
            "strict_continuous_slope_certificate": False,
            "constraints_not_fully_implemented": ["CON-Q2-2"],
            "limitations": ["运行环境没有区间 ODE API"],
        }, ensure_ascii=False),
    }, MetaData(stage=StageID.CODE.value, version=0))
    mgr.save(StageID.MODEL, {
        "model.md": "未激活失败修订",
        "verify_status.json": '{"severity": "block", "issues": []}',
    }, MetaData(stage=StageID.MODEL.value, version=0))

    feedback = stage_model._code_feedback(mgr)

    assert "code v1" in feedback
    assert "PDE 已否决，只保留经验降阶" in feedback
    assert "分区残差比例没有独立依据" in feedback
    assert '"strict_continuous_slope_certificate": false' in feedback
    assert "运行环境没有区间 ODE API" in feedback


def test_model_review_failure_becomes_model_feedback(tmp_path):
    mgr = CheckpointManager(tmp_path)
    mgr.save(StageID.MODEL, {
        "model.md": "模型",
        "verify_status.json": '{"severity": "pass", "issues": []}',
    }, MetaData(stage=StageID.MODEL.value, version=0))
    mgr.approve(StageID.MODEL)
    mgr.save(StageID.REVIEW, {
        "review.md": "负相关不能证明模型验证有效",
        "checklist.json": json.dumps({
            "rework_stage": "model",
            "items": [{"check": "模型验证逻辑", "status": "fail"}],
        }, ensure_ascii=False),
    }, MetaData(stage=StageID.REVIEW.value, version=0))

    feedback = stage_model._review_feedback(mgr)

    assert "回退 model" in feedback
    assert "负相关" in feedback


def test_compare_refuses_blocked_model_without_calling_llm(tmp_path, monkeypatch):
    mgr = CheckpointManager(tmp_path)
    for severity in ("warning", "block"):
        mgr.save(StageID.MODEL, {
            "model.md": f"模型 {severity}",
            "verify_status.json": json.dumps({"severity": severity, "issues": []}),
        }, MetaData(stage=StageID.MODEL.value, version=0))
    monkeypatch.setattr(
        stage_model,
        "get_settings",
        lambda: (_ for _ in ()).throw(AssertionError("blocked 对比不应调用 LLM")),
    )

    assert stage_model.run_compare_model(tmp_path, mgr, 1, 2) is False
    report = (tmp_path / "output" / "compare_model_v1_v2.md").read_text(encoding="utf-8")
    assert "v2=block" in report
