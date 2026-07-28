"""Agent 基类工具函数测试：artifact 解析、代码栅栏剥离、全角标点清洗。"""

import httpx
import subprocess
import sys
from openai import APIConnectionError, AuthenticationError

from mmw.agents.base import (
    RETRYABLE_ERRORS,
    BaseAgent,
    _extract_json_artifact_by_key,
    _extract_named_json_artifact,
    _sanitize_python,
    _strip_code_fences,
)
from mmw.utils import display
from mmw.agents import base


def test_parse_artifacts_multiple_files():
    response = (
        '前置说明文字\n'
        '<artifact name="model.md">数学模型内容</artifact>\n'
        '<artifact name="params.json">{"alpha": 0.5}</artifact>\n'
        '收尾文字'
    )
    artifacts = BaseAgent.parse_artifacts(response)
    assert artifacts["model.md"] == "数学模型内容"
    assert artifacts["params.json"] == '{"alpha": 0.5}'


def test_parse_artifacts_single_quotes_and_multiline():
    response = "<artifact name='a.tex'>第一行\n第二行</artifact>"
    artifacts = BaseAgent.parse_artifacts(response)
    assert artifacts["a.tex"] == "第一行\n第二行"


def test_parse_artifacts_empty_response():
    assert BaseAgent.parse_artifacts("没有任何标签的回复") == {}


def test_parse_artifacts_normalizes_latex_style_closing_tag():
    response = r'<artifact name="a.tex">正文\end{artifact}'
    assert BaseAgent.parse_artifacts(response)["a.tex"] == "正文"


def test_strip_code_fences():
    text = "```python\nprint(1)\n```"
    assert _strip_code_fences(text) == "print(1)"


def test_strip_code_fences_plain_text_unchanged():
    assert _strip_code_fences("print(1)") == "print(1)"


def test_sanitize_python_fullwidth_punctuation():
    code = "f(a，b)：\nx = (1，2)"
    fixed = _sanitize_python(code)
    assert fixed == "f(a,b):\nx = (1,2)"


def test_sanitize_python_keeps_chinese_comments():
    code = "# 这是注释，保留全角，不动\nresult = f(x，y)"
    fixed = _sanitize_python(code)
    lines = fixed.splitlines()
    assert lines[0] == "# 这是注释，保留全角，不动"
    assert lines[1] == "result = f(x,y)"


def test_sanitize_python_drops_leading_natural_language_when_safe():
    code = "我来编写完整的 Python 代码。\nimport json\nprint(json.dumps({}))"
    assert _sanitize_python(code).startswith("import json")


def test_sanitize_python_drops_trailing_markdown_when_prefix_is_valid():
    code = "import json\nprint(json.dumps({}))\n1. **代码说明**：这是裸文本"
    assert _sanitize_python(code) == "import json\nprint(json.dumps({}))"


def test_sanitize_python_keeps_markdown_like_text_inside_string():
    code = 'text = """\n1. **不是尾部说明**\n"""\nprint(text)'
    assert _sanitize_python(code) == code


def test_authentication_error_is_not_retried():
    assert issubclass(APIConnectionError, RETRYABLE_ERRORS)
    assert issubclass(httpx.ReadTimeout, RETRYABLE_ERRORS)
    assert issubclass(httpx.ReadError, RETRYABLE_ERRORS)
    assert not issubclass(AuthenticationError, RETRYABLE_ERRORS)


def test_extract_named_json_artifact_from_fence():
    response = '# verify_status.json\n```json\n{"severity": "pass"}\n```'
    assert '"severity": "pass"' in _extract_named_json_artifact(
        response, "verify_status.json"
    )


def test_extract_unnamed_json_artifact_by_key():
    response = '说明\n```json\n{"items": [{"status": "warning"}]}\n```'
    assert '"warning"' in _extract_json_artifact_by_key(response, "items")


def test_run_stream_without_tty_does_not_create_live(monkeypatch):
    class LLM:
        def chat_stream(self, messages):
            return iter(["a", "b"])

    class Stdout:
        @staticmethod
        def isatty():
            return False

    monkeypatch.setattr("mmw.agents.base.sys.stdout", Stdout())
    monkeypatch.setattr(
        "mmw.agents.base.Live",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("不应启用 Live")),
    )

    assert BaseAgent(LLM()).run_stream("test") == "ab"


def test_agents_share_one_console_and_expose_stream_finish_reason(monkeypatch):
    class Stream:
        finish_reason = "length"

        def __iter__(self):
            return iter(["partial"])

    class LLM:
        def chat_stream(self, messages):
            return Stream()

    monkeypatch.setattr(
        "mmw.agents.base.sys.stdout",
        type("Stdout", (), {"isatty": staticmethod(lambda: False)})(),
    )
    agent = BaseAgent(LLM())

    assert base.console is display.console
    assert agent.run_stream("test") == "partial"
    assert agent.last_finish_reason == "length"


def test_plain_print_and_rich_console_share_utf8_output():
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "from mmw.llm import _warn_truncated;"
                "print('执行阶段');"
                "_warn_truncated('测试模型')"
            ),
        ],
        capture_output=True,
        check=True,
    )

    text = result.stdout.decode("utf-8")
    assert "执行阶段" in text
    assert "测试模型" in text
