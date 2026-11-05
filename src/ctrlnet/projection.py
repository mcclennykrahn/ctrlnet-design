"""高斯/UTM 投影尺度、子午线收敛角与 grid/ground 距离归算。

本模块是 ``docs/redesign_plan.md`` §5.2 的纯函数实现，复用
:mod:`ctrlnet.thesis` 的椭球常数、Krüger n⁶ 系数与高斯正反算，不复制第二套
椭球参数。所有长度单位为 **米**，角度输入为 **度**；除非函数名/参数明确说明，
内部计算使用弧度。

符号与单位约定
--------------
- 高斯平面坐标按 ``(E, N)``（东、北）表达；``thesis.gauss_forward`` 返回
  ``(x 北, y 东)``，本模块负责顺序转换。
- 投影尺度因子 ``m = ds_grid / ds_ellipsoid``，无量纲。UTM 的中央经线尺度为
  ``k0 = 0.9996``，高斯-克吕格通常 ``k0 = 1``。
- 子午线收敛角 ``γ`` 定义为 **真北方位角 − 网格方位角**，即
  ``grid_azimuth = true_azimuth − γ``。东于中央子午线时 ``γ > 0``。函数返回值
  默认单位为度，另可请求角秒/弧度。
- 高程归算采用平均高程/椭球高近似：

  ``s_ellipsoid ≈ s_ground · R / (R + H_m)``

  其中 ``R = sqrt(M·N)`` 为测区纬度处的局部平均曲率半径（m），``H_m`` 为测线
  平均大地高（m，EGM/正常高作为近似也可，但须在成果中注明）。综合尺度：
  ``k_comb = k_projection · R/(R+H_m)``，``s_grid = s_ground · k_comb``。
  该近似忽略测线两端曲率半径变化与重力线弯曲，适用于工程边长；高精度成果
  应使用逐点/逐边积分或 PROJ/GeographicLib。

尺度/收敛角的严格性
-------------------
高斯-克吕格复变形式（Karney 2011，展开到 n⁶）：

``w = ψ + i·λ``（ψ 为等量纬度，λ 为相对中央子午线的经差），
``z = atan(sinh w)``，``ζ = z + Σ_j α_j sin(2jz)``，
``dζ/dw = sech(w) · [1 + Σ_j 2j·α_j cos(2jz)]``。

于是 ``m = k0 · A/(N cosφ) · |dζ/dw|``，``γ = −arg(dζ/dw)``，``A`` 为
底点纬度的 rectifying radius。对同一 Krüger n⁶ 级数，该式与
:func:`ctrlnet.thesis.gauss_forward` 的雅可比一致；在 3° 带内与二阶解析级数
的差异远小于 0.001 ppm。
"""

from __future__ import annotations

import cmath
import math
from dataclasses import dataclass
from math import atan, cos, degrees, floor, isfinite, pi, radians, sin, sqrt
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple, Union

from .thesis import (
    Ellipsoid,
    _alpha_coefficients,
    _rectifying_radius,
    central_meridian as _thesis_central_meridian,
    gauss_forward,
    gauss_inverse,
    get_ellipsoid,
)

DEFAULT_ZONE_WIDTH = 3.0
"""默认 3° 带（中国高斯-克吕格常用）。"""

UTM_SCALE_FACTOR = 0.9996
"""UTM 中央经线尺度因子。"""

GAUSS_SCALE_FACTOR = 1.0
"""高斯-克吕格中央经线尺度因子。"""

DEFAULT_FALSE_EASTING = 500000.0
"""默认东偏移 500 km。"""

SCALE_WARNING_PPM = 10.0
"""|k/k0 − 1| 超过该值（ppm）提示投影变形不可忽略。"""

COMBINED_SCALE_WARNING_PPM = 25.0
"""综合尺度偏差提示阈值（ppm，约 2.5 cm/km）。"""

CONVERGENCE_WARNING_ARCMIN = 30.0
"""子午线收敛角变化/最大值提示阈值（角分）。"""

_ARCSEC_PER_DEG = 3600.0
_MAX_ABS_DELTA_LON = radians(45.0)

_ZONE_CONVENTIONS = ("gauss", "utm")


# ---------------------------------------------------------------------------
# 基础校验
# ---------------------------------------------------------------------------
def _finite(value: Any, name: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise ValueError(f"{name} 必须是数值，收到 {value!r}") from None
    if not isfinite(number):
        raise ValueError(f"{name} 必须是有限值，收到 {value!r}")
    return number


def _check_lat(lat_deg: Any) -> float:
    lat = _finite(lat_deg, "纬度")
    if not (-90.0 < lat < 90.0):
        raise ValueError("纬度必须位于 (-90°, 90°)")
    return lat


def _check_lon(lon_deg: Any) -> float:
    lon = _finite(lon_deg, "经度")
    if not (-180.0 <= lon <= 180.0):
        raise ValueError("经度必须位于 [-180°, 180°]")
    return lon


def _wrap_delta(lon_deg: float, central_meridian_deg: float) -> float:
    """返回 [-180, 180) 内的经差（度）。"""
    return (float(lon_deg) - float(central_meridian_deg) + 180.0) % 360.0 - 180.0


def _validate_zone_width(zone_width: Any) -> float:
    width = _finite(zone_width, "zone_width")
    if width <= 0.0:
        raise ValueError("zone_width 必须为正")
    return width


def _validate_convention(convention: str) -> str:
    text = str(convention).strip().lower()
    if text not in _ZONE_CONVENTIONS:
        raise ValueError(f"未知分带约定 {convention!r}，可选 {_ZONE_CONVENTIONS}")
    return text


def _default_scale_factor(convention: str) -> float:
    return UTM_SCALE_FACTOR if convention == "utm" else GAUSS_SCALE_FACTOR


# ---------------------------------------------------------------------------
# 分带
# ---------------------------------------------------------------------------
def zone_number(
    lon_deg: float,
    *,
    zone_width: float = DEFAULT_ZONE_WIDTH,
    convention: str = "gauss",
) -> int:
    """按经度返回带号。

    - ``convention="gauss"``、``zone_width=3``：中国 3° 带，带号 ``round(λ/3)``，
      中央经线 ``3·带号``（117.2°E → 39 带 / 117°E）。
    - ``gauss``、``zone_width=6``：中国 6° 带，带号 ``floor(λ/6)+1``，
      中央经线 ``6·带号−3``（117.2°E → 20 带 / 117°E）。
    - ``utm``：UTM 6° 带，带号 ``floor((λ+180)/6)+1``，
      中央经线 ``6·带号−183``（117.2°E → 50N / 117°E）。
    """
    lon = _check_lon(lon_deg)
    width = _validate_zone_width(zone_width)
    mode = _validate_convention(convention)
    if mode == "utm":
        if abs(width - 6.0) > 1e-9:
            raise ValueError("UTM 分带要求 zone_width=6")
        return min(60, max(1, int(floor((lon + 180.0) / 6.0)) + 1))
    if abs(width - 6.0) <= 1e-9:
        # 中国 6° 带：1 带中央经线 3°E。
        return int(floor(lon / 6.0)) + 1
    # 3° 带及一般高斯分带：以中央经线为带中心。
    cm = _thesis_central_meridian(lon, width)
    return int(round(cm / width))


def zone_central_meridian(
    zone: int,
    *,
    zone_width: float = DEFAULT_ZONE_WIDTH,
    convention: str = "gauss",
) -> float:
    """由带号返回中央经线（度）。"""
    width = _validate_zone_width(zone_width)
    mode = _validate_convention(convention)
    try:
        number = int(zone)
    except (TypeError, ValueError):
        raise ValueError(f"带号必须是整数，收到 {zone!r}") from None
    if mode == "utm":
        if abs(width - 6.0) > 1e-9:
            raise ValueError("UTM 分带要求 zone_width=6")
        if not (1 <= number <= 60):
            raise ValueError("UTM 带号必须位于 1..60")
        return number * 6.0 - 183.0
    if abs(width - 6.0) <= 1e-9:
        return number * 6.0 - 3.0
    return number * width


def _zone_from_central_meridian(
    central_meridian_deg: float,
    *,
    zone_width: float,
    convention: str,
) -> int:
    width = _validate_zone_width(zone_width)
    mode = _validate_convention(convention)
    cm = _finite(central_meridian_deg, "central_meridian")
    if mode == "utm":
        return min(60, max(1, int(round((cm + 183.0) / 6.0))))
    if abs(width - 6.0) <= 1e-9:
        return int(round((cm + 3.0) / 6.0))
    return int(round(cm / width))


# ---------------------------------------------------------------------------
# 椭球局部量
# ---------------------------------------------------------------------------
def _ellipsoid_radii(lat_deg: float, ellipsoid: Union[str, Ellipsoid]) -> Tuple[float, float]:
    """返回 (子午圈曲率半径 M, 卯酉圈曲率半径 N)，单位 m。"""
    ell = get_ellipsoid(ellipsoid)
    lat = radians(_check_lat(lat_deg))
    sin_lat = sin(lat)
    w = 1.0 - ell.e2 * sin_lat * sin_lat
    n = ell.a / sqrt(w)
    m = ell.a * (1.0 - ell.e2) / (w ** 1.5)
    return m, n


def local_curvature_radius(
    lat_deg: float, ellipsoid: Union[str, Ellipsoid] = "CGCS2000"
) -> float:
    """局部平均曲率半径 ``R = sqrt(M·N)``（m）。"""
    m, n = _ellipsoid_radii(lat_deg, ellipsoid)
    return sqrt(m * n)


# ---------------------------------------------------------------------------
# 投影规格
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class ProjectionSpec:
    """一个高斯/UTM 投影带的参数。

    ``central_meridian=None`` 时按点经度自动选带。``scale_factor`` 是中央经线
    尺度因子 ``k0``；``false_easting``/``false_northing`` 为投影常数（m）。
    """

    central_meridian: Optional[float] = None
    ellipsoid: Union[str, Ellipsoid] = "CGCS2000"
    zone_width: float = DEFAULT_ZONE_WIDTH
    scale_factor: float = GAUSS_SCALE_FACTOR
    false_easting: float = DEFAULT_FALSE_EASTING
    false_northing: float = 0.0
    convention: str = "gauss"
    name: str = ""

    def __post_init__(self) -> None:
        width = _validate_zone_width(self.zone_width)
        mode = _validate_convention(self.convention)
        k0 = _finite(self.scale_factor, "scale_factor")
        if k0 <= 0.0:
            raise ValueError("scale_factor 必须为正")
        cm = None
        if self.central_meridian is not None:
            cm = _check_lon(self.central_meridian)
        object.__setattr__(self, "zone_width", width)
        object.__setattr__(self, "convention", mode)
        object.__setattr__(self, "scale_factor", k0)
        object.__setattr__(self, "central_meridian", cm)
        object.__setattr__(self, "false_easting", _finite(self.false_easting, "false_easting"))
        object.__setattr__(self, "false_northing", _finite(self.false_northing, "false_northing"))
        if not isinstance(self.ellipsoid, Ellipsoid):
            # 提前校验名称，避免延迟到点计算时才报错。
            get_ellipsoid(self.ellipsoid)

    @property
    def ellipsoid_model(self) -> Ellipsoid:
        return get_ellipsoid(self.ellipsoid)

    def resolve_central_meridian(self, lon_deg: float) -> float:
        if self.central_meridian is not None:
            return float(self.central_meridian)
        lon = _check_lon(lon_deg)
        return zone_central_meridian(
            zone_number(lon, zone_width=self.zone_width, convention=self.convention),
            zone_width=self.zone_width,
            convention=self.convention,
        )

    # ---- 尺度与收敛角 ------------------------------------------------
    def scale(self, lat_deg: float, lon_deg: float) -> float:
        lat = _check_lat(lat_deg)
        lon = _check_lon(lon_deg)
        cm = self.resolve_central_meridian(lon)
        return _scale_at(lat, lon, cm, self.ellipsoid_model, self.scale_factor)

    def convergence(
        self,
        lat_deg: float,
        lon_deg: float,
        *,
        unit: str = "deg",
    ) -> float:
        lat = _check_lat(lat_deg)
        lon = _check_lon(lon_deg)
        cm = self.resolve_central_meridian(lon)
        rad = _convergence_rad_at(lat, lon, cm, self.ellipsoid_model)
        return _angle_from_rad(rad, unit)

    # ---- 坐标正反算 --------------------------------------------------
    def forward(self, lat_deg: float, lon_deg: float) -> Tuple[float, float]:
        """经纬度 → ``(E, N)``（m）。"""
        lat = _check_lat(lat_deg)
        lon = _check_lon(lon_deg)
        cm = self.resolve_central_meridian(lon)
        x, y = gauss_forward(
            lat,
            lon,
            central_meridian=cm,
            ellipsoid=self.ellipsoid,
            false_easting=DEFAULT_FALSE_EASTING,
            zone_width=self.zone_width,
        )
        easting = self.scale_factor * (y - DEFAULT_FALSE_EASTING) + self.false_easting
        northing = self.scale_factor * x + self.false_northing
        return easting, northing

    def inverse(
        self,
        easting: float,
        northing: float,
        *,
        lon_hint: Optional[float] = None,
    ) -> Tuple[float, float]:
        """``(E, N)``（m）→ 经纬度；``central_meridian=None`` 时必须给 ``lon_hint``。"""
        e = _finite(easting, "easting")
        n = _finite(northing, "northing")
        if self.central_meridian is None and lon_hint is None:
            raise ValueError("自动分带的投影反算需要 lon_hint")
        cm = (
            self.central_meridian
            if self.central_meridian is not None
            else self.resolve_central_meridian(float(lon_hint))
        )
        x = (n - self.false_northing) / self.scale_factor
        y = (e - self.false_easting) / self.scale_factor + DEFAULT_FALSE_EASTING
        return gauss_inverse(
            x,
            y,
            central_meridian=cm,
            ellipsoid=self.ellipsoid,
            false_easting=DEFAULT_FALSE_EASTING,
            zone_width=self.zone_width,
            lon_hint=lon_hint,
        )

    def as_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "ellipsoid": self.ellipsoid_model.name,
            "central_meridian_deg": self.central_meridian,
            "zone_width_deg": self.zone_width,
            "scale_factor": self.scale_factor,
            "false_easting_m": self.false_easting,
            "false_northing_m": self.false_northing,
            "convention": self.convention,
        }


def _conformal_latitude_psi(lat_rad: float, ell: Ellipsoid) -> Tuple[float, float]:
    e = ell.e
    sin_lat = sin(lat_rad)
    chi = 2.0 * atan(
        math.tan(pi / 4.0 + lat_rad / 2.0)
        * ((1.0 - e * sin_lat) / (1.0 + e * sin_lat)) ** (e / 2.0)
    ) - pi / 2.0
    psi = math.asinh(math.tan(chi))
    return chi, psi


def _scale_and_convergence_rad(
    lat_deg: float,
    lon_deg: float,
    central_meridian_deg: float,
    ell: Ellipsoid,
    k0: float,
) -> Tuple[float, float]:
    lat = radians(lat_deg)
    delta_lon = radians(_wrap_delta(lon_deg, central_meridian_deg))
    if abs(delta_lon) > _MAX_ABS_DELTA_LON:
        raise ValueError("相对中央子午线的经差过大（>45°），不适用本局部投影")
    chi, psi = _conformal_latitude_psi(lat, ell)
    w = complex(psi, delta_lon)
    z = cmath.atan(cmath.sinh(w))
    sech = 1.0 / cmath.cosh(w)
    series = 1.0 + 0.0j
    for j, alpha in enumerate(_alpha_coefficients(ell.n), start=1):
        series += 2.0 * j * alpha * cmath.cos(2.0 * j * z)
    derivative = sech * series

    sin_lat = sin(lat)
    n = ell.a / sqrt(1.0 - ell.e2 * sin_lat * sin_lat)
    a_rect = _rectifying_radius(ell)
    m = k0 * (a_rect / (n * cos(lat))) * abs(derivative)
    gamma = -cmath.phase(derivative)
    return m, gamma


def _scale_at(
    lat_deg: float,
    lon_deg: float,
    central_meridian_deg: float,
    ell: Ellipsoid,
    k0: float,
) -> float:
    m, _ = _scale_and_convergence_rad(lat_deg, lon_deg, central_meridian_deg, ell, k0)
    return m


def _convergence_rad_at(
    lat_deg: float,
    lon_deg: float,
    central_meridian_deg: float,
    ell: Ellipsoid,
) -> float:
    _, gamma = _scale_and_convergence_rad(lat_deg, lon_deg, central_meridian_deg, ell, 1.0)
    return gamma


def _angle_from_rad(value_rad: float, unit: str) -> float:
    text = str(unit).strip().lower()
    if text in ("rad", "radian", "radians"):
        return value_rad
    if text in ("deg", "degree", "degrees", "°"):
        return degrees(value_rad)
    if text in ("arcsec", "arcseconds", "second", "seconds", "″", '"'):
        return degrees(value_rad) * _ARCSEC_PER_DEG
    if text in ("arcmin", "arcminutes", "minute", "minutes", "′", "'"):
        return degrees(value_rad) * 60.0
    raise ValueError(f"未知角度单位 {unit!r}，可选 deg/arcmin/arcsec/rad")


# ---------------------------------------------------------------------------
# 模块级便捷函数
# ---------------------------------------------------------------------------
def point_scale_factor(
    lat_deg: float,
    lon_deg: float,
    *,
    central_meridian: Optional[float] = None,
    ellipsoid: Union[str, Ellipsoid] = "CGCS2000",
    zone_width: float = DEFAULT_ZONE_WIDTH,
    scale_factor: Optional[float] = None,
    convention: str = "gauss",
) -> float:
    """点投影尺度因子 ``m``（无量纲）。

    ``scale_factor=None`` 时 UTM 取 0.9996，其余取 1.0。
    """
    mode = _validate_convention(convention)
    k0 = _default_scale_factor(mode) if scale_factor is None else float(scale_factor)
    spec = ProjectionSpec(
        central_meridian=central_meridian,
        ellipsoid=ellipsoid,
        zone_width=zone_width,
        scale_factor=k0,
        convention=mode,
    )
    return spec.scale(lat_deg, lon_deg)


def meridian_convergence(
    lat_deg: float,
    lon_deg: float,
    *,
    central_meridian: Optional[float] = None,
    ellipsoid: Union[str, Ellipsoid] = "CGCS2000",
    zone_width: float = DEFAULT_ZONE_WIDTH,
    scale_factor: Optional[float] = None,
    convention: str = "gauss",
    unit: str = "deg",
) -> float:
    """子午线收敛角 ``γ = 真北 − 网格北``；默认返回度。"""
    mode = _validate_convention(convention)
    k0 = _default_scale_factor(mode) if scale_factor is None else float(scale_factor)
    spec = ProjectionSpec(
        central_meridian=central_meridian,
        ellipsoid=ellipsoid,
        zone_width=zone_width,
        scale_factor=k0,
        convention=mode,
    )
    return spec.convergence(lat_deg, lon_deg, unit=unit)


def convergence(
    lat_deg: float,
    lon_deg: float,
    **kwargs: Any,
) -> float:
    """``meridian_convergence`` 的短别名。"""
    return meridian_convergence(lat_deg, lon_deg, **kwargs)


def azimuth_true_to_grid(true_azimuth_deg: float, gamma_deg: float) -> float:
    """真北方位角 → 网格方位角：``grid = true − γ``，返回 [0,360)。"""
    true_az = _finite(true_azimuth_deg, "true_azimuth_deg")
    gamma = _finite(gamma_deg, "gamma_deg")
    return (true_az - gamma) % 360.0


def azimuth_grid_to_true(grid_azimuth_deg: float, gamma_deg: float) -> float:
    """网格方位角 → 真北方位角：``true = grid + γ``，返回 [0,360)。"""
    grid_az = _finite(grid_azimuth_deg, "grid_azimuth_deg")
    gamma = _finite(gamma_deg, "gamma_deg")
    return (grid_az + gamma) % 360.0


# ---------------------------------------------------------------------------
# grid / ground 距离归算
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class ReductionFactors:
    """一条边的投影/高程归算因子。"""

    projection_scale: float
    height_factor: float
    combined_scale: float
    radius_m: float
    mean_height_m: float

    @property
    def combined_deviation_ppm(self) -> float:
        return (self.combined_scale - 1.0) * 1.0e6

    def as_dict(self) -> Dict[str, float]:
        return {
            "projection_scale": self.projection_scale,
            "height_factor": self.height_factor,
            "combined_scale": self.combined_scale,
            "combined_deviation_ppm": self.combined_deviation_ppm,
            "radius_m": self.radius_m,
            "mean_height_m": self.mean_height_m,
        }


def height_reduction_factor(mean_height_m: float, radius_m: float) -> float:
    """``R/(R+H_m)``；``H_m`` 为平均大地高（m），``R`` 为局部曲率半径（m）。"""
    height = _finite(mean_height_m, "mean_height_m")
    radius = _finite(radius_m, "radius_m")
    if radius <= 0.0:
        raise ValueError("radius_m 必须为正")
    if radius + height <= 0.0:
        raise ValueError("R + H_m 必须为正")
    return radius / (radius + height)


def reduction_factors(
    *,
    mean_height_m: float,
    projection_scale: float = 1.0,
    radius_m: Optional[float] = None,
    latitude_deg: Optional[float] = None,
    ellipsoid: Union[str, Ellipsoid] = "CGCS2000",
) -> ReductionFactors:
    """计算 ``k_projection``、``R/(R+H)`` 与综合尺度。

    ``radius_m`` 未给时，必须给 ``latitude_deg``，用 ``sqrt(M·N)`` 近似。
    """
    k = _finite(projection_scale, "projection_scale")
    if k <= 0.0:
        raise ValueError("projection_scale 必须为正")
    if radius_m is None:
        if latitude_deg is None:
            raise ValueError("需要 radius_m 或 latitude_deg 以确定局部曲率半径")
        radius = local_curvature_radius(latitude_deg, ellipsoid)
    else:
        radius = _finite(radius_m, "radius_m")
    height = _finite(mean_height_m, "mean_height_m")
    factor = height_reduction_factor(height, radius)
    return ReductionFactors(
        projection_scale=k,
        height_factor=factor,
        combined_scale=k * factor,
        radius_m=radius,
        mean_height_m=height,
    )


def grid_to_ground(
    grid_distance_m: float,
    *,
    mean_height_m: float,
    projection_scale: float = 1.0,
    radius_m: Optional[float] = None,
    latitude_deg: Optional[float] = None,
    ellipsoid: Union[str, Ellipsoid] = "CGCS2000",
) -> float:
    """投影平面距离 → 平均高程面地面距离（m）。

    ``s_ground = s_grid / [k_projection · R/(R+H_m)]``。
    """
    distance = _finite(grid_distance_m, "grid_distance_m")
    if distance < 0.0:
        raise ValueError("距离不能为负")
    factors = reduction_factors(
        mean_height_m=mean_height_m,
        projection_scale=projection_scale,
        radius_m=radius_m,
        latitude_deg=latitude_deg,
        ellipsoid=ellipsoid,
    )
    return distance / factors.combined_scale


def ground_to_grid(
    ground_distance_m: float,
    *,
    mean_height_m: float,
    projection_scale: float = 1.0,
    radius_m: Optional[float] = None,
    latitude_deg: Optional[float] = None,
    ellipsoid: Union[str, Ellipsoid] = "CGCS2000",
) -> float:
    """平均高程面地面距离 → 投影平面距离（m）。

    ``s_grid = s_ground · k_projection · R/(R+H_m)``。
    """
    distance = _finite(ground_distance_m, "ground_distance_m")
    if distance < 0.0:
        raise ValueError("距离不能为负")
    factors = reduction_factors(
        mean_height_m=mean_height_m,
        projection_scale=projection_scale,
        radius_m=radius_m,
        latitude_deg=latitude_deg,
        ellipsoid=ellipsoid,
    )
    return distance * factors.combined_scale


def mean_projection_scale(
    lat1_deg: float,
    lon1_deg: float,
    lat2_deg: float,
    lon2_deg: float,
    *,
    central_meridian: Optional[float] = None,
    ellipsoid: Union[str, Ellipsoid] = "CGCS2000",
    zone_width: float = DEFAULT_ZONE_WIDTH,
    scale_factor: Optional[float] = None,
    convention: str = "gauss",
) -> float:
    """边两端点投影尺度的算术平均（短边近似）。"""
    k1 = point_scale_factor(
        lat1_deg,
        lon1_deg,
        central_meridian=central_meridian,
        ellipsoid=ellipsoid,
        zone_width=zone_width,
        scale_factor=scale_factor,
        convention=convention,
    )
    k2 = point_scale_factor(
        lat2_deg,
        lon2_deg,
        central_meridian=central_meridian,
        ellipsoid=ellipsoid,
        zone_width=zone_width,
        scale_factor=scale_factor,
        convention=convention,
    )
    return 0.5 * (k1 + k2)


# ---------------------------------------------------------------------------
# 跨带/中央子午线检查
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class GeoPoint:
    """经纬度点（度）。``name`` 仅用于报告。"""

    lat: float
    lon: float
    name: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "lat", _check_lat(self.lat))
        object.__setattr__(self, "lon", _check_lon(self.lon))
        object.__setattr__(self, "name", str(self.name))


@dataclass(frozen=True)
class PointZoneInfo:
    """单点在当前/推荐带下的尺度与收敛角。"""

    name: str
    lat: float
    lon: float
    zone: int
    central_meridian: float
    longitude_offset_deg: float
    scale: float
    convergence_deg: float
    recommended_scale: float
    recommended_convergence_deg: float
    nominal_scale: float

    @property
    def scale_deviation_ppm(self) -> float:
        return (self.scale / self.nominal_scale - 1.0) * 1.0e6

    @property
    def recommended_scale_deviation_ppm(self) -> float:
        return (self.recommended_scale / self.nominal_scale - 1.0) * 1.0e6

    def as_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "lat": self.lat,
            "lon": self.lon,
            "zone": self.zone,
            "central_meridian": self.central_meridian,
            "longitude_offset_deg": self.longitude_offset_deg,
            "scale": self.scale,
            "scale_deviation_ppm": self.scale_deviation_ppm,
            "convergence_deg": self.convergence_deg,
            "recommended_scale": self.recommended_scale,
            "recommended_scale_deviation_ppm": self.recommended_scale_deviation_ppm,
            "recommended_convergence_deg": self.recommended_convergence_deg,
        }


@dataclass(frozen=True)
class ZoneCheck:
    """跨带/中央子午线偏离检查结果。"""

    zone_width: float
    convention: str
    current_zone: int
    current_central_meridian: float
    recommended_zone: int
    recommended_central_meridian: float
    crosses_zone: bool
    should_switch_zone: bool
    max_scale_deviation_ppm: float
    scale_range_ppm: float
    recommended_max_scale_deviation_ppm: float
    max_convergence_arcmin: float
    convergence_range_arcmin: float
    max_longitude_offset_deg: float
    warning_codes: Tuple[str, ...]
    warnings: Tuple[str, ...]
    points: Tuple[PointZoneInfo, ...]

    @property
    def max_scale_distortion_ppm(self) -> float:
        """``max_scale_deviation_ppm`` 的别名。"""
        return self.max_scale_deviation_ppm

    @property
    def max_scale_deformation_ppm(self) -> float:
        return self.max_scale_deviation_ppm

    @property
    def should_switch(self) -> bool:
        return self.should_switch_zone

    def as_dict(self) -> Dict[str, Any]:
        return {
            "zone_width": self.zone_width,
            "convention": self.convention,
            "current_zone": self.current_zone,
            "current_central_meridian": self.current_central_meridian,
            "recommended_zone": self.recommended_zone,
            "recommended_central_meridian": self.recommended_central_meridian,
            "crosses_zone": self.crosses_zone,
            "should_switch_zone": self.should_switch_zone,
            "max_scale_deviation_ppm": self.max_scale_deviation_ppm,
            "max_scale_distortion_ppm": self.max_scale_distortion_ppm,
            "scale_range_ppm": self.scale_range_ppm,
            "recommended_max_scale_deviation_ppm": self.recommended_max_scale_deviation_ppm,
            "max_convergence_arcmin": self.max_convergence_arcmin,
            "convergence_range_arcmin": self.convergence_range_arcmin,
            "max_longitude_offset_deg": self.max_longitude_offset_deg,
            "warning_codes": list(self.warning_codes),
            "warnings": list(self.warnings),
            "points": [point.as_dict() for point in self.points],
        }


def _coerce_geo_points(points: Iterable[Any]) -> List[GeoPoint]:
    if isinstance(points, (str, bytes)):
        raise TypeError("points 必须是经纬度点序列，不能是字符串")
    rows: List[GeoPoint] = []
    for index, item in enumerate(points):
        if isinstance(item, GeoPoint):
            rows.append(item)
            continue
        name = ""
        lat = lon = None
        if isinstance(item, Mapping):
            name = str(item.get("name", item.get("label", "")) or "")
            for key in ("lat", "latitude", "phi"):
                if key in item:
                    lat = item[key]
                    break
            for key in ("lon", "lng", "longitude", "lambda"):
                if key in item:
                    lon = item[key]
                    break
        elif hasattr(item, "lat") and hasattr(item, "lon"):
            lat = getattr(item, "lat")
            lon = getattr(item, "lon")
            name = str(getattr(item, "name", "") or "")
        elif isinstance(item, (tuple, list)) and len(item) == 2:
            # 与模块函数一致： (lat, lon)。
            lat, lon = item
        if lat is None or lon is None:
            raise ValueError(f"无法解析第 {index} 个经纬度点：{item!r}")
        rows.append(GeoPoint(lat=float(lat), lon=float(lon), name=name))
    if not rows:
        raise ValueError("至少需要一个经纬度点")
    return rows


def _choose_central_meridian(
    rows: Sequence[GeoPoint],
    *,
    current_cm: float,
    zone_width: float,
    convention: str,
) -> Tuple[float, int]:
    """在候选带中选最大经差最小的中央子午线。"""
    candidates = {float(current_cm)}
    for row in rows:
        zone = zone_number(row.lon, zone_width=zone_width, convention=convention)
        candidates.add(zone_central_meridian(zone, zone_width=zone_width, convention=convention))
    lons = [row.lon for row in rows]
    mid = 0.5 * (min(lons) + max(lons))
    candidates.add(
        zone_central_meridian(
            zone_number(mid, zone_width=zone_width, convention=convention),
            zone_width=zone_width,
            convention=convention,
        )
    )
    # 相邻带也作为候选，避免中值恰好落在带边界时错失更优中心。
    base_zones = {zone_number(lon, zone_width=zone_width, convention=convention) for lon in lons}
    for zone in list(base_zones):
        for delta in (-1, 1):
            candidates.add(
                zone_central_meridian(
                    zone + delta, zone_width=zone_width, convention=convention
                )
            )

    def cost(cm: float) -> Tuple[float, float]:
        offsets = [abs(_wrap_delta(row.lon, cm)) for row in rows]
        return max(offsets), sum(offsets) / len(offsets)

    best_cm = min(candidates, key=cost)
    best_zone = _zone_from_central_meridian(
        best_cm, zone_width=zone_width, convention=convention
    )
    return float(best_cm), best_zone


def check_cross_zone(
    points: Iterable[Any],
    *,
    zone: Optional[int] = None,
    central_meridian: Optional[float] = None,
    zone_width: float = DEFAULT_ZONE_WIDTH,
    convention: str = "gauss",
    ellipsoid: Union[str, Ellipsoid] = "CGCS2000",
    scale_factor: Optional[float] = None,
    max_scale_ppm: float = SCALE_WARNING_PPM,
    max_convergence_arcmin: float = CONVERGENCE_WARNING_ARCMIN,
) -> ZoneCheck:
    """检查点集相对当前带/中央子午线的跨带与投影变形。

    参数
    ----
    points:
        ``GeoPoint``、``{"lat":..., "lon":..., "name":...}``、``(lat, lon)``
        或带 ``lat/lon`` 属性的对象组成的序列。
    zone, central_meridian:
        当前带号/中央经线。二者均省略时按点集平均经度自动取带；给 ``zone``
        时按 ``zone_width``/``convention`` 换算中央经线。``central_meridian``
        优先于 ``zone``。
    max_scale_ppm:
        ``|m/k0 − 1|`` 的提示阈值，默认 10 ppm。
    max_convergence_arcmin:
        收敛角绝对值/变化范围提示阈值，默认 30′。

    返回的 ``ZoneCheck`` 同时给出当前带和“最大经差最小”的推荐带下的结果。
    """
    width = _validate_zone_width(zone_width)
    mode = _validate_convention(convention)
    if float(max_scale_ppm) < 0.0:
        raise ValueError("max_scale_ppm 不能为负")
    if float(max_convergence_arcmin) < 0.0:
        raise ValueError("max_convergence_arcmin 不能为负")
    rows = _coerce_geo_points(points)
    nominal = (
        _default_scale_factor(mode) if scale_factor is None else _finite(scale_factor, "scale_factor")
    )
    if nominal <= 0.0:
        raise ValueError("scale_factor 必须为正")
    if central_meridian is not None:
        current_cm = _check_lon(central_meridian)
        current_zone = (
            int(zone)
            if zone is not None
            else _zone_from_central_meridian(current_cm, zone_width=width, convention=mode)
        )
    elif zone is not None:
        current_zone = int(zone)
        current_cm = zone_central_meridian(current_zone, zone_width=width, convention=mode)
    else:
        mean_lon = sum(row.lon for row in rows) / len(rows)
        current_zone = zone_number(mean_lon, zone_width=width, convention=mode)
        current_cm = zone_central_meridian(current_zone, zone_width=width, convention=mode)

    ell = get_ellipsoid(ellipsoid)
    native_zones = {
        zone_number(row.lon, zone_width=width, convention=mode) for row in rows
    }
    recommended_cm, recommended_zone = _choose_central_meridian(
        rows,
        current_cm=current_cm,
        zone_width=width,
        convention=mode,
    )
    crosses_zone = len(native_zones) > 1 or any(zn != current_zone for zn in native_zones)
    should_switch = crosses_zone or abs(recommended_cm - current_cm) > 1.0e-9

    infos: List[PointZoneInfo] = []
    for row in rows:
        offset = _wrap_delta(row.lon, current_cm)
        m_current, gamma_current = _scale_and_convergence_rad(
            row.lat, row.lon, current_cm, ell, nominal
        )
        m_recommended, gamma_recommended = _scale_and_convergence_rad(
            row.lat, row.lon, recommended_cm, ell, nominal
        )
        infos.append(
            PointZoneInfo(
                name=row.name,
                lat=row.lat,
                lon=row.lon,
                zone=zone_number(row.lon, zone_width=width, convention=mode),
                central_meridian=current_cm,
                longitude_offset_deg=offset,
                scale=m_current,
                convergence_deg=degrees(gamma_current),
                recommended_scale=m_recommended,
                recommended_convergence_deg=degrees(gamma_recommended),
                nominal_scale=nominal,
            )
        )

    deviations = [abs(point.scale_deviation_ppm) for point in infos]
    recommended_deviations = [abs(point.recommended_scale_deviation_ppm) for point in infos]
    scales = [point.scale for point in infos]
    convergence_values = [point.convergence_deg * 60.0 for point in infos]
    max_deviation = max(deviations)
    scale_range = (max(scales) - min(scales)) * 1.0e6
    max_gamma = max(abs(value) for value in convergence_values)
    gamma_range = max(convergence_values) - min(convergence_values)
    max_offset = max(abs(point.longitude_offset_deg) for point in infos)

    codes: List[str] = []
    messages: List[str] = []
    if len(native_zones) > 1:
        codes.append("cross_zone")
        messages.append(
            "点集跨越多带（带号：{}），禁止把不同带坐标直接混算；应按带分区或改用 3D/ENU。".format(
                "、".join(str(v) for v in sorted(native_zones))
            )
        )
    elif any(zn != current_zone for zn in native_zones):
        codes.append("zone_mismatch")
        messages.append(
            f"当前带号 {current_zone} 与点集所在带 "
            f"{'、'.join(str(v) for v in sorted(native_zones))} 不一致。"
        )
    if max_deviation > float(max_scale_ppm):
        codes.append("scale_distortion")
        messages.append(
            f"当前投影最大尺度偏差 {max_deviation:.1f} ppm，超过 {float(max_scale_ppm):g} ppm 阈值。"
        )
    if max_gamma > float(max_convergence_arcmin) or gamma_range > float(max_convergence_arcmin):
        codes.append("convergence")
        messages.append(
            "子午线收敛角最大 {:.3f}′、变化 {:.3f}′，超过 {:.0f}′ 提示阈值。".format(
                max_gamma, gamma_range, float(max_convergence_arcmin)
            )
        )
    if should_switch:
        codes.append("recommend_switch_zone")
        if recommended_zone == current_zone:
            messages.append(
                "点集无法由单一带完整覆盖；当前 {} 带（中央经线 {:.3f}°）需按带分区处理。".format(
                    current_zone, current_cm
                )
            )
        else:
            messages.append(
                "建议换至 {} 带（中央经线 {:.3f}°）；当前 {} 带（{:.3f}°）。".format(
                    recommended_zone,
                    recommended_cm,
                    current_zone,
                    current_cm,
                )
            )
    if (
        max(recommended_deviations) + 0.5 < max_deviation
        and max_deviation > float(max_scale_ppm)
    ):
        codes.append("recommend_central_meridian")
        messages.append(
            "推荐中央经线 {:.3f}° 可把最大尺度偏差从 {:.1f} ppm 降到 {:.1f} ppm。".format(
                recommended_cm, max_deviation, max(recommended_deviations)
            )
        )
    if max(abs(_wrap_delta(point.lon, current_cm)) for point in rows) > 1.5 * width:
        codes.append("central_meridian_far")
        messages.append(
            "测区距中央子午线超过 1.5 个带宽，局部投影级数精度与尺度变形均需复核。"
        )

    return ZoneCheck(
        zone_width=width,
        convention=mode,
        current_zone=current_zone,
        current_central_meridian=current_cm,
        recommended_zone=recommended_zone,
        recommended_central_meridian=recommended_cm,
        crosses_zone=crosses_zone,
        should_switch_zone=should_switch,
        max_scale_deviation_ppm=max_deviation,
        scale_range_ppm=scale_range,
        recommended_max_scale_deviation_ppm=max(recommended_deviations),
        max_convergence_arcmin=max_gamma,
        convergence_range_arcmin=gamma_range,
        max_longitude_offset_deg=max_offset,
        warning_codes=tuple(dict.fromkeys(codes)),
        warnings=tuple(messages),
        points=tuple(infos),
    )


# 便捷别名，便于外部按 §5.2 命名调用。
project_zone_check = check_cross_zone
scale_factor = point_scale_factor


__all__ = [
    "DEFAULT_ZONE_WIDTH",
    "UTM_SCALE_FACTOR",
    "GAUSS_SCALE_FACTOR",
    "DEFAULT_FALSE_EASTING",
    "SCALE_WARNING_PPM",
    "COMBINED_SCALE_WARNING_PPM",
    "CONVERGENCE_WARNING_ARCMIN",
    "ProjectionSpec",
    "ReductionFactors",
    "GeoPoint",
    "PointZoneInfo",
    "ZoneCheck",
    "zone_number",
    "zone_central_meridian",
    "local_curvature_radius",
    "point_scale_factor",
    "scale_factor",
    "meridian_convergence",
    "convergence",
    "azimuth_true_to_grid",
    "azimuth_grid_to_true",
    "height_reduction_factor",
    "reduction_factors",
    "grid_to_ground",
    "ground_to_grid",
    "mean_projection_scale",
    "check_cross_zone",
    "project_zone_check",
]
