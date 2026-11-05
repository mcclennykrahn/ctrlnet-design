"""投影尺度、子午线收敛角、grid/ground 与跨带检查测试。"""

from __future__ import annotations

import math

import pytest

from ctrlnet.projection import (
    GeoPoint,
    ProjectionSpec,
    azimuth_grid_to_true,
    azimuth_true_to_grid,
    check_cross_zone,
    grid_to_ground,
    ground_to_grid,
    height_reduction_factor,
    local_curvature_radius,
    mean_projection_scale,
    meridian_convergence,
    point_scale_factor,
    reduction_factors,
    zone_central_meridian,
    zone_number,
)
from ctrlnet.thesis import (
    _alpha_coefficients,
    _rectifying_radius,
    gauss_forward,
    get_ellipsoid,
)


# 公开/论文算例附近点 + UTM 50N 点。期望值由 Krüger n⁶ 严格复变导数给出，
# 并与下面的二阶解析级数（0.01 ppm / 0.005″ 内）、gauss_forward 数值雅可比
# （1e-9 / 5e-6″ 内）交叉验证。
KNOWN_CASES = [
    # lat, lon, central_meridian, k0, m, gamma_deg
    (34.2, 117.2, 117.0, 1.0, 1.000004186768218, 0.112416992238746),
    (34.2, 117.0, 117.0, 1.0, 1.000000000000000, 0.0),
    (39.95, 116.05, 117.0, 0.9996, 0.999681072010783, -0.610046166749857),
    (0.0, 1.0, 0.0, 1.0, 1.000153354895143, 0.0),
    (45.0, 120.5, 120.0, 1.0, 1.000019102801522, 0.353557923532368),
    (60.0, 10.0, 9.0, 0.9996, 0.999638124356629, 0.866047498546157),
]


@pytest.mark.parametrize("lat,lon,cm,k0,expected_m,expected_gamma", KNOWN_CASES)
def test_known_scale_and_convergence(
    lat: float,
    lon: float,
    cm: float,
    k0: float,
    expected_m: float,
    expected_gamma: float,
) -> None:
    """已知点尺度因子容差 2e-10，收敛角容差 5e-10°（约 0.002″）。"""
    m = point_scale_factor(lat, lon, central_meridian=cm, scale_factor=k0)
    gamma = meridian_convergence(lat, lon, central_meridian=cm, scale_factor=k0)
    assert m == pytest.approx(expected_m, abs=2e-10)
    assert gamma == pytest.approx(expected_gamma, abs=5e-10)


def _series_scale_gamma(
    lat_deg: float, lon_deg: float, cm: float, k0: float
) -> tuple[float, float]:
    """独立二阶尺度/三阶收敛角解析式，用作已知值交叉检查。"""
    ell = get_ellipsoid("CGCS2000")
    lat = math.radians(lat_deg)
    lam = math.radians(lon_deg - cm)
    ep2 = ell.e2 / (1.0 - ell.e2)
    t = math.tan(lat)
    eta2 = ep2 * math.cos(lat) ** 2
    c = math.cos(lat)
    m = k0 * (
        1.0
        + 0.5 * lam**2 * c**2 * (1.0 + eta2)
        + (lam**4 * c**4 / 24.0)
        * (5.0 - 4.0 * t**2 + 14.0 * eta2 - 28.0 * t**2 * eta2)
        + (lam**6 * c**6 / 720.0)
        * (61.0 - 148.0 * t**2 + 16.0 * t**4 + 330.0 * eta2 - 600.0 * t**2 * eta2)
    )
    gamma = math.degrees(
        lam * math.sin(lat)
        + (lam**3 / 3.0) * math.sin(lat) * c**2 * (1.0 + 3.0 * eta2 + 2.0 * eta2**2)
        + (lam**5 / 15.0) * math.sin(lat) * c**4 * (2.0 - t**2)
    )
    return m, gamma


@pytest.mark.parametrize("lat,lon,cm,k0,expected_m,expected_gamma", KNOWN_CASES)
def test_against_independent_series(
    lat: float,
    lon: float,
    cm: float,
    k0: float,
    expected_m: float,
    expected_gamma: float,
) -> None:
    m = point_scale_factor(lat, lon, central_meridian=cm, scale_factor=k0)
    gamma = meridian_convergence(lat, lon, central_meridian=cm, scale_factor=k0)
    series_m, series_gamma = _series_scale_gamma(lat, lon, cm, k0)
    # 级数截断误差在 3° 带内远小于这些阈值。
    assert abs(m - series_m) * 1e6 < 0.01  # ppm
    assert abs(gamma - series_gamma) * 3600.0 < 0.005  # arcsec


@pytest.mark.parametrize("lat", [0.0, 20.0, 34.2, 45.0, 60.0, 75.0])
def test_central_meridian_scale_is_nominal_and_gamma_zero(lat: float) -> None:
    m = point_scale_factor(lat, 117.0, central_meridian=117.0, scale_factor=0.9996)
    gamma = meridian_convergence(lat, 117.0, central_meridian=117.0)
    assert m == pytest.approx(0.9996, abs=2e-15)
    assert gamma == pytest.approx(0.0, abs=1e-13)


def _numeric_scale_gamma(
    lat_deg: float, lon_deg: float, cm: float, k0: float, step: float = 1e-4
) -> tuple[float, float]:
    """由 thesis.gauss_forward 的中心差分独立求尺度/收敛角。"""
    ell = get_ellipsoid("CGCS2000")
    lat = math.radians(lat_deg)
    x1, y1 = gauss_forward(lat_deg - step, lon_deg, central_meridian=cm)
    x2, y2 = gauss_forward(lat_deg + step, lon_deg, central_meridian=cm)
    m_radius = ell.a * (1.0 - ell.e2) / (1.0 - ell.e2 * math.sin(lat) ** 2) ** 1.5
    scale = math.hypot(x2 - x1, y2 - y1) * k0 / (m_radius * 2.0 * math.radians(step))
    gamma = -math.degrees(math.atan2(y2 - y1, x2 - x1))
    return scale, gamma


@pytest.mark.parametrize("lat,lon,cm,k0,expected_m,expected_gamma", KNOWN_CASES)
def test_against_numeric_jacobian(
    lat: float,
    lon: float,
    cm: float,
    k0: float,
    expected_m: float,
    expected_gamma: float,
) -> None:
    scale, gamma = point_scale_factor(
        lat, lon, central_meridian=cm, scale_factor=k0
    ), meridian_convergence(lat, lon, central_meridian=cm, scale_factor=k0)
    numeric_scale, numeric_gamma = _numeric_scale_gamma(lat, lon, cm, k0)
    assert scale == pytest.approx(numeric_scale, abs=5e-10)
    assert gamma * 3600.0 == pytest.approx(numeric_gamma * 3600.0, abs=5e-6)


def test_symmetry_and_unit_conversion() -> None:
    m_east = point_scale_factor(34.2, 117.3, central_meridian=117.0)
    m_west = point_scale_factor(34.2, 116.7, central_meridian=117.0)
    g_east = meridian_convergence(34.2, 117.3, central_meridian=117.0)
    g_west = meridian_convergence(34.2, 116.7, central_meridian=117.0)
    assert m_east == pytest.approx(m_west, rel=1e-14)
    assert g_east == pytest.approx(-g_west, abs=1e-14)
    assert meridian_convergence(34.2, 117.3, central_meridian=117.0, unit="arcsec") == pytest.approx(
        g_east * 3600.0, rel=1e-14
    )
    assert meridian_convergence(34.2, 117.3, central_meridian=117.0, unit="rad") == pytest.approx(
        math.radians(g_east), rel=1e-14
    )


def test_projection_spec_forward_inverse_and_auto_zone() -> None:
    spec = ProjectionSpec(
        central_meridian=117.0,
        scale_factor=0.9996,
        false_northing=0.0,
        convention="utm",
        zone_width=6.0,
    )
    easting, northing = spec.forward(39.95, 116.05)
    lat, lon = spec.inverse(easting, northing)
    assert lat == pytest.approx(39.95, abs=1e-10)
    assert lon == pytest.approx(116.05, abs=1e-10)
    assert spec.scale(39.95, 116.05) == pytest.approx(
        point_scale_factor(39.95, 116.05, central_meridian=117.0, scale_factor=0.9996),
        rel=1e-15,
    )
    auto = ProjectionSpec(convention="utm", zone_width=6.0, scale_factor=0.9996)
    assert auto.resolve_central_meridian(116.05) == pytest.approx(117.0)


def test_zone_numbering_and_central_meridians() -> None:
    assert zone_number(117.2) == 39
    assert zone_central_meridian(39) == pytest.approx(117.0)
    assert zone_number(117.2, zone_width=6.0) == 20
    assert zone_central_meridian(20, zone_width=6.0) == pytest.approx(117.0)
    assert zone_number(117.2, zone_width=6.0, convention="utm") == 50
    assert zone_central_meridian(50, zone_width=6.0, convention="utm") == pytest.approx(117.0)
    with pytest.raises(ValueError):
        zone_number(117.2, zone_width=3.0, convention="utm")
    with pytest.raises(ValueError):
        zone_central_meridian(0, zone_width=6.0, convention="utm")


def test_local_radius_and_height_reduction() -> None:
    radius = local_curvature_radius(34.2)
    assert radius == pytest.approx(6_371_000.0, rel=0.01)
    assert height_reduction_factor(500.0, 6_371_000.0) == pytest.approx(
        6_371_000.0 / 6_371_500.0, rel=1e-15
    )
    factors = reduction_factors(
        mean_height_m=500.0,
        projection_scale=1.0002,
        latitude_deg=34.2,
    )
    assert factors.combined_scale == pytest.approx(
        1.0002 * factors.height_factor, rel=1e-15
    )
    assert factors.combined_deviation_ppm == pytest.approx(
        (factors.combined_scale - 1.0) * 1e6, rel=1e-12
    )


@pytest.mark.parametrize(
    "grid_m,height,k,radius",
    [
        (0.0, 0.0, 1.0, 6_371_000.0),
        (1000.0, 500.0, 1.0002, 6_371_000.0),
        (10_000.0, 3000.0, 1.0000, 6_371_000.0),
        (1234.567, -100.0, 0.9996, 6_378_137.0),
        (50_000.0, 4500.0, 1.0004, 6_371_000.0),
    ],
)
def test_grid_ground_roundtrip_and_manual_formula(
    grid_m: float, height: float, k: float, radius: float
) -> None:
    ground = grid_to_ground(
        grid_m,
        mean_height_m=height,
        projection_scale=k,
        radius_m=radius,
    )
    expected = grid_m / (k * radius / (radius + height))
    assert ground == pytest.approx(expected, rel=1e-14)
    assert ground_to_grid(
        ground,
        mean_height_m=height,
        projection_scale=k,
        radius_m=radius,
    ) == pytest.approx(grid_m, abs=1e-9)



def test_height_reduction_increases_ground_distance_at_unit_scale() -> None:
    grid = 1000.0
    high = grid_to_ground(grid, mean_height_m=500.0, projection_scale=1.0, radius_m=6_371_000.0)
    low = grid_to_ground(grid, mean_height_m=0.0, projection_scale=1.0, radius_m=6_371_000.0)
    assert high > low == pytest.approx(grid, rel=1e-15)


def test_grid_ground_requires_radius_context() -> None:
    with pytest.raises(ValueError):
        reduction_factors(mean_height_m=100.0, projection_scale=1.0)
    with pytest.raises(ValueError):
        grid_to_ground(-1.0, mean_height_m=0.0, radius_m=6_371_000.0)
    with pytest.raises(ValueError):
        grid_to_ground(1.0, mean_height_m=0.0, radius_m=0.0)


def test_mean_projection_scale_and_azimuth_conversion() -> None:
    mean = mean_projection_scale(34.2, 117.1, 34.2, 117.3, central_meridian=117.0)
    expected = 0.5 * (
        point_scale_factor(34.2, 117.1, central_meridian=117.0)
        + point_scale_factor(34.2, 117.3, central_meridian=117.0)
    )
    assert mean == pytest.approx(expected, rel=1e-15)
    gamma = meridian_convergence(34.2, 117.3, central_meridian=117.0)
    assert azimuth_true_to_grid(90.0, gamma) == pytest.approx((90.0 - gamma) % 360.0)
    assert azimuth_grid_to_true(
        azimuth_true_to_grid(90.0, gamma), gamma
    ) == pytest.approx(90.0, abs=1e-12)


def test_cross_zone_detects_span_and_recommends_switch() -> None:
    points = [GeoPoint(34.2, 118.4, "E1"), GeoPoint(34.2, 118.7, "E2")]
    result = check_cross_zone(points, zone=39)
    assert result.crosses_zone is True
    assert result.should_switch_zone is True
    assert result.should_switch is True
    assert result.current_central_meridian == pytest.approx(117.0)
    assert result.recommended_zone == 40
    assert result.recommended_central_meridian == pytest.approx(120.0)
    assert result.max_scale_deviation_ppm > 10.0
    assert result.max_scale_distortion_ppm == pytest.approx(
        result.max_scale_deviation_ppm
    )
    assert "cross_zone" in result.warning_codes
    assert "recommend_switch_zone" in result.warning_codes
    assert any("跨带" in text or "换" in text for text in result.warnings)
    payload = result.as_dict()
    assert payload["crosses_zone"] is True
    assert len(payload["points"]) == 2


def test_cross_zone_utm_within_zone_reports_scale_only() -> None:
    points = [
        {"name": "P1", "lat": 39.95, "lon": 116.05},
        {"name": "P2", "lat": 39.96, "lon": 116.10},
    ]
    result = check_cross_zone(
        points, zone=50, zone_width=6.0, convention="utm"
    )
    assert result.crosses_zone is False
    assert result.should_switch_zone is False
    assert result.current_central_meridian == pytest.approx(117.0)
    assert result.current_zone == 50
    assert result.max_scale_deviation_ppm > 10.0
    assert "scale_distortion" in result.warning_codes
    assert result.points[0].zone == 50
    assert result.points[0].scale == pytest.approx(
        point_scale_factor(
            39.95, 116.05, central_meridian=117.0, scale_factor=0.9996
        ),
        rel=1e-15,
    )


def test_cross_zone_wrong_current_zone_is_detected() -> None:
    points = [(34.2, 117.2), (34.2, 117.25)]
    result = check_cross_zone(points, zone=40)
    assert result.crosses_zone is True
    assert result.should_switch_zone is True
    assert result.recommended_zone == 39
    assert result.recommended_central_meridian == pytest.approx(117.0)
    assert "zone_mismatch" in result.warning_codes


def test_cross_zone_validation() -> None:
    with pytest.raises(ValueError):
        check_cross_zone([], zone=39)
    with pytest.raises(ValueError):
        check_cross_zone([(91.0, 117.0)], zone=39)
    with pytest.raises(ValueError):
        check_cross_zone([(34.2, 117.0)], zone=39, central_meridian=200.0)
    with pytest.raises(ValueError):
        check_cross_zone([("bad", "point")], zone=39)
