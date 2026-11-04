"""平差求解核心。

本模块只做设计态（先验）线性化：由设计矩阵 A 和观测协方差 Ql 计算
``Cx = (Aᵀ Ql⁻¹ A)⁺``，并给出秩、条件数、冗余数与零空间诊断。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from math import isfinite
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np

from .datum import (
    Datum,
    FixedDatum,
    MinimalDatum,
    canonical_null_modes,
    normalize_datum,
)
from .design import (
    DesignSystem,
    ParameterIndex,
    build_design,
    build_parameter_index,
    whiten,
)
from .exceptions import (
    AdjustmentError,
    InvalidGeometryError,
    InvalidPrecisionError,
    RankDeficientError,
)
from .model import Network, Point, Scenario, point_name


@dataclass
class AdjustmentResult:
    """设计态平差结果。

    A 为未白化设计矩阵，Aw 为白化后的设计矩阵；Cx 为坐标/定向参数协方差
    （米² 或弧度²），形状为 (u, u)。
    """

    network: Network
    datum: Datum
    index: ParameterIndex
    design: DesignSystem
    A: np.ndarray
    Aw: np.ndarray
    Ql: np.ndarray
    Cx: np.ndarray
    rank: int
    n_rows: int
    n_params: int
    n_observations: int
    redundancy: int
    condition_number: float
    singular_values: np.ndarray
    null_space: np.ndarray
    datum_transform: Optional[np.ndarray] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    # ---- 常用别名 -------------------------------------------------
    @property
    def Qxx(self) -> np.ndarray:
        return self.Cx

    @property
    def Ql_inv(self) -> np.ndarray:
        """观测协方差的逆（即权阵，含约束伪观测行）。"""
        if self.Ql.shape[0] == 0:
            return np.zeros((0, 0), dtype=float)
        return np.linalg.inv(self.Ql)

    @property
    def P(self) -> np.ndarray:
        return self.Ql_inv

    @property
    def n(self) -> int:
        """设计矩阵行数（GNSS 基线按两行计）。"""
        return self.n_rows

    @property
    def m(self) -> int:
        return self.n_rows

    @property
    def u(self) -> int:
        return self.n_params

    @property
    def parameter_names(self) -> List[str]:
        return self.index.names

    @property
    def parameter_order(self) -> List[str]:
        return self.index.point_order

    @property
    def datum_kind(self) -> str:
        return self.datum.kind

    @property
    def sigma0(self) -> float:
        """设计态单位权方差固定为 1。"""
        return 1.0

    def covariance(self, ref: Any) -> np.ndarray:
        return self.point_covariance(ref)

    def point_covariance(self, ref: Any) -> np.ndarray:
        """返回点名对应点的 2x2 协方差（固定点为 0）。"""
        name = point_name(ref)
        point = self.network.point(name)
        if point.fixed or name not in self.index.point_columns:
            return np.zeros((2, 2), dtype=float)
        ie, inn = self.index.point_columns[name]
        return np.array(
            [
                [self.Cx[ie, ie], self.Cx[ie, inn]],
                [self.Cx[inn, ie], self.Cx[inn, inn]],
            ],
            dtype=float,
        )

    def point_mp(self, ref: Any) -> float:
        C = self.point_covariance(ref)
        return float(np.sqrt(max(C[0, 0] + C[1, 1], 0.0)))

    def parameter_covariance(self, name: str) -> float:
        """取参数方差；name 必须与 parameter_names 一致。"""
        if name not in self.index.names:
            raise KeyError(f"未知参数 {name!r}")
        j = self.index.names.index(name)
        return float(self.Cx[j, j])


@dataclass
class RankDiagnosis:
    messages: List[str]
    mode_names: List[str]
    unobserved_points: List[str]

    @property
    def text(self) -> str:
        if not self.messages:
            return "未发现基准缺陷"
        return "；".join(self.messages)


def _validate_rank_tol(rank_tol: Optional[float]) -> Optional[float]:
    if rank_tol is None:
        return None
    rank_tol = float(rank_tol)
    if not isfinite(rank_tol) or rank_tol <= 0.0:
        raise InvalidPrecisionError(f"rank_tol 必须为正的有限值，收到 {rank_tol!r}")
    return rank_tol


def _diagnose_rank(
    network: Network,
    index: ParameterIndex,
    A: np.ndarray,
    rank: int,
    datum: Datum,
) -> RankDiagnosis:
    """由零空间与规范方向给出可读的秩亏原因。"""
    u = index.size
    nullity = u - rank
    messages: List[str] = []
    mode_names: List[str] = []
    unobserved: List[str] = []
    weak: List[str] = []

    for name in index.point_order:
        ie, inn = index.point_columns[name]
        block = A[:, [ie, inn]]
        if not np.any(np.abs(block) > 0.0):
            unobserved.append(name)
            continue
        # 局部秩 < 2 说明该点至少有一个坐标方向未被独立观测约束。
        tol_block = max(float(np.linalg.norm(block, ord=2)), 1.0) * 1e-10
        if np.linalg.matrix_rank(block, tol=tol_block) < 2:
            weak.append(name)
    if unobserved:
        messages.append("点 " + "、".join(unobserved) + " 观测不足（无观测连接）")
    if weak:
        messages.append("点 " + "、".join(weak) + " 观测不足（坐标局部秩<2）")

    origin = None
    if isinstance(datum, MinimalDatum):
        origin = datum.origin_name(network, index)
    modes = canonical_null_modes(network, index, origin=origin)
    # A 的量级；用于判定候选方向是否落在零空间。
    scale = max(float(np.linalg.norm(A, ord=2)) if A.size else 0.0, 1.0)
    for mode_name, g in modes.items():
        ng = float(np.linalg.norm(g))
        if ng <= 1e-14:
            continue
        if float(np.linalg.norm(A @ g)) <= 1e-7 * scale * ng:
            mode_names.append(mode_name)

    # 只有一个固定点时，平移已被该点约束，剩余基准缺陷通常是“绕该点旋转”。
    # canonical_null_modes 的旋转是绕待定点重心的，未必是这里的真实零空间。
    if not any("旋转" in name for name in mode_names):
        for center in network.fixed_points:
            g = np.zeros(u, dtype=float)
            for p in network.points:
                cols = index.point_columns.get(p.name)
                if cols is None:
                    continue
                g[cols[0]] = -(p.N - center.N)
                g[cols[1]] = p.E - center.E
            for station in index.orientation_order:
                if station in index.point_columns:
                    g[index.orientation_columns[station]] = 1.0
            ng = float(np.linalg.norm(g))
            if ng <= 1e-14:
                continue
            if float(np.linalg.norm(A @ g)) <= 1e-7 * scale * ng:
                mode_names.append(f"绕固定点 {center.name} 旋转")
                break

    if mode_names:
        # 尺度缺陷只在没有距离/GNSS 时才是真实基准缺陷；规范方向检查已包含这一点。
        messages.append("缺少基准：" + "、".join(mode_names) + " 未定义")
    elif not unobserved and nullity > 0:
        messages.append("存在局部网形不可解或观测连接不足")
    return RankDiagnosis(messages, mode_names, unobserved)


def _make_rank_error(
    network: Network,
    index: ParameterIndex,
    design: DesignSystem,
    rank: int,
    null_space: np.ndarray,
) -> RankDeficientError:
    u = index.size
    diag = _diagnose_rank(network, index, design.A, rank, FixedDatum())
    parts = [
        f"设计矩阵秩亏：rank={rank}，参数数={u}，零空间维数={u - rank}",
    ]
    diagnostics = list(diag.messages)
    if not diagnostics:
        diagnostics.append("缺少足够基准或存在孤立/弱连接点")
    # 零空间向量与参数的对应关系（只列主要分量，便于定位）。
    for k in range(null_space.shape[1]):
        coeff = np.abs(null_space[:, k])
        if coeff.size == 0:
            continue
        threshold = max(float(coeff.max()) * 0.25, 1e-9)
        names = [
            index.names[j]
            for j in np.argsort(coeff)[::-1]
            if coeff[j] >= threshold
        ][:4]
        diagnostics.append(f"零空间方向{k + 1}主要参数：" + "、".join(names))
    parts.append("；".join(diagnostics))
    msg = "。".join(parts) + "。"
    return RankDeficientError(
        msg,
        rank=rank,
        n_params=u,
        null_space=null_space,
        parameter_names=index.names,
        diagnostics=diagnostics,
    )


def solve(
    network: Any,
    datum: Any = None,
    parameter_order: Optional[Sequence[Any]] = None,
    rank_tol: Optional[float] = None,
    **options: Any,
) -> AdjustmentResult:
    """求解设计态平面控制网。

    Parameters
    ----------
    network:
        Network 或 Scenario。传入 Scenario 且 datum=None 时使用方案自带基准。
    datum:
        Datum 对象、'fixed'/'weighted'/'minimal'/'free' 字符串或 None。
    parameter_order:
        可选的待定点顺序；固定点会被忽略，其余待定点自动追加。
    rank_tol:
        秩判定阈值；默认 ``max(m,u) * eps * s_max``。
    """
    if isinstance(network, Scenario):
        scenario = network
        if datum is None:
            datum = scenario.datum
        net = scenario.network
    else:
        net = network
    if not isinstance(net, Network):
        raise TypeError("solve 的第一个参数必须是 Network 或 Scenario")

    datum_obj = normalize_datum(datum)
    rank_tol = _validate_rank_tol(rank_tol)

    index = build_parameter_index(net, parameter_order=parameter_order)
    constraints = datum_obj.constraints(net, index)
    design = build_design(net, index, constraints=constraints)
    Aw, _L = whiten(design.A, design.Ql)

    u = index.size
    m = design.n_rows
    if u == 0:
        rank = 0
        Cx = np.zeros((0, 0), dtype=float)
        singular_values = np.zeros((0,), dtype=float)
        null_space = np.zeros((0, 0), dtype=float)
        condition = 1.0 if m == 0 else float("inf")
        redundancy = m
        S = np.zeros((0, 0))
    else:
        if m == 0:
            singular_values = np.zeros((0,), dtype=float)
            Vt = np.eye(u)
            rank = 0
            smax = 0.0
        else:
            _U, singular_values, Vt = np.linalg.svd(Aw, full_matrices=True)
            smax = float(singular_values[0]) if singular_values.size else 0.0
        tol = (
            rank_tol
            if rank_tol is not None
            else max(m, u) * np.finfo(float).eps * max(smax, 1.0)
        )
        rank = int(np.sum(singular_values > tol))
        null_space = Vt[rank:u, :].T.copy()

        if rank < u and not datum_obj.is_minimal:
            raise _make_rank_error(net, index, design, rank, null_space)

        if rank > 0:
            s = singular_values[:rank]
            Vr = Vt[:rank, :]
            Cx = Vr.T @ (Vr / (s * s)[:, None])
        else:
            Cx = np.zeros((u, u), dtype=float)

        if rank < u:
            # 自由网/最小约束：Moore-Penrose 伪逆给出基准相关协方差。
            # 显式 S 变换把最小范数解投影到不含零空间分量的子空间。
            G = null_space
            S = np.eye(u) - G @ G.T
            Cx = S @ Cx @ S.T
        else:
            S = np.eye(u)

        Cx = 0.5 * (Cx + Cx.T)
        if not np.all(np.isfinite(Cx)):
            raise InvalidPrecisionError("协方差矩阵含非有限值")
        eigmin = float(np.linalg.eigvalsh(Cx).min()) if u else 0.0
        if eigmin < -1e-10 * max(1.0, float(np.trace(Cx))):
            raise InvalidPrecisionError(
                f"协方差矩阵出现显著负特征值（min eigenvalue={eigmin:.3e}）"
            )
        condition = (
            float(singular_values[0] / singular_values[rank - 1])
            if rank > 0 and singular_values[rank - 1] > 0
            else float("inf")
        )
        redundancy = m - rank

    return AdjustmentResult(
        network=net,
        datum=datum_obj,
        index=index,
        design=design,
        A=design.A,
        Aw=Aw,
        Ql=design.Ql,
        Cx=Cx,
        rank=rank,
        n_rows=m,
        n_params=u,
        n_observations=design.n_observations,
        redundancy=redundancy,
        condition_number=condition,
        singular_values=singular_values,
        null_space=null_space,
        datum_transform=S,
        metadata={
            "datum_kind": datum_obj.kind,
            "datum_summary": datum_obj.summary(),
            "rank_tolerance": rank_tol,
            "parameter_names": list(index.names),
            "fixed_points": list(index.fixed_point_names),
        },
    )


__all__ = [
    "AdjustmentResult",
    "RankDiagnosis",
    "AdjustmentError",
    "RankDeficientError",
    "InvalidPrecisionError",
    "InvalidGeometryError",
    "solve",
]


# 常用别名
adjust = solve
