"""论文《基于在线地图的网页端控制网设计与精度估算系统》第 3–5 章约定。

本模块把论文中的公式整理为可复用、可测试的实现：

* 高斯-克吕格投影正反算（CGCS2000 / WGS84，3° 带，东坐标加 500 km）；
* 椭球面大地线距离、方位角，以及与高斯平面反算结果的对比；
* 表 3-1 控制网等级参数与按平均边长建议等级；
* 测距先验 ``σS = a + b·S``（论文式 3-37）与平方和模型；
* 测角网 ``P=I`` 的误差方程、协因数阵、最弱点中误差与误差椭圆；
* 坐标转换文本、角度拓扑文本的导出与解析。

单位约定
--------
论文的观测方程使用 ``x``（北）、``y``（东），角度单位为弧度，系数乘
``ρ″=206265``。本模块默认把**坐标改正数取为 mm**，因此测角设计矩阵的
单位为 ``(″)/mm``，协因数阵 ``Q`` 的单位为 ``mm²/(″)²``，
``M = Mw·sqrt(Qxx+Qyy)`` 的单位为 mm。

论文正文/截图中的 ``Qxx=0.6502`` 与本模块严格 mm² 结果的数值关系为
``Q_paper = Q_mm2 / 100``（即论文数值实际对应 cm²/(″)²）。为了让两种口径
都能复核，结果对象同时提供 ``Q``（mm²）与 ``paper_q``（论文截图数值）。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from math import (
    asin,
    asinh,
    atan,
    atan2,
    cos,
    cosh,
    degrees,
    hypot,
    isfinite,
    pi,
    radians,
    sin,
    sinh,
    sqrt,
    tan,
)
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple, Union

import numpy as np

RHO_ARCSEC = 206265.0
"""ρ″，论文式 3-17/3-22 使用的角秒换算常数。"""

ARCSEC_TO_RAD = pi / (180.0 * 3600.0)
RAD_TO_ARCSEC = 1.0 / ARCSEC_TO_RAD


# ---------------------------------------------------------------------------
# 椭球与高斯投影
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Ellipsoid:
    """旋转椭球。``a`` 为长半轴，``f`` 为扁率。"""

    name: str
    a: float
    f: float

    @property
    def b(self) -> float:
        return self.a * (1.0 - self.f)

    @property
    def e2(self) -> float:
        return self.f * (2.0 - self.f)

    @property
    def e(self) -> float:
        return sqrt(self.e2)

    @property
    def n(self) -> float:
        return self.f / (2.0 - self.f)


ELLIPSOIDS: Dict[str, Ellipsoid] = {
    "CGCS2000": Ellipsoid("CGCS2000", 6378137.0, 1.0 / 298.257222101),
    "WGS84": Ellipsoid("WGS84", 6378137.0, 1.0 / 298.257223563),
    "GRS80": Ellipsoid("GRS80", 6378137.0, 1.0 / 298.257222101),
}


def get_ellipsoid(name: Union[str, Ellipsoid] = "CGCS2000") -> Ellipsoid:
    """按名称取椭球；也接受 :class:`Ellipsoid` 实例。"""
    if isinstance(name, Ellipsoid):
        return name
    key = str(name).strip()
    for candidate in (key, key.upper(), key.replace("-", "")):
        if candidate in ELLIPSOIDS:
            return ELLIPSOIDS[candidate]
    aliases = {
        "CGCS-2000": "CGCS2000",
        "CGC2000": "CGCS2000",
        "WGS-84": "WGS84",
        "WGS1984": "WGS84",
    }
    if key.upper() in aliases:
        return ELLIPSOIDS[aliases[key.upper()]]
    raise ValueError(f"未知椭球 {name!r}，可选：{', '.join(ELLIPSOIDS)}")


def central_meridian(lon_deg: float, zone_width: float = 3.0) -> float:
    """按经度计算 3°（或指定带宽）带的中央子午线。"""
    width = float(zone_width)
    if width <= 0.0 or not isfinite(width):
        raise ValueError("zone_width 必须为正的有限值")
    return width * round(float(lon_deg) / width)


def _central_meridian_for(lon_deg: float, zone_width: float) -> float:
    """内部辅助函数，避免与 ``central_meridian`` 形参同名遮蔽。"""
    width = float(zone_width)
    if width <= 0.0 or not isfinite(width):
        raise ValueError("zone_width 必须为正的有限值")
    return width * round(float(lon_deg) / width)


def _alpha_coefficients(n: float) -> Tuple[float, ...]:
    """Krüger 正算 α 系数（Karney 2011，展开到 n⁶）。"""
    return (
        n / 2
        - 2 * n**2 / 3
        + 5 * n**3 / 16
        + 41 * n**4 / 180
        - 127 * n**5 / 288
        + 7891 * n**6 / 37800,
        13 * n**2 / 48
        - 3 * n**3 / 5
        + 557 * n**4 / 1440
        + 281 * n**5 / 630
        - 1983433 * n**6 / 1935360,
        61 * n**3 / 240
        - 103 * n**4 / 140
        + 15061 * n**5 / 26880
        + 167603 * n**6 / 181440,
        49561 * n**4 / 161280
        - 179 * n**5 / 168
        + 6601661 * n**6 / 7257600,
        34729 * n**5 / 80640 - 3418889 * n**6 / 1995840,
        212378941 * n**6 / 319334400,
    )


def _beta_coefficients(n: float) -> Tuple[float, ...]:
    """Krüger 反算 β 系数（Karney 2011，展开到 n⁶）。"""
    return (
        n / 2
        - 2 * n**2 / 3
        + 37 * n**3 / 96
        - n**4 / 360
        - 81 * n**5 / 512
        + 96199 * n**6 / 604800,
        n**2 / 48
        + n**3 / 15
        - 437 * n**4 / 1440
        + 46 * n**5 / 105
        - 1118711 * n**6 / 3870720,
        17 * n**3 / 480
        - 37 * n**4 / 840
        - 209 * n**5 / 4480
        + 5569 * n**6 / 90720,
        4397 * n**4 / 161280
        - 11 * n**5 / 504
        - 830251 * n**6 / 7257600,
        4583 * n**5 / 161280 - 108847 * n**6 / 3991680,
        20648693 * n**6 / 638668800,
    )


def _rectifying_radius(ellipsoid: Ellipsoid) -> float:
    n = ellipsoid.n
    return (
        ellipsoid.a
        / (1.0 + n)
        * (1.0 + n**2 / 4.0 + n**4 / 64.0 + n**6 / 256.0)
    )


def gauss_forward(
    lat_deg: float,
    lon_deg: float,
    *,
    central_meridian: Optional[float] = None,
    ellipsoid: Union[str, Ellipsoid] = "CGCS2000",
    false_easting: float = 500000.0,
    zone_width: float = 3.0,
) -> Tuple[float, float]:
    """经纬度 → 高斯平面坐标 ``(x 北, y 东)``。

    ``central_meridian=None`` 时按 3° 带自动选取中央子午线；``y`` 默认加
    500 km 东偏移。返回单位 m。
    """
    ell = get_ellipsoid(ellipsoid)
    lat = radians(float(lat_deg))
    lon = radians(float(lon_deg))
    if not (-pi / 2.0 < lat < pi / 2.0):
        raise ValueError("纬度必须位于 (-90°, 90°)")
    if central_meridian is None:
        l0_deg = _central_meridian_for(lon_deg, zone_width)
    else:
        l0_deg = float(central_meridian)
    lam = lon - radians(l0_deg)
    if abs(lam) > radians(zone_width * 1.5 + 0.1):
        # 允许少量越带，但明显的中央子午线错误应尽早暴露。
        raise ValueError(
            f"经差 {degrees(lam):.4f}° 超出 {zone_width}° 带的合理范围"
        )

    e = ell.e
    sin_lat = sin(lat)
    chi = 2.0 * atan(
        tan(pi / 4.0 + lat / 2.0)
        * ((1.0 - e * sin_lat) / (1.0 + e * sin_lat)) ** (e / 2.0)
    ) - pi / 2.0

    tan_chi = tan(chi)
    xi_p = atan2(tan_chi, cos(lam))
    eta_p = asinh(sin(lam) / hypot(tan_chi, cos(lam)))

    xi = xi_p
    eta = eta_p
    for j, alpha in enumerate(_alpha_coefficients(ell.n), start=1):
        xi += alpha * sin(2.0 * j * xi_p) * cosh(2.0 * j * eta_p)
        eta += alpha * cos(2.0 * j * xi_p) * sinh(2.0 * j * eta_p)

    scale = _rectifying_radius(ell)
    return scale * xi, scale * eta + float(false_easting)


def gauss_inverse(
    x: float,
    y: float,
    *,
    central_meridian: Optional[float] = None,
    ellipsoid: Union[str, Ellipsoid] = "CGCS2000",
    false_easting: float = 500000.0,
    zone_width: float = 3.0,
    lon_hint: Optional[float] = None,
) -> Tuple[float, float]:
    """高斯平面坐标 ``(x 北, y 东)`` → ``(纬度, 经度)``，单位度。

    若 ``y`` 含带号前缀（``带号*1e6 + 500km``），可自动识别带号；
    否则必须给出 ``central_meridian`` 或 ``lon_hint`` 才能确定中央子午线。
    """
    ell = get_ellipsoid(ellipsoid)
    easting = float(y)
    l0_deg = central_meridian
    if l0_deg is None:
        if easting >= 1_000_000.0:
            zone = int(easting // 1_000_000.0)
            easting -= zone * 1_000_000.0
            l0_deg = zone * float(zone_width)
        elif lon_hint is not None:
            l0_deg = _central_meridian_for(float(lon_hint), zone_width)
        else:
            raise ValueError(
                "反算需要 central_meridian、lon_hint，或含带号的 y 坐标"
            )

    scale = _rectifying_radius(ell)
    xi = float(x) / scale
    eta = (easting - float(false_easting)) / scale

    xi_p = xi
    eta_p = eta
    for j, beta in enumerate(_beta_coefficients(ell.n), start=1):
        xi_p -= beta * sin(2.0 * j * xi) * cosh(2.0 * j * eta)
        eta_p -= beta * cos(2.0 * j * xi) * sinh(2.0 * j * eta)

    sin_chi = sin(xi_p) / cosh(eta_p)
    sin_chi = min(1.0, max(-1.0, sin_chi))
    chi = asin(sin_chi)
    lam = atan2(sinh(eta_p), cos(xi_p))

    e = ell.e
    phi = chi
    for _ in range(20):
        phi_new = 2.0 * atan(
            tan(pi / 4.0 + chi / 2.0)
            * ((1.0 + e * sin(phi)) / (1.0 - e * sin(phi))) ** (e / 2.0)
        ) - pi / 2.0
        if abs(phi_new - phi) < 1e-15:
            phi = phi_new
            break
        phi = phi_new

    lon = radians(float(l0_deg)) + lam
    return degrees(phi), degrees(lon)


# ---------------------------------------------------------------------------
# 椭球面距离与方位角
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class GeodesicResult:
    """椭球面大地线反算结果。"""

    distance: float
    azimuth: float
    back_azimuth: float
    iterations: int = 0

    @property
    def azimuth_deg(self) -> float:
        return self.azimuth

    @property
    def back_azimuth_deg(self) -> float:
        return self.back_azimuth


def geodesic_inverse(
    lat1_deg: float,
    lon1_deg: float,
    lat2_deg: float,
    lon2_deg: float,
    *,
    ellipsoid: Union[str, Ellipsoid] = "CGCS2000",
    tolerance: float = 1e-13,
    max_iterations: int = 200,
) -> GeodesicResult:
    """Vincenty 大地线反算：距离（m）与正/反方位角（°，从北顺时针）。"""
    ell = get_ellipsoid(ellipsoid)
    a, b, f = ell.a, ell.b, ell.f
    phi1, phi2 = radians(float(lat1_deg)), radians(float(lat2_deg))
    L = radians(float(lon2_deg) - float(lon1_deg))
    if not all(isfinite(v) for v in (phi1, phi2, L)):
        raise ValueError("经纬度必须是有限值")

    U1 = atan((1.0 - f) * tan(phi1))
    U2 = atan((1.0 - f) * tan(phi2))
    sinU1, cosU1 = sin(U1), cos(U1)
    sinU2, cosU2 = sin(U2), cos(U2)

    lam = L
    for iteration in range(1, max_iterations + 1):
        sin_lam, cos_lam = sin(lam), cos(lam)
        sin_sigma = hypot(
            cosU2 * sin_lam, cosU1 * sinU2 - sinU1 * cosU2 * cos_lam
        )
        if sin_sigma == 0.0:
            return GeodesicResult(0.0, 0.0, 0.0, iteration)
        cos_sigma = sinU1 * sinU2 + cosU1 * cosU2 * cos_lam
        sigma = atan2(sin_sigma, cos_sigma)
        sin_alpha = cosU1 * cosU2 * sin_lam / sin_sigma
        cos2_alpha = 1.0 - sin_alpha * sin_alpha
        if cos2_alpha == 0.0:
            cos2_sigma_m = 0.0
        else:
            cos2_sigma_m = cos_sigma - 2.0 * sinU1 * sinU2 / cos2_alpha
        C = f / 16.0 * cos2_alpha * (4.0 + f * (4.0 - 3.0 * cos2_alpha))
        lam_prev = lam
        lam = L + (1.0 - C) * f * sin_alpha * (
            sigma
            + C
            * sin_sigma
            * (
                cos2_sigma_m
                + C * cos_sigma * (-1.0 + 2.0 * cos2_sigma_m * cos2_sigma_m)
            )
        )
        if abs(lam - lam_prev) < tolerance:
            break
    else:  # pragma: no cover - 近对跖点才会触发
        raise ArithmeticError("Vincenty 反算未收敛（可能为近对跖点）")

    u2 = cos2_alpha * (a * a - b * b) / (b * b)
    A = 1.0 + u2 / 16384.0 * (
        4096.0 + u2 * (-768.0 + u2 * (320.0 - 175.0 * u2))
    )
    B = u2 / 1024.0 * (256.0 + u2 * (-128.0 + u2 * (74.0 - 47.0 * u2)))
    delta_sigma = B * sin_sigma * (
        cos2_sigma_m
        + B
        / 4.0
        * (
            cos_sigma * (-1.0 + 2.0 * cos2_sigma_m * cos2_sigma_m)
            - B
            / 6.0
            * cos2_sigma_m
            * (-3.0 + 4.0 * sin_sigma * sin_sigma)
            * (-3.0 + 4.0 * cos2_sigma_m * cos2_sigma_m)
        )
    )
    distance = b * A * (sigma - delta_sigma)

    az1 = atan2(
        cosU2 * sin(lam),
        cosU1 * sinU2 - sinU1 * cosU2 * cos(lam),
    )
    az2 = atan2(
        cosU1 * sin(lam),
        -sinU1 * cosU2 + cosU1 * sinU2 * cos(lam),
    )
    az1_deg = degrees(az1) % 360.0
    # az2 是沿大地线到达点 2 后的前进方向；B→A 的反方位角与其相差 180°。
    back_azimuth_deg = (degrees(az2) + 180.0) % 360.0
    return GeodesicResult(distance, az1_deg, back_azimuth_deg, iteration)


def plane_distance_azimuth(
    x1: float,
    y1: float,
    x2: float,
    y2: float,
) -> Tuple[float, float]:
    """高斯平面两点距离与方位角（°）；``x`` 北、``y`` 东。"""
    dx = float(x2) - float(x1)
    dy = float(y2) - float(y1)
    distance = hypot(dx, dy)
    azimuth = degrees(atan2(dy, dx)) % 360.0
    return distance, azimuth


@dataclass(frozen=True)
class GeodesicPlaneComparison:
    """同一对点的椭球面结果与高斯平面反算结果。"""

    geodesic_distance: float
    geodesic_azimuth: float
    plane_distance: float
    plane_azimuth: float
    distance_difference: float
    azimuth_difference: float


def compare_geodesic_and_plane(
    lat1_deg: float,
    lon1_deg: float,
    lat2_deg: float,
    lon2_deg: float,
    *,
    central_meridian: Optional[float] = None,
    ellipsoid: Union[str, Ellipsoid] = "CGCS2000",
) -> GeodesicPlaneComparison:
    """椭球面距离/方位角与高斯平面反算的对比（差值：椭球 − 平面）。"""
    geo = geodesic_inverse(lat1_deg, lon1_deg, lat2_deg, lon2_deg, ellipsoid=ellipsoid)
    x1, y1 = gauss_forward(
        lat1_deg, lon1_deg, central_meridian=central_meridian, ellipsoid=ellipsoid
    )
    x2, y2 = gauss_forward(
        lat2_deg, lon2_deg, central_meridian=central_meridian, ellipsoid=ellipsoid
    )
    plane_s, plane_az = plane_distance_azimuth(x1, y1, x2, y2)
    daz = (geo.azimuth - plane_az + 180.0) % 360.0 - 180.0
    return GeodesicPlaneComparison(
        geodesic_distance=geo.distance,
        geodesic_azimuth=geo.azimuth,
        plane_distance=plane_s,
        plane_azimuth=plane_az,
        distance_difference=geo.distance - plane_s,
        azimuth_difference=daz,
    )


# ---------------------------------------------------------------------------
# 表 3-1：控制网等级
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ControlGrade:
    """论文表 3-1 的一行。"""

    name: str
    mean_side_km: Optional[float]
    angle_sigma_arcsec: float
    a_mm: float
    b_ppm: float
    max_relative_denominator: int

    @property
    def label(self) -> str:
        return self.name

    @property
    def max_relative(self) -> float:
        return 1.0 / self.max_relative_denominator


GRADES: Tuple[ControlGrade, ...] = (
    ControlGrade("二等", 9.0, 1.0, 10.0, 2.0, 120000),
    ControlGrade("三等", 5.0, 1.8, 10.0, 5.0, 80000),
    ControlGrade("四等", 2.0, 2.5, 10.0, 10.0, 45000),
    ControlGrade("一级", 1.0, 5.0, 10.0, 10.0, 20000),
    ControlGrade("二级", None, 10.0, 15.0, 20.0, 10000),
)
GRADE_TABLE: Dict[str, ControlGrade] = {g.name: g for g in GRADES}


def get_grade(name: Union[str, ControlGrade]) -> ControlGrade:
    """按名称取等级参数。"""
    if isinstance(name, ControlGrade):
        return name
    key = str(name).strip()
    aliases = {"2": "二等", "3": "三等", "4": "四等", "1": "一级", "二": "二级"}
    if key in GRADE_TABLE:
        return GRADE_TABLE[key]
    if key in aliases:
        return GRADE_TABLE[aliases[key]]
    raise ValueError(f"未知控制网等级 {name!r}，可选：{', '.join(GRADE_TABLE)}")


def suggest_grade(mean_side_m: float) -> ControlGrade:
    """按平均边长建议等级（表 3-1）。

    等级区间：≥9 km 二等；[5, 9) km 三等；[2, 5) km 四等；
    [1, 2) km 一级；<1 km 二级。``二级`` 的平均边长为“<1 km”。
    """
    mean_km = float(mean_side_m) / 1000.0
    if not isfinite(mean_km) or mean_km <= 0.0:
        raise ValueError("平均边长必须为正的有限值")
    if mean_km >= 9.0:
        return GRADE_TABLE["二等"]
    if mean_km >= 5.0:
        return GRADE_TABLE["三等"]
    if mean_km >= 2.0:
        return GRADE_TABLE["四等"]
    if mean_km >= 1.0:
        return GRADE_TABLE["一级"]
    return GRADE_TABLE["二级"]


def grade_from_mean_side(mean_side_m: float) -> ControlGrade:
    """``suggest_grade`` 的别名。"""
    return suggest_grade(mean_side_m)


# ---------------------------------------------------------------------------
# 测距先验中误差与定权
# ---------------------------------------------------------------------------


def distance_sigma_mm(
    s_m: float,
    *,
    a_mm: float,
    b_ppm: float,
    model: str = "quadrature",
) -> float:
    """测距先验中误差（mm）。

    ``model="linear"``：``a + b·S``（S 以 km 计，论文式 3-37）；
    ``model="quadrature"``：``sqrt(a² + (b·S)²)``。
    """
    s_km = abs(float(s_m)) / 1000.0
    a = float(a_mm)
    b = float(b_ppm)
    choice = str(model).strip().lower()
    if choice == "linear":
        return a + b * s_km
    if choice in ("quadrature", "sqrt", "rss"):
        return hypot(a, b * s_km)
    raise ValueError("model 只能是 'linear' 或 'quadrature'")


def distance_sigma_m(
    s_m: float,
    *,
    a_mm: float,
    b_ppm: float,
    model: str = "quadrature",
) -> float:
    """与 :func:`distance_sigma_mm` 相同，返回米。"""
    return distance_sigma_mm(s_m, a_mm=a_mm, b_ppm=b_ppm, model=model) / 1000.0


def distance_weight(
    s_m: float,
    *,
    a_mm: float,
    b_ppm: float,
    model: str = "linear",
    sigma0: float = 1.0,
) -> float:
    """论文式 3-36 的权 ``P = σ0² / σS²``（σS 以 mm 计）。"""
    sigma_mm = distance_sigma_mm(s_m, a_mm=a_mm, b_ppm=b_ppm, model=model)
    return float(sigma0) ** 2 / (sigma_mm * sigma_mm)


def grade_distance_sigma_mm(
    s_m: float,
    grade: Union[str, ControlGrade],
    *,
    model: str = "linear",
) -> float:
    """按等级表参数计算测距先验中误差。"""
    g = get_grade(grade)
    return distance_sigma_mm(s_m, a_mm=g.a_mm, b_ppm=g.b_ppm, model=model)


# ---------------------------------------------------------------------------
# 角度拓扑 / 坐标文本的导出与解析
# ---------------------------------------------------------------------------


def _split_topology(text: str) -> List[List[int]]:
    raw = str(text).strip()
    raw = raw.replace("，", ",").replace("；", ";").replace(" ", "")
    if raw.startswith("["):
        raw = raw[1:]
    if raw.endswith("]"):
        raw = raw[:-1]
    triples: List[List[int]] = []
    for chunk in raw.split(";"):
        chunk = chunk.strip()
        if not chunk:
            continue
        parts = [p for p in chunk.split(",") if p != ""]
        if len(parts) != 3:
            raise ValueError(f"角度拓扑每组必须三个编号：{chunk!r}")
        triples.append([int(p) for p in parts])
    if not triples:
        raise ValueError("角度拓扑为空")
    return triples


def parse_angle_topology(
    text: str,
    *,
    known_names: Sequence[str] = ("8", "9"),
    order: str = "station_first",
) -> List[Tuple[str, str, str]]:
    """解析 ``[-1,1,2;-2,-1,2;...]`` 形式的角度拓扑。

    负编号 ``-1``、``-2`` … 依次映射到 ``known_names``；正编号保留为点名。
    返回规范化的 ``(后视, 测站, 前视)`` 三元组列表。

    ``order="station_first"`` 表示原文三元组为 ``(测站, 后视, 前视)``；
    ``order="backsight_first"`` 表示原文即为 ``(后视, 测站, 前视)``。
    """
    known = [str(k) for k in known_names]
    mode = str(order).strip().lower()
    if mode not in ("station_first", "backsight_first"):
        raise ValueError("order 只能是 'station_first' 或 'backsight_first'")
    angles: List[Tuple[str, str, str]] = []
    for triple in _split_topology(text):
        names: List[str] = []
        for value in triple:
            if value < 0:
                index = -value - 1
                if index >= len(known):
                    raise ValueError(
                        f"负编号 {value} 超出已知点表 {tuple(known_names)!r}"
                    )
                names.append(known[index])
            elif value == 0:
                raise ValueError("角度拓扑中不允许编号 0")
            else:
                names.append(str(value))
        if mode == "station_first":
            station, backsight, foresight = names
        else:
            backsight, station, foresight = names
        angles.append((backsight, station, foresight))
    return angles


def export_angle_topology(
    angles: Iterable[Sequence[str]],
    *,
    known_names: Sequence[str] = ("8", "9"),
    order: str = "station_first",
    unknown_ids: Optional[Mapping[str, int]] = None,
    include_brackets: bool = True,
) -> str:
    """把 ``(后视, 测站, 前视)`` 角列表导出为论文的 ``[-1,1,2;...]`` 文本。"""
    known = [str(k) for k in known_names]
    known_to_negative = {name: -(i + 1) for i, name in enumerate(known)}
    mapping = dict(unknown_ids or {})
    if mapping:
        used = set(mapping.values())
        if any(v <= 0 or int(v) != v for v in used):
            raise ValueError("unknown_ids 必须是正整数编号")
        if len(used) != len(mapping):
            raise ValueError("unknown_ids 的编号必须唯一")

    def code(name: Any) -> int:
        text = str(name)
        if text in known_to_negative:
            return known_to_negative[text]
        if text in mapping:
            return int(mapping[text])
        try:
            value = int(text)
        except ValueError:
            raise ValueError(
                f"未知点 {text!r} 没有数字编号；请提供 unknown_ids"
            ) from None
        if value <= 0:
            raise ValueError(f"未知点编号必须为正整数：{text!r}")
        return value

    mode = str(order).strip().lower()
    if mode not in ("station_first", "backsight_first"):
        raise ValueError("order 只能是 'station_first' 或 'backsight_first'")
    chunks: List[str] = []
    for angle in angles:
        if len(angle) != 3:
            raise ValueError("每个角度必须给出三个点")
        backsight, station, foresight = (str(v) for v in angle)
        if mode == "station_first":
            triple = (station, backsight, foresight)
        else:
            triple = (backsight, station, foresight)
        chunks.append(",".join(str(code(v)) for v in triple))
    text = ";".join(chunks)
    return f"[{text}]" if include_brackets else text


def export_coordinate_text(
    points: Union[Mapping[str, Sequence[float]], Iterable[Any]],
    names: Optional[Sequence[str]] = None,
    *,
    precision: int = 9,
    point_prefix: str = "点",
    separator: str = "；",
    coordinate_separator: str = "，",
) -> str:
    """导出“点1；x，y”逐行文本（``x`` 北、``y`` 东，单位 m）。"""
    coords = _coerce_point_map(points)
    order = [str(n) for n in names] if names is not None else list(coords)
    lines: List[str] = []
    for name in order:
        if name not in coords:
            raise KeyError(f"坐标表中不存在点 {name!r}")
        x, y = coords[name]
        lines.append(
            f"{point_prefix}{name}{separator}"
            f"{x:.{int(precision)}f}{coordinate_separator}{y:.{int(precision)}f}"
        )
    return "\n".join(lines)


def parse_coordinate_text(text: str) -> "Dict[str, Tuple[float, float]]":
    """解析“点1；x，y”逐行文本。"""
    import re

    result: Dict[str, Tuple[float, float]] = {}
    for raw in str(text).splitlines():
        line = raw.strip()
        if not line:
            continue
        line = re.sub(r"^点\s*", "", line)
        parts = [p for p in re.split(r"[；;，,\s]+", line) if p]
        if len(parts) != 3:
            raise ValueError(f"无法解析坐标行：{raw!r}")
        name = parts[0]
        try:
            x, y = float(parts[1]), float(parts[2])
        except ValueError as exc:
            raise ValueError(f"坐标不是数值：{raw!r}") from exc
        if name in result:
            raise ValueError(f"点号重复：{name}")
        if not np.isfinite(x) or not np.isfinite(y):
            raise ValueError(f"坐标必须为有限数：{name}")
        result[name] = (x, y)
    if not result:
        raise ValueError("坐标文本为空")
    return result


# ---------------------------------------------------------------------------
# 测角网 / 边角网的论文约定
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ThesisEllipse:
    """论文式 3-38/3-39 的误差椭圆元素。"""

    E: float
    F: float
    phi_E_deg: float
    QEE: float
    QFF: float
    K: float

    @property
    def semi_major(self) -> float:
        return self.E

    @property
    def semi_minor(self) -> float:
        return self.F

    @property
    def azimuth_deg(self) -> float:
        return self.phi_E_deg


def error_ellipse(
    qxx: float,
    qyy: float,
    qxy: float = 0.0,
    *,
    mw: float = 1.0,
) -> ThesisEllipse:
    """按式 3-38/3-39 计算误差椭圆。

    ``Q`` 的单位应与 ``mw`` 对应：若 ``Q`` 为 mm²/(″)²、``mw`` 为 ″，
    则 ``E``、``F`` 为 mm。
    """
    qxx = float(qxx)
    qyy = float(qyy)
    qxy = float(qxy)
    k = sqrt(max((qxx - qyy) ** 2 + 4.0 * qxy * qxy, 0.0))
    qee = 0.5 * (qxx + qyy + k)
    qff = 0.5 * (qxx + qyy - k)
    # 与式 3-38 的 atan((QEE-QXX)/QXY) 等价，但使用 atan2 保证象限正确。
    phi = degrees(0.5 * atan2(2.0 * qxy, qxx - qyy)) % 180.0
    scale = float(mw)
    return ThesisEllipse(
        E=scale * sqrt(max(qee, 0.0)),
        F=scale * sqrt(max(qff, 0.0)),
        phi_E_deg=phi,
        QEE=qee,
        QFF=qff,
        K=k,
    )


def _coerce_point_map(
    points: Union[Mapping[str, Sequence[float]], Iterable[Any]],
) -> Dict[str, Tuple[float, float]]:
    """把映射、``Point`` 序列或 ``(name, x, y)`` 序列统一为坐标表。"""
    result: Dict[str, Tuple[float, float]] = {}
    if isinstance(points, Mapping):
        for name, value in points.items():
            if len(value) != 2:
                raise ValueError(f"点 {name!r} 的坐标必须是 (x, y)")
            result[str(name)] = (float(value[0]), float(value[1]))
        return result
    for item in points:
        if hasattr(item, "E") and hasattr(item, "N") and hasattr(item, "name"):
            result[str(item.name)] = (float(item.N), float(item.E))
        elif isinstance(item, (tuple, list)) and len(item) == 3:
            result[str(item[0])] = (float(item[1]), float(item[2]))
        else:
            raise TypeError(f"无法解析点坐标：{item!r}")
    return result


def _angle_row(
    backsight: str,
    station: str,
    foresight: str,
    coords: Mapping[str, Tuple[float, float]],
    columns: Mapping[str, int],
    *,
    rho: float,
    coordinate_unit_mm: float,
    row: np.ndarray,
    index: int,
) -> None:
    """式 3-22 的一行；坐标改正单位为 ``coordinate_unit_mm`` 毫米。"""
    xs, ys = coords[station]

    def gradients(target: str) -> Tuple[float, float, float, float]:
        xt, yt = coords[target]
        dx = xt - xs
        dy = yt - ys
        s2 = dx * dx + dy * dy
        if s2 <= 0.0:
            raise ValueError(f"点 {station!r} 与 {target!r} 重合")
        # α 对 station/target 坐标（m）的偏导，rad/m。
        return (dy / s2, -dx / s2, -dy / s2, dx / s2)

    gb = gradients(backsight)
    gf = gradients(foresight)
    factor = rho * float(coordinate_unit_mm) / 1000.0
    # 角 = α(前视) − α(后视)
    terms = (
        (station, gf[0] - gb[0], gf[1] - gb[1]),
        (backsight, -gb[2], -gb[3]),
        (foresight, gf[2], gf[3]),
    )
    for name, gx, gy in terms:
        col = columns.get(name)
        if col is None:
            continue
        row[index, col] += gx * factor
        row[index, col + 1] += gy * factor


def _distance_row(
    frm: str,
    to: str,
    coords: Mapping[str, Tuple[float, float]],
    columns: Mapping[str, int],
    row: np.ndarray,
    index: int,
) -> None:
    """式 3-30 的一行；距离以 mm 计、坐标改正以 mm 计，故系数无量纲。"""
    xf, yf = coords[frm]
    xt, yt = coords[to]
    dx, dy = xt - xf, yt - yf
    s = hypot(dx, dy)
    if s <= 0.0:
        raise ValueError(f"点 {frm!r} 与 {to!r} 重合")
    for name, sign in ((frm, -1.0), (to, 1.0)):
        col = columns.get(name)
        if col is None:
            continue
        row[index, col] += sign * dx / s
        row[index, col + 1] += sign * dy / s


@dataclass
class ThesisNetworkResult:
    """论文约定的设计态平差结果。"""

    points: Dict[str, Tuple[float, float]]
    unknown: List[str]
    angles: List[Tuple[str, str, str]]
    distances: List[Tuple[str, str]]
    B: np.ndarray
    Q: np.ndarray
    mw_arcsec: float = 10.0
    coordinate_unit_mm: float = 1.0
    weights: Optional[np.ndarray] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    # ---- 基本索引 -------------------------------------------------
    @property
    def parameter_names(self) -> List[str]:
        return [f"{axis}_{name}" for name in self.unknown for axis in ("x", "y")]

    def _cols(self, name: str) -> Tuple[int, int]:
        try:
            i = self.unknown.index(str(name))
        except ValueError:
            raise KeyError(f"{name!r} 不是未知点") from None
        return 2 * i, 2 * i + 1

    @property
    def q_mm2(self) -> np.ndarray:
        """严格 mm²/(″)² 的协因数阵（仅对测角网有意义）。"""
        return self.Q * self.coordinate_unit_mm**2

    def point_q(self, name: str) -> Tuple[float, float, float]:
        """返回 ``(Qxx, Qyy, Qxy)``，单位为 mm²/(″)²。"""
        i, j = self._cols(name)
        q = self.q_mm2
        return float(q[i, i]), float(q[j, j]), float(q[i, j])

    def paper_q(self, name: str) -> Tuple[float, float, float]:
        """论文截图口径的数值（严格 mm² 数值 / 100，即 cm²/(″)²）。"""
        qxx, qyy, qxy = self.point_q(name)
        return qxx / 100.0, qyy / 100.0, qxy / 100.0

    def mp_mm(self, name: str, mw_arcsec: Optional[float] = None) -> float:
        """严格最弱点中误差 ``Mw·sqrt(Qxx+Qyy)``，单位 mm。"""
        qxx, qyy, _ = self.point_q(name)
        mw = self.mw_arcsec if mw_arcsec is None else float(mw_arcsec)
        return mw * sqrt(max(qxx + qyy, 0.0))

    def paper_mp_mm(self, name: str, mw_arcsec: Optional[float] = None) -> float:
        """论文数值口径的 ``Mw·sqrt(Qpaper_xx+Qpaper_yy)``。

        该数值可精确复现论文的 9.77/8.06 等数字，但其单位标注在论文中
        存在 cm→mm 的口径问题；严格结果请用 :meth:`mp_mm`。
        """
        qxx, qyy, _ = self.paper_q(name)
        mw = self.mw_arcsec if mw_arcsec is None else float(mw_arcsec)
        return mw * sqrt(max(qxx + qyy, 0.0))

    def weakest_point(self) -> str:
        values = {name: self.mp_mm(name) for name in self.unknown}
        return max(values, key=values.get)

    def weakest_points(self) -> List[str]:
        values = {name: self.mp_mm(name) for name in self.unknown}
        best = max(values.values()) if values else 0.0
        return [name for name, value in values.items() if abs(value - best) <= 1e-12]

    def ellipse(self, name: str, mw_arcsec: Optional[float] = None) -> ThesisEllipse:
        qxx, qyy, qxy = self.point_q(name)
        mw = self.mw_arcsec if mw_arcsec is None else float(mw_arcsec)
        return error_ellipse(qxx, qyy, qxy, mw=mw)

    def edge_propagated_sigma_mm(
        self, frm: str, to: str, mw_arcsec: Optional[float] = None
    ) -> float:
        """按 ``Q`` 传播的边长中误差（mm），仅用于和论文表值对比。"""
        xf, yf = self.points[frm]
        xt, yt = self.points[to]
        dx, dy = xt - xf, yt - yf
        s = hypot(dx, dy)
        if s <= 0.0:
            raise ValueError("重合点不能计算边长精度")
        g = np.zeros(self.Q.shape[0])
        for name, sign in ((frm, -1.0), (to, 1.0)):
            col = self._columns_or_none(name)
            if col is None:
                continue
            g[col] += sign * dx / s
            g[col + 1] += sign * dy / s
        mw = self.mw_arcsec if mw_arcsec is None else float(mw_arcsec)
        variance = float(g @ self.q_mm2 @ g)
        return mw * sqrt(max(variance, 0.0))

    def _columns_or_none(self, name: str) -> Optional[int]:
        try:
            return self._cols(name)[0]
        except KeyError:
            return None

    def edge_denominators(
        self,
        edges: Iterable[Sequence[str]],
        *,
        paper_sigma_m: float = 0.01,
    ) -> List[Dict[str, float]]:
        """论文图 5-7/5-12 的“边长相对中误差分母”。

        反推得到论文算法等价于取固定边长中误差 1 cm：
        ``分母 = S / 0.01 m = 100·S``（与端点坐标精度无关）。同时给出
        按 Q 严格传播的边长中误差供对照。
        """
        rows: List[Dict[str, float]] = []
        for edge in edges:
            frm, to = str(edge[0]), str(edge[1])
            xf, yf = self.points[frm]
            xt, yt = self.points[to]
            length = hypot(xt - xf, yt - yf)
            denominator = length / float(paper_sigma_m) if paper_sigma_m > 0 else float("inf")
            rows.append(
                {
                    "from": frm,
                    "to": to,
                    "length": length,
                    "paper_denominator": denominator,
                    "propagated_sigma_mm": self.edge_propagated_sigma_mm(frm, to),
                }
            )
        return rows


def build_network(
    points: Union[Mapping[str, Sequence[float]], Iterable[Any]],
    *,
    unknown: Optional[Sequence[str]] = None,
    known: Sequence[str] = (),
    angles: Iterable[Sequence[str]] = (),
    distances: Iterable[Sequence[str]] = (),
    mw_arcsec: float = 10.0,
    coordinate_unit_mm: float = 1.0,
    rho: float = RHO_ARCSEC,
    distance_a_mm: float = 15.0,
    distance_b_ppm: float = 20.0,
    distance_sigma_model: str = "linear",
    distance_weights: bool = False,
    sigma0: float = 1.0,
) -> ThesisNetworkResult:
    """按论文式 3-22/3-30 组装设计矩阵并求 ``Q=(BᵀPB)⁻¹``。

    ``angles`` 使用规范化顺序 ``(后视, 测站, 前视)``。``distances`` 的权
    默认关闭（测角网 ``P=I``）；边角网可设 ``distance_weights=True``，此时
    ``P=σ0²/σ_S²``、``σS=a+bS``。
    """
    coords = _coerce_point_map(points)
    names = list(coords)
    known_names = [str(k) for k in known]
    if unknown is None:
        unknown_names = [n for n in names if n not in known_names]
    else:
        unknown_names = [str(n) for n in unknown]
    for name in unknown_names:
        if name not in coords:
            raise KeyError(f"未知点 {name!r} 不在坐标表中")
        if name in known_names:
            raise ValueError(f"点 {name!r} 同时被指定为已知点和未知点")

    angle_list = [(str(a[0]), str(a[1]), str(a[2])) for a in angles]
    distance_list = [(str(d[0]), str(d[1])) for d in distances]
    columns = {name: 2 * i for i, name in enumerate(unknown_names)}
    n_angle = len(angle_list)
    n_distance = len(distance_list)
    n_rows = n_angle + n_distance
    if n_rows == 0:
        raise ValueError("至少需要一个角度或边长观测")

    B = np.zeros((n_rows, 2 * len(unknown_names)), dtype=float)
    weights = np.ones(n_rows, dtype=float)
    for i, (backsight, station, foresight) in enumerate(angle_list):
        _angle_row(
            backsight,
            station,
            foresight,
            coords,
            columns,
            rho=rho,
            coordinate_unit_mm=coordinate_unit_mm,
            row=B,
            index=i,
        )
    for k, (frm, to) in enumerate(distance_list):
        i = n_angle + k
        _distance_row(frm, to, coords, columns, B, i)
        if distance_weights:
            length = hypot(
                coords[to][0] - coords[frm][0], coords[to][1] - coords[frm][1]
            )
            sigma_mm = distance_sigma_mm(
                length,
                a_mm=distance_a_mm,
                b_ppm=distance_b_ppm,
                model=distance_sigma_model,
            )
            weights[i] = (float(sigma0) ** 2) / (sigma_mm * sigma_mm)

    P = np.diag(weights)
    normal = B.T @ P @ B
    rank = int(np.linalg.matrix_rank(normal))
    if rank < normal.shape[0]:
        raise np.linalg.LinAlgError(
            f"法方程秩亏：rank={rank}，参数数={normal.shape[0]}；"
            "请检查已知点、观测连接与拓扑"
        )
    Q = np.linalg.inv(normal)
    return ThesisNetworkResult(
        points=coords,
        unknown=unknown_names,
        angles=angle_list,
        distances=distance_list,
        B=B,
        Q=Q,
        mw_arcsec=float(mw_arcsec),
        coordinate_unit_mm=float(coordinate_unit_mm),
        weights=weights,
        metadata={
            "rank": rank,
            "n_rows": n_rows,
            "redundancy": n_rows - rank,
            "rho": float(rho),
            "distance_weights": bool(distance_weights),
        },
    )


def build_angle_network(
    points: Union[Mapping[str, Sequence[float]], Iterable[Any]],
    angles: Iterable[Sequence[str]],
    *,
    unknown: Optional[Sequence[str]] = None,
    known: Sequence[str] = (),
    mw_arcsec: float = 10.0,
    coordinate_unit_mm: float = 1.0,
) -> ThesisNetworkResult:
    """测角网便捷入口（``P=I``）。"""
    return build_network(
        points,
        unknown=unknown,
        known=known,
        angles=angles,
        mw_arcsec=mw_arcsec,
        coordinate_unit_mm=coordinate_unit_mm,
    )


def thesis_edge_denominator(length_m: float, *, sigma_m: float = 0.01) -> float:
    """论文图 5-7 的边长相对中误差分母：``S / 0.01``。"""
    if sigma_m <= 0:
        raise ValueError("sigma_m 必须为正")
    return abs(float(length_m)) / float(sigma_m)


def check_tolerance(
    mp_mm: float,
    *,
    tolerance_mm: float = 20.0,
) -> Tuple[bool, str]:
    """按限差判定最弱点是否满足精度要求。"""
    ok = float(mp_mm) <= float(tolerance_mm)
    text = f"{mp_mm:.2f} mm {'≤' if ok else '>'} {tolerance_mm:.2f} mm"
    return ok, ("满足精度要求：" if ok else "不满足精度要求：") + text


__all__ = [
    "RHO_ARCSEC",
    "ARCSEC_TO_RAD",
    "RAD_TO_ARCSEC",
    "Ellipsoid",
    "ELLIPSOIDS",
    "get_ellipsoid",
    "central_meridian",
    "gauss_forward",
    "gauss_inverse",
    "GeodesicResult",
    "geodesic_inverse",
    "plane_distance_azimuth",
    "GeodesicPlaneComparison",
    "compare_geodesic_and_plane",
    "ControlGrade",
    "GRADES",
    "GRADE_TABLE",
    "get_grade",
    "suggest_grade",
    "grade_from_mean_side",
    "distance_sigma_mm",
    "distance_sigma_m",
    "distance_weight",
    "grade_distance_sigma_mm",
    "parse_angle_topology",
    "export_angle_topology",
    "export_coordinate_text",
    "parse_coordinate_text",
    "ThesisEllipse",
    "error_ellipse",
    "ThesisNetworkResult",
    "build_network",
    "build_angle_network",
    "thesis_edge_denominator",
    "check_tolerance",
]
