"""阶段 6：求解运行（subprocess 执行代码，收集结果和图表）。"""

from __future__ import annotations

import json
import hashlib
import tempfile
from pathlib import Path

from mmw.agents.figure_polisher import FigurePolisherAgent
from mmw.config import get_settings
from mmw.llm import LLMClient
from mmw.models import MetaData, StageID
from mmw.project import ProjectPaths
from mmw.utils.checkpoint import CheckpointManager
from mmw.utils.display import print_error, print_info, print_success, print_warning
from mmw.utils.executor import run_python_script
from mmw.utils.figure_quality import load_figure_manifest
from mmw.utils.figure_renderer import render_matplotlib_manifest
from mmw.utils.file_io import read_yaml
from mmw.utils.method_contract import build_solve_contract
from mmw.utils.origin_renderer import render_origin_manifest

FileSignature = tuple[int, int]


def run_solve(workspace: Path, mgr: CheckpointManager) -> None:
    paths = ProjectPaths(workspace)
    code_arts = mgr.load_artifacts(StageID.CODE)
    if not code_arts:
        print_error("请先完成并审批代码实现阶段")
        return

    code = code_arts.get("solution.py", "")
    if not code:
        print_error("未找到 solution.py")
        return

    # 生成代码常以 __file__ 的父目录作为输出根；临时脚本必须位于项目根目录，
    # 否则会把结果误写到 .mmw/cache/output/。
    script_path = _write_temp_script(workspace, code)

    # 确保 figures 目录存在
    figures_dir = paths.figures
    figures_dir.mkdir(parents=True, exist_ok=True)

    # 代码阶段也会试运行 solution.py。记录旧产物，solve 只接受本次执行重写的文件。
    paths.result_data.mkdir(parents=True, exist_ok=True)
    results_path = paths.result_data / "results.json"
    sensitivity_path = paths.result_data / "sensitivity.json"
    figure_manifest_path = paths.result_data / "figure_manifest.json"
    method_runtime_path = paths.result_data / "method_runtime.json"
    old_results = _file_signature(results_path)
    old_sensitivity = _file_signature(sensitivity_path)
    old_figure_manifest = _file_signature(figure_manifest_path)
    old_method_runtime = _file_signature(method_runtime_path)
    old_figures = {path.name: _file_signature(path) for path in figures_dir.glob("*.png")}
    old_data_tables = {
        path.name: _file_signature(path)
        for path in paths.result_data.glob("*.csv")
    }
    from mmw.pipeline.stage_code import load_deliverables
    deliverables = load_deliverables(mgr)
    old_deliverables = {
        item["file"]: _file_signature(paths.deliverable(item["file"]))
        for item in deliverables
    }

    print_info("正在运行求解代码...")
    try:
        result = run_python_script(
            script_path,
            workspace,
            timeout=get_settings().mmw_max_runtime_seconds,
        )
    finally:
        # Windows 上杀毒软件或解释器句柄释放延迟可能导致短暂拒绝访问。
        _cleanup_temp_script(script_path)

    artifacts: dict[str, str] = {}

    if result.success:
        print_success("代码运行成功")
        artifacts["run_log.txt"] = f"STDOUT:\n{result.stdout}"
    else:
        print_error(f"运行失败: {result.error_summary}")
        artifacts["run_log.txt"] = f"[失败] {result.error_summary}\n\nSTDOUT:\n{result.stdout}\n\nSTDERR:\n{result.stderr}"

    # 收集生成的图表
    figure_list = _collect_changed_figures(figures_dir, old_figures)
    manifest = _collect_current_manifest(figure_manifest_path, old_figure_manifest)
    if manifest:
        manifest, renderer, agent_meta = polish_figure_manifest(workspace, manifest)
        figure_manifest_path.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        (paths.result_data / "renderer.json").write_text(
            json.dumps(renderer, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        (paths.result_data / "figure_quality_report.json").write_text(
            json.dumps(renderer, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        artifacts["figure_manifest.json"] = json.dumps(manifest, ensure_ascii=False, indent=2)
        artifacts["renderer.json"] = json.dumps(renderer, ensure_ascii=False, indent=2)
        artifacts["figure_quality_report.json"] = json.dumps(
            renderer, ensure_ascii=False, indent=2
        )
        figure_list = [item["file"] for item in manifest["figures"]]
    else:
        agent_meta = {"model": None, "input": 0, "output": 0}
    if figure_list:
        print_info(f"收集到本次运行生成的 {len(figure_list)} 张图表")

    artifacts["figures_list.json"] = json.dumps(figure_list, ensure_ascii=False, indent=2)

    # 收集结构化数值结果与灵敏度数据（论文写作的数值出处约束）
    artifacts["results.json"] = _collect_json_output(
        results_path, default="[]",
        missing_msg="警告：solution.py 未产出 results.json，论文数值将缺乏出处约束",
        previous=old_results,
    )
    artifacts["sensitivity.json"] = _collect_json_output(
        sensitivity_path, default="{}",
        missing_msg="警告：solution.py 未产出 sensitivity.json，灵敏度章节将缺乏真实数据",
        previous=old_sensitivity,
    )
    if code_arts.get("method_contract.json"):
        artifacts["method_runtime.json"] = _collect_json_output(
            method_runtime_path,
            default="{}",
            missing_msg="警告：solution.py 未产出 method_runtime.json，无法验证运行级最优性证据",
            previous=old_method_runtime,
        )
        try:
            method_contract, method_validation = build_solve_contract(
                code_arts["method_contract.json"],
                solution=code,
                results=artifacts["results.json"],
                runtime=artifacts["method_runtime.json"],
                solve_version=mgr.get_next_version(StageID.SOLVE),
            )
        except ValueError as error:
            print_error(str(error))
        else:
            artifacts["method_contract.json"] = json.dumps(
                method_contract, ensure_ascii=False, indent=2,
            )
            artifacts["method_validation.json"] = json.dumps(
                method_validation, ensure_ascii=False, indent=2,
            )

    # 校验题目硬性交付文件（result*.xlsx 等）是否已生成（二进制文件留在 workspace 根供 export 打包，不进检查点）
    stale_deliverables = set(
        _check_deliverables(workspace, mgr, previous=old_deliverables)
    )
    deliverables_manifest = _deliverables_manifest(workspace, mgr)
    for name in stale_deliverables:
        deliverables_manifest.pop(name, None)
    artifacts["deliverables_manifest.json"] = json.dumps(
        deliverables_manifest, ensure_ascii=False, indent=2
    )
    artifacts["data_tables.json"] = json.dumps(
        _data_tables_manifest(workspace, old_data_tables), ensure_ascii=False, indent=2
    )

    # 提取 stdout 中的数值结果作为 results 摘要
    artifacts["interpretation.md"] = _extract_results_summary(result.stdout)

    meta = MetaData(
        stage=StageID.SOLVE.value,
        version=0,
        model_used=agent_meta["model"],
        tokens_input=agent_meta["input"],
        tokens_output=agent_meta["output"],
    )
    vdir = mgr.save(StageID.SOLVE, artifacts, meta)
    print_success(f"求解运行完成，产出保存到: {vdir}")


def _file_signature(path: Path) -> FileSignature | None:
    if not path.is_file():
        return None
    stat = path.stat()
    return stat.st_mtime_ns, stat.st_size


def _write_temp_script(workspace: Path, code: str) -> Path:
    with tempfile.NamedTemporaryFile(
        mode="w",
        suffix=".py",
        prefix=".mmw-solve-",
        dir=workspace,
        delete=False,
        encoding="utf-8",
    ) as handle:
        handle.write(code)
        return Path(handle.name)


def _collect_changed_figures(
    figures_dir: Path,
    previous: dict[str, FileSignature | None],
) -> list[str]:
    return [
        path.name
        for path in sorted(figures_dir.glob("*.png"))
        if _file_signature(path) != previous.get(path.name)
    ]


def _collect_current_manifest(path: Path, previous: FileSignature | None) -> dict | None:
    if not path.is_file() or (previous is not None and _file_signature(path) == previous):
        return None
    try:
        return load_figure_manifest(path)
    except (OSError, json.JSONDecodeError, ValueError) as error:
        print_warning(f"figure_manifest.json 无效，保留原始图表：{error}")
        return None


def polish_figure_manifest(
    workspace: Path,
    manifest: dict,
) -> tuple[dict, dict, dict[str, int | str | None]]:
    """约束式修订 manifest 并按项目选择的后端重制图表。"""
    paths = ProjectPaths(workspace)
    settings = get_settings()
    llm_config = settings.get_llm_config("figure_polisher")
    llm = None
    polished = manifest
    if getattr(llm_config, "backend", "openai") != "openai" or llm_config.api_key:
        llm = LLMClient(llm_config, log_dir=paths.logs)
        try:
            polished = FigurePolisherAgent(llm).polish(manifest)
        except (ValueError, RuntimeError) as error:
            print_warning(f"图表 Agent 输出未采用，使用原 manifest：{error}")
    else:
        print_warning("未配置图表 Agent，使用原 manifest 做确定性重制")

    config = read_yaml(paths.config) if paths.config.is_file() else {}
    backend = config.get("figure_backend", "matplotlib")
    try:
        renderer = (
            render_origin_manifest(polished, paths.result_data, paths.figures)
            if backend == "origin"
            else render_matplotlib_manifest(polished, paths.result_data, paths.figures)
        )
    except (OSError, ValueError) as error:
        print_warning(f"图表重制失败：{error}")
        renderer = {
            "schema_version": 1,
            "renderer": backend,
            "passed": False,
            "failures": [str(error)],
            "figures": [],
        }
    return polished, renderer, {
        "model": llm.model if llm else None,
        "input": llm.total_input_tokens if llm else 0,
        "output": llm.total_output_tokens if llm else 0,
    }


def rerun_figure_polish(workspace: Path, mgr: CheckpointManager) -> Path:
    artifacts = mgr.load_artifacts(
        StageID.SOLVE,
        version=mgr.get_latest_version(StageID.SOLVE),
    )
    try:
        manifest = json.loads(artifacts["figure_manifest.json"])
    except (KeyError, json.JSONDecodeError) as error:
        raise ValueError("当前 solve 版本没有合法 figure_manifest.json") from error
    polished, renderer, agent_meta = polish_figure_manifest(workspace, manifest)
    artifacts["figure_manifest.json"] = json.dumps(polished, ensure_ascii=False, indent=2)
    artifacts["renderer.json"] = json.dumps(renderer, ensure_ascii=False, indent=2)
    artifacts["figure_quality_report.json"] = json.dumps(renderer, ensure_ascii=False, indent=2)
    artifacts["figures_list.json"] = json.dumps(
        [item["file"] for item in polished["figures"]], ensure_ascii=False, indent=2
    )
    return mgr.save(
        StageID.SOLVE,
        artifacts,
        MetaData(
            stage=StageID.SOLVE.value,
            version=0,
            model_used=agent_meta["model"],
            tokens_input=agent_meta["input"],
            tokens_output=agent_meta["output"],
        ),
    )


def _check_deliverables(
    workspace: Path,
    mgr: CheckpointManager,
    previous: dict[str, FileSignature | None] | None = None,
) -> list[str]:
    """校验题目硬性交付文件是否已在工作目录生成，返回缺失清单。"""
    from mmw.pipeline.stage_code import load_deliverables

    paths = ProjectPaths(workspace)
    missing = []
    for item in load_deliverables(mgr, report_ignored=False):
        name = item["file"]
        current = _file_signature(paths.deliverable(name))
        if current is None or (previous is not None and current == previous.get(name)):
            missing.append(name)
    if missing:
        print_error(
            f"题目要求的交付文件未生成: {', '.join(missing)}（题目硬性要求，建议 rework code 补齐）"
        )
    return missing


def _deliverables_manifest(workspace: Path, mgr: CheckpointManager) -> dict[str, str]:
    from mmw.pipeline.stage_code import load_deliverables

    paths = ProjectPaths(workspace)
    return {
        item["file"]: hashlib.sha256(paths.deliverable(item["file"]).read_bytes()).hexdigest()
        for item in load_deliverables(mgr, report_ignored=False)
        if paths.deliverable(item["file"]).is_file()
    }


def _data_tables_manifest(
    workspace: Path,
    previous: dict[str, FileSignature | None] | None = None,
) -> dict[str, str]:
    """仅绑定本轮求解器写入或更新的 CSV 表。"""
    result_data = ProjectPaths(workspace).result_data
    return {
        path.name: hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(result_data.glob("*.csv"))
        if path.is_file()
        and (previous is None or _file_signature(path) != previous.get(path.name))
    }


def _cleanup_temp_script(script_path: Path) -> None:
    """尽力清理临时脚本，清理失败不影响已完成的 solve 检查点。"""
    try:
        script_path.unlink(missing_ok=True)
    except PermissionError as exc:
        print_warning(f"临时脚本清理失败，已保留 {script_path.name}: {exc}")


def _collect_json_output(
    path: Path,
    default: str,
    missing_msg: str,
    previous: FileSignature | None = None,
) -> str:
    """收集求解代码产出的 JSON 文件，缺失或格式非法时降级为 default。"""
    if not path.exists():
        print_error(missing_msg)
        return default
    if previous is not None and _file_signature(path) == previous:
        print_error(f"{path.name} 未被本次求解更新，已忽略旧文件")
        return default
    text = path.read_text(encoding="utf-8")
    try:
        json.loads(text)
    except json.JSONDecodeError:
        print_error(f"{path.name} 格式非法，已忽略")
        return default
    return text


def _extract_results_summary(stdout: str) -> str:
    """从 stdout 中提取关键结果行。"""
    if not stdout.strip():
        return "# 运行结果\n\n（无输出）\n"

    lines = stdout.strip().splitlines()
    key_lines = [l for l in lines if any(kw in l for kw in ("结果", "最优", "=", ":", "误差", "精度"))]

    md = "# 运行结果摘要\n\n"
    if key_lines:
        md += "## 关键输出\n\n"
        for l in key_lines[:30]:
            md += f"- {l.strip()}\n"

    md += "\n## 完整输出\n\n```\n"
    md += stdout[:5000]
    if len(stdout) > 5000:
        md += f"\n... (截断，共 {len(stdout)} 字符)"
    md += "\n```\n"
    return md
