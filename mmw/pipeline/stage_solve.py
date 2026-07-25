"""阶段 6：求解运行（subprocess 执行代码，收集结果和图表）。"""

from __future__ import annotations

import json
import hashlib
from pathlib import Path

from mmw.models import MetaData, StageID
from mmw.project import ProjectPaths
from mmw.utils.checkpoint import CheckpointManager
from mmw.utils.display import print_error, print_info, print_success, print_warning
from mmw.utils.executor import run_python_script

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

    # 写入代码到工作目录
    paths.cache.mkdir(parents=True, exist_ok=True)
    script_path = paths.cache / "solution.py"
    script_path.write_text(code, encoding="utf-8")

    # 确保 figures 目录存在
    figures_dir = paths.figures
    figures_dir.mkdir(parents=True, exist_ok=True)

    # 代码阶段也会试运行 solution.py。记录旧产物，solve 只接受本次执行重写的文件。
    paths.result_data.mkdir(parents=True, exist_ok=True)
    results_path = paths.result_data / "results.json"
    sensitivity_path = paths.result_data / "sensitivity.json"
    old_results = _file_signature(results_path)
    old_sensitivity = _file_signature(sensitivity_path)
    old_figures = {path.name: _file_signature(path) for path in figures_dir.glob("*.png")}
    from mmw.pipeline.stage_code import load_deliverables
    deliverables = load_deliverables(mgr)
    old_deliverables = {
        item["file"]: _file_signature(paths.deliverable(item["file"]))
        for item in deliverables
    }

    print_info("正在运行求解代码...")
    result = run_python_script(script_path, workspace, timeout=300)

    artifacts: dict[str, str] = {}

    if result.success:
        print_success("代码运行成功")
        artifacts["run_log.txt"] = f"STDOUT:\n{result.stdout}"
    else:
        print_error(f"运行失败: {result.error_summary}")
        artifacts["run_log.txt"] = f"[失败] {result.error_summary}\n\nSTDOUT:\n{result.stdout}\n\nSTDERR:\n{result.stderr}"

    # 收集生成的图表
    figure_list = _collect_changed_figures(figures_dir, old_figures)
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

    # 校验题目硬性交付文件（result*.xlsx 等）是否已生成（二进制文件留在 workspace 根供 export 打包，不进检查点）
    _check_deliverables(workspace, mgr, previous=old_deliverables)
    artifacts["deliverables_manifest.json"] = json.dumps(
        _deliverables_manifest(workspace, mgr), ensure_ascii=False, indent=2
    )

    # 提取 stdout 中的数值结果作为 results 摘要
    artifacts["interpretation.md"] = _extract_results_summary(result.stdout)

    meta = MetaData(stage=StageID.SOLVE.value, version=0)
    vdir = mgr.save(StageID.SOLVE, artifacts, meta)
    print_success(f"求解运行完成，产出保存到: {vdir}")

    # 清理临时脚本；Windows 上杀毒软件或解释器句柄释放延迟可能导致短暂拒绝访问。
    _cleanup_temp_script(script_path)


def _file_signature(path: Path) -> FileSignature | None:
    if not path.is_file():
        return None
    stat = path.stat()
    return stat.st_mtime_ns, stat.st_size


def _collect_changed_figures(
    figures_dir: Path,
    previous: dict[str, FileSignature | None],
) -> list[str]:
    return [
        path.name
        for path in sorted(figures_dir.glob("*.png"))
        if _file_signature(path) != previous.get(path.name)
    ]


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
