"""中文文本报告格式化。"""

from __future__ import annotations

from typing import Any, List, Optional

from .adjustment import AdjustmentResult
from .model import Network, Scenario
from .precision import PrecisionResult, analyze_precision
from .reliability import ReliabilityResult, analyze_reliability


def _coerce(result: Any) -> AdjustmentResult:
    if isinstance(result, AdjustmentResult):
        return result
    if isinstance(result, Scenario):
        return result.solve()
    if isinstance(result, Network):
        from .adjustment import solve

        return solve(result)
    raise TypeError("需要 AdjustmentResult、Scenario 或 Network")


def format_precision_table(
    precision: PrecisionResult, confidence: Optional[float] = None
) -> str:
    title = "标准椭圆" if confidence is None else f"{confidence:g} 置信椭圆"
    lines = [
        f"点位精度（单位 mm，椭圆为{title}；长轴方位从北起顺时针）",
        "| 点 | 类型 | σE/mm | σN/mm | mp/mm | 椭圆a/mm | 椭圆b/mm | 长轴方位/° |",
        "|---|---|---:|---:|---:|---:|---:|---:|",
    ]
    for name in precision.point_order:
        p = precision.points[name]
        role = "固定" if p.fixed else ("加权" if p.role == "constrained" else "待定")
        mark = " *" if p.is_weakest and not p.fixed else ""
        lines.append(
            "| {n}{m} | {r} | {se:.3f} | {sn:.3f} | {mp:.3f} | {a:.3f} | "
            "{b:.3f} | {az:.3f} |".format(
                n=name,
                m=mark,
                r=role,
                se=p.sigma_E_mm,
                sn=p.sigma_N_mm,
                mp=p.mp_mm,
                a=p.ellipse.a * 1000.0,
                b=p.ellipse.b * 1000.0,
                az=p.ellipse.azimuth_deg,
            )
        )
    return "\n".join(lines)


def format_edge_table(precision: PrecisionResult) -> str:
    lines = [
        "边长相对精度",
        "| 边 | 边长/m | σs/mm | 相对精度 |",
        "|---|---:|---:|---:|",
    ]
    for key in precision.edge_order:
        e = precision.edges[key]
        mark = " *" if e.is_weakest else ""
        lines.append(
            f"| {e.label}{mark} | {e.length:.3f} | {e.sigma_s_mm:.3f} | {e.ratio_text} |"
        )
    return "\n".join(lines)


def format_reliability_table(reliability: ReliabilityResult) -> str:
    lines = [
        "可靠性（λ0={:.6f}，α={:g}，power={:g}）".format(
            reliability.lambda0_value, reliability.alpha, reliability.power
        ),
        "| 观测 | σ | r_i | MDB | 外部最大影响/mm | 影响点 |",
        "|---|---:|---:|---:|---:|---|",
    ]
    for row in reliability.records:
        if row.kind in ("distance", "gnss", "constraint"):
            sigma = f"{row.sigma * 1000.0:.3f} mm"
        elif row.kind in ("angle", "direction"):
            sigma = f"{row.sigma * (180.0 * 3600.0 / 3.141592653589793):.3f}″"
        else:
            sigma = f"{row.sigma:.6g}"
        if row.mdb_unit == "mm":
            mdb = f"{row.mdb * 1000.0:.3f} mm" if row.mdb != float("inf") else "∞"
        elif row.mdb_unit == "arcsec":
            mdb = (
                f"{row.mdb * (180.0 * 3600.0 / 3.141592653589793):.3f}″"
                if row.mdb != float("inf")
                else "∞"
            )
        else:
            mdb = f"{row.mdb:.6g}"
        ext = f"{row.external_max * 1000.0:.3f}"
        lines.append(
            f"| {row.label} | {sigma} | {row.r_i:.4f} | {mdb} | {ext} | "
            f"{row.external_point or '—'} |"
        )
    lines.append(
        f"\nΣr_i = {reliability.trace_r:.6f}（期望冗余数 {reliability.expected_redundancy}）"
    )
    return "\n".join(lines)


def format_report(
    result: Any,
    precision: Optional[PrecisionResult] = None,
    reliability: Optional[ReliabilityResult] = None,
    confidence: Optional[float] = None,
    title: str = "平面控制网精度估算报告（设计态/先验）",
) -> str:
    """把平差、精度与可靠性结果格式化为中文文本表格。"""
    res = _coerce(result)
    if precision is not None and confidence is None:
        confidence = precision.confidence
    prec = precision or analyze_precision(res, confidence=confidence)
    rel = reliability or analyze_reliability(res)

    fixed = [p.name for p in res.network.points if p.fixed]
    weighted = [
        p.name
        for p in res.network.points
        if not p.fixed and (p.sigma_E is not None or p.sigma_N is not None)
    ]
    lines: List[str] = [title, ""]
    lines.append(f"方案：{res.network.name}")
    lines.append(f"基准：{res.metadata.get('datum_summary', res.datum_kind)}")
    if fixed:
        lines.append("固定点：" + "、".join(fixed))
    if weighted:
        lines.append("加权约束点：" + "、".join(weighted))
    lines.append(
        "观测数={}（设计矩阵行数={}），参数数={}，秩={}，冗余数={}，条件数={:.4g}".format(
            res.n_observations,
            res.n_rows,
            res.n_params,
            res.rank,
            res.redundancy,
            res.condition_number,
        )
    )
    if prec.weakest_points:
        lines.append("最弱点：" + "、".join(prec.weakest_points))
    if prec.weakest_edges:
        lines.append("最弱边：" + "、".join(prec.weakest_edges))
    lines.append("")
    lines.append(format_precision_table(prec, confidence=confidence))
    lines.append("")
    lines.append(format_edge_table(prec))
    lines.append("")
    lines.append(format_reliability_table(rel))
    return "\n".join(lines)


def report(*args: Any, **kwargs: Any) -> str:
    return format_report(*args, **kwargs)


__all__ = [
    "format_precision_table",
    "format_edge_table",
    "format_reliability_table",
    "format_report",
    "report",
]
