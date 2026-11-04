"""一维水准/高程网设计态精度与可靠性。

本模块实现 ``docs/redesign_plan.md`` §5.9 的 MVP 部分：

- 水准点高程 ``H``：固定、待定或加权约束（``sigma_H``，单位米）；
- 水准高差观测 ``Δh_ij = H_j - H_i``，随机模型支持
  ``σ = σ_km·sqrt(L)``（mm/√km）与 ``σ = σ_station·sqrt(n)``（mm/√站）；
- 三角高程：由斜距/平距、天顶距、仪器高、目标高与折光系数计算高差，
  并按误差传播给出高差标准差；
- 设计态最小二乘：``Cx``、每点高程中误差、相对高差中误差、``r_i``、
  MDB 与外部可靠性；
- 无高程基准时抛 :class:`RankDeficientError`；可选自由网最小约束（伪逆）。

单位约定：内部高程/高差为米，标准差为米；输入 ``sigma_*_mm`` 为毫米，
天顶距默认用度，也可显式给弧度。正常高/大地高只是属性字段，
MVP 不做 geoid/高程异常转换。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from math import cos, isfinite, pi, sin, sqrt, tan
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple, Union

import numpy as np

from .exceptions import InvalidGeometryError, InvalidPrecisionError, RankDeficientError
from .reliability import LAMBDA0_DEFAULT, noncentrality

ARCSEC_TO_RAD = pi / (180.0 * 3600.0)
HEIGHT_TYPES = ("normal", "orthometric", "ellipsoidal", "geoid", "unknown")
_HEIGHT_TYPE_ALIASES = {
    "正常高": "normal",
    "正高": "orthometric",
    "大地高": "ellipsoidal",
    "椭球高": "ellipsoidal",
    "geoid": "geoid",
    "未知": "unknown",
}


def _point_ref_name(ref: Any) -> str:
    if isinstance(ref, str):
        return ref
    name = getattr(ref, "name", None)
    if isinstance(name, str):
        return name
    raise TypeError(f"点引用必须是 str 或带 name 属性的点对象，收到 {type(ref)!r}")


def _normalize_height_type(value: Any) -> str:
    if value is None:
        return "normal"
    text = str(value).strip()
    key = text.lower()
    key = _HEIGHT_TYPE_ALIASES.get(text, _HEIGHT_TYPE_ALIASES.get(key, key))
    if key not in HEIGHT_TYPES:
        raise ValueError(
            f"未知高程类型 {value!r}；可选 {', '.join(HEIGHT_TYPES)} "
            "或 正常高/正高/大地高"
        )
    return key


def _finite(value: Any, what: str) -> float:
    try:
        out = float(value)
    except (TypeError, ValueError) as exc:
        raise InvalidPrecisionError(f"{what} 必须是数值，收到 {value!r}") from exc
    if not isfinite(out):
        raise InvalidPrecisionError(f"{what} 必须是有限值，收到 {value!r}")
    return out


def _positive(value: Any, what: str, *, allow_zero: bool = False) -> float:
    out = _finite(value, what)
    if allow_zero:
        if out < 0.0:
            raise InvalidPrecisionError(f"{what} 不能为负，收到 {out!r}")
    elif out <= 0.0:
        raise InvalidPrecisionError(f"{what} 必须为正，收到 {out!r}")
    return out


@dataclass
class LevelingPoint:
    """水准/高程点。

    ``fixed=True`` 为精确固定高程点，求解时从参数中剔除；``sigma_H``（米）
    表示该点高程的加权约束伪观测标准差。``height_type`` 仅记录高程类型
    （正常高/正高/大地高），本模块不做高程基准转换。
    """

    name: str
    H: float
    fixed: bool = False
    sigma_H: Optional[float] = None
    height_type: str = "normal"

    def __post_init__(self) -> None:
        self.name = str(self.name)
        if not self.name:
            raise ValueError("点名不能为空")
        self.H = _finite(self.H, f"点 {self.name!r} 的高程 H")
        self.fixed = bool(self.fixed)
        if self.sigma_H is not None:
            self.sigma_H = _positive(self.sigma_H, f"点 {self.name!r} 的 sigma_H")
        self.height_type = _normalize_height_type(self.height_type)

    @property
    def role(self) -> str:
        if self.fixed:
            return "fixed"
        if self.sigma_H is not None:
            return "constrained"
        return "unknown"

    @property
    def is_weighted(self) -> bool:
        return self.sigma_H is not None


@dataclass
class HeightDifference:
    """水准测段高差观测 ``Δh = H_to - H_from``。

    标准差优先顺序：

    1. 显式 ``sigma_mm``（单段标准差，毫米）；
    2. ``n_stations`` + ``sigma_per_station_mm``：``σ = σ_station·sqrt(n)``；
    3. ``length_km`` + ``sigma_per_km_mm``：``σ = σ_km·sqrt(L)``。

    后两种同时给出时优先按测站数。``length_km`` 与 ``n_stations`` 仅作为
    路线属性保留，报告可追溯。
    """

    frm: Any
    to: Any
    delta_h: float
    length_km: Optional[float] = None
    sigma_per_km_mm: float = 1.0
    n_stations: Optional[int] = None
    sigma_per_station_mm: Optional[float] = None
    sigma_mm: Optional[float] = None
    label: str = ""
    height_type: str = "normal"

    kind = "leveling"

    def __post_init__(self) -> None:
        self.frm = _point_ref_name(self.frm)
        self.to = _point_ref_name(self.to)
        if self.frm == self.to:
            raise InvalidGeometryError(
                f"水准测段两端点不能相同：{self.frm!r}"
            )
        self.delta_h = _finite(self.delta_h, "水准高差 delta_h")
        if self.length_km is not None:
            self.length_km = _positive(
                self.length_km, f"{self.frm}-{self.to} 的 length_km"
            )
        self.sigma_per_km_mm = _positive(
            self.sigma_per_km_mm, f"{self.frm}-{self.to} 的 sigma_per_km_mm"
        )
        if self.n_stations is not None:
            n = _finite(self.n_stations, "n_stations")
            if abs(n - round(n)) > 1e-9 or n <= 0:
                raise InvalidPrecisionError(
                    f"n_stations 必须为正整数，收到 {self.n_stations!r}"
                )
            self.n_stations = int(round(n))
        if self.sigma_per_station_mm is not None:
            self.sigma_per_station_mm = _positive(
                self.sigma_per_station_mm,
                f"{self.frm}-{self.to} 的 sigma_per_station_mm",
            )
        if self.sigma_mm is not None:
            self.sigma_mm = _positive(
                self.sigma_mm, f"{self.frm}-{self.to} 的 sigma_mm"
            )
        self.label = str(self.label) if self.label else f"{self.frm}-{self.to}"
        self.height_type = _normalize_height_type(self.height_type)

    @property
    def referenced_points(self) -> Tuple[str, str]:
        return (self.frm, self.to)

    @property
    def mode(self) -> str:
        if self.sigma_mm is not None:
            return "explicit"
        if self.n_stations is not None and self.sigma_per_station_mm is not None:
            return "station"
        if self.length_km is not None:
            return "length"
        return "invalid"

    @property
    def sigma(self) -> float:
        """单段高差先验标准差（米）。"""
        if self.sigma_mm is not None:
            return self.sigma_mm * 1e-3
        if self.n_stations is not None and self.sigma_per_station_mm is not None:
            return self.sigma_per_station_mm * 1e-3 * sqrt(self.n_stations)
        if self.length_km is not None:
            return self.sigma_per_km_mm * 1e-3 * sqrt(self.length_km)
        raise InvalidPrecisionError(
            f"测段 {self.label!r} 未给出可计算标准差的信息；"
            "请提供 sigma_mm、length_km 或 n_stations+sigma_per_station_mm"
        )

    @property
    def variance(self) -> float:
        sigma = self.sigma
        return sigma * sigma

    @property
    def weight(self) -> float:
        return 1.0 / self.variance

    @property
    def sigma_mm_value(self) -> float:
        return self.sigma * 1e3

    def __str__(self) -> str:  # pragma: no cover - 便于交互调试
        return f"HeightDifference({self.label}, Δh={self.delta_h:+.4f} m)"


# 语义更明确的别名，便于从模型层按“观测”命名。
LevelingObservation = HeightDifference
HeightObservation = HeightDifference


@dataclass
class TrigHeight:
    """三角高程观测（单向）。

    斜距形式（天顶距 ``z`` 从铅垂方向起算，单位弧度）::

        Δh = S·cos(z) + (1-k)·S²·sin²(z)/(2R) + i - v

    平距形式 ``D`` 等价于 ``S = D/sin(z)``::

        Δh = D·cot(z) + (1-k)·D²/(2R) + i - v

    天顶距用 ``zenith_deg`` 或 ``zenith_rad`` 二选一；距离用
    ``slope_distance`` 或 ``horizontal_distance`` 二选一。标准差参数均为
    1σ，角度用角秒，长度/仪器高/目标高用毫米。``sigma_k`` 为无量纲的
    折光系数标准差，可选。
    """

    frm: Any
    to: Any
    slope_distance: Optional[float] = None
    horizontal_distance: Optional[float] = None
    zenith_deg: Optional[float] = None
    zenith_rad: Optional[float] = None
    instrument_height: float = 0.0
    target_height: float = 0.0
    k: float = 0.13
    R: float = 6371000.0
    sigma_zenith_arcsec: float = 1.0
    sigma_slope_mm: float = 1.0
    sigma_horizontal_mm: Optional[float] = None
    sigma_instrument_mm: float = 1.0
    sigma_target_mm: float = 1.0
    sigma_k: Optional[float] = None
    label: str = ""
    height_type: str = "normal"

    kind = "trig_height"

    def __post_init__(self) -> None:
        self.frm = _point_ref_name(self.frm)
        self.to = _point_ref_name(self.to)
        if self.frm == self.to:
            raise InvalidGeometryError(f"三角高程两端点不能相同：{self.frm!r}")
        if (self.slope_distance is None) == (self.horizontal_distance is None):
            raise InvalidPrecisionError(
                "三角高程必须且只能给出 slope_distance 或 horizontal_distance 之一"
            )
        if self.slope_distance is not None:
            self.slope_distance = _positive(self.slope_distance, "slope_distance")
        if self.horizontal_distance is not None:
            self.horizontal_distance = _positive(
                self.horizontal_distance, "horizontal_distance"
            )
        if (self.zenith_deg is None) == (self.zenith_rad is None):
            raise InvalidPrecisionError(
                "三角高程必须且只能给出 zenith_deg 或 zenith_rad 之一"
            )
        if self.zenith_deg is not None:
            z = float(self.zenith_deg)
            if not isfinite(z) or not (0.0 < z < 180.0):
                raise InvalidPrecisionError(f"zenith_deg 必须在 (0,180) 内，收到 {z!r}")
            self.zenith_deg = z
        if self.zenith_rad is not None:
            z = float(self.zenith_rad)
            if not isfinite(z) or not (0.0 < z < pi):
                raise InvalidPrecisionError(f"zenith_rad 必须在 (0,π) 内，收到 {z!r}")
            self.zenith_rad = z
        self.instrument_height = _finite(self.instrument_height, "instrument_height")
        self.target_height = _finite(self.target_height, "target_height")
        self.k = _finite(self.k, "折光系数 k")
        self.R = _positive(self.R, "地球曲率半径 R")
        self.sigma_zenith_arcsec = _positive(
            self.sigma_zenith_arcsec, "sigma_zenith_arcsec", allow_zero=True
        )
        self.sigma_slope_mm = _positive(
            self.sigma_slope_mm, "sigma_slope_mm", allow_zero=True
        )
        if self.sigma_horizontal_mm is None:
            self.sigma_horizontal_mm = self.sigma_slope_mm
        else:
            self.sigma_horizontal_mm = _positive(
                self.sigma_horizontal_mm, "sigma_horizontal_mm", allow_zero=True
            )
        self.sigma_instrument_mm = _positive(
            self.sigma_instrument_mm, "sigma_instrument_mm", allow_zero=True
        )
        self.sigma_target_mm = _positive(
            self.sigma_target_mm, "sigma_target_mm", allow_zero=True
        )
        if self.sigma_k is not None:
            self.sigma_k = _positive(self.sigma_k, "sigma_k", allow_zero=True)
        self.label = str(self.label) if self.label else f"{self.frm}-{self.to}"
        self.height_type = _normalize_height_type(self.height_type)

    @property
    def referenced_points(self) -> Tuple[str, str]:
        return (self.frm, self.to)

    # 与 §5.9/数据模型字段命名对齐的只读别名，便于报告和导入层使用。
    @property
    def slope_distance_m(self) -> Optional[float]:
        return self.slope_distance

    @property
    def horizontal_distance_m(self) -> Optional[float]:
        return self.horizontal_distance

    @property
    def instrument_height_m(self) -> float:
        return self.instrument_height

    @property
    def target_height_m(self) -> float:
        return self.target_height

    @property
    def refraction_k(self) -> float:
        return self.k

    @property
    def vertical_angle_rad(self) -> float:
        """竖直角（从水平方向起算，弧度），与天顶距 z 满足 α=π/2-z。"""
        return pi / 2.0 - self.zenith_angle_rad

    @property
    def zenith_angle_rad(self) -> float:
        if self.zenith_rad is not None:
            return float(self.zenith_rad)
        assert self.zenith_deg is not None
        return self.zenith_deg * pi / 180.0

    @property
    def zenith_angle_deg(self) -> float:
        if self.zenith_deg is not None:
            return float(self.zenith_deg)
        assert self.zenith_rad is not None
        return self.zenith_rad * 180.0 / pi

    @property
    def slope_distance_value(self) -> float:
        if self.slope_distance is not None:
            return float(self.slope_distance)
        assert self.horizontal_distance is not None
        return float(self.horizontal_distance) / sin(self.zenith_angle_rad)

    @property
    def horizontal_distance_value(self) -> float:
        if self.horizontal_distance is not None:
            return float(self.horizontal_distance)
        return self.slope_distance_value * sin(self.zenith_angle_rad)

    @property
    def distance_mode(self) -> str:
        return "slope" if self.slope_distance is not None else "horizontal"

    @property
    def curvature_correction(self) -> float:
        """球气差改正项 ``(1-k)·D²/(2R)``，米；正值抬高目标高差。"""
        d = self.horizontal_distance_value
        return (1.0 - self.k) * d * d / (2.0 * self.R)

    @property
    def delta_h(self) -> float:
        """由几何量计算的 frm→to 高差（米）。"""
        z = self.zenith_angle_rad
        if self.slope_distance is not None:
            s = float(self.slope_distance)
            return (
                s * cos(z)
                + (1.0 - self.k) * s * s * sin(z) ** 2 / (2.0 * self.R)
                + self.instrument_height
                - self.target_height
            )
        d = self.horizontal_distance_value
        return (
            d / tan(z)
            + (1.0 - self.k) * d * d / (2.0 * self.R)
            + self.instrument_height
            - self.target_height
        )

    @property
    def height_difference(self) -> float:
        return self.delta_h

    @property
    def sigma_distance(self) -> float:
        if self.slope_distance is not None:
            assert self.sigma_slope_mm is not None
            return self.sigma_slope_mm * 1e-3
        assert self.sigma_horizontal_mm is not None
        return self.sigma_horizontal_mm * 1e-3

    def derivatives(self) -> Dict[str, float]:
        """高差对各输入量的偏导。

        ``distance`` 对斜距（斜距模式）或平距（平距模式），单位 m/m；
        ``zenith`` 对天顶距，单位 m/rad；``instrument``/``target`` 为 ±1；
        ``k`` 为 m/无量纲。
        """
        z = self.zenith_angle_rad
        s = self.slope_distance_value
        d = self.horizontal_distance_value
        dk = -(d * d) / (2.0 * self.R)
        if self.slope_distance is not None:
            ddist = cos(z) + (1.0 - self.k) * s * sin(z) ** 2 / self.R
            # S 固定时对天顶距求导（与平距固定时不同）。
            dz = -s * sin(z) + (1.0 - self.k) * s * s * sin(z) * cos(z) / self.R
        else:
            ddist = 1.0 / tan(z) + (1.0 - self.k) * d / self.R
            # 平距固定时 d(cot z)/dz = -csc²z。
            dz = -d / (sin(z) ** 2)
        return {
            "distance": ddist,
            "zenith": dz,
            "instrument": 1.0,
            "target": -1.0,
            "k": dk,
        }

    def sigma_components(self) -> Dict[str, float]:
        """各来源对高差标准差的贡献（米，未合成）。"""
        der = self.derivatives()
        out = {
            "distance": abs(der["distance"]) * self.sigma_distance,
            "zenith": abs(der["zenith"]) * self.sigma_zenith_arcsec * ARCSEC_TO_RAD,
            "instrument": abs(der["instrument"]) * self.sigma_instrument_mm * 1e-3,
            "target": abs(der["target"]) * self.sigma_target_mm * 1e-3,
            "k": 0.0,
        }
        if self.sigma_k is not None:
            out["k"] = abs(der["k"]) * self.sigma_k
        return out

    @property
    def variance(self) -> float:
        return sum(v * v for v in self.sigma_components().values())

    @property
    def sigma(self) -> float:
        """三角高程高差先验标准差（米）。"""
        return sqrt(self.variance)

    @property
    def sigma_mm(self) -> float:
        return self.sigma * 1e3

    @property
    def sigma_mm_value(self) -> float:
        return self.sigma * 1e3

    @property
    def weight(self) -> float:
        return 1.0 / self.variance


@dataclass
class LevelingNetwork:
    """1D 高程网：水准点 + 水准/三角高程观测。"""

    points: Sequence[LevelingPoint]
    observations: Sequence[Union[HeightDifference, TrigHeight]] = field(
        default_factory=list
    )
    name: str = "leveling"

    def __post_init__(self) -> None:
        self.points = list(self.points)
        self.observations = list(self.observations)
        names = [p.name for p in self.points]
        if len(names) != len(set(names)):
            duplicates = sorted({n for n in names if names.count(n) > 1})
            raise InvalidGeometryError(f"点名重复：{', '.join(duplicates)}")
        for obs in self.observations:
            if not isinstance(obs, (HeightDifference, TrigHeight)):
                raise TypeError(
                    "高程网观测必须是 HeightDifference/LevelingObservation "
                    f"或 TrigHeight，收到 {type(obs)!r}"
                )
        self._validate_connections()

    def _validate_connections(self) -> None:
        names = {p.name for p in self.points}
        for obs in self.observations:
            for name in obs.referenced_points:
                if name not in names:
                    raise InvalidGeometryError(
                        f"观测 {obs.label!r} 引用了不存在的点 {name!r}"
                    )

    def point(self, ref: Any) -> LevelingPoint:
        name = _point_ref_name(ref)
        for point in self.points:
            if point.name == name:
                return point
        raise KeyError(f"未知高程点 {name!r}")

    @property
    def point_names(self) -> List[str]:
        return [p.name for p in self.points]

    @property
    def fixed_points(self) -> List[LevelingPoint]:
        return [p for p in self.points if p.fixed]

    def solve(self, datum: Any = None, **kwargs: Any) -> "LevelingResult":
        return solve_leveling(self, datum=datum, **kwargs)


# 更短的高程网别名。
HeightNetwork = LevelingNetwork


@dataclass
class LevelingPointPrecision:
    name: str
    H: float
    sigma: float
    fixed: bool
    constrained: bool
    role: str
    height_type: str = "normal"

    @property
    def sigma_mm(self) -> float:
        return self.sigma * 1e3


@dataclass
class RelativeHeightPrecision:
    frm: str
    to: str
    delta_h: float
    sigma: float

    @property
    def sigma_mm(self) -> float:
        return self.sigma * 1e3

    @property
    def weight(self) -> float:
        return 1.0 / (self.sigma * self.sigma) if self.sigma > 0.0 else float("inf")


@dataclass
class LevelingObservationRecord:
    """单条高程观测（或加权约束）的可靠性结果。"""

    label: str
    kind: str
    sigma: float
    r_i: float
    mdb: float
    external_max: float
    external_point: Optional[str]
    undetectable: bool = False
    observation: Any = None

    @property
    def r(self) -> float:
        return self.r_i

    @property
    def mdb_mm(self) -> float:
        return self.mdb * 1e3

    @property
    def external_max_mm(self) -> float:
        return self.external_max * 1e3

    @property
    def mdb_sigma_ratio(self) -> float:
        return self.mdb / self.sigma if self.sigma > 0.0 else float("inf")


@dataclass
class LevelingReliabilityResult:
    records: List[LevelingObservationRecord]
    lambda0_value: float
    alpha: float
    power: float
    trace_r: float
    redundancy: int

    @property
    def rows(self) -> List[LevelingObservationRecord]:
        return self.records

    @property
    def observation_records(self) -> List[LevelingObservationRecord]:
        return [r for r in self.records if r.kind != "constraint"]

    @property
    def constraint_records(self) -> List[LevelingObservationRecord]:
        return [r for r in self.records if r.kind == "constraint"]

    @property
    def sum_r(self) -> float:
        return sum((row.r_i for row in self.records), 0.0)

    @property
    def min_r(self) -> float:
        return min((row.r_i for row in self.records), default=float("inf"))

    @property
    def max_mdb(self) -> float:
        return max((row.mdb for row in self.records), default=0.0)

    @property
    def by_label(self) -> Dict[str, LevelingObservationRecord]:
        return {row.label: row for row in self.records}

    def __getitem__(self, label: str) -> LevelingObservationRecord:
        return self.by_label[label]


@dataclass
class LevelingResult:
    """1D 高程网设计态解算结果。

    内部单位均为米；``Cx`` 对应 ``unknown_names`` 顺序。固定点/加权约束点
    的高程精度分别由 0 与约束先验给出。``reliability`` 在 solve 后填充。
    """

    network: LevelingNetwork
    datum_kind: str
    datum_summary: str
    point_order: List[str]
    fixed_names: List[str]
    constrained_names: List[str]
    unknown_names: List[str]
    heights: np.ndarray
    Cx: np.ndarray
    A: np.ndarray
    Ql: np.ndarray
    P: np.ndarray
    index: Dict[str, int]
    rank: int
    n_params: int
    n_rows: int
    n_observations: int
    n_constraints: int
    redundancy: int
    condition_number: float
    singular_values: np.ndarray
    null_space: np.ndarray
    residuals: np.ndarray
    misclosure: np.ndarray
    dx: np.ndarray
    reliability: Optional[LevelingReliabilityResult] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    # ---- 常用别名 -------------------------------------------------
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
    def Qxx(self) -> np.ndarray:
        return self.Cx

    @property
    def sigma0(self) -> float:
        """设计态单位权标准差固定为 1。"""
        return 1.0

    def _index_of(self, ref: Any) -> int:
        name = _point_ref_name(ref)
        if name not in self.point_order:
            raise KeyError(f"未知高程点 {name!r}")
        return self.point_order.index(name)

    def height(self, ref: Any) -> float:
        return float(self.heights[self._index_of(ref)])

    def covariance(self, ref_a: Any, ref_b: Any) -> float:
        name_a = _point_ref_name(ref_a)
        name_b = _point_ref_name(ref_b)
        self.network.point(name_a)
        self.network.point(name_b)
        if name_a in self.index and name_b in self.index:
            return float(self.Cx[self.index[name_a], self.index[name_b]])
        return 0.0

    def sigma_H(self, ref: Any) -> float:
        return sqrt(max(self.covariance(ref, ref), 0.0))

    def sigma_H_mm(self, ref: Any) -> float:
        return self.sigma_H(ref) * 1e3

    def point_precision(self, ref: Any) -> LevelingPointPrecision:
        point = self.network.point(ref)
        return LevelingPointPrecision(
            name=point.name,
            H=self.height(point.name),
            sigma=self.sigma_H(point.name),
            fixed=point.fixed,
            constrained=point.name in self.constrained_names,
            role=point.role,
            height_type=point.height_type,
        )

    @property
    def point_precisions(self) -> Dict[str, LevelingPointPrecision]:
        return {name: self.point_precision(name) for name in self.point_order}

    def relative_height(self, frm: Any, to: Any) -> RelativeHeightPrecision:
        name_f = _point_ref_name(frm)
        name_t = _point_ref_name(to)
        self.network.point(name_f)
        self.network.point(name_t)
        var = (
            self.sigma_H(name_f) ** 2
            + self.sigma_H(name_t) ** 2
            - 2.0 * self.covariance(name_f, name_t)
        )
        return RelativeHeightPrecision(
            frm=name_f,
            to=name_t,
            delta_h=self.height(name_t) - self.height(name_f),
            sigma=sqrt(max(var, 0.0)),
        )

    def relative_sigma(self, frm: Any, to: Any) -> float:
        return self.relative_height(frm, to).sigma

    def relative_sigma_mm(self, frm: Any, to: Any) -> float:
        return self.relative_sigma(frm, to) * 1e3

    @property
    def observation_records(self) -> List[LevelingObservationRecord]:
        return [] if self.reliability is None else self.reliability.observation_records

    @property
    def records(self) -> List[LevelingObservationRecord]:
        return [] if self.reliability is None else self.reliability.records


def _validate_rank_tol(rank_tol: Optional[float]) -> Optional[float]:
    if rank_tol is None:
        return None
    rank_tol = _positive(rank_tol, "rank_tol")
    return rank_tol


def _resolve_height_datum(
    network: LevelingNetwork, datum: Any
) -> Tuple[str, str, List[LevelingPoint], List[LevelingPoint]]:
    """返回 (计算用基准类型, 说明, 固定点, 加权约束点)。"""
    if datum is None:
        mode = "auto"
    elif isinstance(datum, str):
        key = datum.strip().lower()
        aliases = {
            "": "auto",
            "auto": "auto",
            "fixed": "fixed",
            "fix": "fixed",
            "固定": "fixed",
            "weighted": "weighted",
            "weight": "weighted",
            "加权": "weighted",
            "minimal": "minimal",
            "min": "minimal",
            "最小": "minimal",
            "free": "minimal",
            "自由": "minimal",
        }
        if key not in aliases:
            raise ValueError(f"未知高程基准类型字符串：{datum!r}")
        mode = aliases[key]
    else:
        kind = getattr(datum, "kind", None)
        if kind in ("fixed",):
            mode = "fixed"
        elif kind in ("weighted",):
            mode = "weighted"
        elif kind in ("minimal", "free"):
            mode = "minimal"
        else:
            raise TypeError(f"datum 必须是字符串、基准对象或 None，收到 {type(datum)!r}")

    fixed = [p for p in network.points if p.fixed]
    weighted = [p for p in network.points if (not p.fixed and p.sigma_H is not None)]

    if mode == "minimal":
        if fixed or weighted:
            raise InvalidPrecisionError(
                "自由网/最小约束基准不能同时使用固定点或加权高程约束；"
                "请移除 fixed=True / sigma_H 或改用 datum='fixed'/'weighted'"
            )
        return "minimal", "自由网最小约束（伪逆，零空间为整体高程平移）", [], []

    if mode in ("auto", "weighted"):
        for p in network.points:
            if p.fixed and p.sigma_H is not None:
                raise InvalidPrecisionError(
                    f"点 {p.name!r} 同时为固定点和加权约束；请只保留一种"
                )
        if mode == "auto":
            use_weighted = weighted
            kind = "weighted" if use_weighted else "fixed"
            summary = (
                "自动基准：固定点 + 加权高程约束"
                if fixed and use_weighted
                else ("自动基准：加权高程约束" if use_weighted else "自动基准：固定点")
            )
            return kind, summary, fixed, use_weighted
        if not weighted:
            raise InvalidPrecisionError(
                "datum='weighted' 但没有任何非固定点提供 sigma_H"
            )
        return (
            "weighted",
            "加权高程约束基准（固定点 + sigma_H 伪观测）" if fixed else "加权高程约束基准（sigma_H 伪观测）",
            fixed,
            weighted,
        )

    # mode == "fixed"
    return "fixed", "固定高程基准（fixed=True 的点从参数中剔除）", fixed, []


def _null_space_diagnostics(
    network: LevelingNetwork,
    unknown_names: Sequence[str],
    null_space: np.ndarray,
    *,
    free_datum: bool,
) -> List[str]:
    diagnostics: List[str] = []
    if not free_datum:
        diagnostics.append(
            "缺少高程基准：至少需要 1 个 fixed=True 的高程点或带 sigma_H 的加权约束"
        )
    else:
        diagnostics.append("自由网存在多个独立高程基准缺陷（可能为不连通子网）")
    for k in range(null_space.shape[1]):
        coeff = np.abs(null_space[:, k])
        if coeff.size == 0:
            continue
        threshold = max(float(coeff.max()) * 0.25, 1e-9)
        names = [
            unknown_names[j]
            for j in np.argsort(coeff)[::-1]
            if coeff[j] >= threshold
        ][:6]
        diagnostics.append(f"零空间方向{k + 1}主要点：" + "、".join(names))
    return diagnostics


def _make_rank_error(
    network: LevelingNetwork,
    unknown_names: Sequence[str],
    rank: int,
    null_space: np.ndarray,
    *,
    free_datum: bool,
) -> RankDeficientError:
    u = len(unknown_names)
    diagnostics = _null_space_diagnostics(
        network, unknown_names, null_space, free_datum=free_datum
    )
    msg = (
        f"高程网设计矩阵秩亏：rank={rank}，参数数={u}，"
        f"零空间维数={u - rank}。" + "；".join(diagnostics) + "。"
    )
    return RankDeficientError(
        msg,
        rank=rank,
        n_params=u,
        null_space=null_space,
        parameter_names=list(unknown_names),
        diagnostics=diagnostics,
    )


def _observation_value(obs: Union[HeightDifference, TrigHeight]) -> float:
    return float(obs.delta_h)


def _observation_sigma(obs: Union[HeightDifference, TrigHeight], label: str) -> float:
    sigma = float(obs.sigma)
    if not isfinite(sigma) or sigma <= 0.0:
        raise InvalidPrecisionError(
            f"观测 {label!r} 的标准差必须为正的有限值，收到 {sigma!r}"
        )
    return sigma


def solve_leveling(
    network: LevelingNetwork,
    datum: Any = None,
    *,
    rank_tol: Optional[float] = None,
    alpha: float = 0.05,
    power: float = 0.80,
) -> LevelingResult:
    """解算 1D 水准/高程网的设计态精度与可靠性。

    Parameters
    ----------
    network:
        :class:`LevelingNetwork`。
    datum:
        ``None``/``'auto'``（默认）：使用固定点，并自动采用非固定点的
        ``sigma_H`` 加权约束；``'fixed'``：只用固定点；``'weighted'``：
        加权约束；``'free'``/``'minimal'``：自由网伪逆最小约束。
        默认无固定点/无加权约束时抛 :class:`RankDeficientError`。
    rank_tol:
        SVD 秩判定阈值；默认 ``max(m,u,1)·eps·s_max``。
    alpha, power:
        可靠性 MDB 的显著性水平与检验功效，默认 0.05/0.80（λ0=7.849）。
    """
    if not isinstance(network, LevelingNetwork):
        net = getattr(network, "network", None)
        if isinstance(net, LevelingNetwork):
            network = net
        else:
            raise TypeError("solve_leveling 的第一个参数必须是 LevelingNetwork")
    network._validate_connections()
    rank_tol = _validate_rank_tol(rank_tol)
    datum_kind, datum_summary, fixed, weighted = _resolve_height_datum(network, datum)

    fixed_names = [p.name for p in fixed]
    constrained_names = [p.name for p in weighted]
    unknown = [p for p in network.points if not p.fixed]
    unknown_names = [p.name for p in unknown]
    index = {name: i for i, name in enumerate(unknown_names)}
    u = len(unknown_names)

    rows: List[np.ndarray] = []
    reduced_obs: List[float] = []
    sigmas: List[float] = []
    row_kinds: List[str] = []
    row_labels: List[str] = []
    row_observations: List[Any] = []

    for obs in network.observations:
        row = np.zeros(u, dtype=float)
        fixed_constant = 0.0
        for ref, sign in ((obs.frm, -1.0), (obs.to, 1.0)):
            if ref in index:
                row[index[ref]] += sign
            else:
                fixed_constant += sign * network.point(ref).H
        label = obs.label
        sigma = _observation_sigma(obs, label)
        rows.append(row)
        reduced_obs.append(_observation_value(obs) - fixed_constant)
        sigmas.append(sigma)
        row_kinds.append(obs.kind)
        row_labels.append(label)
        row_observations.append(obs)

    for point in weighted:
        row = np.zeros(u, dtype=float)
        row[index[point.name]] = 1.0
        assert point.sigma_H is not None
        rows.append(row)
        reduced_obs.append(float(point.H))
        sigmas.append(float(point.sigma_H))
        row_kinds.append("constraint")
        row_labels.append(f"H:{point.name}")
        row_observations.append(point)

    m = len(rows)
    A = np.vstack(rows) if rows else np.zeros((0, u), dtype=float)
    Ql = np.diag(np.square(sigmas)) if sigmas else np.zeros((0, 0), dtype=float)
    P = np.diag(1.0 / np.square(sigmas)) if sigmas else np.zeros((0, 0), dtype=float)
    l_reduced = np.asarray(reduced_obs, dtype=float)
    x0 = np.asarray([p.H for p in unknown], dtype=float)

    if u == 0:
        singular_values = np.zeros((0,), dtype=float)
        null_space = np.zeros((0, 0), dtype=float)
        rank = 0
        Cx = np.zeros((0, 0), dtype=float)
        dx = np.zeros((0,), dtype=float)
        condition = 1.0 if m == 0 else float("inf")
        redundancy = m
        misclosure = l_reduced.copy()
    else:
        if m == 0:
            singular_values = np.zeros((0,), dtype=float)
            Vt = np.eye(u)
            rank = 0
            smax = 0.0
        else:
            Aw = np.sqrt(P) @ A
            _U, singular_values, Vt = np.linalg.svd(Aw, full_matrices=True)
            smax = float(singular_values[0]) if singular_values.size else 0.0
        tol = (
            rank_tol
            if rank_tol is not None
            else max(m, u, 1) * np.finfo(float).eps * max(smax, 1.0)
        )
        rank = int(np.sum(singular_values > tol))
        null_space = Vt[rank:u, :].T.copy()
        free_datum = datum_kind == "minimal"
        if rank < u:
            if not free_datum or (u - rank) > 1:
                raise _make_rank_error(
                    network, unknown_names, rank, null_space, free_datum=free_datum
                )

        if rank > 0:
            s = singular_values[:rank]
            Vr = Vt[:rank, :]
            Cx = Vr.T @ (Vr / (s * s)[:, None])
        else:
            Cx = np.zeros((u, u), dtype=float)

        if rank < u:
            # 自由网：最小范数伪逆解；零空间为整体高程平移。
            G = null_space
            Cx = (np.eye(u) - G @ G.T) @ Cx @ (np.eye(u) - G @ G.T)
        Cx = 0.5 * (Cx + Cx.T)
        if not np.all(np.isfinite(Cx)):
            raise InvalidPrecisionError("高程网协方差矩阵含非有限值")
        eigmin = float(np.linalg.eigvalsh(Cx).min()) if u else 0.0
        if eigmin < -1e-10 * max(1.0, float(np.trace(Cx))):
            raise InvalidPrecisionError(
                f"高程网协方差矩阵出现显著负特征值（min eigenvalue={eigmin:.3e}）"
            )
        condition = (
            float(singular_values[0] / singular_values[rank - 1])
            if rank > 0 and singular_values[rank - 1] > 0
            else float("inf")
        )
        redundancy = m - rank

        misclosure = l_reduced - A @ x0
        rhs = A.T @ (P @ misclosure)
        if rank > 0:
            s = singular_values[:rank]
            Vr = Vt[:rank, :]
            dx = Vr.T @ ((Vr @ rhs) / (s * s))
        else:
            dx = np.zeros(u, dtype=float)
        if rank < u:
            # 伪逆解已不含零空间分量；显式投影可抑制舍入误差。
            dx = (np.eye(u) - null_space @ null_space.T) @ dx

    adjusted_unknown = x0 + dx
    height_map = {p.name: p.H for p in fixed}
    height_map.update({name: float(adjusted_unknown[i]) for i, name in enumerate(unknown_names)})
    heights = np.asarray([height_map[p.name] for p in network.points], dtype=float)
    residuals = misclosure - A @ dx if m else np.zeros(0, dtype=float)

    result = LevelingResult(
        network=network,
        datum_kind=datum_kind,
        datum_summary=datum_summary,
        point_order=network.point_names,
        fixed_names=fixed_names,
        constrained_names=constrained_names,
        unknown_names=unknown_names,
        heights=heights,
        Cx=Cx,
        A=A,
        Ql=Ql,
        P=P,
        index=index,
        rank=rank,
        n_params=u,
        n_rows=m,
        n_observations=len(network.observations),
        n_constraints=len(weighted),
        redundancy=redundancy,
        condition_number=condition,
        singular_values=singular_values,
        null_space=null_space,
        residuals=residuals,
        misclosure=misclosure,
        dx=dx,
        metadata={
            "datum_kind": datum_kind,
            "datum_summary": datum_summary,
            "rank_tolerance": rank_tol,
            "parameter_names": list(unknown_names),
            "fixed_points": list(fixed_names),
            "constrained_points": list(constrained_names),
            "height_types": {p.name: p.height_type for p in network.points},
        },
    )
    result.reliability = analyze_leveling_reliability(
        result, alpha=alpha, power=power
    )
    return result


def analyze_leveling_reliability(
    result: LevelingResult,
    alpha: float = 0.05,
    power: float = 0.80,
    *,
    lambda0_value: Optional[float] = None,
) -> LevelingReliabilityResult:
    """计算 1D 高程网的 ``r_i``、MDB 与外部可靠性。

    对独立观测，``r_i = 1 - h_ii``；MDB 使用非中心参数 λ0 与
    ``K = P Qv P`` 的对角元；外部可靠性为未检出粗差对任一点高程的
    最大绝对影响（米）。
    """
    if isinstance(result, LevelingNetwork):
        result = solve_leveling(result)
    if not isinstance(result, LevelingResult):
        raise TypeError("需要 LevelingResult 或 LevelingNetwork")

    if lambda0_value is not None:
        lam = _positive(lambda0_value, "lambda0_value")
    elif abs(float(alpha) - 0.05) < 1e-15 and abs(float(power) - 0.80) < 1e-15:
        lam = LAMBDA0_DEFAULT
    else:
        lam = noncentrality(alpha, power)

    m = result.n_rows
    records: List[LevelingObservationRecord] = []
    if m == 0:
        return LevelingReliabilityResult([], lam, alpha, power, 0.0, result.redundancy)

    A = result.A
    Cx = result.Cx
    Ql = result.Ql
    P = result.P
    Qv = Ql - A @ Cx @ A.T
    Qv = 0.5 * (Qv + Qv.T)
    R = Qv @ P
    r_diag = np.diag(R)
    K = P @ Qv @ P
    K = 0.5 * (K + K.T)
    k_diag = np.diag(K)

    # 逐行元数据与设计矩阵行一一对应：观测在前，加权约束在后。
    meta: List[Tuple[str, str, Any, float]] = []
    for obs in result.network.observations:
        meta.append((obs.label, obs.kind, obs, float(obs.sigma)))
    for point in result.network.points:
        if point.fixed or point.name not in result.constrained_names:
            continue
        assert point.sigma_H is not None
        meta.append((f"H:{point.name}", "constraint", point, float(point.sigma_H)))
    if len(meta) != m:
        raise RuntimeError("内部错误：高程网观测元数据与设计矩阵行数不一致")

    for i, (label, kind, obs, sigma) in enumerate(meta):
        r_i = float(r_diag[i])
        kk = float(k_diag[i])
        if not isfinite(kk) or kk <= 1e-30 or r_i <= 1e-12:
            mdb = float("inf")
            undetectable = True
        else:
            mdb = sqrt(lam / kk)
            undetectable = False

        # 外部可靠性：该粗差未检出时对未知点高程的影响。
        dx = Cx @ (A[i, :] * P[i, i]) * mdb if mdb < float("inf") else np.zeros_like(result.dx)
        best_abs = 0.0
        best_name: Optional[str] = None
        for name, col in result.index.items():
            effect = abs(float(dx[col]))
            if effect > best_abs:
                best_abs = effect
                best_name = name

        records.append(
            LevelingObservationRecord(
                label=label,
                kind=kind,
                sigma=sigma,
                r_i=r_i,
                mdb=mdb,
                external_max=best_abs,
                external_point=best_name,
                undetectable=undetectable,
                observation=obs,
            )
        )

    return LevelingReliabilityResult(
        records=records,
        lambda0_value=lam,
        alpha=float(alpha),
        power=float(power),
        trace_r=float(np.trace(R)),
        redundancy=result.redundancy,
    )


def plot_leveling_network(
    result: LevelingResult,
    positions: Optional[Mapping[str, Tuple[float, float]]] = None,
    ax: Any = None,
    figsize: Tuple[float, float] = (9.0, 6.3),
    title: Optional[str] = None,
    scale: float = 1.0,
    label_offsets: Optional[Mapping[str, Tuple[float, float]]] = None,
) -> Tuple[Any, Any]:
    """绘制 1D 高程网的路线图。

    边宽按观测权重 ``1/σ²`` 线性映射；水准实线、三角高程虚线；固定点三角、
    加权约束点方形、待定点圆点。点标注 ``H`` 与 ``σ_H``（mm）。无外部
    坐标时默认按点序画在圆上；也可传入 ``positions`` 指定布局。
    """
    import matplotlib.pyplot as plt
    from matplotlib.lines import Line2D

    if not isinstance(result, LevelingResult):
        result = solve_leveling(result)
    if ax is None:
        fig, ax = plt.subplots(figsize=figsize)
    else:
        fig = ax.figure

    names = result.point_order
    if positions is None:
        n = max(len(names), 1)
        positions = {
            name: (
                float(np.cos(2.0 * pi * i / n)),
                float(np.sin(2.0 * pi * i / n)),
            )
            for i, name in enumerate(names)
        }
    else:
        missing = [name for name in names if name not in positions]
        if missing:
            raise KeyError(f"positions 缺少点：{', '.join(missing)}")

    sigmas = [float(obs.sigma) for obs in result.network.observations]
    weights = [1.0 / (s * s) for s in sigmas]
    wmax = max(weights, default=1.0)

    for obs, weight in zip(result.network.observations, weights):
        p, q = positions[obs.frm], positions[obs.to]
        rel = weight / wmax
        lw = (1.2 + 3.2 * rel) * scale
        if isinstance(obs, TrigHeight):
            ax.plot(
                [p[0], q[0]],
                [p[1], q[1]],
                color="#d95f02",
                lw=lw,
                ls=(0, (5, 2)),
                zorder=1,
                alpha=0.9,
            )
        else:
            ax.plot(
                [p[0], q[0]],
                [p[1], q[1]],
                color="#253494",
                lw=lw,
                ls="-",
                zorder=1,
                alpha=0.85,
            )

    for name in names:
        point = result.network.point(name)
        precision = result.point_precision(name)
        x, y = positions[name]
        if point.fixed:
            marker, color, size = "^", "#1b9e77", 110.0
        elif name in result.constrained_names:
            marker, color, size = "s", "#7570b3", 85.0
        else:
            marker, color, size = "o", "#d73027", 75.0
        ax.scatter([x], [y], marker=marker, s=size, c=color, edgecolors="white", zorder=5)
        offset = (8.0, 8.0) if label_offsets is None else label_offsets.get(name, (8.0, 8.0))
        ax.annotate(
            f"{name}\nH={precision.H:.4f} m\nσ={precision.sigma_mm:.2f} mm",
            (x, y),
            xytext=offset,
            textcoords="offset points",
            fontsize=8,
            ha="left",
            va="bottom",
            bbox=dict(boxstyle="round,pad=0.25", fc="white", ec="none", alpha=0.85),
            zorder=6,
        )

    handles = [
        Line2D([0], [0], color="#253494", lw=2.2, label="Leveling"),
        Line2D([0], [0], color="#d95f02", lw=2.2, ls=(0, (5, 2)), label="Trig height"),
        Line2D([0], [0], marker="^", color="none", markerfacecolor="#1b9e77",
               markeredgecolor="white", markersize=9, label="Fixed"),
        Line2D([0], [0], marker="s", color="none", markerfacecolor="#7570b3",
               markeredgecolor="white", markersize=8, label="Weighted"),
        Line2D([0], [0], marker="o", color="none", markerfacecolor="#d73027",
               markeredgecolor="white", markersize=8, label="Unknown"),
    ]
    ax.legend(handles=handles, loc="upper left", bbox_to_anchor=(1.02, 1.0), fontsize=8)
    ax.set_aspect("equal", adjustable="datalim")
    ax.set_axis_off()
    ax.set_title(title or f"Leveling network: {result.network.name}")
    ax.margins(0.18)
    fig.tight_layout()
    return fig, ax


__all__ = [
    "ARCSEC_TO_RAD",
    "HeightDifference",
    "HeightNetwork",
    "HeightObservation",
    "LevelingNetwork",
    "LevelingObservation",
    "LevelingObservationRecord",
    "LevelingPoint",
    "LevelingPointPrecision",
    "LevelingReliabilityResult",
    "LevelingResult",
    "RelativeHeightPrecision",
    "TrigHeight",
    "analyze_leveling_reliability",
    "plot_leveling_network",
    "solve_leveling",
]


# 便捷别名
leveling = solve_leveling
solve_height_network = solve_leveling
analyze_height_reliability = analyze_leveling_reliability
