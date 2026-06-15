"""数据模型测试：阶段顺序、子问题依赖分组。"""

from mmw.models import (
    STAGE_META,
    STAGE_ORDER,
    StageID,
    SubProblem,
    SubProblemsSpec,
    next_stage,
    prev_stage,
)


def test_stage_order_has_eight_stages():
    assert len(STAGE_ORDER) == 8
    assert STAGE_ORDER[0] == StageID.ANALYZE
    assert STAGE_ORDER[-1] == StageID.REVIEW


def test_stage_meta_indices_match_order():
    for i, stage in enumerate(STAGE_ORDER, start=1):
        assert STAGE_META[stage]["index"] == i


def test_next_stage():
    assert next_stage(StageID.ANALYZE) == StageID.EDA
    assert next_stage(StageID.PAPER) == StageID.REVIEW
    assert next_stage(StageID.REVIEW) is None


def test_prev_stage():
    assert prev_stage(StageID.ANALYZE) is None
    assert prev_stage(StageID.EDA) == StageID.ANALYZE


def test_independent_groups_linear_chain():
    spec = SubProblemsSpec(
        sub_problems=[
            SubProblem(id="q1", title="预测", depends_on=[]),
            SubProblem(id="q2", title="优化", depends_on=["q1"]),
            SubProblem(id="q3", title="灵敏度", depends_on=["q1", "q2"]),
        ]
    )
    assert spec.get_independent_groups() == [["q1"], ["q2"], ["q3"]]


def test_independent_groups_parallel():
    spec = SubProblemsSpec(
        sub_problems=[
            SubProblem(id="q1", title="A", depends_on=[]),
            SubProblem(id="q2", title="B", depends_on=[]),
            SubProblem(id="q3", title="C", depends_on=["q1", "q2"]),
        ]
    )
    groups = spec.get_independent_groups()
    assert sorted(groups[0]) == ["q1", "q2"]
    assert groups[1] == ["q3"]


def test_independent_groups_circular_fallback():
    # 循环依赖时不应死循环，剩余的全部作为一批返回
    spec = SubProblemsSpec(
        sub_problems=[
            SubProblem(id="q1", title="A", depends_on=["q2"]),
            SubProblem(id="q2", title="B", depends_on=["q1"]),
        ]
    )
    groups = spec.get_independent_groups()
    assert len(groups) == 1
    assert sorted(groups[0]) == ["q1", "q2"]
