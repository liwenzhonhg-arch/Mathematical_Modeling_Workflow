"""FigurePolisherAgent：只修订图表表达元数据，不接触数值。"""

from __future__ import annotations

import json
from typing import Any

from mmw.agents.base import BaseAgent
from mmw.llm import LLMClient
from mmw.utils.figure_quality import load_paper_style


IMMUTABLE_KEYS = ("file", "data_file", "x", "y", "value")
EDITABLE_KEYS = (
    "kind", "title", "x_label", "y_label", "caption", "paper_width", "series_labels",
)


def validate_polisher_plan(
    original: dict[str, Any],
    candidate: dict[str, Any],
) -> dict[str, Any]:
    old_items = original.get("figures", [])
    new_items = candidate.get("figures", []) if isinstance(candidate, dict) else []
    if len(old_items) != len(new_items):
        raise ValueError("图表计划不得增删图表")
    allowed = set(load_paper_style()["figure"]["allowed_types"])
    result = []
    for old, new in zip(old_items, new_items, strict=True):
        if any(new.get(key) != old.get(key) for key in IMMUTABLE_KEYS):
            raise ValueError(f"{old.get('file', '未知图表')} 修改了数据映射")
        merged = dict(old)
        merged.update({key: new[key] for key in EDITABLE_KEYS if key in new})
        if merged.get("kind") not in allowed:
            raise ValueError(f"{merged.get('file')} 使用不支持的图表类型")
        result.append(merged)
    return {"schema_version": 1, "figures": result}


class FigurePolisherAgent(BaseAgent):
    role = "figure_polisher"
    system_prompt_template = "system/figure_polisher.j2"

    def polish(self, manifest: dict[str, Any]) -> dict[str, Any]:
        response = self.run(
            self.render_prompt(
                "figure_polisher.j2",
                manifest=json.dumps(manifest, ensure_ascii=False, indent=2),
            ),
            system_kwargs={"style": json.dumps(load_paper_style(), ensure_ascii=False)},
        )
        artifacts = self.parse_artifacts(response)
        try:
            candidate = json.loads(artifacts.get("figure_manifest.json", ""))
        except json.JSONDecodeError as exc:
            raise ValueError("FigurePolisher 未返回合法 manifest") from exc
        return validate_polisher_plan(manifest, candidate)
