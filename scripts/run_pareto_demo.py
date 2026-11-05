"""运行：.venv/bin/python scripts/run_pareto_demo.py。"""
from pathlib import Path
from math import hypot

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from ctrlnet import Candidate, Distance, pareto_frontier, section13_base

ROOT = Path(__file__).resolve().parents[1]


def main():
    base = section13_base()
    # 固定控制点与待定点之间的新增距离；不修改原算例。
    pairs = [("A", "C"), ("A", "D"), ("B", "C"), ("B", "D")]
    points = {p.name: p for p in base.network.points}
    observations = [Distance(a, b) for a, b in pairs]
    lengths = [hypot(points[a].E - points[b].E,
                     points[a].N - points[b].N) / 1000 for a, b in pairs]
    lines = ["# 观测优化 Pareto 前沿", "",
             "第 13 节基准网增加 4 条候选距离；保持原算例和黄金期望值。",
             "成本分别为新增观测数、边长之和（km）；不计既有观测成本。",
             "ε-预算扫描覆盖全部可达成本，精确求解后删除支配解。",
             "A=trace(Cx)，D=log det(Cx)，E=最大特征值，max_mp=最大点位中误差（m）；均越小越好。",
             "完整性仅针对当前小规模候选集，不包含大规模 MICP。", "",
             "![成本—精度前沿](pareto_frontier.png)", ""]
    fig, axes = plt.subplots(2, 4, figsize=(14, 7))
    for row, (name, costs) in enumerate((("count", [1.0]*4), ("length_km", lengths))):
        cands = [Candidate(o, c) for o, c in zip(observations, costs)]
        for col, criterion in enumerate(("A", "D", "E", "max_mp")):
            front = pareto_frontier(base, cands, criterion)
            ax = axes[row, col]
            ax.plot([p.spent for p in front.points],
                    [p.objective_value for p in front.points], "o-")
            ax.set(xlabel=name, ylabel=criterion, title=f"{name}: {criterion}")
            ax.grid(alpha=0.25)
            lines += [f"## {name} / {criterion}", "",
                      "| 成本 | 精度目标 | 新增观测数 | 选中观测 |",
                      "|---:|---:|---:|---|"]
            for p in front.points:
                lines.append(f"| {p.spent:.9g} | {p.objective_value:.12g} | {len(p.selected)} | {'; '.join(p.selected_labels) or '—'} |")
            lines.append("")
    fig.tight_layout()
    out = ROOT / "outputs"
    out.mkdir(exist_ok=True)
    fig.savefig(out / "pareto_frontier.png", dpi=160)
    plt.close(fig)
    (out / "pareto_results.md").write_text("\n".join(lines), encoding="utf-8")
    print("outputs/pareto_results.md\noutputs/pareto_frontier.png")


if __name__ == "__main__":
    main()
