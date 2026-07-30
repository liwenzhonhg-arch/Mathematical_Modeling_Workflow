"""摘要打分迭代循环测试：用 stub LLM 验证打分解析与循环控制。"""

import json

from mmw.agents.abstract_critic import AbstractCriticAgent, _abstract_plain_text
from mmw.agents.writer import WriterAgent
from mmw.pipeline.stage_paper import _refine_abstract


class StubLLM:
    """按预设序列依次返回响应的假 LLM。"""

    model = "stub"
    total_input_tokens = 0
    total_output_tokens = 0

    def __init__(self, responses: list[str]):
        self.responses = list(responses)
        self.calls = 0

    def chat(self, messages, **kwargs):
        self.calls += 1
        return self.responses.pop(0)

    def chat_stream(self, messages, **kwargs):
        # 返回可迭代对象，模拟流式输出
        self.calls += 1
        return iter([self.responses.pop(0)])


class CapturingStubLLM(StubLLM):
    def __init__(self, responses: list[str]):
        super().__init__(responses)
        self.messages = []

    def chat_stream(self, messages, **kwargs):
        self.messages.append(messages)
        return super().chat_stream(messages, **kwargs)


def _score_response(score: int, issues: list[str] | None = None) -> str:
    data = {
        "score": score,
        "dimensions": {"四要素": 25},
        "issues": issues or [],
        "suggestions": [],
    }
    return f'<artifact name="abstract_score.json">{json.dumps(data, ensure_ascii=False)}</artifact>'


def _revise_response(text: str) -> str:
    return f'<artifact name="sections/abstract.tex">{text}</artifact>'


def test_score_parses_valid_json():
    critic = AbstractCriticAgent(StubLLM([_score_response(78, ["结论缺失"])]))
    result = critic.score("摘要内容", "[]")
    assert result["score"] == 78
    assert result["issues"] == ["结论缺失"]


def test_score_broken_json_returns_minus_one():
    critic = AbstractCriticAgent(
        StubLLM(['<artifact name="abstract_score.json">{broken</artifact>'])
    )
    result = critic.score("摘要内容", "[]")
    assert result["score"] == -1


def test_score_is_memoryless():
    llm = StubLLM([_score_response(70), _score_response(80)])
    critic = AbstractCriticAgent(llm)
    critic.score("摘要", "[]")
    critic.score("摘要", "[]")
    # 每次打分清空历史：第二次调用时历史只含本轮 system+user+assistant
    assert len(critic.chat_history) == 3


def test_refine_stops_at_threshold_first_round():
    critic_llm = StubLLM([_score_response(90)])
    writer_llm = StubLLM([])  # 不应被调用
    artifacts = {"sections/abstract.tex": "高分摘要"}
    out = _refine_abstract(
        WriterAgent(writer_llm), AbstractCriticAgent(critic_llm), artifacts, "[]"
    )
    assert writer_llm.calls == 0
    assert critic_llm.calls == 1
    iterations = json.loads(out["abstract_iterations.json"])
    assert len(iterations) == 1
    assert iterations[0]["score"] == 90


def test_refine_does_not_accept_overlong_high_score():
    critic_llm = StubLLM([_score_response(90), _score_response(86)])
    writer_llm = CapturingStubLLM([_revise_response("压缩后的摘要")])
    artifacts = {"sections/abstract.tex": "长" * 601}

    out = _refine_abstract(
        WriterAgent(writer_llm), AbstractCriticAgent(critic_llm), artifacts, "[]"
    )

    assert critic_llm.calls == 2
    assert writer_llm.calls == 1
    assert out["sections/abstract.tex"] == "压缩后的摘要"
    iterations = json.loads(out["abstract_iterations.json"])
    assert iterations[0]["length"] == 601
    assert json.loads(out["abstract_score.json"])["score"] == 86
    assert "400-480" in str(writer_llm.messages[0])


def test_refine_prefers_within_limit_fallback_over_higher_overlong_score(monkeypatch):
    monkeypatch.setattr("mmw.pipeline.stage_paper._build_fallback_abstract", lambda _: "结构化兜底摘要")
    critic_llm = StubLLM([_score_response(95), _score_response(80)])
    artifacts = {"sections/abstract.tex": "长" * 601}

    out = _refine_abstract(
        WriterAgent(StubLLM([])), AbstractCriticAgent(critic_llm), artifacts, "[]", max_rounds=1
    )

    assert out["sections/abstract.tex"] == "结构化兜底摘要"
    assert json.loads(out["abstract_score.json"])["score"] == 80


def test_refine_max_rounds_forced_exit():
    # 4 轮都不达标：critic 调 4 次，writer 修订 3 次
    critic_llm = StubLLM([_score_response(s) for s in (60, 65, 70, 75)])
    writer_llm = StubLLM([_revise_response(f"修订{i}") for i in (1, 2, 3)])
    artifacts = {"sections/abstract.tex": "初稿"}
    out = _refine_abstract(
        WriterAgent(writer_llm), AbstractCriticAgent(critic_llm), artifacts, "[]"
    )
    assert critic_llm.calls == 4
    assert writer_llm.calls == 3
    assert out["sections/abstract.tex"] == "修订3"
    assert len(json.loads(out["abstract_iterations.json"])) == 4
    assert json.loads(out["abstract_score.json"])["score"] == 75


def test_refine_keeps_best_version_when_revision_regresses():
    # 分数回退场景（59 是最高分）：最终保留第 2 轮版本而非最后一轮
    critic_llm = StubLLM([_score_response(s) for s in (54, 59, 52, 50)])
    writer_llm = StubLLM([_revise_response(f"修订{i}") for i in (1, 2, 3)])
    artifacts = {"sections/abstract.tex": "初稿"}
    out = _refine_abstract(
        WriterAgent(writer_llm), AbstractCriticAgent(critic_llm), artifacts, "[]"
    )
    # 第 2 轮打分的对象是第 1 次修订的产物
    assert out["sections/abstract.tex"] == "修订1"
    assert json.loads(out["abstract_score.json"])["score"] == 59


def test_refine_needs_upstream_data_early_exit():
    # 评审归因为上游数据缺口：不再修订，提前退出并保留当前最佳
    data = {
        "score": 50,
        "dimensions": {},
        "issues": ["q2/q3 在 results.json 中无数值结果"],
        "suggestions": [],
        "needs_upstream_data": True,
    }
    critic_llm = StubLLM([
        f'<artifact name="abstract_score.json">{json.dumps(data, ensure_ascii=False)}</artifact>'
    ])
    writer_llm = StubLLM([])  # 不应被调用
    artifacts = {"sections/abstract.tex": "初稿"}
    out = _refine_abstract(
        WriterAgent(writer_llm), AbstractCriticAgent(critic_llm), artifacts, "[]"
    )
    assert writer_llm.calls == 0
    assert critic_llm.calls == 1
    assert out["sections/abstract.tex"] == "初稿"
    assert json.loads(out["abstract_score.json"])["score"] == 50


def test_score_defaults_needs_upstream_data_false():
    critic = AbstractCriticAgent(StubLLM([_score_response(70)]))
    result = critic.score("摘要", "[]")
    assert result["needs_upstream_data"] is False


def test_refine_parse_failure_degrades_gracefully():
    critic_llm = StubLLM(["完全不是 JSON 的回复"])
    writer_llm = StubLLM([])
    artifacts = {"sections/abstract.tex": "初稿"}
    out = _refine_abstract(
        WriterAgent(writer_llm), AbstractCriticAgent(critic_llm), artifacts, "[]"
    )
    # 解析失败：循环退出、摘要保留原文、不调用 writer
    assert out["sections/abstract.tex"] == "初稿"
    assert writer_llm.calls == 0


def test_refine_no_abstract_noop():
    out = _refine_abstract(
        WriterAgent(StubLLM([])), AbstractCriticAgent(StubLLM([])), {}, "[]"
    )
    assert "abstract_score.json" not in out


def test_plain_text_strips_latex():
    text = _abstract_plain_text(r"\textbf{摘要}内容 $x^2$ \par 关键词：规划")
    assert "textbf" not in text
    assert "摘要" in text
