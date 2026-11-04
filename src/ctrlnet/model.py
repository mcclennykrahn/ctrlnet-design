"""平面控制网的数据模型。

坐标约定：E 为东坐标、N 为北坐标，单位米；角度内部使用弧度。
``Point``、``Distance`` 等即使用户传入点对象，也统一按点名解析。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from math import hypot, pi
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple, Union

PointRef = Union[str, "Point"]

ARCSEC_TO_RAD = pi / (180.0 * 3600.0)
RAD_TO_ARCSEC = 1.0 / ARCSEC_TO_RAD


def point_name(ref: PointRef) -> str:
    """把点名或 Point 对象统一转换为点名。"""
    if isinstance(ref, Point):
        return ref.name
    if isinstance(ref, str):
        return ref
    raise TypeError(f"点引用必须是 str 或 Point，收到 {type(ref)!r}")


class Observation:
    """观测对象公共基类。"""

    kind = "observation"

    @property
    def label(self) -> str:  # pragma: no cover - 子类覆盖
        raise NotImplementedError

    def referenced_points(self) -> Tuple[str, ...]:  # pragma: no cover
        raise NotImplementedError


@dataclass
class Point:
    """控制点。

    fixed=True 表示精确固定点，求解时直接从参数中剔除；否则为待定点。
    sigma_E/sigma_N 可选，供加权基准作为坐标伪观测的先验标准差（米）。
    """

    name: str
    E: float
    N: float
    fixed: bool = False
    sigma_E: Optional[float] = None
    sigma_N: Optional[float] = None

    def __post_init__(self) -> None:
        self.name = str(self.name)
        self.E = float(self.E)
        self.N = float(self.N)
        self.fixed = bool(self.fixed)
        if self.sigma_E is not None:
            self.sigma_E = float(self.sigma_E)
        if self.sigma_N is not None:
            self.sigma_N = float(self.sigma_N)

    @property
    def role(self) -> str:
        if self.fixed:
            return "fixed"
        if self.sigma_E is not None or self.sigma_N is not None:
            return "constrained"
        return "unknown"

    @property
    def is_weighted(self) -> bool:
        return self.sigma_E is not None or self.sigma_N is not None


@dataclass
class Distance(Observation):
    """两点间平距观测。

    先验标准差：``sigma(s) = sqrt(a^2 + (b_ppm * 1e-6 * s)^2)``，单位米。
    """

    frm: PointRef
    to: PointRef
    a: float = 0.002
    b_ppm: float = 2.0

    kind = "distance"

    def __post_init__(self) -> None:
        self.frm = point_name(self.frm)
        self.to = point_name(self.to)
        self.a = float(self.a)
        self.b_ppm = float(self.b_ppm)

    @property
    def label(self) -> str:
        return f"{self.frm}{self.to}"

    def referenced_points(self) -> Tuple[str, ...]:
        return (self.frm, self.to)

    def sigma(self, s: float) -> float:
        return hypot(self.a, self.b_ppm * 1e-6 * abs(s))

    def variance(self, s: float) -> float:
        return self.a * self.a + (self.b_ppm * 1e-6 * s) ** 2


@dataclass
class Direction(Observation):
    """测站至目标的方向观测，测站附加一个定向未知数 omega。

    观测方程：``alpha(station, target) - omega(station)``。sigma_arcsec 为方向
    先验标准差（角秒）。
    """

    station: PointRef
    target: PointRef
    sigma_arcsec: float = 1.0

    kind = "direction"

    def __post_init__(self) -> None:
        self.station = point_name(self.station)
        self.target = point_name(self.target)
        self.sigma_arcsec = float(self.sigma_arcsec)

    @property
    def label(self) -> str:
        return f"方向 {self.station}-{self.target}"

    def referenced_points(self) -> Tuple[str, ...]:
        return (self.station, self.target)

    @property
    def sigma_rad(self) -> float:
        return self.sigma_arcsec * ARCSEC_TO_RAD


@dataclass
class Angle(Observation):
    """水平角观测：后视 backsight、测站 station、前视 foresight。

    角值 = 前视方位角 - 后视方位角（逆时针为正，内部弧度）。
    """

    backsight: PointRef
    station: PointRef
    foresight: PointRef
    sigma_arcsec: float = 1.0

    kind = "angle"

    def __post_init__(self) -> None:
        self.backsight = point_name(self.backsight)
        self.station = point_name(self.station)
        self.foresight = point_name(self.foresight)
        self.sigma_arcsec = float(self.sigma_arcsec)

    @property
    def label(self) -> str:
        return f"∠{self.backsight}-{self.station}-{self.foresight}"

    def referenced_points(self) -> Tuple[str, ...]:
        return (self.backsight, self.station, self.foresight)

    @property
    def sigma_rad(self) -> float:
        return self.sigma_arcsec * ARCSEC_TO_RAD


@dataclass
class GnssBaseline2D(Observation):
    """二维 GNSS 基线（E、N 分量），带 2x2 协方差。

    correlation 为 E、N 分量的相关系数，默认 0。
    """

    frm: PointRef
    to: PointRef
    sigma_E: float
    sigma_N: float
    correlation: float = 0.0

    kind = "gnss"

    def __post_init__(self) -> None:
        self.frm = point_name(self.frm)
        self.to = point_name(self.to)
        self.sigma_E = float(self.sigma_E)
        self.sigma_N = float(self.sigma_N)
        self.correlation = float(self.correlation)

    @property
    def label(self) -> str:
        return f"GNSS {self.frm}-{self.to}"

    def referenced_points(self) -> Tuple[str, ...]:
        return (self.frm, self.to)

    @property
    def covariance(self) -> "Any":
        """返回 2x2 协方差矩阵（numpy.ndarray）。"""
        import numpy as np

        sE, sN, rho = self.sigma_E, self.sigma_N, self.correlation
        return np.array(
            [[sE * sE, rho * sE * sN], [rho * sE * sN, sN * sN]], dtype=float
        )


@dataclass
class CoordinateConstraint:
    """坐标伪观测（加权基准）：点分量 = 已知值 + v。"""

    point: str
    component: str  # "E" 或 "N"
    sigma: float
    value: Optional[float] = None

    def __post_init__(self) -> None:
        self.point = point_name(self.point)
        self.component = str(self.component).upper()
        self.sigma = float(self.sigma)
        if self.component not in ("E", "N"):
            raise ValueError("component 只能是 'E' 或 'N'")
        if self.value is not None:
            self.value = float(self.value)

    @property
    def label(self) -> str:
        return f"约束{self.component}-{self.point}"


@dataclass
class Network:
    """控制网：点表 + 启用观测列表。"""

    points: Sequence[Point]
    observations: Sequence[Observation] = field(default_factory=list)
    name: str = "network"

    def __post_init__(self) -> None:
        if isinstance(self.points, Mapping):
            self.points = list(self.points.values())
        else:
            self.points = list(self.points)
        self.observations = list(self.observations)
        self._by_name: Dict[str, Point] = {}
        for p in self.points:
            if not isinstance(p, Point):
                raise TypeError("points 必须由 Point 组成")
            if p.name in self._by_name:
                raise ValueError(f"点名重复：{p.name}")
            self._by_name[p.name] = p

    def point(self, ref: PointRef) -> Point:
        name = point_name(ref)
        try:
            return self._by_name[name]
        except KeyError as exc:
            raise KeyError(f"网中不存在点 {name!r}") from exc

    @property
    def point_names(self) -> List[str]:
        return [p.name for p in self.points]

    @property
    def unknown_points(self) -> List[Point]:
        return [p for p in self.points if not p.fixed]

    @property
    def fixed_points(self) -> List[Point]:
        return [p for p in self.points if p.fixed]

    def distance_edges(self) -> List[Tuple[str, str]]:
        """按观测顺序返回距离边（去重）。"""
        seen = set()
        edges: List[Tuple[str, str]] = []
        for obs in self.observations:
            if isinstance(obs, Distance):
                key = tuple(sorted((obs.frm, obs.to)))
                if key not in seen:
                    seen.add(key)
                    edges.append((obs.frm, obs.to))
        return edges

    def with_observations(self, extra: Iterable[Observation]) -> "Network":
        """返回加入额外观测后的新网（点对象共享）。"""
        return Network(
            list(self.points),
            list(self.observations) + list(extra),
            name=self.name,
        )

    def copy(self) -> "Network":
        return Network(list(self.points), list(self.observations), name=self.name)


@dataclass
class Scenario:
    """方案：一张网 + 一个基准定义。"""

    name: str
    network: Network
    datum: Any = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def points(self) -> Sequence[Point]:
        return self.network.points

    @property
    def observations(self) -> Sequence[Observation]:
        return self.network.observations

    def solve(self, **kwargs: Any) -> "Any":
        from .adjustment import solve

        kwargs.setdefault("datum", self.datum)
        return solve(self.network, **kwargs)


__all__ = [
    "PointRef",
    "ARCSEC_TO_RAD",
    "RAD_TO_ARCSEC",
    "point_name",
    "Observation",
    "Point",
    "Distance",
    "Direction",
    "Angle",
    "GnssBaseline2D",
    "CoordinateConstraint",
    "Network",
    "Scenario",
]
