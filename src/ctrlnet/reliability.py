"""可靠性指标：多余观测分量、内部/外部可靠性、w 检验。"""

from __future__ import annotations

from dataclasses import dataclass, field
from math import isfinite, sqrt
from statistics import NormalDist
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

import numpy as np

from .adjustment import AdjustmentResult
from .design import ObservationBlock
from .model import Distance, Direction, Angle, GnssBaseline2D, Network, Scenario, point_name


def noncentrality(alpha: float = 0.05, power: float = 0.80) -> float:
    """λ0 = (z_{1-α/2} + z_{power})²。

    α 为双侧显著性水平，power 为检验功效。α=0.05、power=0.80 时约 7.849。
    """
    alpha = float(alpha)
    power = float(power)
    if not (0.0 < alpha < 1.0):
        raise ValueError("alpha 必须满足 0 < alpha < 1")
    if not (0.0 < power < 1.0):
        raise ValueError("power 必须满足 0 < power < 1")
    nd = NormalDist()
    z_alpha = nd.inv_cdf(1.0 - alpha / 2.0)
    z_power = nd.inv_cdf(power)
    return (z_alpha + z_power) ** 2


# 设计回归采用惯用的三位小数 λ0=7.849（α=0.05，power=0.80）；
# noncentrality() 仍按 NormalDist 精确计算，供自定义显著性/功效使用。
LAMBDA0_DEFAULT = round(noncentrality(0.05, 0.80), 3)


@dataclass
class ReliabilityRecord:
    """单条观测的可靠性结果。

    r_i 为多余观测分量；GNSS 基线的 ``r_i=sum(r_components)``。
    mdb 在内部单位中保存（距离/基线为米，方向/角度为弧度），
    ``mdb_display`` 按观测类型转成 mm 或角秒。
    """

    label: str
    kind: str
    sigma: float
    r_i: float
    r_components: np.ndarray
    mdb: float
    mdb_components: np.ndarray
    mdb_unit: str
    external_max: float
    external_max_norm: float
    external_point: Optional[str]
    external_by_point: Dict[str, np.ndarray]
    external_dx: np.ndarray
    undetectable: bool = False
    observation: Any = None
    rows: Tuple[int, ...] = ()

    @property
    def r(self) -> float:
        return self.r_i

    @property
    def mdb_mm(self) -> Optional[float]:
        if self.undetectable or not isfinite(self.mdb):
            return float("inf")
        return self.mdb * 1000.0

    @property
    def mdb_display(self) -> float:
        if self.mdb_unit == "mm":
            return self.mdb * 1000.0
        if self.mdb_unit == "arcsec":
            return self.mdb * (180.0 * 3600.0 / np.pi)
        return self.mdb

    @property
    def external_max_mm(self) -> float:
        return self.external_max * 1000.0

    @property
    def external_max_component_mm(self) -> float:
        return self.external_max * 1000.0

    @property
    def external_max_norm_mm(self) -> float:
        return self.external_max_norm * 1000.0

    @property
    def mdb_sigma_ratio(self) -> float:
        """MDB_i / σ_i，即内部可靠性倍数。"""
        return self.mdb / self.sigma if self.sigma > 0.0 else float("inf")


@dataclass
class ReliabilityResult:
    result: AdjustmentResult
    records: List[ReliabilityRecord]
    lambda0_value: float
    alpha: float
    power: float
    trace_r: float
    expected_redundancy: int
    include_constraints: bool = False
    Qv: Optional[np.ndarray] = None
    R: Optional[np.ndarray] = None

    @property
    def rows(self) -> List[ReliabilityRecord]:
        return self.records

    @property
    def by_label(self) -> Dict[str, ReliabilityRecord]:
        return {row.label: row for row in self.records}

    @property
    def redundancy(self) -> int:
        return self.expected_redundancy

    @property
    def sum_r(self) -> float:
        return sum((row.r_i for row in self.records), 0.0)

    @property
    def min_r(self) -> float:
        return min((row.r_i for row in self.records), default=float("inf"))

    @property
    def max_mdb(self) -> float:
        return max((row.mdb for row in self.records), default=0.0)

    def __getitem__(self, label: str) -> ReliabilityRecord:
        return self.by_label[label]


def _display_unit(kind: str) -> str:
    if kind in ("distance", "gnss", "constraint", "leveling", "height", "trig_height"):
        return "mm"
    if kind in ("angle", "direction"):
        return "arcsec"
    return "m"


def _group_sigma(block: ObservationBlock, Ql: np.ndarray) -> float:
    if block.row_count == 1:
        return float(sqrt(max(float(Ql[block.row_start, block.row_start]), 0.0)))
    return float(sqrt(max(float(np.trace(Ql[block.row_slice, block.row_slice])) / block.row_count, 0.0)))


def _external_by_point(
    result: AdjustmentResult, dx: np.ndarray
) -> Tuple[Dict[str, np.ndarray], float, float, Optional[str]]:
    by_point: Dict[str, np.ndarray] = {}
    best_norm = 0.0
    best_comp = 0.0
    best_name: Optional[str] = None
    for name, columns in result.index.point_columns.items():
        cols = tuple(int(c) for c in columns)
        vec = np.asarray([dx[c] for c in cols], dtype=float)
        by_point[name] = vec
        norm = float(np.linalg.norm(vec))
        comp = float(np.max(np.abs(vec))) if vec.size else 0.0
        if norm > best_norm:
            best_norm = norm
            best_name = name
        if comp > best_comp:
            best_comp = comp
    return by_point, best_norm, best_comp, best_name


def analyze_reliability(
    result: Any,
    alpha: float = 0.05,
    power: float = 0.80,
    *,
    lambda0_value: Optional[float] = None,
    include_constraints: bool = False,
) -> ReliabilityResult:
    """计算 r_i、MDB 与外部可靠性。

    对独立观测，``r_i = 1 - h_ii``（h 为白化设计矩阵的帽子矩阵对角元）；
    对 GNSS 2x2 基线，``r_i`` 取块内对角元之和。默认 α=0.05、power=0.80
    使用 λ0=7.849；其它 α/power 或显式 lambda0_value 时按公式计算。
    """
    if isinstance(result, Scenario):
        result = result.solve()
    elif isinstance(result, Network):
        from .adjustment import solve

        result = solve(result)
    required = ("Ql", "A", "Cx", "redundancy", "n_params", "design", "index")
    if not isinstance(result, AdjustmentResult) and not all(
        hasattr(result, name) for name in required
    ):
        raise TypeError("需要 AdjustmentResult、Scenario、Network 或兼容的平差结果")

    if lambda0_value is not None:
        lam = float(lambda0_value)
    elif abs(float(alpha) - 0.05) < 1e-15 and abs(float(power) - 0.80) < 1e-15:
        lam = LAMBDA0_DEFAULT
    else:
        lam = noncentrality(alpha, power)
    if not isfinite(lam) or lam <= 0.0:
        raise ValueError("lambda0 必须为正的有限值")

    Ql = np.asarray(result.Ql, dtype=float)
    A = np.asarray(result.A, dtype=float)
    Cx = np.asarray(result.Cx, dtype=float)
    if Ql.shape[0] == 0:
        qv = np.zeros((0, 0), dtype=float)
        return ReliabilityResult(
            result, [], lam, alpha, power, 0.0, result.redundancy, False, qv, qv
        )

    Ql_inv = np.linalg.inv(Ql)
    Qv = Ql - A @ Cx @ A.T
    Qv = 0.5 * (Qv + Qv.T)
    R = Qv @ Ql_inv
    r_diag = np.diag(R)
    K = Ql_inv @ Qv @ Ql_inv
    K = 0.5 * (K + K.T)
    k_diag = np.diag(K)

    # 每个观测共用同一参数影响矩阵，避免循环内重复矩阵乘法。
    influence = Cx @ A.T @ Ql_inv
    records: List[ReliabilityRecord] = []
    source_blocks = (
        result.design.blocks if include_constraints else result.design.observation_blocks
    )
    for block in source_blocks:
        rows = block.rows
        r_comp = np.array([r_diag[i] for i in rows], dtype=float)
        r_i = float(np.sum(r_comp))
        mdb_comp = np.empty(len(rows), dtype=float)
        undetectable = False
        for j, i in enumerate(rows):
            kk = float(k_diag[i])
            if not isfinite(kk) or kk <= 1e-30 or float(r_comp[j]) <= 1e-12:
                mdb_comp[j] = float("inf")
                undetectable = True
            else:
                mdb_comp[j] = sqrt(lam / kk)
        mdb = float(np.max(mdb_comp))

        # 外部可靠性：单条粗差未检出时对参数的影响。
        best_norm = 0.0
        best_comp = 0.0
        best_name: Optional[str] = None
        best_dx = np.zeros(result.n_params, dtype=float)
        best_by_point: Dict[str, np.ndarray] = {}
        for j, i in enumerate(rows):
            if not isfinite(mdb_comp[j]):
                continue
            dx = influence[:, i] * mdb_comp[j]
            by_point, norm, comp, name = _external_by_point(result, dx)
            if norm > best_norm:
                best_norm = norm
                best_comp = comp
                best_name = name
                best_dx = dx
                best_by_point = by_point
            elif norm == best_norm and comp > best_comp:
                best_comp = comp
                best_name = name
                best_dx = dx
                best_by_point = by_point

        records.append(
            ReliabilityRecord(
                label=block.label,
                kind=block.kind,
                sigma=_group_sigma(block, Ql),
                r_i=r_i,
                r_components=r_comp,
                mdb=mdb,
                mdb_components=mdb_comp,
                mdb_unit=_display_unit(block.kind),
                external_max=best_comp,
                external_max_norm=best_norm,
                external_point=best_name,
                external_by_point=best_by_point,
                external_dx=best_dx,
                undetectable=undetectable,
                observation=block.observation,
                rows=tuple(rows),
            )
        )

    trace_r = float(np.trace(R))
    return ReliabilityResult(
        result=result,
        records=records,
        lambda0_value=lam,
        alpha=float(alpha),
        power=float(power),
        trace_r=trace_r,
        expected_redundancy=result.redundancy,
        include_constraints=include_constraints,
        Qv=Qv,
        R=R,
    )


def redundancy_numbers(result: Any, **kwargs: Any) -> Dict[str, float]:
    rel = analyze_reliability(result, **kwargs)
    return {row.label: row.r_i for row in rel.records}


def mdb_values(result: Any, **kwargs: Any) -> Dict[str, float]:
    rel = analyze_reliability(result, **kwargs)
    return {row.label: row.mdb for row in rel.records}


def w_test(result: Any, residuals: Sequence[float]) -> np.ndarray:
    """给定原始残差 v（长度等于设计矩阵行数），返回逐行 w 检验量。"""
    if isinstance(result, (Scenario, Network)):
        from .adjustment import solve

        result = solve(result)
    if not isinstance(result, AdjustmentResult):
        raise TypeError("需要 AdjustmentResult")
    v = np.asarray(residuals, dtype=float).reshape(-1)
    m = result.n_rows
    if v.size != m:
        raise ValueError(f"残差长度应为 {m}，收到 {v.size}")
    Ql_inv = np.linalg.inv(result.Ql)
    Qv = result.Ql - result.A @ result.Cx @ result.A.T
    Qv = 0.5 * (Qv + Qv.T)
    Kdiag = np.diag(Ql_inv @ Qv @ Ql_inv)
    u = Ql_inv @ v
    denom = np.sqrt(np.maximum(Kdiag, 0.0))
    out = np.full(m, np.inf, dtype=float)
    good = denom > 0.0
    out[good] = u[good] / denom[good]
    return out


def w_test_statistics(result: Any, residuals: Sequence[float]) -> np.ndarray:
    return w_test(result, residuals)


__all__ = [
    "LAMBDA0_DEFAULT",
    "noncentrality",
    "ReliabilityRecord",
    "ReliabilityResult",
    "analyze_reliability",
    "redundancy_numbers",
    "mdb_values",
    "w_test",
    "w_test_statistics",
]


# 常用别名
analyze = analyze_reliability
reliability = analyze_reliability

lambda0 = noncentrality
