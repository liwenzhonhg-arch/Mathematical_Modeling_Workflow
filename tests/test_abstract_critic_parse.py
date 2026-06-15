"""摘要评分 JSON 解析韧性测试。"""

from mmw.agents.abstract_critic import AbstractCriticAgent


class StubLLM:
    model = "stub"
    total_input_tokens = 0
    total_output_tokens = 0

    def __init__(self, response: str):
        self.response = response

    def chat_stream(self, messages, **kwargs):
        return iter([self.response])

    def chat(self, messages, **kwargs):
        return self.response


def test_score_with_surrounding_prose():
    # 模型在 JSON 外说了废话且没用 artifact 标签
    resp = '评分如下：\n{"score": 81, "dimensions": {}, "issues": [], "suggestions": []}\n以上。'
    critic = AbstractCriticAgent(StubLLM(resp))
    assert critic.score("摘要", "[]")["score"] == 81


def test_score_failure_keeps_raw_response():
    critic = AbstractCriticAgent(StubLLM("完全无法解析的内容"))
    result = critic.score("摘要", "[]")
    assert result["score"] == -1
    assert "raw_response" in result


def test_score_non_dict_json_rejected():
    critic = AbstractCriticAgent(StubLLM("[1, 2, 3]"))
    assert critic.score("摘要", "[]")["score"] == -1
