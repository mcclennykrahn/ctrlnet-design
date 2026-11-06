"""精度指标：点位中误差、误差椭圆、边长相对精度。"""

from __future__ import annotations

from dataclasses import dataclass, field
from math import atan2, degrees, isfinite, log, pi, sqrt
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

import numpy as np

from .adjustment import AdjustmentResult
from .model import Distance, Network, Scenario, point_name

# 95% 二维置信椭圆系数：sqrt(chi2_2(0.95)) = sqrt(-2 ln 0.05)
CHI2_2_95 = -2.0 * log(0.05)
K95 = sqrt(CHI2_2_95)  # ≈ 2.44774683


def chi2_2_quantile(p: float) -> float:
    """二维卡方分布分位数（自由度为 2）。"""
    p = float(p)
    if not (0.0 < p < 1.0):
        raise ValueError("置信水平必须满足 0 < p < 1")
    return -2.0 * log(1.0 - p)


def confidence_scale(confidence: Optional[float]) -> float:
    """标准椭圆系数 1；置信水平 p 时返回 sqrt(chi2_2(p))。"""
    if confidence is None or confidence is False:
        return 1.0
    if isinstance(confidence, str) and confidence.lower() in ("standard", "std", "标准"):
        return 1.0
    return sqrt(chi2_2_quantile(float(confidence)))


@dataclass
class ErrorEllipse:
    """二维误差椭圆。

    ``a``/``b`` 为请求置信水平下的半轴（默认标准椭圆，置信水平约 39.35%）；
    ``standard_major``/``standard_minor`` 始终保存标准半轴。方位角从北起顺时针，
    归化到 [0, 180) 度。
    """

    a: float
    b: float
    azimuth_deg: float
    standard_major: float
    standard_minor: float
    confidence: Optional[float] = None
    scale: float = 1.0
    unstable: bool = False

    @property
    def semi_major(self) -> float:
        return self.a

    @property
    def semi_minor(self) -> float:
        return self.b

    @property
    def major(self) -> float:
        return self.a

    @property
    def minor(self) -> float:
        return self.b

    @property
    def azimuth(self) -> float:
        return self.azimuth_deg

    @property
    def standard_a(self) -> float:
        return self.standard_major

    @property
    def standard_b(self) -> float:
        return self.standard_minor

    def scaled(self, factor: float) -> "ErrorEllipse":
        return ErrorEllipse(
            a=self.standard_major * factor,
            b=self.standard_minor * factor,
            azimuth_deg=self.azimuth_deg,
            standard_major=self.standard_major,
            standard_minor=self.standard_minor,
            confidence=self.confidence,
            scale=factor,
            unstable=self.unstable,
        )


@dataclass
class PointPrecision:
    name: str
    sigma_E: float
    sigma_N: float
    mp: float
    ellipse: ErrorEllipse
    fixed: bool = False
    role: str = "unknown"
    is_weakest: bool = False

    @property
    def sigma_E_mm(self) -> float:
        return self.sigma_E * 1000.0

    @property
    def sigma_N_mm(self) -> float:
        return self.sigma_N * 1000.0

    @property
    def mp_mm(self) -> float:
        return self.mp * 1000.0


@dataclass
class EdgePrecision:
    frm: str
    to: str
    length: float
    sigma_s: float
    relative: float
    ratio_denominator: Optional[int]
    is_weakest: bool = False

    @property
    def label(self) -> str:
        return f"{self.frm}{self.to}"

    @property
    def sigma_s_mm(self) -> float:
        return self.sigma_s * 1000.0

    @property
    def ratio_text(self) -> str:
        if self.ratio_denominator is None:
            return "1:∞"
        return f"1:{self.ratio_denominator}"

    @property
    def relative_accuracy(self) -> str:
        return self.ratio_text


@dataclass
class PrecisionResult:
    result: AdjustmentResult
    points: Dict[str, PointPrecision]
    edges: Dict[str, EdgePrecision]
    point_order: List[str]
    edge_order: List[str]
    weakest_point: Optional[str] = None
    weakest_points: List[str] = field(default_factory=list)
    weakest_edge: Optional[str] = None
    weakest_edges: List[str] = field(default_factory=list)
    confidence: Optional[float] = None

    def point(self, ref: Any) -> PointPrecision:
        return self.points[point_name(ref)]

    def edge(self, frm: Any, to: Any) -> EdgePrecision:
        return self.edges[f"{point_name(frm)}{point_name(to)}"]

    @property
    def max_mp(self) -> float:
        vals = [p.mp for p in self.points.values() if not p.fixed]
        return max(vals) if vals else 0.0

    @property
    def worst_relative(self) -> float:
        vals = [e.relative for e in self.edges.values()]
        return max(vals) if vals else 0.0

    @property
    def min_r(self) -> Optional[float]:
        """便捷入口；可靠性分析独立计算。"""
        return self.result.metadata.get("min_r")


def _ellipse_from_cov(cov: np.ndarray, confidence: Optional[float]) -> ErrorEllipse:
    C = np.asarray(cov, dtype=float)
    if C.shape != (2, 2):
        raise ValueError("协方差必须是 2x2")
    C = 0.5 * (C + C.T)
    if not np.all(np.isfinite(C)):
        raise ValueError("协方差含非有限值")
    vals, vecs = np.linalg.eigh(C)
    order = np.argsort(vals)[::-1]
    vals = vals[order]
    vecs = vecs[:, order]
    lam1 = max(float(vals[0]), 0.0)
    lam2 = max(float(vals[1]), 0.0)
    a0, b0 = sqrt(lam1), sqrt(lam2)
    v = vecs[:, 0]
    azimuth = degrees(atan2(float(v[0]), float(v[1]))) % 180.0
    unstable = bool(lam1 > 0.0 and abs(lam1 - lam2) / lam1 < 1e-3)
    if lam1 <= 0.0:
        azimuth = 0.0
    scale = confidence_scale(confidence)
    return ErrorEllipse(
        a=a0 * scale,
        b=b0 * scale,
        azimuth_deg=azimuth,
        standard_major=a0,
        standard_minor=b0,
        confidence=None if scale == 1.0 and confidence is None else confidence,
        scale=scale,
        unstable=unstable,
    )


# 公开的椭圆构造函数，供 GNSS 三维/其他模块复用。
ellipse_from_cov = _ellipse_from_cov


def _point_precision(
    result: AdjustmentResult, point: Any, confidence: Optional[float]
) -> PointPrecision:
    p = result.network.point(point)
    C = result.point_covariance(p.name)
    ellipse = _ellipse_from_cov(C, confidence)
    sigma_E = sqrt(max(float(C[0, 0]), 0.0))
    sigma_N = sqrt(max(float(C[1, 1]), 0.0))
    mp = sqrt(sigma_E * sigma_E + sigma_N * sigma_N)
    return PointPrecision(
        name=p.name,
        sigma_E=sigma_E,
        sigma_N=sigma_N,
        mp=mp,
        ellipse=ellipse,
        fixed=p.fixed,
        role=p.role,
    )


def edge_gradient(result: AdjustmentResult, frm: Any, to: Any) -> np.ndarray:
    """边长对全部参数的梯度，只在两端点坐标列非零。"""
    f = result.network.point(frm)
    t = result.network.point(to)
    dE, dN = t.E - f.E, t.N - f.N
    s = sqrt(dE * dE + dN * dN)
    g = np.zeros(result.n_params, dtype=float)
    if s <= 0.0:
        return g
    for name, sign in ((f.name, -1.0), (t.name, 1.0)):
        cols = result.index.point_columns.get(name)
        if cols is not None:
            g[cols[0]] += sign * dE / s
            g[cols[1]] += sign * dN / s
    return g


def _edge_precision(
    result: AdjustmentResult, frm: Any, to: Any
) -> EdgePrecision:
    f = result.network.point(frm)
    t = result.network.point(to)
    length = sqrt((t.E - f.E) ** 2 + (t.N - f.N) ** 2)
    g = edge_gradient(result, f.name, t.name)
    columns = np.flatnonzero(g)
    local = g[columns]
    var = float(local @ result.Cx[np.ix_(columns, columns)] @ local)
    sigma_s = sqrt(max(var, 0.0))
    relative = sigma_s / length if length > 0.0 else float("inf")
    denom = int(round(length / sigma_s)) if sigma_s > 0.0 and length > 0.0 else None
    return EdgePrecision(
        frm=f.name,
        to=t.name,
        length=length,
        sigma_s=sigma_s,
        relative=relative,
        ratio_denominator=denom,
    )


def _normalize_edges(
    network: Network, edges: Optional[Iterable[Any]]
) -> List[Tuple[str, str]]:
    if edges is None:
        return network.distance_edges()
    out: List[Tuple[str, str]] = []
    for item in edges:
        if isinstance(item, Distance):
            pair = (item.frm, item.to)
        elif isinstance(item, str):
            if len(item) < 2:
                raise ValueError(f"无法解析边标识：{item!r}")
            pair = (item[:-1], item[-1])
        elif isinstance(item, (tuple, list)) and len(item) == 2:
            pair = (point_name(item[0]), point_name(item[1]))
        else:
            try:
                frm, to = item
                pair = (point_name(frm), point_name(to))
            except Exception as exc:  # pragma: no cover
                raise TypeError(f"无法解析边：{item!r}") from exc
        out.append((pair[0], pair[1]))
    return out


def analyze_precision(
    result: Any,
    edges: Optional[Iterable[Any]] = None,
    confidence: Optional[float] = None,
) -> PrecisionResult:
    """计算全部点精度、误差椭圆与指定边的相对精度。

    edges 为空时使用网中所有距离观测边（按观测顺序去重）。
    """
    if isinstance(result, Scenario):
        result = result.solve()
    elif isinstance(result, Network):
        from .adjustment import solve

        result = solve(result)
    if not isinstance(result, AdjustmentResult):
        raise TypeError("需要 AdjustmentResult、Scenario 或 Network")

    points: Dict[str, PointPrecision] = {}
    for p in result.network.points:
        points[p.name] = _point_precision(result, p.name, confidence)

    unknown = [p.name for p in result.network.points if not p.fixed]
    if unknown:
        max_mp = max(points[n].mp for n in unknown)
        tol = max(1e-15, 1e-9 * max_mp)
        weakest = [n for n in unknown if max_mp - points[n].mp <= tol]
    else:
        weakest = []
    for n in weakest:
        points[n].is_weakest = True

    edge_pairs = _normalize_edges(result.network, edges)
    edge_map: Dict[str, EdgePrecision] = {}
    edge_order: List[str] = []
    for frm, to in edge_pairs:
        e = _edge_precision(result, frm, to)
        key = e.label
        # 同一条边若以反向出现，按第一次出现的键保存
        if key not in edge_map:
            edge_order.append(key)
        edge_map[key] = e

    if edge_map:
        worst = max(e.relative for e in edge_map.values())
        tol = max(1e-18, 1e-9 * abs(worst))
        weakest_e = [k for k, e in edge_map.items() if abs(worst - e.relative) <= tol]
        for k in weakest_e:
            edge_map[k].is_weakest = True
    else:
        weakest_e = []

    return PrecisionResult(
        result=result,
        points=points,
        edges=edge_map,
        point_order=[p.name for p in result.network.points],
        edge_order=edge_order,
        weakest_point=weakest[0] if weakest else None,
        weakest_points=weakest,
        weakest_edge=weakest_e[0] if weakest_e else None,
        weakest_edges=weakest_e,
        confidence=confidence,
    )


def point_precision(
    result: Any, ref: Any, confidence: Optional[float] = None
) -> PointPrecision:
    if not isinstance(result, AdjustmentResult):
        result = analyze_precision(result).result
    return _point_precision(result, ref, confidence)


def point_precisions(
    result: Any, confidence: Optional[float] = None
) -> Dict[str, PointPrecision]:
    return analyze_precision(result, confidence=confidence).points


def edge_precision(
    result: Any, frm: Any, to: Any
) -> EdgePrecision:
    if not isinstance(result, AdjustmentResult):
        result = analyze_precision(result).result
    return _edge_precision(result, frm, to)


def edge_precisions(
    result: Any, edges: Optional[Iterable[Any]] = None
) -> Dict[str, EdgePrecision]:
    return analyze_precision(result, edges=edges).edges


def weakest_point(result: Any) -> Optional[str]:
    return analyze_precision(result).weakest_point


def weakest_edge(result: Any) -> Optional[str]:
    return analyze_precision(result).weakest_edge


__all__ = [
    "CHI2_2_95",
    "K95",
    "chi2_2_quantile",
    "confidence_scale",
    "ErrorEllipse",
    "PointPrecision",
    "EdgePrecision",
    "PrecisionResult",
    "analyze_precision",
    "point_precision",
    "point_precisions",
    "edge_precision",
    "edge_precisions",
    "edge_gradient",
    "ellipse_from_cov",
    "weakest_point",
    "weakest_edge",
]


# 常用别名
compute_precision = analyze_precision
