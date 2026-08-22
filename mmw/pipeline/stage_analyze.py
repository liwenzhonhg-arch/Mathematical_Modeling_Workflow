"""阶段 1：问题分析。"""

from __future__ import annotations

import base64
import hashlib
import json
import re
from pathlib import Path

from mmw.agents.analyst import AnalystAgent
from mmw.config import get_settings
from mmw.llm import LLMClient
from mmw.models import MetaData, StageID
from mmw.project import (
    MAX_VISUAL_ASSET_BYTES,
    MAX_VISUAL_ASSET_COUNT,
    MAX_VISUAL_ASSETS_BYTES,
    ProjectPaths,
)
from mmw.utils.checkpoint import CheckpointManager
from mmw.utils.display import print_info, print_success
from mmw.utils.file_io import write_json
from mmw.utils.model_handoff import normalize_assumption_artifacts


VISUAL_MIMES = {"image/png", "image/jpeg", "image/gif", "image/webp"}


def _scan_data_files(workspace: Path) -> list[dict]:
    """扫描项目输入清单或旧式 data/raw，返回数据文件信息。"""
    paths = ProjectPaths(workspace)
    files = []
    for f in paths.data_files():
        if f.is_file() and not f.name.startswith("."):
            info: dict = {
                "name": paths.relative(f),
                "size": _format_size(f.stat().st_size),
                "preview": None,
            }
            if f.suffix in (".csv", ".txt", ".tsv"):
                try:
                    lines = f.read_text(encoding="utf-8", errors="replace").splitlines()[:5]
                    info["preview"] = "\n".join(lines)
                except Exception:
                    pass
            files.append(info)
    return files


def _format_size(size: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024:
            return f"{size:.0f} {unit}"
        size /= 1024
    return f"{size:.1f} TB"


def _visual_dependency_likely(problem_text: str, evidence: dict) -> bool:
    native = evidence.get("native_shape_text")
    return bool(
        evidence.get("visual_assets")
        and not (isinstance(native, dict) and native.get("present"))
        and re.search(r"如图|见图|题图|图\s*\d|示意图|几何|尺寸|角度|位置|截面|布局", problem_text)
    )


def _visual_inputs(paths: ProjectPaths, evidence: dict, supported: bool) -> list[dict]:
    if not supported:
        return []
    root = (paths.cache / "problem-assets").resolve()
    inputs = []
    total = 0
    for asset in evidence.get("visual_assets", []):
        if (
            len(inputs) >= MAX_VISUAL_ASSET_COUNT
            or not isinstance(asset, dict)
            or not isinstance(asset.get("id"), str)
            or asset.get("mime") not in VISUAL_MIMES
        ):
            continue
        path = (paths.internal / str(asset.get("cache_path", ""))).resolve()
        if not path.is_relative_to(root) or not path.is_file():
            continue
        data = path.read_bytes()
        if (
            not data
            or len(data) > MAX_VISUAL_ASSET_BYTES
            or total + len(data) > MAX_VISUAL_ASSETS_BYTES
            or asset.get("size") != len(data)
            or asset.get("sha256") != hashlib.sha256(data).hexdigest()
        ):
            continue
        inputs.append({
            "id": asset.get("id"),
            "url": f"data:{asset['mime']};base64,{base64.b64encode(data).decode('ascii')}",
        })
        total += len(data)
    return inputs


def _visual_report(
    artifacts: dict[str, str],
    evidence: dict,
    supported: bool,
    problem_text: str,
) -> dict:
    assets = evidence.get("visual_assets", [])
    asset_ids = {
        item.get("id") for item in assets
        if isinstance(item, dict) and isinstance(item.get("id"), str)
    }
    dependency = _visual_dependency_likely(problem_text, evidence)
    base = {
        "schema_version": 1,
        "provider_supports_images": supported,
        "evidence": [],
        "requires_human_confirmation": False,
        "confirmation_items": [],
    }
    if not asset_ids:
        return {**base, "status": "no_assets", "reason": "题目未提取到受支持图片资产"}
    if not supported:
        return {
            **base,
            "status": "not_run",
            "reason": "Analyst 供应商未显式声明支持图像输入",
            "requires_human_confirmation": dependency,
            "confirmation_items": sorted(asset_ids) if dependency else [],
        }
    try:
        raw = json.loads(artifacts.get("visual_evidence.json", ""))
    except json.JSONDecodeError:
        raw = None
    items = raw.get("evidence") if isinstance(raw, dict) else None
    valid = isinstance(items, list) and len(items) == len(asset_ids)
    normalized = []
    if valid:
        for item in items:
            confidence = item.get("confidence") if isinstance(item, dict) else None
            if (
                not isinstance(item, dict)
                or item.get("id") not in asset_ids
                or not str(item.get("conclusion", "")).strip()
                or isinstance(confidence, bool)
                or not isinstance(confidence, (int, float))
                or not 0 <= confidence <= 1
            ):
                valid = False
                break
            normalized.append({
                "id": item["id"],
                "conclusion": str(item["conclusion"]).strip(),
                "confidence": float(confidence),
            })
        valid = valid and {item["id"] for item in normalized} == asset_ids
    if not valid:
        return {
            **base,
            "status": "failed",
            "reason": "视觉解释缺失、ID 不匹配或置信度非法",
            "requires_human_confirmation": dependency,
            "confirmation_items": sorted(asset_ids) if dependency else [],
        }
    requires_confirmation = bool(raw.get("requires_human_confirmation")) or (
        dependency and any(item["confidence"] < 0.6 for item in normalized)
    )
    return {
        **base,
        "status": "completed",
        "reason": "视觉证据已由显式支持图像的 Analyst 解释",
        "evidence": normalized,
        "requires_human_confirmation": requires_confirmation,
        "confirmation_items": sorted(asset_ids) if requires_confirmation else [],
    }


def run_analyze(workspace: Path, mgr: CheckpointManager) -> None:
    """执行问题分析阶段。"""
    paths = ProjectPaths(workspace)
    problem_path = paths.problem
    if not problem_path.exists():
        print_info(f"请先将题目粘贴到: {problem_path}")
        return

    problem_text = problem_path.read_text(encoding="utf-8").strip()
    if not problem_text or problem_text.startswith("<!--"):
        print_info(f"题目文件为空，请先编辑: {problem_path}")
        return

    data_files = _scan_data_files(workspace)
    if data_files:
        print_info(f"检测到 {len(data_files)} 个数据文件")

    settings = get_settings()
    llm_config = settings.get_llm_config("analyst")
    if getattr(llm_config, "backend", "openai") == "openai" and not llm_config.api_key:
        from mmw.utils.display import print_error
        print_error("未配置 LLM API Key，请复制 .env.example 为 .env 并填入 API Key")
        return
    llm = LLMClient(llm_config, log_dir=paths.logs)

    agent = AnalystAgent(llm)

    print_info("正在分析题目...")
    input_evidence = ""
    evidence: dict = {}
    if paths.evidence.is_file():
        try:
            evidence = json.loads(paths.evidence.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            evidence = {}
    supports_images = llm_config.backend == "openai" and llm_config.supports_images
    if not isinstance(evidence.get("visual_interpretation"), dict):
        evidence["visual_interpretation"] = {}
    evidence["visual_interpretation"]["provider_supports_images"] = supports_images
    input_evidence = json.dumps(evidence, ensure_ascii=False, indent=2) if evidence else ""
    artifacts = agent.analyze(
        problem_text,
        data_files,
        input_evidence,
        _visual_inputs(paths, evidence, supports_images),
    )
    try:
        artifacts = normalize_assumption_artifacts(artifacts)
    except ValueError as error:
        from mmw.utils.display import print_error

        print_error(f"分析阶段假设合同无效：{error}")
        return
    visual_report = _visual_report(artifacts, evidence, supports_images, problem_text)
    artifacts["visual_evidence.json"] = json.dumps(
        visual_report, ensure_ascii=False, indent=2,
    )
    if evidence:
        evidence["visual_interpretation"] = visual_report
        write_json(paths.evidence, evidence)

    meta = MetaData(
        stage=StageID.ANALYZE.value,
        version=0,
        model_used=llm.model,
        tokens_input=llm.total_input_tokens,
        tokens_output=llm.total_output_tokens,
    )
    vdir = mgr.save(StageID.ANALYZE, artifacts, meta)

    print_success(f"分析完成，产出保存到: {vdir}")
    print_info("查看产出: mmw show analyze")
    print_info("审批通过: mmw approve analyze")
