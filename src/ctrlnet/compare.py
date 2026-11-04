"""两个设计方案的可比性检查与对比表。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

from .adjustment import AdjustmentResult, solve
from .model import Network, Scenario
from .precision import PrecisionResult, analyze_precision
from .reliability import ReliabilityResult, analyze_reliability


@dataclass
class PlanMetrics:
    name: str
    result: AdjustmentResult
    precision: PrecisionResult
    reliability: Optional[ReliabilityResult] = None

    @property
    def n_observations(self) -> int:
        return self.result.n_observations

    @property
    def n_rows(self) -> int:
        return self.result.n_rows

    @property
    def redundancy(self) -> int:
        return self.result.redundancy

    @property
    def max_mp(self) -> float:
        return self.precision.max_mp

    @property
    def worst_relative(self) -> float:
        return self.precision.worst_relative

    @property
    def min_r(self) -> Optional[float]:
        return self.reliability.min_r if self.reliability is not None else None


@dataclass
class PointComparison:
    name: str
    base_mp: float
    cand_mp: float
    base_a: float
    cand_a: float
    base_b: float
    cand_b: float
    base_sigma_E: float
    cand_sigma_E: float
    base_sigma_N: float
    cand_sigma_N: float

    @property
    def delta_mp(self) -> float:
        return self.cand_mp - self.base_mp


@dataclass
class EdgeComparison:
    label: str
    length: float
    base_sigma_s: float
    cand_sigma_s: float
    base_ratio: str
    cand_ratio: str

    @property
    def delta_sigma_s(self) -> float:
        return self.cand_sigma_s - self.base_sigma_s


@dataclass
class Comparison:
    base: PlanMetrics
    candidate: PlanMetrics
    point_rows: List[PointComparison]
    edge_rows: List[EdgeComparison]
    summary_rows: List[Tuple[str, str, str, str]] = field(default_factory=list)

    def to_text(self) -> str:
        b, c = self.base.name, self.candidate.name
        lines: List[str] = []
        lines.append(f"方案对比：{b} vs {c}")
        lines.append("")
        lines.append(f"| 指标 | {b} | {c} | 变化 |")
        lines.append("|---|---:|---:|---:|")
        for row in self.summary_rows:
            lines.append("| " + " | ".join(row) + " |")
        lines.append("")
        lines.append(f"| 点 | {b} mp/mm | {c} mp/mm | 变化/mm | {b} a/b/mm | {c} a/b/mm |")
        lines.append("|---|---:|---:|---:|---:|---:|")
        for row in self.point_rows:
            lines.append(
                "| {n} | {bm:.3f} | {cm:.3f} | {dm:+.3f} | {ba:.3f}/{bb:.3f} | "
                "{ca:.3f}/{cb:.3f} |".format(
                    n=row.name,
                    bm=row.base_mp * 1000.0,
                    cm=row.cand_mp * 1000.0,
                    dm=row.delta_mp * 1000.0,
                    ba=row.base_a * 1000.0,
                    bb=row.base_b * 1000.0,
                    ca=row.cand_a * 1000.0,
                    cb=row.cand_b * 1000.0,
                )
            )
        lines.append("")
        lines.append(f"| 边 | 边长/m | {b} σs/mm | {b} 相对精度 | {c} σs/mm | {c} 相对精度 |")
        lines.append("|---|---:|---:|---:|---:|---:|")
        for row in self.edge_rows:
            lines.append(
                "| {lab} | {s:.3f} | {bs:.3f} | {br} | {cs:.3f} | {cr} |".format(
                    lab=row.label,
                    s=row.length,
                    bs=row.base_sigma_s * 1000.0,
                    br=row.base_ratio,
                    cs=row.cand_sigma_s * 1000.0,
                    cr=row.cand_ratio,
                )
            )
        return "\n".join(lines)


def _coerce(obj: Any, name: Optional[str] = None, datum: Any = None) -> PlanMetrics:
    if isinstance(obj, PlanMetrics):
        return obj
    if isinstance(obj, AdjustmentResult):
        result = obj
        label = name or "方案"
    elif isinstance(obj, Scenario):
        result = obj.solve()
        label = name or obj.name
    elif isinstance(obj, Network):
        result = solve(obj, datum=datum)
        label = name or obj.name
    else:
        raise TypeError("需要 Scenario、Network 或 AdjustmentResult")
    precision = analyze_precision(result)
    try:
        reliability = analyze_reliability(result)
    except Exception:
        reliability = None
    return PlanMetrics(label, result, precision, reliability)


def compare(
    base: Any,
    candidate: Any,
    base_name: Optional[str] = None,
    candidate_name: Optional[str] = None,
    datum: Any = None,
) -> Comparison:
    """比较两个方案的点位、椭圆、边精度、冗余数与工作量。"""
    b = _coerce(base, base_name, datum)
    c = _coerce(candidate, candidate_name, datum)
    if b.name == c.name and base_name is None and candidate_name is None:
        b.name, c.name = "基准方案", "候选方案"

    point_rows: List[PointComparison] = []
    for name in b.precision.point_order:
        if name not in c.precision.points:
            continue
        pb = b.precision.points[name]
        pc = c.precision.points[name]
        point_rows.append(
            PointComparison(
                name,
                pb.mp,
                pc.mp,
                pb.ellipse.standard_major,
                pc.ellipse.standard_major,
                pb.ellipse.standard_minor,
                pc.ellipse.standard_minor,
                pb.sigma_E,
                pc.sigma_E,
                pb.sigma_N,
                pc.sigma_N,
            )
        )

    edge_labels = [k for k in b.precision.edge_order if k in c.precision.edges]
    edge_rows: List[EdgeComparison] = []
    for key in edge_labels:
        eb = b.precision.edges[key]
        ec = c.precision.edges[key]
        edge_rows.append(
            EdgeComparison(
                key,
                eb.length,
                eb.sigma_s,
                ec.sigma_s,
                eb.ratio_text,
                ec.ratio_text,
            )
        )

    def ratio_text(value: float) -> str:
        if value <= 0.0:
            return "—"
        return f"1:{round(1.0 / value):d}"

    summary: List[Tuple[str, str, str, str]] = [
        ("观测数（工作量）", str(b.n_observations), str(c.n_observations), f"{c.n_observations - b.n_observations:+d}"),
        ("冗余数", str(b.redundancy), str(c.redundancy), f"{c.redundancy - b.redundancy:+d}"),
        (
            "最弱点 mp/mm",
            f"{b.max_mp * 1000.0:.3f}",
            f"{c.max_mp * 1000.0:.3f}",
            f"{(c.max_mp - b.max_mp) * 1000.0:+.3f}",
        ),
        (
            "最弱边 σs/s",
            ratio_text(b.worst_relative),
            ratio_text(c.worst_relative),
            f"{(c.worst_relative - b.worst_relative):+.3e}",
        ),
        (
            "最弱点",
            ",".join(b.precision.weakest_points) or "—",
            ",".join(c.precision.weakest_points) or "—",
            "",
        ),
        (
            "最弱边",
            ",".join(b.precision.weakest_edges) or "—",
            ",".join(c.precision.weakest_edges) or "—",
            "",
        ),
        (
            "最小 r_i",
            f"{b.min_r:.4f}" if b.min_r is not None else "—",
            f"{c.min_r:.4f}" if c.min_r is not None else "—",
            (
                f"{c.min_r - b.min_r:+.4f}"
                if b.min_r is not None and c.min_r is not None
                else ""
            ),
        ),
    ]
    return Comparison(b, c, point_rows, edge_rows, summary)


def compare_scenarios(
    base: Any,
    candidate: Any,
    base_name: Optional[str] = None,
    candidate_name: Optional[str] = None,
) -> Comparison:
    return compare(base, candidate, base_name, candidate_name)


__all__ = [
    "PlanMetrics",
    "PointComparison",
    "EdgeComparison",
    "Comparison",
    "compare",
    "compare_scenarios",
]


compare_networks = compare
