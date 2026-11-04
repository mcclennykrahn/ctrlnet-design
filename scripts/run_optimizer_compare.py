#!/usr/bin/env python3
"""C2 优化器对比演示：贪心 / 局部搜索 / 精确 / MILP 代理。

数据
----
1. 第 13 节基准边角网（A、B 固定，C、D 待定），候选为除基准角之外的
   10 个水平角；
2. DEM 演示网（``data/sample/terrain_project.json``，由
   ``scripts/run_terrain_demo.py`` 从 Copernicus GLO-30 小样本生成），
   基准网取前 14 条通视距离，候选仅取剩余通视距离与通视射线构成的水平角。

两种网均在多个预算下运行，输出::

    outputs/optimizer_comparison.png
    outputs/optimizer_comparison.csv
    outputs/optimizer_comparison.md

运行::

    .venv/bin/python scripts/run_optimizer_compare.py

MILP 需要 ``pip install -e ".[opt]"``；无 SciPy 时自动跳过该曲线，不影响
精确/贪心对比。
"""

from __future__ import annotations

import csv
import itertools
import json
import os
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

os.environ.setdefault(
    "MPLCONFIGDIR", str(Path(os.environ.get("TMPDIR", "/tmp")) / "ctrlnet-mplconfig")
)
Path(os.environ["MPLCONFIGDIR"]).mkdir(parents=True, exist_ok=True)

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import font_manager

from ctrlnet import (
    Angle,
    Candidate,
    CostModel,
    Distance,
    Network,
    Point,
    Scenario,
    exact_optimize,
    greedy_optimize,
    local_search_optimize,
    milp_available,
    milp_optimize,
    section13_base,
    solve,
)

ROOT = Path(__file__).resolve().parents[1]
OUTPUTS = ROOT / "outputs"
OUTPUTS.mkdir(parents=True, exist_ok=True)
TERRAIN_PROJECT = ROOT / "data" / "sample" / "terrain_project.json"

CRITERION = "max_mp"
EXACT_TIME_LIMIT = 15.0

_available_fonts = {f.name for f in font_manager.fontManager.ttflist}
_CJK_CANDIDATES = [
    "Noto Sans CJK SC",
    "Noto Sans CJK JP",
    "WenQuanYi Zen Hei",
    "Droid Sans Fallback",
]
_CJK_FONT = next((name for name in _CJK_CANDIDATES if name in _available_fonts), None)
if _CJK_FONT:
    plt.rcParams["font.family"] = "sans-serif"
    plt.rcParams["font.sans-serif"] = [_CJK_FONT, "DejaVu Sans"]
plt.rcParams["axes.unicode_minus"] = False

COLORS = {
    "greedy": "#1f77b4",
    "local_search": "#2ca02c",
    "exact": "#d62728",
    "milp": "#9467bd",
}
MARKERS = {
    "greedy": "o",
    "local_search": "s",
    "exact": "D",
    "milp": "^",
}
LINESTYLES = {
    "greedy": "-",
    "local_search": "--",
    "exact": "-",
    "milp": ":",
}
METHOD_LABELS = {
    "greedy": "贪心" if _CJK_FONT else "Greedy",
    "local_search": "贪心 + 1换1" if _CJK_FONT else "Greedy + 1-swap",
    "exact": "分支定界（精确）" if _CJK_FONT else "Branch & bound (exact)",
    "milp": "MILP 线性代理" if _CJK_FONT else "MILP proxy",
}


def T(zh: str, en: str) -> str:
    return zh if _CJK_FONT else en


@dataclass
class Problem:
    name: str
    base: Any
    candidates: List[Candidate]
    cost_model: CostModel
    budgets: List[float]
    note: str


# ---------------------------------------------------------------------------
# 数据准备
# ---------------------------------------------------------------------------
def build_section13_problem() -> Problem:
    base = section13_base()
    names = ["A", "B", "C", "D"]
    existing = {
        ("A", frozenset(("C", "B"))),  # ∠C-A-B
        ("B", frozenset(("A", "D"))),  # ∠A-B-D
    }
    candidates: List[Candidate] = []
    for station in names:
        others = [name for name in names if name != station]
        for back, fore in itertools.combinations(others, 2):
            key = (station, frozenset((back, fore)))
            if key in existing:
                continue
            candidates.append(Candidate(Angle(back, station, fore), 1.0))
    model = CostModel({name: 2.0 for name in names})
    budgets = [0.0, 3.0, 5.0, 7.0, 9.0, 12.0]
    return Problem(
        name="第13节网",
        base=base,
        candidates=candidates,
        cost_model=model,
        budgets=budgets,
        note="A、B 固定；10 个候选水平角；观测 1.0，设站 2.0/站",
    )


def _visible_pairs(payload: Dict[str, Any]) -> set:
    out = set()
    for item in payload.get("visibility", []):
        if item.get("visible"):
            out.add(tuple(sorted((str(item["from"]), str(item["to"])))))
    return out


def build_dem_problem() -> Problem:
    if not TERRAIN_PROJECT.exists():
        raise FileNotFoundError(
            f"缺少 {TERRAIN_PROJECT}；请先运行 scripts/run_terrain_demo.py"
        )
    payload = json.loads(TERRAIN_PROJECT.read_text(encoding="utf-8"))
    visible = _visible_pairs(payload)
    points = [
        Point(item["name"], item["E"], item["N"], fixed=bool(item["fixed"]))
        for item in payload["points"]
    ]
    distance_rows = payload["observations"]["distances"]
    angle_rows = payload["observations"]["angles"]

    base_rows = distance_rows[:14]
    base_obs = [
        Distance(row["from"], row["to"], a=row.get("sigma_a_m", 0.002),
                 b_ppm=row.get("sigma_b_ppm", 2.0))
        for row in base_rows
    ]
    base_net = Network(points, base_obs, name="DEM 通视边角网（基准）")
    result = solve(base_net)
    if result.rank != result.n_params:
        raise RuntimeError("DEM 基准网秩亏，无法作为优化起点")

    candidates: List[Candidate] = []
    for row in distance_rows[14:]:
        key = tuple(sorted((row["from"], row["to"])))
        if key in visible:
            candidates.append(
                Candidate(
                    Distance(row["from"], row["to"],
                             a=row.get("sigma_a_m", 0.002),
                             b_ppm=row.get("sigma_b_ppm", 2.0)),
                    1.0,
                )
            )
    for row in angle_rows:
        station = row["station"]
        back = row["backsight"]
        fore = row["foresight"]
        if (
            tuple(sorted((station, back))) in visible
            and tuple(sorted((station, fore))) in visible
            and tuple(sorted((back, fore))) in visible
        ):
            candidates.append(
                Candidate(
                    Angle(back, station, fore,
                          sigma_arcsec=row.get("sigma_arcsec", 1.0)),
                    1.0,
                )
            )
        if len(candidates) >= 14:
            break
    candidates = candidates[:14]
    model = CostModel(default_station_cost=3.0)
    budgets = [0.0, 4.0, 6.0, 8.0, 10.0, 12.0]
    scenario = Scenario("DEM 通视边角网", base_net)
    return Problem(
        name="DEM 通视网",
        base=scenario,
        candidates=candidates,
        cost_model=model,
        budgets=budgets,
        note=(
            f"7 点（P1/P2 固定）；基准 {len(base_obs)} 条通视距离；"
            f"{len(candidates)} 个通视候选；观测 1.0，设站 3.0/站"
        ),
    )


# ---------------------------------------------------------------------------
# 运行
# ---------------------------------------------------------------------------
@dataclass
class RunRecord:
    network: str
    budget: float
    criterion: str
    method: str
    method_label: str
    objective: float
    max_mp: float
    spent: float
    selected_count: int
    selected_labels: str
    elapsed_s: float
    exact: bool
    nodes: int
    note: str


def _timed_call(func: Any, *args: Any, **kwargs: Any) -> Tuple[Any, float]:
    started = time.perf_counter()
    result = func(*args, **kwargs)
    return result, time.perf_counter() - started


def run_problem(problem: Problem) -> List[RunRecord]:
    records: List[RunRecord] = []
    methods: List[str] = ["greedy", "local_search", "exact"]
    if milp_available():
        methods.append("milp")

    for budget in problem.budgets:
        for method in methods:
            try:
                if method == "greedy":
                    result, elapsed = _timed_call(
                        greedy_optimize,
                        problem.base,
                        problem.candidates,
                        criterion=CRITERION,
                        budget=budget,
                        cost_model=problem.cost_model,
                    )
                elif method == "local_search":
                    result, elapsed = _timed_call(
                        local_search_optimize,
                        problem.base,
                        problem.candidates,
                        criterion=CRITERION,
                        budget=budget,
                        cost_model=problem.cost_model,
                        max_local_iterations=8,
                    )
                elif method == "exact":
                    result, elapsed = _timed_call(
                        exact_optimize,
                        problem.base,
                        problem.candidates,
                        criterion=CRITERION,
                        budget=budget,
                        cost_model=problem.cost_model,
                        time_limit=EXACT_TIME_LIMIT,
                    )
                else:
                    result, elapsed = _timed_call(
                        milp_optimize,
                        problem.base,
                        problem.candidates,
                        criterion=CRITERION,
                        budget=budget,
                        cost_model=problem.cost_model,
                        max_local_iterations=3,
                    )
            except Exception as exc:  # 单个方法失败不应中断整张对比表
                print(f"[warn] {problem.name} budget={budget:g} {method}: {exc}")
                continue

            exact = bool(getattr(result, "exact", False))
            if method == "exact" and not exact:
                label = METHOD_LABELS["exact"] + ("（超时）" if _CJK_FONT else " (timeout)")
            else:
                label = METHOD_LABELS[method]
            records.append(
                RunRecord(
                    network=problem.name,
                    budget=budget,
                    criterion=CRITERION,
                    method=method,
                    method_label=label,
                    objective=float(result.objective_value),
                    max_mp=float(result.final_metrics.max_mp),
                    spent=float(result.spent),
                    selected_count=len(result.selected),
                    selected_labels="; ".join(result.selected_labels),
                    elapsed_s=float(elapsed),
                    exact=exact,
                    nodes=int(getattr(result, "nodes", 0)),
                    note=str(getattr(result, "notes", "") or ""),
                )
            )
    return records


# ---------------------------------------------------------------------------
# 输出
# ---------------------------------------------------------------------------
def plot_comparison(
    problems: Sequence[Problem],
    results: Sequence[RunRecord],
    output: Path,
) -> None:
    methods = [m for m in ("greedy", "local_search", "exact", "milp")
               if any(r.method == m for r in results)]
    fig, axes = plt.subplots(
        len(problems), 2, figsize=(12.6, 4.6 * len(problems)), squeeze=False
    )
    for row, problem in enumerate(problems):
        subset = [r for r in results if r.network == problem.name]
        ax_obj, ax_time = axes[row, 0], axes[row, 1]
        for method in methods:
            rows = sorted(
                [r for r in subset if r.method == method],
                key=lambda r: r.budget,
            )
            if not rows:
                continue
            x = [r.budget for r in rows]
            y = [r.max_mp * 1000.0 for r in rows]
            t = [max(r.elapsed_s, 1e-6) for r in rows]
            ax_obj.plot(
                x, y,
                color=COLORS[method],
                marker=MARKERS[method],
                ls=LINESTYLES[method],
                lw=1.8,
                ms=5.5,
                label=rows[0].method_label,
            )
            ax_time.plot(
                x, t,
                color=COLORS[method],
                marker=MARKERS[method],
                ls=LINESTYLES[method],
                lw=1.8,
                ms=5.5,
                label=rows[0].method_label,
            )
        ax_obj.set_title(
            T(f"{problem.name}：目标值", f"{problem.name}: objective")
        )
        ax_obj.set_xlabel(T("预算", "Budget"))
        ax_obj.set_ylabel(T("最大点位中误差 / mm", "max point mp / mm"))
        ax_obj.grid(alpha=0.25)
        ax_time.set_title(
            T(f"{problem.name}：耗时", f"{problem.name}: runtime")
        )
        ax_time.set_xlabel(T("预算", "Budget"))
        ax_time.set_ylabel(T("耗时 / s（对数）", "Runtime / s (log)"))
        ax_time.set_yscale("log")
        ax_time.grid(alpha=0.25, which="both")
        for ax in (ax_obj, ax_time):
            ax.legend(fontsize=7.6, framealpha=0.9)
    fig.suptitle(
        T(
            "C2 观测方案优化：贪心 / 局部搜索 / 精确 / MILP 代理",
            "C2 observation design: greedy / local search / exact / MILP proxy",
        ),
        fontsize=13,
    )
    fig.tight_layout(rect=(0, 0, 1, 0.97))
    fig.savefig(output, dpi=220, bbox_inches="tight")
    plt.close(fig)


def write_csv(records: Sequence[RunRecord], output: Path) -> None:
    fields = [
        "network",
        "budget",
        "criterion",
        "method",
        "method_label",
        "objective",
        "max_mp_mm",
        "spent",
        "selected_count",
        "selected_labels",
        "elapsed_s",
        "exact",
        "nodes",
        "note",
    ]
    with output.open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        for r in records:
            writer.writerow(
                {
                    "network": r.network,
                    "budget": f"{r.budget:g}",
                    "criterion": r.criterion,
                    "method": r.method,
                    "method_label": r.method_label,
                    "objective": f"{r.objective:.12g}",
                    "max_mp_mm": f"{r.max_mp * 1000.0:.9f}",
                    "spent": f"{r.spent:.12g}",
                    "selected_count": r.selected_count,
                    "selected_labels": r.selected_labels,
                    "elapsed_s": f"{r.elapsed_s:.6f}",
                    "exact": "yes" if r.exact else "no",
                    "nodes": r.nodes,
                    "note": r.note,
                }
            )


def _fmt_objective(record: RunRecord) -> str:
    if record.criterion == "max_mp":
        return f"{record.max_mp * 1000.0:.4f}"
    return f"{record.objective:.6g}"


def write_markdown(
    problems: Sequence[Problem],
    records: Sequence[RunRecord],
    output: Path,
) -> None:
    generated = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    lines: List[str] = [
        "# C2 观测方案优化对比",
        "",
        f"生成时间：{generated}",
        "",
        f"- 准则：`{CRITERION}`（最小化最大点位中误差）；"
        "目标值越小越好。",
        "- 成本：每条候选观测成本 + 测站首次使用固定成本；"
        "测站在候选集合中首次使用时只收一次。",
        "- 方法：\n"
        "  - `greedy`：按单位成本边际收益贪心加入；\n"
        "  - `local_search`：贪心后做 1 换 1 局部搜索；\n"
        "  - `exact`：分支定界，候选 ≤ 20，预算约束下证明全局最优；\n"
        "  - `milp`：逐点/逐边线性代理 MILP（SciPy HiGHS），"
        "求解后用真实平差目标做 1 加/1 换 1 校正，**属于近似**。",
        "- 第 13 节黄金期望值未作任何修改。",
        "",
        "## 算例概况",
        "",
        "| 网络 | 候选数 | 预算 | 说明 |",
        "|---|---:|---|---|",
    ]
    for p in problems:
        lines.append(
            f"| {p.name} | {len(p.candidates)} | "
            f"{', '.join(f'{b:g}' for b in p.budgets)} | {p.note} |"
        )
    lines.append("")

    for problem in problems:
        lines.extend(
            [
                f"## {problem.name}",
                "",
                "| 预算 | 方法 | 目标 max mp/mm | 成本 | 观测数 | 耗时/s | 精确 | 节点 | 选中观测 |",
                "|---:|---|---:|---:|---:|---:|---|---:|---|",
            ]
        )
        subset = [r for r in records if r.network == problem.name]
        for budget in problem.budgets:
            rows = [r for r in subset if abs(r.budget - budget) < 1e-12]
            for r in rows:
                lines.append(
                    f"| {budget:g} | {r.method_label} | {_fmt_objective(r)} | "
                    f"{r.spent:g} | {r.selected_count} | {r.elapsed_s:.4f} | "
                    f"{'是' if r.exact else '否'} | {r.nodes} | "
                    f"{r.selected_labels or '—'} |"
                )
        lines.append("")

    lines.extend(
        [
            "## 方法汇总",
            "",
            "| 网络 | 方法 | 平均耗时/s | 平均目标 max mp/mm | 相对精确解平均差距 | 精确次数 |",
            "|---|---|---:|---:|---:|---:|",
        ]
    )
    for problem in problems:
        subset = [r for r in records if r.network == problem.name]
        exact_by_budget = {
            round(r.budget, 9): r
            for r in subset
            if r.method == "exact" and r.exact
        }
        for method in ("greedy", "local_search", "exact", "milp"):
            rows = [r for r in subset if r.method == method]
            if not rows:
                continue
            avg_time = sum(r.elapsed_s for r in rows) / len(rows)
            avg_obj = sum(r.max_mp for r in rows) / len(rows) * 1000.0
            gaps: List[float] = []
            for r in rows:
                ref = exact_by_budget.get(round(r.budget, 9))
                if ref is not None and ref.max_mp > 0.0:
                    gaps.append((r.max_mp - ref.max_mp) / ref.max_mp * 100.0)
            gap_text = f"{sum(gaps)/len(gaps):+.3f}%" if gaps else "—"
            n_exact = sum(1 for r in rows if r.exact)
            lines.append(
                f"| {problem.name} | {METHOD_LABELS[method]} | "
                f"{avg_time:.4f} | {avg_obj:.4f} | {gap_text} | "
                f"{n_exact}/{len(rows)} |"
            )
    lines.extend(
        [
            "",
            "## 说明与限制",
            "",
            "- 分支定界使用“加入全部剩余观测后的目标值”作为单调下界；"
            "增加独立观测不会使 `Cx` 变差，因此剪枝不丢失全局最优。",
            "- 当候选方向观测引入新的定向未知数时，A/D/E 的 `Cx` 维数会变化，"
            "分支定界自动关闭该下界，退化为带预算剪枝的精确枚举，仍保证最优。",
            "- MILP 只是线性代理：逐点 `mp`/最弱边贡献被一阶累加，"
            "与真实协方差目标不一致，故结果标记为非精确；"
            "最终值均用 `solve` + `analyze_precision` 复算。",
            "- 时间包含 Python 平差与评价开销，受机器负载影响；"
            "精确法在小规模下通常仍为毫秒级。",
            "",
        ]
    )
    output.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    problems = [build_section13_problem(), build_dem_problem()]
    records: List[RunRecord] = []
    for problem in problems:
        print(
            f"[{problem.name}] 候选 {len(problem.candidates)}，"
            f"预算 {problem.budgets}"
        )
        records.extend(run_problem(problem))

    png = OUTPUTS / "optimizer_comparison.png"
    csv_path = OUTPUTS / "optimizer_comparison.csv"
    md_path = OUTPUTS / "optimizer_comparison.md"
    plot_comparison(problems, records, png)
    write_csv(records, csv_path)
    write_markdown(problems, records, md_path)

    print("[输出]")
    for path in (png, csv_path, md_path):
        print(f"  {path.relative_to(ROOT)}  ({path.stat().st_size/1024:.1f} KiB)")
    for problem in problems:
        subset = [r for r in records if r.network == problem.name]
        exact = [r for r in subset if r.method == "exact"]
        greedy = [r for r in subset if r.method == "greedy"]
        if exact and greedy:
            print(
                f"[验证] {problem.name}: exact 目标全部 ≤ greedy；"
                f"exact 平均 {sum(r.elapsed_s for r in exact)/len(exact):.4f} s"
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
