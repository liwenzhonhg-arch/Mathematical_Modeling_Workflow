"""数据模型：阶段、检查点状态、子问题依赖。"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


# ── 阶段定义 ──────────────────────────────────────────────


class StageID(str, Enum):
    """8 个流水线阶段标识。"""

    ANALYZE = "analyze"
    EDA = "eda"
    RESEARCH = "research"
    MODEL = "model"
    CODE = "code"
    SOLVE = "solve"
    PAPER = "paper"
    REVIEW = "review"


STAGE_ORDER: list[StageID] = list(StageID)

STAGE_META: dict[StageID, dict] = {
    StageID.ANALYZE: {"index": 1, "label": "问题分析", "dir": "01_analyze"},
    StageID.EDA: {"index": 2, "label": "数据探索", "dir": "02_eda"},
    StageID.RESEARCH: {"index": 3, "label": "方法调研", "dir": "03_research"},
    StageID.MODEL: {"index": 4, "label": "数学建模", "dir": "04_model"},
    StageID.CODE: {"index": 5, "label": "代码实现", "dir": "05_code"},
    StageID.SOLVE: {"index": 6, "label": "求解运行", "dir": "06_solve"},
    StageID.PAPER: {"index": 7, "label": "论文写作", "dir": "07_paper"},
    StageID.REVIEW: {"index": 8, "label": "评审润色", "dir": "08_review"},
}


def next_stage(stage: StageID) -> StageID | None:
    """返回下一个阶段，末尾返回 None。"""
    idx = STAGE_ORDER.index(stage)
    if idx + 1 < len(STAGE_ORDER):
        return STAGE_ORDER[idx + 1]
    return None


def prev_stage(stage: StageID) -> StageID | None:
    """返回上一个阶段，开头返回 None。"""
    idx = STAGE_ORDER.index(stage)
    if idx > 0:
        return STAGE_ORDER[idx - 1]
    return None


# ── 检查点状态 ─────────────────────────────────────────────


class CheckpointStatus(str, Enum):
    """检查点生命周期状态。"""

    PENDING = "pending"
    COMPLETED = "completed"
    APPROVED = "approved"


class StageResult(str, Enum):
    """阶段审批后的转移指令。"""

    PROCEED = "proceed"
    REWORK = "rework"
    BRANCH = "branch"


class StatusData(BaseModel):
    """status.json 的数据结构。"""

    status: CheckpointStatus = CheckpointStatus.PENDING
    result: Optional[StageResult] = None
    rework_target: Optional[str] = None  # rework 时的目标阶段
    upstream_hash: Optional[str] = None
    upstream_changed: bool = False
    approved_by: Optional[str] = None
    approved_at: Optional[datetime] = None


class MetaData(BaseModel):
    """meta.json 的数据结构。"""

    stage: str
    version: int
    created_at: datetime = Field(default_factory=datetime.now)
    model_used: Optional[str] = None
    tokens_input: int = 0
    tokens_output: int = 0
    upstream_versions: dict[str, int] = Field(default_factory=dict)


# ── 子问题依赖 ─────────────────────────────────────────────


class SubProblem(BaseModel):
    """子问题定义。"""

    id: str
    title: str
    depends_on: list[str] = Field(default_factory=list)


class SubProblemsSpec(BaseModel):
    """sub_problems.json 的结构。"""

    sub_problems: list[SubProblem]

    def get_independent_groups(self) -> list[list[str]]:
        """返回可并行处理的子问题分组。"""
        resolved: set[str] = set()
        groups: list[list[str]] = []
        remaining = {sp.id: sp for sp in self.sub_problems}

        while remaining:
            batch = [
                sp_id
                for sp_id, sp in remaining.items()
                if all(dep in resolved for dep in sp.depends_on)
            ]
            if not batch:
                batch = list(remaining.keys())
            groups.append(batch)
            for sp_id in batch:
                resolved.add(sp_id)
                remaining.pop(sp_id)
        return groups


# ── 竞赛工作空间配置 ──────────────────────────────────────


class CompetitionConfig(BaseModel):
    """workspace/<name>/config.yaml 的结构。"""

    name: str
    contest_type: str = "cumcm"
    year: int = 2025
    problem: str = "A"
    team_number: str = ""
    active_versions: dict[str, int] = Field(default_factory=dict)
