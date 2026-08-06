"""2018 CUMCM A 题公开论文交叉基线。

这里不复用 MMW 生成的模型或结果。三组公开论文分别采用有限差分/枚举或
局部搜索，数值并不一致，因此 Oracle 使用它们共同覆盖的公开结果包络，
而不把任一篇论文的单点答案当作唯一真值。
"""

from __future__ import annotations

import json
from pathlib import Path
from statistics import median


PUBLIC_BASELINES = {
    "A401": {"q2_最优L_II": 19.3, "q3_最优L_II": 21.7, "q3_最优L_IV": 6.4},
    "A440": {"q2_最优L_II": 17.5, "q3_最优L_II": 19.2, "q3_最优L_IV": 6.4},
    "independent_entry": {
        "q2_最优L_II": 12.26,
        "q3_最优L_II": 15.42,
        "q3_最优L_IV": 3.0,
    },
}


def solve_reference() -> dict[str, float]:
    names = next(iter(PUBLIC_BASELINES.values()))
    return {
        name: float(median(row[name] for row in PUBLIC_BASELINES.values()))
        for name in names
    }


def main() -> int:
    contract = json.loads(
        Path(__file__).with_name("reference_expected.json").read_text(encoding="utf-8")
    )
    bounds = {item["name"]: item for item in contract["results"]}
    failures = [
        f"{source}:{name}={value} 不在公开交叉包络"
        for source, row in PUBLIC_BASELINES.items()
        for name, value in row.items()
        if not bounds[name]["min"] <= value <= bounds[name]["max"]
    ]
    print(json.dumps({
        "consensus_median": solve_reference(),
        "source_count": len(PUBLIC_BASELINES),
    }, ensure_ascii=False, indent=2))
    if failures:
        print("\n".join(failures))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
