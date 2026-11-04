"""参数排列、观测方程与设计矩阵组装。

参数排列约定：
    [E1, N1, E2, N2, ...] 按待定点出现顺序；
    若含方向观测，在每个方向测站后附加一个定向未知数 omega（弧度）。

设计矩阵 A 的行单位为：距离/坐标分量 = 米，方向/角度 = 弧度。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from math import atan2, hypot, isfinite, pi
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

import numpy as np

from .exceptions import InvalidGeometryError, InvalidPrecisionError
from .model import (
    Angle,
    CoordinateConstraint,
    Direction,
    Distance,
    GnssBaseline2D,
    Network,
    Observation,
    Point,
    point_name,
)

GEOM_TOL = 1e-9  # 米


@dataclass
class ParameterIndex:
    """未知参数索引。"""

    point_order: List[str]
    point_columns: Dict[str, Tuple[int, int]]
    orientation_order: List[str]
    orientation_columns: Dict[str, int]
    names: List[str]
    fixed_point_names: List[str] = field(default_factory=list)

    @property
    def size(self) -> int:
        return len(self.names)

    @property
    def n_points(self) -> int:
        return len(self.point_order)

    def columns_of(self, ref: Any) -> Optional[Tuple[int, int]]:
        return self.point_columns.get(point_name(ref))

    def name_of_column(self, j: int) -> str:
        return self.names[j]


def build_parameter_index(
    network: Network,
    parameter_order: Optional[Sequence[Any]] = None,
) -> ParameterIndex:
    """建立参数索引。

    parameter_order 可给出待定点顺序；未列出的待定点按其在网中的出现顺序追加。
    精确固定点永远不占参数列。
    """
    by_name = {p.name: p for p in network.points}
    unknown = [p for p in network.points if not p.fixed]

    ordered: List[Point] = []
    seen: set = set()
    if parameter_order is not None:
        for ref in parameter_order:
            name = point_name(ref)
            if name not in by_name:
                raise ValueError(f"parameter_order 中的点 {name!r} 不在网中")
            p = by_name[name]
            if p.fixed:
                # 固定点不占参数列；显式传入时忽略，避免调用者重复维护基准状态。
                continue
            if name not in seen:
                ordered.append(p)
                seen.add(name)
    for p in unknown:
        if p.name not in seen:
            ordered.append(p)
            seen.add(p.name)

    point_columns: Dict[str, Tuple[int, int]] = {}
    names: List[str] = []
    for p in ordered:
        ie = len(names)
        names.extend([f"E_{p.name}", f"N_{p.name}"])
        point_columns[p.name] = (ie, ie + 1)

    orientation_order: List[str] = []
    for obs in network.observations:
        if isinstance(obs, Direction) and obs.station not in orientation_order:
            orientation_order.append(obs.station)
    orientation_columns: Dict[str, int] = {}
    for station in orientation_order:
        orientation_columns[station] = len(names)
        names.append(f"omega_{station}")

    return ParameterIndex(
        point_order=[p.name for p in ordered],
        point_columns=point_columns,
        orientation_order=orientation_order,
        orientation_columns=orientation_columns,
        names=names,
        fixed_point_names=[p.name for p in network.points if p.fixed],
    )


@dataclass
class ObservationBlock:
    """一段设计矩阵行对应的观测（GNSS 基线为两行）。"""

    observation: Optional[Observation]
    row_start: int
    row_count: int
    label: str
    kind: str
    unit: str = "m"

    @property
    def rows(self) -> List[int]:
        return list(range(self.row_start, self.row_start + self.row_count))

    @property
    def row_slice(self) -> slice:
        return slice(self.row_start, self.row_start + self.row_count)


@dataclass
class DesignSystem:
    """未白化的设计矩阵与观测协方差。"""

    network: Network
    index: ParameterIndex
    A: np.ndarray
    Ql: np.ndarray
    blocks: List[ObservationBlock]
    observation_blocks: List[ObservationBlock]
    constraint_blocks: List[ObservationBlock]
    n_rows: int
    n_observations: int

    @property
    def parameter_names(self) -> List[str]:
        return self.index.names

    @property
    def labels(self) -> List[str]:
        labels: List[str] = []
        for block in self.blocks:
            labels.extend([block.label] * block.row_count)
        return labels


def _check_finite(value: float, what: str) -> None:
    if not isfinite(float(value)):
        raise InvalidPrecisionError(f"{what} 不是有限值：{value!r}")


def _coords(network: Network, ref: Any) -> Tuple[float, float]:
    p = network.point(ref)
    _check_finite(p.E, f"点 {p.name} 的 E")
    _check_finite(p.N, f"点 {p.name} 的 N")
    return p.E, p.N


def _delta(network: Network, frm: Any, to: Any) -> Tuple[float, float, float]:
    e1, n1 = _coords(network, frm)
    e2, n2 = _coords(network, to)
    dE, dN = e2 - e1, n2 - n1
    s = hypot(dE, dN)
    if not isfinite(s) or s <= GEOM_TOL:
        raise InvalidGeometryError(
            f"点 {point_name(frm)} 与 {point_name(to)} 重合或距离过小（s={s:.3e} m）"
        )
    return dE, dN, s


def _direction_gradient(
    network: Network, station: Any, target: Any
) -> Tuple[Tuple[float, float], Tuple[float, float]]:
    """返回 (测站 E,N 偏导, 目标 E,N 偏导)，单位 rad/m。"""
    dE, dN, s = _delta(network, station, target)
    s2 = s * s
    g_target = (dN / s2, -dE / s2)
    g_station = (-g_target[0], -g_target[1])
    return g_station, g_target


def _write(
    A: np.ndarray,
    index: ParameterIndex,
    ref: Any,
    row: int,
    gE: float,
    gN: float,
) -> None:
    cols = index.columns_of(ref)
    if cols is None:
        return
    A[row, cols[0]] += gE
    A[row, cols[1]] += gN


def _positive(value: float, what: str) -> float:
    _check_finite(value, what)
    if value <= 0.0:
        raise InvalidPrecisionError(f"{what} 必须大于 0，收到 {value!r}")
    return float(value)


def _add_constraint(
    A: np.ndarray,
    Ql: np.ndarray,
    index: ParameterIndex,
    constraint: CoordinateConstraint,
    row: int,
) -> ObservationBlock:
    sigma = _positive(constraint.sigma, f"{constraint.label} 的标准差")
    cols = index.columns_of(constraint.point)
    if cols is None:
        raise InvalidPrecisionError(
            f"加权约束点 {constraint.point!r} 不在未知参数中（可能被设为精确固定点）"
        )
    col = cols[0] if constraint.component == "E" else cols[1]
    A[row, col] = 1.0
    Ql[row, row] = sigma * sigma
    return ObservationBlock(
        observation=None,
        row_start=row,
        row_count=1,
        label=constraint.label,
        kind="constraint",
        unit="m",
    )


def build_design(
    network: Network,
    index: ParameterIndex,
    constraints: Iterable[CoordinateConstraint] = (),
) -> DesignSystem:
    """按观测顺序组装未白化设计矩阵 A 与观测协方差 Ql。"""
    constraints = list(constraints)

    n_rows = 0
    for obs in network.observations:
        if isinstance(obs, GnssBaseline2D):
            n_rows += 2
        else:
            n_rows += 1
    n_obs_rows = n_rows
    n_rows += len(constraints)

    A = np.zeros((n_rows, index.size), dtype=float)
    Ql = np.zeros((n_rows, n_rows), dtype=float)
    blocks: List[ObservationBlock] = []
    observation_blocks: List[ObservationBlock] = []
    constraint_blocks: List[ObservationBlock] = []
    row = 0

    for obs in network.observations:
        if isinstance(obs, Distance):
            dE, dN, s = _delta(network, obs.frm, obs.to)
            _check_finite(obs.a, f"{obs.label} 的 a")
            _check_finite(obs.b_ppm, f"{obs.label} 的 b_ppm")
            if obs.a < 0.0 or obs.b_ppm < 0.0:
                raise InvalidPrecisionError(f"{obs.label} 的 a、b_ppm 不能为负")
            sigma = _positive(obs.sigma(s), f"{obs.label} 的 σ_s")
            A[row, :] = 0.0
            _write(A, index, obs.frm, row, -dE / s, -dN / s)
            _write(A, index, obs.to, row, dE / s, dN / s)
            Ql[row, row] = sigma * sigma
            block = ObservationBlock(obs, row, 1, obs.label, obs.kind, "m")
            blocks.append(block)
            observation_blocks.append(block)
            row += 1

        elif isinstance(obs, Direction):
            g_station, g_target = _direction_gradient(network, obs.station, obs.target)
            sigma = _positive(obs.sigma_rad, f"{obs.label} 的 σ")
            _write(A, index, obs.station, row, g_station[0], g_station[1])
            _write(A, index, obs.target, row, g_target[0], g_target[1])
            omega_col = index.orientation_columns.get(obs.station)
            if omega_col is None:
                raise InvalidPrecisionError(
                    f"方向观测 {obs.label} 的测站缺少定向未知数"
                )
            A[row, omega_col] = -1.0
            Ql[row, row] = sigma * sigma
            block = ObservationBlock(obs, row, 1, obs.label, obs.kind, "rad")
            blocks.append(block)
            observation_blocks.append(block)
            row += 1

        elif isinstance(obs, Angle):
            if obs.backsight == obs.foresight:
                raise InvalidGeometryError(
                    f"角度观测 {obs.label} 的后视与前视不能是同一点"
                )
            gs_b, gt_b = _direction_gradient(network, obs.station, obs.backsight)
            gs_f, gt_f = _direction_gradient(network, obs.station, obs.foresight)
            sigma = _positive(obs.sigma_rad, f"{obs.label} 的 σ")
            # beta = alpha(station -> foresight) - alpha(station -> backsight)
            _write(A, index, obs.foresight, row, gt_f[0], gt_f[1])
            _write(A, index, obs.backsight, row, -gt_b[0], -gt_b[1])
            # 测站同时出现在两条方向中，其贡献相加
            _write(
                A,
                index,
                obs.station,
                row,
                gs_f[0] - gs_b[0],
                gs_f[1] - gs_b[1],
            )
            Ql[row, row] = sigma * sigma
            block = ObservationBlock(obs, row, 1, obs.label, obs.kind, "rad")
            blocks.append(block)
            observation_blocks.append(block)
            row += 1

        elif isinstance(obs, GnssBaseline2D):
            e1, n1 = _coords(network, obs.frm)
            e2, n2 = _coords(network, obs.to)
            if hypot(e2 - e1, n2 - n1) <= GEOM_TOL:
                raise InvalidGeometryError(
                    f"GNSS 基线 {obs.label} 两端点重合或距离过小"
                )
            _positive(obs.sigma_E, f"{obs.label} 的 σ_E")
            _positive(obs.sigma_N, f"{obs.label} 的 σ_N")
            _check_finite(obs.correlation, f"{obs.label} 的相关系数")
            if abs(obs.correlation) >= 1.0:
                raise InvalidPrecisionError(
                    f"{obs.label} 的相关系数必须满足 |ρ|<1，收到 {obs.correlation!r}"
                )
            # ΔE = E_to - E_from; ΔN = N_to - N_from
            _write(A, index, obs.frm, row, -1.0, 0.0)
            _write(A, index, obs.to, row, 1.0, 0.0)
            _write(A, index, obs.frm, row + 1, 0.0, -1.0)
            _write(A, index, obs.to, row + 1, 0.0, 1.0)
            C = obs.covariance
            Ql[row : row + 2, row : row + 2] = C
            block = ObservationBlock(obs, row, 2, obs.label, obs.kind, "m")
            blocks.append(block)
            observation_blocks.append(block)
            row += 2

        else:  # pragma: no cover - 防御性
            raise TypeError(f"不支持的观测类型：{type(obs)!r}")

    for constraint in constraints:
        block = _add_constraint(A, Ql, index, constraint, row)
        blocks.append(block)
        constraint_blocks.append(block)
        row += 1

    assert row == n_rows
    return DesignSystem(
        network=network,
        index=index,
        A=A,
        Ql=Ql,
        blocks=blocks,
        observation_blocks=observation_blocks,
        constraint_blocks=constraint_blocks,
        n_rows=n_rows,
        n_observations=len(network.observations),
    )


def whiten(
    A: np.ndarray, Ql: np.ndarray
) -> Tuple[np.ndarray, np.ndarray]:
    """用 Cholesky 分解 Ql = L Lᵀ 白化：Aw = L⁻¹ A。

    返回 (Aw, L)。Ql 必须对称正定；非正定时抛 InvalidPrecisionError。
    """
    if A.shape[0] != Ql.shape[0] or Ql.shape[0] != Ql.shape[1]:
        raise InvalidPrecisionError("A 与 Ql 的维数不匹配")
    if Ql.shape[0] == 0:
        return A.copy(), np.zeros((0, 0))
    if not np.all(np.isfinite(Ql)):
        raise InvalidPrecisionError("观测协方差矩阵含非有限值")
    Qs = 0.5 * (Ql + Ql.T)
    try:
        L = np.linalg.cholesky(Qs)
    except np.linalg.LinAlgError as exc:
        raise InvalidPrecisionError(
            "观测协方差矩阵非正定，无法进行 Cholesky 白化"
        ) from exc
    Aw = np.linalg.solve(L, A)
    return Aw, L


__all__ = [
    "GEOM_TOL",
    "ParameterIndex",
    "ObservationBlock",
    "DesignSystem",
    "build_parameter_index",
    "build_design",
    "whiten",
]
