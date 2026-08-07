import hashlib
import json

from mmw.agents.analyst import AnalystAgent
from mmw.pipeline.stage_analyze import _visual_inputs, _visual_report
from mmw.project import ProjectPaths


def _evidence(*, native=False):
    return {
        "native_shape_text": {"present": native},
        "visual_assets": [{"id": "visual-1"}],
    }


def test_no_images_is_not_reported_as_visual_verification():
    report = _visual_report({}, {"visual_assets": []}, False, "普通文本题")

    assert report["status"] == "no_assets"
    assert report["evidence"] == []


def test_unsupported_image_provider_pauses_only_when_geometry_depends_on_bitmap():
    blocked = _visual_report({}, _evidence(), False, "请根据图1中的几何尺寸求解")
    covered = _visual_report({}, _evidence(native=True), False, "请根据图1中的几何尺寸求解")

    assert blocked["status"] == "not_run"
    assert blocked["requires_human_confirmation"] is True
    assert covered["requires_human_confirmation"] is False


def test_supported_visual_report_requires_exact_ids_and_confidence():
    valid = _visual_report({
        "visual_evidence.json": json.dumps({
            "evidence": [{"id": "visual-1", "conclusion": "尺寸线连接两端", "confidence": 0.8}],
            "requires_human_confirmation": False,
        }, ensure_ascii=False),
    }, _evidence(), True, "根据图1几何尺寸求解")
    invalid = _visual_report({
        "visual_evidence.json": '{"evidence":[{"id":"unknown","conclusion":"猜测","confidence":2}]}',
    }, _evidence(), True, "根据图1几何尺寸求解")

    assert valid["status"] == "completed"
    assert valid["evidence"][0]["id"] == "visual-1"
    assert invalid["status"] == "failed"
    assert invalid["requires_human_confirmation"] is True


def test_visual_inputs_are_hash_checked_and_project_scoped(tmp_path):
    internal = tmp_path / ".mmw"
    asset = internal / "cache" / "problem-assets" / "image.png"
    asset.parent.mkdir(parents=True)
    data = b"\x89PNG\r\n\x1a\nfixture"
    asset.write_bytes(data)
    evidence = {"visual_assets": [{
        "id": "visual-1",
        "mime": "image/png",
        "cache_path": "cache/problem-assets/image.png",
        "size": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
    }]}

    inputs = _visual_inputs(ProjectPaths(tmp_path), evidence, True)

    assert inputs[0]["id"] == "visual-1"
    assert inputs[0]["url"].startswith("data:image/png;base64,")
    evidence["visual_assets"][0]["sha256"] = "0" * 64
    assert _visual_inputs(ProjectPaths(tmp_path), evidence, True) == []

    secret = internal / "config.yaml"
    secret.write_bytes(data)
    evidence["visual_assets"][0].update({
        "cache_path": "config.yaml",
        "sha256": hashlib.sha256(data).hexdigest(),
    })
    assert _visual_inputs(ProjectPaths(tmp_path), evidence, True) == []


def test_analyst_binds_each_image_to_its_evidence_id():
    class StubLLM:
        log_role = ""

        def chat_stream(self, messages):
            self.messages = messages
            return iter((
                '<artifact name="analysis.md">分析</artifact>'
                '<artifact name="visual_evidence.json">{"evidence":[]}</artifact>',
            ))

    llm = StubLLM()
    artifacts = AnalystAgent(llm).analyze(
        "题目正文", visual_inputs=[{"id": "visual-1", "url": "data:image/png;base64,AA=="}],
    )

    user_content = llm.messages[-2]["content"]
    assert artifacts["analysis.md"] == "分析"
    assert user_content[1]["text"] == "视觉证据 ID：visual-1"
    assert user_content[2]["image_url"]["url"] == "data:image/png;base64,AA=="
