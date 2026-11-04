"""基准定义：固定点、加权约束、自由网最小约束。

- FixedDatum：精确固定点从参数中剔除（Point.fixed=True）。
- WeightedDatum：对坐标附加伪观测，标准差取 Point.sigma_E/sigma_N 或显式给定。
- MinimalDatum：自由网内约束/伪逆解，至少处理平移；旋转与尺度由实际零空间判断。
- FreeDatum：MinimalDatum 的别名，便于表达自由网语义。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, ClassVar, Dict, List, Optional, Sequence

import numpy as np

from .design import ParameterIndex
from .exceptions import InvalidPrecisionError
from .model import CoordinateConstraint, Network, point_name


class Datum:
    """基准基类。"""

    kind: ClassVar[str] = "base"
    description: str = ""

    def constraints(
        self, network: Network, index: ParameterIndex
    ) -> List[CoordinateConstraint]:
        return []

    @property
    def is_minimal(self) -> bool:
        return self.kind in ("minimal", "free")

    def summary(self) -> str:
        return self.description or self.kind


@dataclass
class FixedDatum(Datum):
    """精确固定点基准：Point.fixed=True 的坐标不进入未知参数。"""

    kind: ClassVar[str] = "fixed"
    description: str = "精确固定点基准（固定点坐标从参数中剔除）"

    def constraints(
        self, network: Network, index: ParameterIndex
    ) -> List[CoordinateConstraint]:
        return []

    def summary(self) -> str:
        return "固定基准（Point.fixed=True 的坐标从参数中剔除）"


@dataclass
class WeightedDatum(Datum):
    """加权坐标约束基准。

    points 为空时自动选择所有带 sigma_E/sigma_N 的待定点。
    sigma_E/sigma_N 为未在 Point 上给出时的默认值。
    """

    points: Optional[Sequence[Any]] = None
    sigma_E: Optional[float] = None
    sigma_N: Optional[float] = None

    kind: ClassVar[str] = "weighted"
    description: str = "加权坐标约束基准（坐标伪观测）"

    def constraints(
        self, network: Network, index: ParameterIndex
    ) -> List[CoordinateConstraint]:
        if self.points is None:
            selected = [
                p
                for p in network.points
                if not p.fixed and (p.sigma_E is not None or p.sigma_N is not None)
            ]
        else:
            selected = [network.point(ref) for ref in self.points]

        constraints: List[CoordinateConstraint] = []
        for p in selected:
            if p.fixed:
                raise InvalidPrecisionError(
                    f"点 {p.name!r} 是精确固定点，不能同时作为加权约束；"
                    "请将其 fixed 设为 False 并提供 sigma_E/sigma_N"
                )
            if p.name not in index.point_columns:
                raise InvalidPrecisionError(f"加权约束点 {p.name!r} 不在未知参数中")
            sE = p.sigma_E if p.sigma_E is not None else self.sigma_E
            sN = p.sigma_N if p.sigma_N is not None else self.sigma_N
            if sE is not None:
                constraints.append(
                    CoordinateConstraint(p.name, "E", sE, value=p.E)
                )
            if sN is not None:
                constraints.append(
                    CoordinateConstraint(p.name, "N", sN, value=p.N)
                )
        if not constraints:
            raise InvalidPrecisionError(
                "加权基准未找到任何坐标约束；请设置 Point.sigma_E/sigma_N "
                "或向 WeightedDatum 传入 points 与默认 sigma"
            )
        return constraints

    def summary(self) -> str:
        pts = "自动" if self.points is None else ", ".join(
            point_name(p) for p in self.points
        )
        return f"加权基准；约束点：{pts}"


@dataclass
class MinimalDatum(Datum):
    """自由网最小约束基准。

    origin 指定 S 变换/内约束的基准点（默认第一个待定点）；实际参与约束的
    平移、旋转、尺度方向由设计矩阵的零空间决定。use_pseudoinverse=True 时
    采用 Moore-Penrose 伪逆计算基准相关协方差。
    """

    origin: Optional[Any] = None
    use_pseudoinverse: bool = True

    kind: ClassVar[str] = "minimal"
    description: str = "自由网最小约束基准（内约束/伪逆）"

    def origin_name(self, network: Network, index: ParameterIndex) -> Optional[str]:
        if self.origin is not None:
            name = point_name(self.origin)
            network.point(name)
            return name
        if index.point_order:
            return index.point_order[0]
        return None

    def summary(self) -> str:
        origin = "自动" if self.origin is None else point_name(self.origin)
        return f"最小约束基准；基准点：{origin}；伪逆：{self.use_pseudoinverse}"


@dataclass
class FreeDatum(MinimalDatum):
    """自由网基准（与 MinimalDatum 相同的计算方法，语义务为自由网）。"""

    kind: ClassVar[str] = "free"
    description: str = "自由网基准（内约束/伪逆）"


def normalize_datum(datum: Any) -> Datum:
    """把 None/字符串/基准对象统一为 Datum。"""
    if datum is None:
        return FixedDatum()
    if isinstance(datum, Datum):
        return datum
    if isinstance(datum, str):
        key = datum.strip().lower()
        if key in ("fixed", "fix", "固定"):
            return FixedDatum()
        if key in ("weighted", "weight", "加权"):
            return WeightedDatum()
        if key in ("minimal", "min", "最小"):
            return MinimalDatum()
        if key in ("free", "自由"):
            return FreeDatum()
        raise ValueError(f"未知基准类型字符串：{datum!r}")
    raise TypeError(f"datum 必须是 Datum、字符串或 None，收到 {type(datum)!r}")


def canonical_null_modes(
    network: Network,
    index: ParameterIndex,
    origin: Optional[Any] = None,
) -> Dict[str, np.ndarray]:
    """构造平面网的规范基准零空间方向，用于诊断“缺哪种基准”。

    返回东平移、北平移、旋转、尺度四个向量（长度 = 参数个数）。这些向量
    只是候选方向；是否为真实零空间需由调用方乘 A 检查。
    """
    u = index.size
    modes: Dict[str, np.ndarray] = {}
    gE = np.zeros(u)
    gN = np.zeros(u)
    for name, (ie, inn) in index.point_columns.items():
        gE[ie] = 1.0
        gN[inn] = 1.0
    modes["平移(E)"] = gE
    modes["平移(N)"] = gN

    pts = [network.point(name) for name in index.point_order]
    if not pts:
        return modes
    if origin is not None:
        op = network.point(point_name(origin))
        e0, n0 = op.E, op.N
    else:
        e0 = sum(p.E for p in pts) / len(pts)
        n0 = sum(p.N for p in pts) / len(pts)

    gR = np.zeros(u)
    gS = np.zeros(u)
    for p in pts:
        ie, inn = index.point_columns[p.name]
        gR[ie] = -(p.N - n0)
        gR[inn] = p.E - e0
        gS[ie] = p.E - e0
        gS[inn] = p.N - n0
    for station in index.orientation_order:
        gR[index.orientation_columns[station]] = 1.0
    modes["旋转"] = gR
    modes["尺度"] = gS
    return modes


__all__ = [
    "Datum",
    "FixedDatum",
    "WeightedDatum",
    "MinimalDatum",
    "FreeDatum",
    "normalize_datum",
    "canonical_null_modes",
]
