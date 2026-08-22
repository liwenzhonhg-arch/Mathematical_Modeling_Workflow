"""把各后端 PNG 汇总为便于人工评审的联系表。"""

from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "DejaVu Sans"]
plt.rcParams["axes.unicode_minus"] = False


ROOT = Path(__file__).resolve().parent.parent
REPORT_DIR = ROOT / "reports"


def make_sheet(backend: str) -> None:
    paths = sorted((ROOT / "outputs" / backend).glob("*.png"))
    if not paths:
        return
    columns = 2 if len(paths) <= 4 else 4
    rows = (len(paths) + columns - 1) // columns
    fig, axes = plt.subplots(rows, columns, figsize=(5.4 * columns, 3.7 * rows), squeeze=False)
    for ax in axes.flat:
        ax.axis("off")
    for ax, path in zip(axes.flat, paths, strict=False):
        ax.imshow(plt.imread(path))
        ax.set_title(path.stem, fontsize=11)
        ax.axis("off")
    fig.suptitle(f"{backend} 科研绘图基准", fontsize=16)
    fig.tight_layout()
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    fig.savefig(REPORT_DIR / f"contact_sheet_{backend}.png", dpi=160, facecolor="white")
    plt.close(fig)


def main() -> None:
    for backend in ("matplotlib", "matlab", "origin"):
        make_sheet(backend)


if __name__ == "__main__":
    main()
