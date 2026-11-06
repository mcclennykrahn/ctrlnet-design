"""GNSS 三维基线向量网、局部 ENU 联合平差与高程异常近似。

模块内容
--------
1. WGS84 大地坐标 ``(φ, λ, h)`` ↔ ECEF ``(X, Y, Z)`` ↔ 局部 ENU ``(E, N, U)``；
2. 三维基线向量观测 ``l_ij = X_j − X_i + v``，支持 ECEF/ENU 输入与完整
   3×3 协方差（含 ENU→ECEF 的旋转传播）；
3. 固定点/最小约束基准、Cholesky 白化、SVD 求协方差、点位三维精度、
   水平误差椭圆、垂直中误差、基线相对精度、复用 ``reliability`` 的
   ``r_i``/MDB；
4. 与地面距离/角度/水准高差的联合平差（局部 ENU 切平面近似）；
5. 高程异常 ζ=h−H 的常数/平面拟合，以及可选的 EGM96 格网插值。

坐标与单位约定
--------------
- 经纬度对外使用**度**，内部转为弧度；长度/高程单位为米。
- 局部 ENU 以 ``GnssNetwork.origin`` 点的椭球法线为基准，是切平面近似，
  不是严格的椭球面曲线坐标。平面距离/角度在切平面上计算。
- 基线协方差单位 m²，必须对称正定。ENU 基线按 ``reference`` 点（默认
  ``frm``）的 ECEF→ENU 旋转矩阵转到 ECEF 后参与平差。

关于自由网秩亏
--------------
若观测是**基线向量**（三个分量都已知），设计矩阵的零空间只有 3 个整体
平移分量；固定 1 个点即可消除。方案 §5.8.3 提到的 7 个基准缺陷对应的是
只观测距离/方向或需要估计相似变换参数的网；本模块按实际设计矩阵报告
零空间维数，不强行凑成 7。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from math import atan2, cos, degrees, floor, hypot, isfinite, pi, radians, sin, sqrt
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple, Union

import numpy as np

from .design import ObservationBlock, whiten
from .exceptions import (
    InvalidGeometryError,
    InvalidPrecisionError,
    RankDeficientError,
)
from .leveling import HeightDifference
from .model import Angle, Distance
from .precision import ErrorEllipse, ellipse_from_cov
from .reliability import ReliabilityResult, analyze_reliability

# ---------------------------------------------------------------------------
# WGS84 椭球与坐标转换
# ---------------------------------------------------------------------------
WGS84_A = 6378137.0
WGS84_F = 1.0 / 298.257223563
WGS84_B = WGS84_A * (1.0 - WGS84_F)
WGS84_E2 = WGS84_F * (2.0 - WGS84_F)
WGS84_EP2 = (WGS84_A * WGS84_A - WGS84_B * WGS84_B) / (WGS84_B * WGS84_B)

_GEODETIC_TOL = 1e-12


def _finite(value: Any, what: str) -> float:
    try:
        out = float(value)
    except (TypeError, ValueError) as exc:
        raise InvalidPrecisionError(f"{what} 必须是数值，收到 {value!r}") from exc
    if not isfinite(out):
        raise InvalidPrecisionError(f"{what} 必须是有限值，收到 {value!r}")
    return out


def _ref_name(ref: Any) -> str:
    if isinstance(ref, str):
        name = ref
    else:
        name = getattr(ref, "name", None)
        if name is None:
            raise TypeError(f"点引用必须是 str 或带 name 属性的对象，收到 {type(ref)!r}")
        name = str(name)
    if not name:
        raise ValueError("点名不能为空")
    return name


def _normalize_frame(frame: Any, *, what: str = "坐标系") -> str:
    key = str(frame).strip().upper().replace("-", "_")
    if key in ("ECEF", "XYZ", "EARTH", "地心", "地心地固"):
        return "ECEF"
    if key in ("ENU", "LOCAL_ENU", "ENU_LOCAL", "局部", "东北天"):
        return "ENU"
    raise ValueError(f"{what} 只能是 'ECEF' 或 'ENU'，收到 {frame!r}")


def _normalize_lat_lon(lat: Any, lon: Any) -> Tuple[float, float]:
    lat = _finite(lat, "纬度 lat")
    lon = _finite(lon, "经度 lon")
    if not -90.0 <= lat <= 90.0:
        raise ValueError(f"纬度必须位于 [-90, 90] 度，收到 {lat!r}")
    # 允许 [-180,180] 之外的值，按 360° 周期归化，便于跨日界线输入。
    lon = (lon + 180.0) % 360.0 - 180.0
    return lat, lon


def geodetic_to_ecef(lat_deg: Any, lon_deg: Any, h: Any = 0.0) -> np.ndarray:
    """WGS84 大地坐标（度、度、米）→ ECEF（米）。"""
    lat, lon = _normalize_lat_lon(lat_deg, lon_deg)
    h = _finite(h, "椭球高 h")
    phi = radians(lat)
    lam = radians(lon)
    sp, cp = sin(phi), cos(phi)
    sl, cl = sin(lam), cos(lam)
    n = WGS84_A / sqrt(1.0 - WGS84_E2 * sp * sp)
    x = (n + h) * cp * cl
    y = (n + h) * cp * sl
    z = (n * (1.0 - WGS84_E2) + h) * sp
    return np.array([x, y, z], dtype=float)


def ecef_to_geodetic(xyz: Sequence[float], degrees_out: bool = True) -> Tuple[float, float, float]:
    """ECEF（米）→ WGS84 大地坐标 ``(lat, lon, h)``；默认经纬度输出度。"""
    p = np.asarray(xyz, dtype=float).reshape(-1)
    if p.size != 3:
        raise ValueError(f"ECEF 必须是长度 3 的向量，收到 {xyz!r}")
    if not np.all(np.isfinite(p)):
        raise ValueError("ECEF 坐标含非有限值")
    x, y, z = float(p[0]), float(p[1]), float(p[2])
    rho = hypot(x, y)
    lon = atan2(y, x) if rho > _GEODETIC_TOL else 0.0
    if rho <= _GEODETIC_TOL:
        lat = pi / 2.0 if z >= 0.0 else -pi / 2.0
        h = abs(z) - WGS84_B
    else:
        lat = atan2(z, rho * (1.0 - WGS84_E2))
        h = 0.0
        for _ in range(8):
            sp = sin(lat)
            n = WGS84_A / sqrt(1.0 - WGS84_E2 * sp * sp)
            h = rho / cos(lat) - n
            lat_new = atan2(z, rho * (1.0 - WGS84_E2 * n / (n + h)))
            if abs(lat_new - lat) < 1e-14:
                lat = lat_new
                break
            lat = lat_new
        sp = sin(lat)
        n = WGS84_A / sqrt(1.0 - WGS84_E2 * sp * sp)
        h = rho / cos(lat) - n
    if degrees_out:
        return degrees(lat), degrees(lon), float(h)
    return float(lat), float(lon), float(h)


def ecef_to_enu_matrix(lat_deg: Any, lon_deg: Any) -> np.ndarray:
    """返回测站 ECEF→ENU 旋转矩阵 ``R``（3×3，正交，``R C_XYZ Rᵀ=C_ENU``）。"""
    lat, lon = _normalize_lat_lon(lat_deg, lon_deg)
    phi = radians(lat)
    lam = radians(lon)
    sp, cp = sin(phi), cos(phi)
    sl, cl = sin(lam), cos(lam)
    return np.array(
        [
            [-sl, cl, 0.0],
            [-sp * cl, -sp * sl, cp],
            [cp * cl, cp * sl, sp],
        ],
        dtype=float,
    )


def enu_to_ecef_matrix(lat_deg: Any, lon_deg: Any) -> np.ndarray:
    """返回测站 ENU→ECEF 旋转矩阵（``ecef_to_enu_matrix`` 的转置）。"""
    return ecef_to_enu_matrix(lat_deg, lon_deg).T


def ecef_to_enu(
    xyz: Sequence[float],
    origin_lat: Any,
    origin_lon: Any,
    origin_h: Any = 0.0,
) -> np.ndarray:
    """ECEF → 以给定大地坐标点为原点的局部 ENU。"""
    origin = geodetic_to_ecef(origin_lat, origin_lon, origin_h)
    p = np.asarray(xyz, dtype=float).reshape(3)
    return ecef_to_enu_matrix(origin_lat, origin_lon) @ (p - origin)


def enu_to_ecef(
    enu: Sequence[float],
    origin_lat: Any,
    origin_lon: Any,
    origin_h: Any = 0.0,
) -> np.ndarray:
    """局部 ENU → ECEF。"""
    origin = geodetic_to_ecef(origin_lat, origin_lon, origin_h)
    vector = np.asarray(enu, dtype=float).reshape(3)
    return origin + enu_to_ecef_matrix(origin_lat, origin_lon) @ vector


def geodetic_to_enu(
    lat_deg: Any,
    lon_deg: Any,
    h: Any,
    origin_lat: Any,
    origin_lon: Any,
    origin_h: Any = 0.0,
) -> np.ndarray:
    """大地坐标 → 以另一点为原点的局部 ENU。"""
    return ecef_to_enu(
        geodetic_to_ecef(lat_deg, lon_deg, h), origin_lat, origin_lon, origin_h
    )


# 常见命名别名
ecef_to_enu_rotation = ecef_to_enu_matrix
enu_to_ecef_rotation = enu_to_ecef_matrix


def covariance_enu_to_ecef(cov_enu: Any, lat_deg: Any, lon_deg: Any) -> np.ndarray:
    """把 ENU 3×3 协方差旋转到 ECEF：``C_XYZ = Rᵀ C_ENU R``。"""
    c = np.asarray(cov_enu, dtype=float)
    if c.shape != (3, 3):
        raise InvalidPrecisionError(f"ENU 协方差必须是 3×3，收到 {c.shape}")
    r = ecef_to_enu_matrix(lat_deg, lon_deg)
    return r.T @ c @ r


def covariance_ecef_to_enu(cov_ecef: Any, lat_deg: Any, lon_deg: Any) -> np.ndarray:
    """把 ECEF 3×3 协方差旋转到 ENU：``C_ENU = R C_XYZ Rᵀ``。"""
    c = np.asarray(cov_ecef, dtype=float)
    if c.shape != (3, 3):
        raise InvalidPrecisionError(f"ECEF 协方差必须是 3×3，收到 {c.shape}")
    r = ecef_to_enu_matrix(lat_deg, lon_deg)
    return r @ c @ r.T


def _check_covariance(cov: Any, what: str) -> np.ndarray:
    c = np.asarray(cov, dtype=float)
    if c.shape != (3, 3):
        raise InvalidPrecisionError(f"{what} 必须是 3×3 协方差，收到 {c.shape}")
    if not np.all(np.isfinite(c)):
        raise InvalidPrecisionError(f"{what} 含非有限值")
    if not np.allclose(c, c.T, rtol=0.0, atol=1e-9 * max(1.0, float(np.max(np.abs(c))))):
        raise InvalidPrecisionError(f"{what} 必须对称")
    c = 0.5 * (c + c.T)
    try:
        np.linalg.cholesky(c)
    except np.linalg.LinAlgError as exc:
        raise InvalidPrecisionError(f"{what} 必须对称正定（Cholesky 失败）") from exc
    return c


# ---------------------------------------------------------------------------
# GNSS 数据模型
# ---------------------------------------------------------------------------
@dataclass
class GnssPoint:
    """三维 GNSS 点。

    可用 ``lat/lon/h``（度、度、椭球高米）或 ``xyz``（ECEF 米）之一构造。
    ``fixed=True`` 时该点不参与未知参数，作为三维固定基准。
    """

    name: str
    lat: Optional[float] = None
    lon: Optional[float] = None
    h: Optional[float] = None
    fixed: bool = False
    xyz: Optional[Sequence[float]] = None

    def __post_init__(self) -> None:
        self.name = str(self.name)
        if not self.name:
            raise ValueError("点名不能为空")
        self.fixed = bool(self.fixed)
        if self.xyz is not None:
            if any(value is not None for value in (self.lat, self.lon, self.h)):
                raise ValueError("GnssPoint 不能同时给出 xyz 与 lat/lon/h")
            arr = np.asarray(self.xyz, dtype=float).reshape(-1)
            if arr.size != 3 or not np.all(np.isfinite(arr)):
                raise ValueError("xyz 必须是长度 3 的有限 ECEF 向量")
            lat, lon, h = ecef_to_geodetic(arr)
            self.lat, self.lon, self.h = lat, lon, h
            self.xyz = arr
        else:
            if self.lat is None or self.lon is None or self.h is None:
                raise ValueError("GnssPoint 需要 lat/lon/h 或 xyz")
            lat, lon = _normalize_lat_lon(self.lat, self.lon)
            self.lat, self.lon = lat, lon
            self.h = _finite(self.h, f"点 {self.name} 的椭球高 h")
            self.xyz = geodetic_to_ecef(lat, lon, self.h)

    @classmethod
    def from_ecef(
        cls, name: str, xyz: Sequence[float], fixed: bool = False
    ) -> "GnssPoint":
        return cls(name=name, xyz=xyz, fixed=fixed)

    @property
    def ecef(self) -> np.ndarray:
        return np.asarray(self.xyz, dtype=float)

    @property
    def geodetic(self) -> Tuple[float, float, float]:
        return float(self.lat), float(self.lon), float(self.h)

    def enu_from(self, origin: "GnssPoint") -> np.ndarray:
        """返回相对另一个点的局部 ENU（使用 ``origin`` 的椭球法线）。"""
        return ecef_to_enu(self.ecef, origin.lat, origin.lon, origin.h)


@dataclass
class GnssBaseline:
    """三维基线向量观测。

    ``delta`` 为 ``to − from`` 的三分量；``frame='ECEF'`` 时为 ΔX/ΔY/ΔZ，
    ``frame='ENU'`` 时为 ΔE/ΔN/ΔU。``covariance`` 必须是与 ``delta`` 同框架
    的 3×3 协方差（m²）。ENU 基线用 ``reference`` 点（默认 ``frm``）的旋转
    矩阵转到 ECEF，协方差同步旋转。
    """

    frm: str
    to: str
    delta: Sequence[float]
    covariance: Sequence[Sequence[float]]
    frame: str = "ECEF"
    reference: Optional[str] = None

    def __post_init__(self) -> None:
        self.frm = _ref_name(self.frm)
        self.to = _ref_name(self.to)
        if self.frm == self.to:
            raise InvalidGeometryError("GNSS 基线两端点不能相同")
        self.frame = _normalize_frame(self.frame, what="基线坐标系")
        value = np.asarray(self.delta, dtype=float).reshape(-1)
        if value.size != 3 or not np.all(np.isfinite(value)):
            raise InvalidPrecisionError("基线 delta 必须是长度 3 的有限向量")
        self.delta = value
        if not np.any(np.abs(value) > 0.0):
            raise InvalidGeometryError(f"GNSS 基线 {self.frm}-{self.to} 长度为 0")
        self.covariance = _check_covariance(
            self.covariance, f"基线 {self.frm}-{self.to} 的协方差"
        )
        self.reference = (
            _ref_name(self.reference) if self.reference is not None else self.frm
        )

    @property
    def label(self) -> str:
        return f"GNSS {self.frm}-{self.to}"

    @property
    def length(self) -> float:
        return float(np.linalg.norm(np.asarray(self.delta, dtype=float)))

    def ecef_observation(self, points: Mapping[str, GnssPoint]) -> Tuple[np.ndarray, np.ndarray]:
        """返回 ECEF 框架下的 ``(delta, covariance)``。"""
        if self.frame == "ECEF":
            return np.asarray(self.delta, dtype=float), np.asarray(self.covariance, dtype=float)
        ref = points.get(self.reference)
        if ref is None:
            raise KeyError(f"基线参考点 {self.reference!r} 不在网中")
        r = ecef_to_enu_matrix(ref.lat, ref.lon)
        delta = r.T @ np.asarray(self.delta, dtype=float)
        cov = r.T @ np.asarray(self.covariance, dtype=float) @ r
        return delta, 0.5 * (cov + cov.T)


@dataclass
class GnssCovarianceBlock:
    """同一时段基线索引（从 0 起）及按各基线原框架排列的 3n×3n VCV。"""

    indices: Sequence[int]
    covariance: Sequence[Sequence[float]]
    name: str = "session"

    def __post_init__(self) -> None:
        self.indices = tuple(self.indices)
        if not self.indices or any(type(i) is not int or i < 0 for i in self.indices):
            raise ValueError("块索引必须为非空非负整数序列")
        if len(set(self.indices)) != len(self.indices):
            raise ValueError("块内基线索引重复")
        c = np.asarray(self.covariance, dtype=float)
        n = 3 * len(self.indices)
        if c.shape != (n, n) or not np.all(np.isfinite(c)):
            raise InvalidPrecisionError("块 VCV 必须为有限 3n×3n 矩阵")
        if not np.allclose(c, c.T, rtol=1e-12, atol=1e-15):
            raise InvalidPrecisionError("块 VCV 必须对称")
        c = (c + c.T) / 2
        try:
            np.linalg.cholesky(c)
        except np.linalg.LinAlgError as exc:
            raise InvalidPrecisionError("块 VCV 必须正定") from exc
        self.covariance = c


@dataclass
class GnssNetwork:
    """三维 GNSS 基线网 + 可选地面距离/角度/水准观测。"""

    points: Sequence[GnssPoint]
    baselines: Sequence[GnssBaseline] = field(default_factory=list)
    distances: Sequence[Distance] = field(default_factory=list)
    angles: Sequence[Angle] = field(default_factory=list)
    leveling: Sequence[HeightDifference] = field(default_factory=list)
    origin: Optional[str] = None
    parameter_frame: str = "ECEF"
    name: str = "gnss"
    covariance_blocks: Sequence[GnssCovarianceBlock] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.points = list(self.points)
        self.baselines = list(self.baselines)
        self.distances = list(self.distances)
        self.angles = list(self.angles)
        self.leveling = list(self.leveling)
        self.name = str(self.name)
        self.parameter_frame = _normalize_frame(self.parameter_frame, what="参数坐标系")
        self._by_name: Dict[str, GnssPoint] = {}
        for point in self.points:
            if not isinstance(point, GnssPoint):
                raise TypeError("points 必须由 GnssPoint 组成")
            if point.name in self._by_name:
                raise ValueError(f"点名重复：{point.name}")
            self._by_name[point.name] = point
        if not self.points:
            raise ValueError("GnssNetwork 至少需要一个点")
        if self.origin is None:
            self.origin = self.points[0].name
        else:
            self.origin = _ref_name(self.origin)
        if self.origin not in self._by_name:
            raise KeyError(f"原点 {self.origin!r} 不在网中")
        self.covariance_blocks = list(self.covariance_blocks)
        self._validate_covariance_blocks()
        self._validate_references()
        self.geoid: Optional[Any] = None

    def _validate_covariance_blocks(self) -> None:
        used = set()
        for block in self.covariance_blocks:
            block.__post_init__()
            for j, i in enumerate(block.indices):
                if i >= len(self.baselines) or i in used:
                    raise ValueError("块索引越界或时段块重叠")
                used.add(i)
                if not np.allclose(block.covariance[3*j:3*j+3, 3*j:3*j+3],
                                   self.baselines[i].covariance, rtol=1e-12, atol=1e-15):
                    raise InvalidPrecisionError("块 VCV 对角块必须与基线协方差一致")

    def _validate_references(self) -> None:
        for baseline in self.baselines:
            for ref in (baseline.frm, baseline.to, baseline.reference):
                if ref not in self._by_name:
                    raise KeyError(f"基线 {baseline.label} 引用了不存在的点 {ref!r}")
        for obs in self.distances:
            for ref in (obs.frm, obs.to):
                if _ref_name(ref) not in self._by_name:
                    raise KeyError(f"距离观测 {obs.label} 引用了不存在的点 {ref!r}")
        for obs in self.angles:
            for ref in (obs.backsight, obs.station, obs.foresight):
                if _ref_name(ref) not in self._by_name:
                    raise KeyError(f"角度观测 {obs.label} 引用了不存在的点 {ref!r}")
        for obs in self.leveling:
            for ref in (obs.frm, obs.to):
                if _ref_name(ref) not in self._by_name:
                    raise KeyError(f"水准观测 {obs.label} 引用了不存在的点 {ref!r}")

    def point(self, ref: Any) -> GnssPoint:
        name = _ref_name(ref)
        try:
            return self._by_name[name]
        except KeyError as exc:
            raise KeyError(f"网中不存在点 {name!r}") from exc

    @property
    def point_names(self) -> List[str]:
        return [p.name for p in self.points]

    @property
    def fixed_points(self) -> List[GnssPoint]:
        return [p for p in self.points if p.fixed]

    @property
    def unknown_points(self) -> List[GnssPoint]:
        return [p for p in self.points if not p.fixed]

    @property
    def origin_point(self) -> GnssPoint:
        return self.point(self.origin)

    @property
    def observations(self) -> List[Any]:
        return list(self.baselines) + list(self.distances) + list(self.angles) + list(self.leveling)

    def with_geoid(self, geoid: Any) -> "GnssNetwork":
        """返回附高程异常模型的浅拷贝网；用于水准高差与 GNSS 高的统一。"""
        other = GnssNetwork(
            points=self.points,
            baselines=self.baselines,
            distances=self.distances,
            angles=self.angles,
            leveling=self.leveling,
            origin=self.origin,
            parameter_frame=self.parameter_frame,
            name=self.name,
            covariance_blocks=self.covariance_blocks,
        )
        other.geoid = geoid
        return other


# ---------------------------------------------------------------------------
# 参数索引、设计系统与结果
# ---------------------------------------------------------------------------
@dataclass
class GnssParameterIndex:
    point_order: List[str]
    point_columns: Dict[str, Tuple[int, int, int]]
    names: List[str]
    fixed_point_names: List[str] = field(default_factory=list)

    @property
    def size(self) -> int:
        return len(self.names)

    def columns_of(self, ref: Any) -> Optional[Tuple[int, int, int]]:
        return self.point_columns.get(_ref_name(ref))

    def name_of_column(self, j: int) -> str:
        return self.names[j]


@dataclass
class GnssDesignSystem:
    A: np.ndarray
    Ql: np.ndarray
    blocks: List[ObservationBlock]
    observation_blocks: List[ObservationBlock]
    n_rows: int
    n_observations: int

    @property
    def labels(self) -> List[str]:
        labels: List[str] = []
        for block in self.blocks:
            labels.extend([block.label] * block.row_count)
        return labels


@dataclass
class GnssPointPrecision:
    name: str
    fixed: bool
    E: float
    N: float
    U: float
    X: float
    Y: float
    Z: float
    lat: float
    lon: float
    h: float
    sigma_E: float
    sigma_N: float
    sigma_U: float
    sigma_X: float
    sigma_Y: float
    sigma_Z: float
    mp_horizontal: float
    m3D: float
    ellipse: ErrorEllipse
    covariance_enu: np.ndarray
    covariance_ecef: np.ndarray
    H_normal: Optional[float] = None
    sigma_H_normal: Optional[float] = None

    @property
    def mp(self) -> float:
        return self.mp_horizontal

    @property
    def sigma_mp(self) -> float:
        return self.mp_horizontal

    @property
    def sigma_E_mm(self) -> float:
        return self.sigma_E * 1e3

    @property
    def sigma_N_mm(self) -> float:
        return self.sigma_N * 1e3

    @property
    def sigma_U_mm(self) -> float:
        return self.sigma_U * 1e3

    @property
    def m3D_mm(self) -> float:
        return self.m3D * 1e3

    @property
    def mp_mm(self) -> float:
        return self.mp_horizontal * 1e3

    @property
    def sigma_3d(self) -> float:
        return self.m3D

    @property
    def sigma_3d_mm(self) -> float:
        return self.m3D * 1e3


@dataclass
class GnssBaselinePrecision:
    frm: str
    to: str
    delta_enu: np.ndarray
    covariance_enu: np.ndarray
    length_3d: float
    sigma_3d: float
    horizontal_length: float
    sigma_horizontal: float
    sigma_vertical: float
    r_i: Optional[float] = None
    mdb: Optional[float] = None
    r_components: Optional[np.ndarray] = None
    mdb_components: Optional[np.ndarray] = None

    @property
    def label(self) -> str:
        return f"GNSS {self.frm}-{self.to}"

    @property
    def sigma_3d_mm(self) -> float:
        return self.sigma_3d * 1e3

    @property
    def sigma_horizontal_mm(self) -> float:
        return self.sigma_horizontal * 1e3

    @property
    def sigma_vertical_mm(self) -> float:
        return self.sigma_vertical * 1e3

    @property
    def relative_3d(self) -> float:
        return self.sigma_3d / self.length_3d if self.length_3d > 0 else float("inf")

    @property
    def relative_horizontal(self) -> float:
        return (
            self.sigma_horizontal / self.horizontal_length
            if self.horizontal_length > 0
            else float("inf")
        )

    @property
    def relative_3d_ppm(self) -> float:
        return self.relative_3d * 1e6

    @property
    def relative_horizontal_ppm(self) -> float:
        return self.relative_horizontal * 1e6

    @property
    def ratio_3d(self) -> Optional[int]:
        return (
            int(round(1.0 / self.relative_3d))
            if self.relative_3d > 0 and isfinite(self.relative_3d)
            else None
        )

    @property
    def ratio_horizontal(self) -> Optional[int]:
        return (
            int(round(1.0 / self.relative_horizontal))
            if self.relative_horizontal > 0 and isfinite(self.relative_horizontal)
            else None
        )

    @property
    def mdb_mm(self) -> Optional[float]:
        if self.mdb is None or not isfinite(self.mdb):
            return None
        return self.mdb * 1e3


@dataclass
class GnssAdjustmentResult:
    network: GnssNetwork
    datum_kind: str
    parameter_frame: str
    origin: str
    origin_lat: float
    origin_lon: float
    origin_h: float
    rotation_ecef_to_enu: np.ndarray
    index: GnssParameterIndex
    design: GnssDesignSystem
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
    points: Dict[str, GnssPointPrecision] = field(default_factory=dict)
    baselines: Dict[str, GnssBaselinePrecision] = field(default_factory=dict)
    reliability: Optional[ReliabilityResult] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def Qxx(self) -> np.ndarray:
        return self.Cx

    @property
    def sigma0(self) -> float:
        return 1.0

    @property
    def parameter_names(self) -> List[str]:
        return list(self.index.names)

    @property
    def point_order(self) -> List[str]:
        return list(self.index.point_order)

    @property
    def n(self) -> int:
        return self.n_rows

    @property
    def m(self) -> int:
        return self.n_rows

    @property
    def u(self) -> int:
        return self.n_params

    @property
    def point_precisions(self) -> Dict[str, GnssPointPrecision]:
        return self.points

    @property
    def baseline_precisions(self) -> Dict[str, GnssBaselinePrecision]:
        return self.baselines

    def point_precision(self, ref: Any) -> GnssPointPrecision:
        return self.points[_ref_name(ref)]

    def point_covariance(self, ref: Any, frame: str = "ECEF") -> np.ndarray:
        """返回点的 3×3 协方差；``frame='ECEF'`` 或 ``'ENU'``。"""
        point = self.points[_ref_name(ref)]
        key = _normalize_frame(frame, what="协方差坐标系")
        return np.asarray(
            point.covariance_ecef if key == "ECEF" else point.covariance_enu,
            dtype=float,
        )

    def covariance(self, ref: Any, frame: str = "ECEF") -> np.ndarray:
        return self.point_covariance(ref, frame)

    def parameter_covariance(self, name: str) -> float:
        if name not in self.index.names:
            raise KeyError(f"未知参数 {name!r}")
        return float(self.Cx[self.index.names.index(name), self.index.names.index(name)])

    def baseline_precision(self, frm: Any, to: Any) -> GnssBaselinePrecision:
        key = f"{_ref_name(frm)}-{_ref_name(to)}"
        if key not in self.baselines:
            raise KeyError(f"没有基线精度 {key!r}")
        return self.baselines[key]

    @property
    def max_mp(self) -> float:
        return max((p.mp_horizontal for p in self.points.values() if not p.fixed), default=0.0)

    @property
    def max_m3D(self) -> float:
        return max((p.m3D for p in self.points.values() if not p.fixed), default=0.0)

    @property
    def max_sigma_U(self) -> float:
        return max((p.sigma_U for p in self.points.values() if not p.fixed), default=0.0)

    @property
    def min_r(self) -> Optional[float]:
        return None if self.reliability is None else self.reliability.min_r

    @property
    def max_mdb(self) -> Optional[float]:
        return None if self.reliability is None else self.reliability.max_mdb


# ---------------------------------------------------------------------------
# 解算
# ---------------------------------------------------------------------------
def _datum_kind(datum: Any) -> str:
    if datum is None:
        return "fixed"
    if isinstance(datum, str):
        key = datum.strip().lower()
        if key in ("fixed", "fix", "固定"):
            return "fixed"
        if key in ("minimal", "min", "free", "最小", "自由"):
            return "minimal"
        raise ValueError(f"未知 GNSS 基准 {datum!r}；支持 'fixed'/'minimal'")
    kind = getattr(datum, "kind", None)
    if kind in ("fixed",):
        return "fixed"
    if kind in ("minimal", "free"):
        return "minimal"
    raise ValueError(f"不支持的 GNSS 基准对象：{datum!r}")


def _validate_rank_tol(rank_tol: Optional[float]) -> Optional[float]:
    if rank_tol is None:
        return None
    rank_tol = float(rank_tol)
    if not isfinite(rank_tol) or rank_tol <= 0.0:
        raise InvalidPrecisionError(f"rank_tol 必须为正的有限值，收到 {rank_tol!r}")
    return rank_tol


def _build_index(network: GnssNetwork, frame: str) -> GnssParameterIndex:
    point_columns: Dict[str, Tuple[int, int, int]] = {}
    names: List[str] = []
    for point in network.unknown_points:
        i = len(names)
        point_columns[point.name] = (i, i + 1, i + 2)
        if frame == "ECEF":
            names.extend([f"X_{point.name}", f"Y_{point.name}", f"Z_{point.name}"])
        else:
            names.extend([f"E_{point.name}", f"N_{point.name}", f"U_{point.name}"])
    return GnssParameterIndex(
        point_order=[p.name for p in network.unknown_points],
        point_columns=point_columns,
        names=names,
        fixed_point_names=[p.name for p in network.fixed_points],
    )


def _write_gradient(
    A: np.ndarray,
    index: GnssParameterIndex,
    point_name: str,
    row: int,
    gradient: Sequence[float],
) -> None:
    cols = index.point_columns.get(point_name)
    if cols is None:
        return
    g = np.asarray(gradient, dtype=float).reshape(3)
    A[row, list(cols)] += g


def _write_baseline_block(
    A: np.ndarray,
    index: GnssParameterIndex,
    point_name: str,
    row: int,
    block: np.ndarray,
) -> None:
    cols = index.point_columns.get(point_name)
    if cols is None:
        return
    A[row : row + 3, list(cols)] += block


def _enu_gradient_to_params(
    gradient_enu: Sequence[float], frame: str, rotation: np.ndarray
) -> np.ndarray:
    g = np.asarray(gradient_enu, dtype=float).reshape(3)
    if frame == "ENU":
        return g
    # enu = R (X − X0) -> d f / dX = g_enu @ R
    return g @ rotation


def _enu_coordinates(network: GnssNetwork, origin: GnssPoint, rotation: np.ndarray) -> Dict[str, np.ndarray]:
    x0 = origin.ecef
    return {p.name: rotation @ (p.ecef - x0) for p in network.points}


def solve_gnss(
    network: GnssNetwork,
    datum: Any = None,
    *,
    parameter_frame: Optional[str] = None,
    rank_tol: Optional[float] = None,
    alpha: float = 0.05,
    power: float = 0.80,
    compute_reliability: bool = True,
) -> GnssAdjustmentResult:
    """GNSS 三维基线网/联合网设计态解算。

    Parameters
    ----------
    network:
        :class:`GnssNetwork`；观测可包含 3D 基线、平面距离、水平角、水准高差。
    datum:
        ``None``/``'fixed'``（默认，使用 ``GnssPoint.fixed``）或
        ``'minimal'``/``'free'``（SVD 伪逆最小约束，报告零空间）。
    parameter_frame:
        覆盖网的 ``parameter_frame``：``'ECEF'`` 或 ``'ENU'``。
        仅影响参数化与数值条件，几何结果等价。
    rank_tol:
        SVD 秩判定阈值；默认 ``max(m,u,1)·eps·s_max``。
    alpha, power:
        可靠性 MDB 的显著性与功效。
    compute_reliability:
        是否复用 :func:`ctrlnet.reliability.analyze_reliability` 计算 r_i/MDB。
    """
    if not isinstance(network, GnssNetwork):
        raise TypeError("solve_gnss 的第一个参数必须是 GnssNetwork")
    frame = (
        network.parameter_frame
        if parameter_frame is None
        else _normalize_frame(parameter_frame, what="参数坐标系")
    )
    datum_kind = _datum_kind(datum)
    rank_tol = _validate_rank_tol(rank_tol)
    index = _build_index(network, frame)
    origin = network.origin_point
    rotation = ecef_to_enu_matrix(origin.lat, origin.lon)
    enu_to_ecef = rotation.T
    enu = _enu_coordinates(network, origin, rotation)
    u = index.size

    # 每行观测/约束的元数据；先收集再一次性分配，避免重复拼接。
    rows: List[Tuple[str, str, int, Any]] = []
    for baseline in network.baselines:
        rows.append(("baseline", baseline.label, 3, baseline))
    for obs in network.distances:
        rows.append(("distance", obs.label, 1, obs))
    for obs in network.angles:
        rows.append(("angle", obs.label, 1, obs))
    for obs in network.leveling:
        rows.append(("leveling", f"水准 {obs.label}", 1, obs))
    n_rows = sum(row_count for _, _, row_count, _ in rows)
    A = np.zeros((n_rows, u), dtype=float)
    Ql = np.zeros((n_rows, n_rows), dtype=float)
    blocks: List[ObservationBlock] = []
    observation_blocks: List[ObservationBlock] = []
    row = 0

    for kind, label, row_count, obs in rows:
        if kind == "baseline":
            baseline: GnssBaseline = obs
            delta_ecef, cov_ecef = baseline.ecef_observation(network._by_name)
            if frame == "ECEF":
                _write_baseline_block(A, index, baseline.frm, row, -np.eye(3))
                _write_baseline_block(A, index, baseline.to, row, np.eye(3))
            else:
                _write_baseline_block(A, index, baseline.frm, row, -enu_to_ecef)
                _write_baseline_block(A, index, baseline.to, row, enu_to_ecef)
            Ql[row : row + 3, row : row + 3] = cov_ecef
            block = ObservationBlock(baseline, row, 3, baseline.label, "gnss", "m")
        elif kind == "distance":
            obs: Distance = obs
            p = enu[_ref_name(obs.frm)]
            q = enu[_ref_name(obs.to)]
            dE, dN = q[0] - p[0], q[1] - p[1]
            s = hypot(dE, dN)
            if s <= 1e-9:
                raise InvalidGeometryError(f"距离观测 {obs.label} 的平面长度过小")
            g_from = _enu_gradient_to_params((-dE / s, -dN / s, 0.0), frame, rotation)
            g_to = _enu_gradient_to_params((dE / s, dN / s, 0.0), frame, rotation)
            _write_gradient(A, index, _ref_name(obs.frm), row, g_from)
            _write_gradient(A, index, _ref_name(obs.to), row, g_to)
            sigma = float(obs.sigma(s))
            if not isfinite(sigma) or sigma <= 0.0:
                raise InvalidPrecisionError(f"距离观测 {obs.label} 的 σ_s 必须为正")
            Ql[row, row] = sigma * sigma
            block = ObservationBlock(obs, row, 1, obs.label, "distance", "m")
        elif kind == "angle":
            obs: Angle = obs
            s = _ref_name(obs.station)
            b = _ref_name(obs.backsight)
            f = _ref_name(obs.foresight)
            # beta = az(s->f) − az(s->b)。
            def az_grad(target: str) -> Tuple[np.ndarray, np.ndarray]:
                ps, pt = enu[s], enu[target]
                dE, dN = pt[0] - ps[0], pt[1] - ps[1]
                s2 = dE * dE + dN * dN
                if s2 <= 1e-18:
                    raise InvalidGeometryError(
                        f"角度观测 {obs.label} 的 {s}-{target} 平面距离过小"
                    )
                g_target = np.array([dN / s2, -dE / s2, 0.0])
                return -g_target, g_target

            gs_b, gt_b = az_grad(b)
            gs_f, gt_f = az_grad(f)
            g_station = gs_f - gs_b
            g_fore = gt_f
            g_back = -gt_b
            _write_gradient(A, index, s, row, _enu_gradient_to_params(g_station, frame, rotation))
            _write_gradient(A, index, f, row, _enu_gradient_to_params(g_fore, frame, rotation))
            _write_gradient(A, index, b, row, _enu_gradient_to_params(g_back, frame, rotation))
            sigma = float(obs.sigma_rad)
            if not isfinite(sigma) or sigma <= 0.0:
                raise InvalidPrecisionError(f"角度观测 {obs.label} 的 σ 必须为正")
            Ql[row, row] = sigma * sigma
            block = ObservationBlock(obs, row, 1, obs.label, "angle", "rad")
        else:  # leveling
            obs: HeightDifference = obs
            f, t = _ref_name(obs.frm), _ref_name(obs.to)
            # 若附有高程异常模型，把正常高差转为椭球高差：Δh = ΔH + (ζ_t−ζ_f)。
            correction = 0.0
            if network.geoid is not None:
                zeta = getattr(network.geoid, "zeta", None)
                if zeta is None:
                    raise TypeError("network.geoid 必须提供 zeta(E,N) 方法")
                correction = float(zeta(enu[t][0], enu[t][1]) - zeta(enu[f][0], enu[f][1]))
            sigma = float(obs.sigma)
            if not isfinite(sigma) or sigma <= 0.0:
                raise InvalidPrecisionError(f"水准观测 {obs.label} 的 σ 必须为正")
            g_from = _enu_gradient_to_params((0.0, 0.0, -1.0), frame, rotation)
            g_to = _enu_gradient_to_params((0.0, 0.0, 1.0), frame, rotation)
            _write_gradient(A, index, f, row, g_from)
            _write_gradient(A, index, t, row, g_to)
            Ql[row, row] = sigma * sigma
            block = ObservationBlock(obs, row, 1, f"水准 {obs.label}", "leveling", "m")
            block.correction = correction  # 记录正常高差→椭球高差的常数改正（m）
            blocks.append(block)
            observation_blocks.append(block)
            row += 1
            continue
        blocks.append(block)
        observation_blocks.append(block)
        row += row_count

    network._validate_covariance_blocks()
    for session in network.covariance_blocks:
        transforms = []
        for i in session.indices:
            b = network.baselines[i]
            ref = network.point(b.reference)
            transforms.append(np.eye(3) if b.frame == "ECEF" else
                              ecef_to_enu_matrix(ref.lat, ref.lon).T)
        for j, i in enumerate(session.indices):
            for k, h in enumerate(session.indices):
                # Preserve the existing diagonal arithmetic exactly.
                if j != k:
                    Ql[3*i:3*i+3, 3*h:3*h+3] = (
                        transforms[j] @ session.covariance[3*j:3*j+3, 3*k:3*k+3]
                        @ transforms[k].T)

    assert row == n_rows
    if n_rows == 0:
        Aw = np.zeros((0, u), dtype=float)
        singular_values = np.zeros((0,), dtype=float)
        null_space = np.eye(u) if u else np.zeros((0, 0), dtype=float)
        rank = 0
    else:
        Aw, _L = whiten(A, Ql)
        _U, singular_values, Vt = np.linalg.svd(Aw, full_matrices=True)
        smax = float(singular_values[0]) if singular_values.size else 0.0
        tol = (
            rank_tol
            if rank_tol is not None
            else max(n_rows, u, 1) * np.finfo(float).eps * max(smax, 1.0)
        )
        rank = int(np.sum(singular_values > tol))
        null_space = Vt[rank:u, :].T.copy()

    if rank < u and datum_kind == "fixed":
        diagnostics = _rank_diagnostics(network, index, A, rank)
        raise RankDeficientError(
            f"GNSS 联合网设计矩阵秩亏：rank={rank}，参数数={u}，零空间维数={u-rank}。"
            + "；".join(diagnostics)
            + "。纯基线向量网的零空间为整体平移（3 维）；固定至少 1 个点，"
            "或使用 datum='minimal' 获取最小约束解。",
            rank=rank,
            n_params=u,
            null_space=null_space,
            parameter_names=index.names,
            diagnostics=diagnostics,
        )

    if rank > 0:
        s = singular_values[:rank]
        Vr = Vt[:rank, :]
        Cx = Vr.T @ (Vr / (s * s)[:, None])
    else:
        Cx = np.zeros((u, u), dtype=float)
    if rank < u:
        G = null_space
        Cx = (np.eye(u) - G @ G.T) @ Cx @ (np.eye(u) - G @ G.T)
    Cx = 0.5 * (Cx + Cx.T)
    if not np.all(np.isfinite(Cx)):
        raise InvalidPrecisionError("GNSS 网协方差矩阵含非有限值")
    if u:
        eigmin = float(np.linalg.eigvalsh(Cx).min())
        if eigmin < -1e-10 * max(1.0, float(np.trace(Cx))):
            raise InvalidPrecisionError(
                f"GNSS 网协方差矩阵出现显著负特征值（min eigenvalue={eigmin:.3e}）"
            )
    condition = (
        float(singular_values[0] / singular_values[rank - 1])
        if rank > 0 and singular_values[rank - 1] > 0
        else (1.0 if u == 0 else float("inf"))
    )
    redundancy = n_rows - rank

    design = GnssDesignSystem(
        A=A,
        Ql=Ql,
        blocks=blocks,
        observation_blocks=observation_blocks,
        n_rows=n_rows,
        n_observations=len(network.observations),
    )
    result = GnssAdjustmentResult(
        network=network,
        datum_kind=datum_kind,
        parameter_frame=frame,
        origin=network.origin,
        origin_lat=float(origin.lat),
        origin_lon=float(origin.lon),
        origin_h=float(origin.h),
        rotation_ecef_to_enu=rotation,
        index=index,
        design=design,
        A=A,
        Aw=Aw,
        Ql=Ql,
        Cx=Cx,
        rank=rank,
        n_rows=n_rows,
        n_params=u,
        n_observations=design.n_observations,
        redundancy=redundancy,
        condition_number=condition,
        singular_values=singular_values,
        null_space=null_space,
        datum_transform=(
            np.eye(u) - null_space @ null_space.T if rank < u else np.eye(u)
        ),
        metadata={
            "origin": network.origin,
            "parameter_frame": frame,
            "datum_kind": datum_kind,
            "rank_tolerance": rank_tol,
            "nullity": u - rank,
            "nullity_note": (
                "基线向量分量已给出方向与尺度，自由网零空间通常只有 3 个平移；"
                "若仅有距离/方向观测，才可能出现旋转/尺度等附加缺陷。"
            ),
            "geoid_model": None if network.geoid is None else type(network.geoid).__name__,
        },
    )
    _fill_point_precisions(result, enu)
    _fill_baseline_precisions(result, enu)
    if compute_reliability:
        result.reliability = analyze_reliability(result, alpha=alpha, power=power)
        _attach_reliability(result)
    return result


def _rank_diagnostics(
    network: GnssNetwork,
    index: GnssParameterIndex,
    A: np.ndarray,
    rank: int,
) -> List[str]:
    messages: List[str] = []
    if not network.fixed_points:
        messages.append("没有固定点")
    if A.shape[1] and A.size:
        unobserved = [
            name
            for name, cols in index.point_columns.items()
            if not np.any(np.abs(A[:, list(cols)]) > 0.0)
        ]
        if unobserved:
            messages.append("无观测连接的点：" + "、".join(unobserved))
    if rank < index.size and index.size:
        messages.append("检查基线连通性、固定点数量或地面观测是否足以定义基准")
    return messages


def _point_block(
    result: GnssAdjustmentResult, name: str
) -> Optional[Tuple[int, int, int]]:
    return result.index.point_columns.get(name)


def _point_cov_enu(result: GnssAdjustmentResult, name: str) -> np.ndarray:
    cols = _point_block(result, name)
    if cols is None:
        return np.zeros((3, 3), dtype=float)
    block = result.Cx[np.ix_(list(cols), list(cols))]
    if result.parameter_frame == "ENU":
        return np.asarray(block, dtype=float)
    r = result.rotation_ecef_to_enu
    return r @ block @ r.T


def _point_cov_ecef(result: GnssAdjustmentResult, name: str) -> np.ndarray:
    cols = _point_block(result, name)
    if cols is None:
        return np.zeros((3, 3), dtype=float)
    block = result.Cx[np.ix_(list(cols), list(cols))]
    if result.parameter_frame == "ECEF":
        return np.asarray(block, dtype=float)
    r = result.rotation_ecef_to_enu
    return r.T @ block @ r


def _cross_cov_enu(result: GnssAdjustmentResult, a: str, b: str) -> np.ndarray:
    ca = _point_block(result, a)
    cb = _point_block(result, b)
    if ca is None or cb is None:
        return np.zeros((3, 3), dtype=float)
    block = result.Cx[np.ix_(list(ca), list(cb))]
    if result.parameter_frame == "ENU":
        return np.asarray(block, dtype=float)
    r = result.rotation_ecef_to_enu
    return r @ block @ r.T


def _fill_point_precisions(
    result: GnssAdjustmentResult, enu: Mapping[str, np.ndarray]
) -> None:
    network = result.network
    for point in network.points:
        C_enu = _point_cov_enu(result, point.name)
        C_ecef = _point_cov_ecef(result, point.name)
        e, n, u = (float(v) for v in enu[point.name])
        sigma_E = sqrt(max(float(C_enu[0, 0]), 0.0))
        sigma_N = sqrt(max(float(C_enu[1, 1]), 0.0))
        sigma_U = sqrt(max(float(C_enu[2, 2]), 0.0))
        sigma_X = sqrt(max(float(C_ecef[0, 0]), 0.0))
        sigma_Y = sqrt(max(float(C_ecef[1, 1]), 0.0))
        sigma_Z = sqrt(max(float(C_ecef[2, 2]), 0.0))
        mp = hypot(sigma_E, sigma_N)
        m3d = sqrt(max(float(np.trace(C_ecef)), 0.0))
        ellipse = ellipse_from_cov(C_enu[:2, :2], None)
        H_normal = None
        sigma_H_normal = None
        if network.geoid is not None and hasattr(network.geoid, "zeta"):
            H_normal = float(point.h - network.geoid.zeta(e, n))
            zeta_sigma = 0.0
            if hasattr(network.geoid, "zeta_sigma"):
                zeta_sigma = float(network.geoid.zeta_sigma(e, n))
            sigma_H_normal = sqrt(sigma_U * sigma_U + zeta_sigma * zeta_sigma)
        result.points[point.name] = GnssPointPrecision(
            name=point.name,
            fixed=point.fixed,
            E=e,
            N=n,
            U=u,
            X=float(point.xyz[0]),
            Y=float(point.xyz[1]),
            Z=float(point.xyz[2]),
            lat=float(point.lat),
            lon=float(point.lon),
            h=float(point.h),
            sigma_E=sigma_E,
            sigma_N=sigma_N,
            sigma_U=sigma_U,
            sigma_X=sigma_X,
            sigma_Y=sigma_Y,
            sigma_Z=sigma_Z,
            mp_horizontal=mp,
            m3D=m3d,
            ellipse=ellipse,
            covariance_enu=np.asarray(C_enu, dtype=float),
            covariance_ecef=np.asarray(C_ecef, dtype=float),
            H_normal=H_normal,
            sigma_H_normal=sigma_H_normal,
        )


def _fill_baseline_precisions(
    result: GnssAdjustmentResult, enu: Mapping[str, np.ndarray]
) -> None:
    for baseline in result.network.baselines:
        f, t = baseline.frm, baseline.to
        delta = enu[t] - enu[f]
        C = (
            _point_cov_enu(result, f)
            + _point_cov_enu(result, t)
            - _cross_cov_enu(result, f, t)
            - _cross_cov_enu(result, t, f)
        )
        C = 0.5 * (C + C.T)
        length_3d = float(np.linalg.norm(delta))
        if length_3d <= 0.0:
            raise InvalidGeometryError(f"基线 {f}-{t} 的平差后长度为 0")
        g3 = delta / length_3d
        sigma_3d = sqrt(max(float(g3 @ C @ g3), 0.0))
        h = hypot(float(delta[0]), float(delta[1]))
        if h > 0.0:
            g2 = np.array([delta[0] / h, delta[1] / h, 0.0], dtype=float)
            sigma_h = sqrt(max(float(g2 @ C @ g2), 0.0))
        else:
            sigma_h = 0.0
        sigma_u = sqrt(max(float(C[2, 2]), 0.0))
        result.baselines[f"{f}-{t}"] = GnssBaselinePrecision(
            frm=f,
            to=t,
            delta_enu=np.asarray(delta, dtype=float),
            covariance_enu=np.asarray(C, dtype=float),
            length_3d=length_3d,
            sigma_3d=sigma_3d,
            horizontal_length=h,
            sigma_horizontal=sigma_h,
            sigma_vertical=sigma_u,
        )


def _attach_reliability(result: GnssAdjustmentResult) -> None:
    rel = result.reliability
    if rel is None:
        return
    for baseline in result.baselines.values():
        record = rel.by_label.get(baseline.label)
        if record is None:
            continue
        baseline.r_i = record.r_i
        baseline.mdb = record.mdb
        baseline.r_components = record.r_components
        baseline.mdb_components = record.mdb_components


# 别名，便于与其他模块的 solve 命名一致。
gnss = solve_gnss
solve_gnss_network = solve_gnss


# ---------------------------------------------------------------------------
# 高程异常：常数/平面拟合
# ---------------------------------------------------------------------------
def _coerce_geoid_point(sample: Any, index: int) -> "GeoidControlPoint":
    if isinstance(sample, GeoidControlPoint):
        return sample
    if isinstance(sample, Mapping):
        try:
            return GeoidControlPoint(
                name=str(sample.get("name", f"G{index + 1}")),
                E=sample["E"],
                N=sample["N"],
                h=sample["h"],
                H=sample["H"],
            )
        except KeyError as exc:
            raise ValueError(f"高程异常样本缺少字段 {exc.args[0]!r}") from exc
    if isinstance(sample, (tuple, list)):
        if len(sample) == 5:
            name, E, N, h, H = sample
        elif len(sample) == 4:
            name = f"G{index + 1}"
            E, N, h, H = sample
        else:
            raise ValueError("高程异常样本元组必须为 (name,E,N,h,H) 或 (E,N,h,H)")
        return GeoidControlPoint(name=name, E=E, N=N, h=h, H=H)
    raise TypeError(f"不支持的高程异常样本类型：{type(sample)!r}")


@dataclass
class GeoidControlPoint:
    """同时具有大地高 h 和正常高 H 的高程异常控制点。"""

    name: str
    E: float
    N: float
    h: float
    H: float

    def __post_init__(self) -> None:
        self.name = str(self.name)
        self.E = _finite(self.E, f"点 {self.name} 的 E")
        self.N = _finite(self.N, f"点 {self.name} 的 N")
        self.h = _finite(self.h, f"点 {self.name} 的大地高 h")
        self.H = _finite(self.H, f"点 {self.name} 的正常高 H")

    @property
    def zeta(self) -> float:
        return self.h - self.H


@dataclass
class GeoidFitResult:
    """高程异常 ζ=h−H 的常数/平面近似结果。

    注意：这是**局部近似**，不是 geoid 模型。平面模型仅由控制点决定，
    离开控制点覆盖范围外推会迅速失效；报告必须保留该声明。
    """

    mode: str
    parameters: np.ndarray
    covariance: np.ndarray
    residuals: np.ndarray
    point_names: List[str]
    E: np.ndarray
    N: np.ndarray
    h: np.ndarray
    H: np.ndarray
    zeta_values: np.ndarray
    sigma0: float
    dof: int
    center_E: float
    center_N: float
    extent_m: float
    variance_factor_source: str = "estimated"

    @property
    def n(self) -> int:
        return int(self.zeta_values.size)

    @property
    def a(self) -> float:
        return float(self.parameters[0])

    @property
    def b(self) -> float:
        return float(self.parameters[1]) if self.mode == "plane" else 0.0

    @property
    def c(self) -> float:
        return float(self.parameters[2]) if self.mode == "plane" else 0.0

    @property
    def params(self) -> np.ndarray:
        return self.parameters

    @property
    def param_cov(self) -> np.ndarray:
        return self.covariance

    @property
    def parameter_sigmas(self) -> np.ndarray:
        return np.sqrt(np.maximum(np.diag(self.covariance), 0.0))

    @property
    def sigma_a(self) -> float:
        return float(self.parameter_sigmas[0])

    @property
    def sigma_b(self) -> float:
        return float(self.parameter_sigmas[1]) if self.mode == "plane" else 0.0

    @property
    def sigma_c(self) -> float:
        return float(self.parameter_sigmas[2]) if self.mode == "plane" else 0.0

    @property
    def rms(self) -> float:
        return float(np.sqrt(np.mean(np.square(self.residuals)))) if self.n else 0.0

    @property
    def max_abs_residual(self) -> float:
        return float(np.max(np.abs(self.residuals))) if self.n else 0.0

    @property
    def residuals_mm(self) -> np.ndarray:
        return self.residuals * 1e3

    @property
    def applicability_note(self) -> str:
        span_km = self.extent_m / 1e3
        return (
            "近似，仅适用于小范围：本模型由局部控制点拟合，控制点最大间距约 "
            f"{span_km:.2f} km（等效覆盖半径约 {span_km / 2.0:.2f} km）；"
            "不得跨出控制点范围外推，也不得替代 EGM/似大地水准面模型。"
        )

    def zeta(self, E: Any, N: Any) -> Any:
        """在工程平面坐标 (E,N) 处计算高程异常（米）。"""
        e_arr = np.asarray(E, dtype=float)
        n_arr = np.asarray(N, dtype=float)
        if self.mode == "constant":
            out = np.full(np.broadcast(e_arr, n_arr).shape, self.a, dtype=float)
        else:
            out = self.a + self.b * e_arr + self.c * n_arr
        if np.ndim(out) == 0:
            return float(out)
        return out

    def height_anomaly(self, E: Any, N: Any) -> Any:
        return self.zeta(E, N)

    def predict(self, E: Any, N: Any) -> Any:
        return self.zeta(E, N)

    def zeta_gradient(self, E: Any, N: Any) -> np.ndarray:
        if self.mode == "constant":
            return np.array([1.0, 0.0, 0.0], dtype=float)
        return np.array([1.0, float(E), float(N)], dtype=float)

    def zeta_sigma(self, E: Any, N: Any) -> Any:
        """由拟合参数协方差传播的 ζ 中误差（米，不含模型系统误差）。"""
        if np.ndim(E) == 0 and np.ndim(N) == 0:
            g = self.zeta_gradient(E, N)
            return float(sqrt(max(float(g @ self.covariance @ g), 0.0)))
        e_arr, n_arr = np.broadcast_arrays(np.asarray(E, dtype=float), np.asarray(N, dtype=float))
        C = self.covariance
        if self.mode == "constant":
            var = np.full(e_arr.shape, C[0, 0], dtype=float)
        else:
            # g=[1,E,N]；逐元素传播。
            var = (
                C[0, 0]
                + 2.0 * C[0, 1] * e_arr
                + 2.0 * C[0, 2] * n_arr
                + C[1, 1] * e_arr * e_arr
                + 2.0 * C[1, 2] * e_arr * n_arr
                + C[2, 2] * n_arr * n_arr
            )
        return np.sqrt(np.maximum(var, 0.0))

    def normal_height(
        self, h: Any, E: Any, N: Any, sigma_h: Optional[Any] = None
    ) -> Any:
        """由大地高 h 计算正常高 H=h−ζ；给出 ``sigma_h`` 时返回 (H, σ_H)。"""
        h_arr = np.asarray(h, dtype=float)
        H = h_arr - np.asarray(self.zeta(E, N), dtype=float)
        if sigma_h is None:
            if np.ndim(H) == 0:
                return float(H)
            return H
        sigma_h_arr = np.asarray(sigma_h, dtype=float)
        sigma_zeta = np.asarray(self.zeta_sigma(E, N), dtype=float)
        sigma_H = np.sqrt(np.square(sigma_h_arr) + np.square(sigma_zeta))
        if np.ndim(H) == 0:
            return float(H), float(sigma_H)
        return H, sigma_H

    def to_normal_height(self, h: Any, E: Any, N: Any, sigma_h: Optional[Any] = None) -> Any:
        return self.normal_height(h, E, N, sigma_h)

    def ellipsoidal_height(self, H: Any, E: Any, N: Any) -> Any:
        out = np.asarray(H, dtype=float) + np.asarray(self.zeta(E, N), dtype=float)
        if np.ndim(out) == 0:
            return float(out)
        return out

    def as_dict(self) -> Dict[str, Any]:
        return {
            "mode": self.mode,
            "a_m": self.a,
            "b_ppm": self.b * 1e6,
            "c_ppm": self.c * 1e6,
            "sigma_a_mm": self.sigma_a * 1e3,
            "sigma_b_ppm": self.sigma_b * 1e6,
            "sigma_c_ppm": self.sigma_c * 1e6,
            "sigma0_mm": self.sigma0 * 1e3,
            "rms_mm": self.rms * 1e3,
            "max_abs_residual_mm": self.max_abs_residual * 1e3,
            "n": self.n,
            "dof": self.dof,
            "extent_km": self.extent_m / 1e3,
        }


def _normalize_geoid_mode(mode: Any) -> str:
    key = str(mode).strip().lower()
    if key in ("constant", "const", "常数", "固定"):
        return "constant"
    if key in ("plane", "planar", "linear", "平面", "线性"):
        return "plane"
    raise ValueError(f"高程异常模型只能是 'constant' 或 'plane'，收到 {mode!r}")


def fit_height_anomaly(
    samples: Iterable[Any],
    mode: str = "plane",
    *,
    variance_factor: Optional[float] = None,
) -> GeoidFitResult:
    """拟合 ζ=h−H 的常数或平面模型 ``ζ=a+bE+cN``。

    Parameters
    ----------
    samples:
        :class:`GeoidControlPoint`、含 ``name/E/N/h/H`` 的映射，或
        ``(name,E,N,h,H)`` / ``(E,N,h,H)`` 元组。
    mode:
        ``'constant'`` 或 ``'plane'``。
    variance_factor:
        已知单位权方差 σ0²；省略时由残差估计（dof>0），dof=0 时取 1。
        该值只影响参数协方差，不影响参数估值。

    返回 :class:`GeoidFitResult`，包含参数、参数协方差、残差、RMS 与适用范围声明。
    """
    mode_key = _normalize_geoid_mode(mode)
    points = [_coerce_geoid_point(sample, i) for i, sample in enumerate(samples)]
    n = len(points)
    need = 1 if mode_key == "constant" else 3
    if n < need:
        raise InvalidPrecisionError(
            f"{mode_key} 高程异常模型至少需要 {need} 个控制点，收到 {n} 个"
        )
    if len({p.name for p in points}) != n:
        raise ValueError("高程异常控制点点名重复")
    E = np.array([p.E for p in points], dtype=float)
    N = np.array([p.N for p in points], dtype=float)
    h = np.array([p.h for p in points], dtype=float)
    H = np.array([p.H for p in points], dtype=float)
    zeta = h - H
    center_E = float(np.mean(E))
    center_N = float(np.mean(N))
    dE = E - center_E
    dN = N - center_N
    if mode_key == "constant":
        A = np.ones((n, 1), dtype=float)
    else:
        A = np.column_stack([np.ones(n), dE, dN])
    if np.linalg.matrix_rank(A) < A.shape[1]:
        raise InvalidGeometryError(
            "高程异常平面拟合的控制点退化（共线或重合），无法唯一确定 a+bE+cN"
        )
    beta_centered, *_ = np.linalg.lstsq(A, zeta, rcond=None)
    residuals = zeta - A @ beta_centered
    dof = n - A.shape[1]
    if variance_factor is not None:
        vf = _finite(variance_factor, "单位权方差 variance_factor")
        if vf <= 0.0:
            raise InvalidPrecisionError("variance_factor 必须为正")
        sigma0_sq = vf
        source = "given"
    elif dof > 0:
        sigma0_sq = float(residuals @ residuals / dof)
        source = "estimated"
    else:
        sigma0_sq = 1.0
        source = "a_priori"
    sigma0 = sqrt(max(sigma0_sq, 0.0))
    normal = A.T @ A
    try:
        C_centered = sigma0_sq * np.linalg.inv(normal)
    except np.linalg.LinAlgError as exc:  # pragma: no cover - rank 已检查
        raise InvalidGeometryError("高程异常法方程奇异") from exc
    if mode_key == "plane":
        transform = np.array(
            [[1.0, -center_E, -center_N], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]],
            dtype=float,
        )
        parameters = transform @ beta_centered
        covariance = transform @ C_centered @ transform.T
    else:
        parameters = np.asarray(beta_centered, dtype=float)
        covariance = np.asarray(C_centered, dtype=float)
    covariance = 0.5 * (covariance + covariance.T)
    span = 0.0
    if n > 1:
        span = float(
            np.max(
                np.hypot(E[:, None] - E[None, :], N[:, None] - N[None, :])
            )
        )
    return GeoidFitResult(
        mode=mode_key,
        parameters=parameters,
        covariance=covariance,
        residuals=residuals,
        point_names=[p.name for p in points],
        E=E,
        N=N,
        h=h,
        H=H,
        zeta_values=zeta,
        sigma0=sigma0,
        dof=dof,
        center_E=center_E,
        center_N=center_N,
        extent_m=span,
        variance_factor_source=source,
    )


# 兼容更直观的命名
fit_geoid = fit_height_anomaly
fit_geoid_model = fit_height_anomaly
fit_geoid_plane = fit_height_anomaly

# 3D 命名的显式别名，便于调用方区分二维 GnssBaseline2D。
GnssPoint3D = GnssPoint
GnssBaseline3D = GnssBaseline
GnssNetwork3D = GnssNetwork
GeoidFit = GeoidFitResult


# ---------------------------------------------------------------------------
# 可选：EGM96/EGM2008 格网插值
# ---------------------------------------------------------------------------
@dataclass
class EGMGrid:
    """小型 geoid 格网（PROJ-data GeoTIFF，如 ``us_nga_egm96_15.tif``）。

    格网值按米解释，采用双线性插值；本类故意不绑定下载地址，调用方负责
    获取公开格网（演示脚本提供下载/裁剪辅助）。
    """

    data: np.ndarray
    transform: Tuple[float, float, float, float, float, float]
    crs: str
    path: str = ""
    nodata: Optional[float] = None

    @classmethod
    def from_geotiff(cls, path: Union[str, Any]) -> "EGMGrid":
        try:
            import rasterio
        except ImportError as exc:  # pragma: no cover - 依赖缺失
            raise ImportError(
                "读取 geoid GeoTIFF 需要 rasterio；请安装 .[terrain] 或 .[test]"
            ) from exc
        with rasterio.open(path) as ds:
            data = ds.read(1).astype(float)
            nodata = ds.nodata
            if nodata is not None and np.isfinite(nodata):
                data = np.where(data == nodata, np.nan, data)
            transform = tuple(float(v) for v in ds.transform)[:6]
            crs = "" if ds.crs is None else str(ds.crs)
        return cls(
            data=data,
            transform=transform,  # type: ignore[arg-type]
            crs=crs,
            path=str(path),
            nodata=None if nodata is None else float(nodata),
        )

    @property
    def shape(self) -> Tuple[int, int]:
        return int(self.data.shape[0]), int(self.data.shape[1])

    def _fractional_index(self, lon: float, lat: float) -> Tuple[float, float]:
        a, b, c, d, e, f = self.transform
        det = a * e - b * d
        if abs(det) < 1e-30:
            raise ValueError("geoid 格网仿射变换退化")
        dx = lon - c
        dy = lat - f
        col_corner = (e * dx - b * dy) / det
        row_corner = (-d * dx + a * dy) / det
        # GeoTIFF 仿射给的是像素角点；数据值位于像素中心，故减 0.5。
        return row_corner - 0.5, col_corner - 0.5

    def undulation(self, lon: Any, lat: Any) -> Any:
        """在经纬度处双线性插值 geoid 起伏/高程异常（米）。"""
        lon_f = float(lon)
        lat_f = float(lat)
        if not (isfinite(lon_f) and isfinite(lat_f)):
            raise ValueError("经纬度必须是有限值")
        row_f, col_f = self._fractional_index(lon_f, lat_f)
        h, w = self.shape
        # 数据值在像素中心；格网外边界对应中心索引 −0.5 / n−0.5。
        if not (-0.5 <= row_f <= h - 0.5 and -0.5 <= col_f <= w - 0.5):
            raise ValueError(
                f"格网不覆盖 ({lon_f}, {lat_f})；格网范围见 transform/bounds"
            )
        r0 = min(max(int(floor(row_f)), 0), h - 1)
        c0 = min(max(int(floor(col_f)), 0), w - 1)
        r1 = min(r0 + 1, h - 1)
        c1 = min(c0 + 1, w - 1)
        fr = min(max(row_f - r0, 0.0), 1.0)
        fc = min(max(col_f - c0, 0.0), 1.0)
        values = np.array(
            [
                self.data[r0, c0],
                self.data[r0, c1],
                self.data[r1, c0],
                self.data[r1, c1],
            ],
            dtype=float,
        )
        if not np.all(np.isfinite(values)):
            return float("nan")
        top = values[0] * (1.0 - fc) + values[1] * fc
        bottom = values[2] * (1.0 - fc) + values[3] * fc
        return float(top * (1.0 - fr) + bottom * fr)

    def zeta(self, lon: Any, lat: Any) -> Any:
        return self.undulation(lon, lat)

    def height_anomaly(self, lon: Any, lat: Any) -> Any:
        return self.undulation(lon, lat)

    def interpolate(self, lon: Any, lat: Any) -> Any:
        return self.undulation(lon, lat)

    def __call__(self, lon: Any, lat: Any) -> Any:
        return self.undulation(lon, lat)


__all__ = [
    "WGS84_A",
    "WGS84_F",
    "WGS84_B",
    "WGS84_E2",
    "geodetic_to_ecef",
    "ecef_to_geodetic",
    "ecef_to_enu_matrix",
    "enu_to_ecef_matrix",
    "ecef_to_enu_rotation",
    "enu_to_ecef_rotation",
    "ecef_to_enu",
    "enu_to_ecef",
    "geodetic_to_enu",
    "covariance_enu_to_ecef",
    "covariance_ecef_to_enu",
    "GnssPoint",
    "GnssBaseline",
    "GnssCovarianceBlock",
    "GnssNetwork",
    "GnssPoint3D",
    "GnssBaseline3D",
    "GnssNetwork3D",
    "GnssParameterIndex",
    "GnssDesignSystem",
    "GnssPointPrecision",
    "GnssBaselinePrecision",
    "GnssAdjustmentResult",
    "solve_gnss",
    "solve_gnss_network",
    "gnss",
    "GeoidControlPoint",
    "GeoidFitResult",
    "fit_height_anomaly",
    "fit_geoid",
    "fit_geoid_model",
    "fit_geoid_plane",
    "GeoidFit",
    "EGMGrid",
]
