"""LLM 流式响应测试：finish_reason 截断检测。"""

from types import SimpleNamespace

from mmw.llm import StreamResult


class FakeClient:
    model = "fake-model"

    def __init__(self):
        self.tracked = False

    def _track_usage(self, usage, messages, response, duration_seconds=0):
        self.tracked = True


def _chunk(content=None, finish_reason=None, usage=None):
    choice = SimpleNamespace(
        delta=SimpleNamespace(content=content),
        finish_reason=finish_reason,
    )
    return SimpleNamespace(choices=[choice], usage=usage)


def test_finish_reason_length_exposed():
    chunks = [_chunk("被截断的部分输出"), _chunk(finish_reason="length")]
    sr = StreamResult(iter(chunks), FakeClient(), [])
    text = "".join(sr)
    assert text == "被截断的部分输出"
    assert sr.text == "被截断的部分输出"
    assert sr.finish_reason == "length"


def test_finish_reason_stop_normal():
    chunks = [_chunk("完整输出"), _chunk(finish_reason="stop")]
    sr = StreamResult(iter(chunks), FakeClient(), [])
    list(sr)
    assert sr.finish_reason == "stop"


def test_usage_still_tracked_with_finish_reason():
    client = FakeClient()
    usage = SimpleNamespace(prompt_tokens=10, completion_tokens=5)
    chunks = [_chunk("内容"), _chunk(finish_reason="stop", usage=usage)]
    sr = StreamResult(iter(chunks), client, [])
    list(sr)
    assert client.tracked


def test_empty_choices_chunk_tolerated():
    # 部分供应商的 usage 尾包 choices 为空列表
    chunks = [_chunk("内容"), SimpleNamespace(choices=[], usage=None)]
    sr = StreamResult(iter(chunks), FakeClient(), [])
    list(sr)
    assert sr.text == "内容"
    assert sr.finish_reason is None
