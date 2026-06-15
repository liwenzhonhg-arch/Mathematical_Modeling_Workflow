"""Agent 基类工具函数测试：artifact 解析、代码栅栏剥离、全角标点清洗。"""

from mmw.agents.base import BaseAgent, _sanitize_python, _strip_code_fences


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
