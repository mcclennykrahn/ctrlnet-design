"""论文第 3–5 章约定与算例复现测试。"""

from __future__ import annotations

import math

import numpy as np
import pytest

from ctrlnet.model import Distance
from ctrlnet.thesis import (
    RHO_ARCSEC,
    build_angle_network,
    central_meridian,
    check_tolerance,
    compare_geodesic_and_plane,
    distance_sigma_mm,
    distance_weight,
    error_ellipse,
    export_angle_topology,
    export_coordinate_text,
    gauss_forward,
    gauss_inverse,
    geodesic_inverse,
    get_grade,
    parse_angle_topology,
    parse_coordinate_text,
    suggest_grade,
    thesis_edge_denominator,
)
from ctrlnet.thesis_examples import (
    EXAMPLE1_LINES,
    EXAMPLE1_POINTS,
    EXAMPLE1_PUBLISHED,
    EXAMPLE1_TOPOLOGY,
    EXAMPLE2_PUBLISHED,
    example1_angles,
    example1_missing_triangle_angles,
    example1_order_probe,
    example1_result,
    example1_triangle_angles,
    example2_result,
)


# ---------------------------------------------------------------------------
# 高斯投影
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "lat,lon",
    [
        (34.2, 117.2),
        (34.213224, 117.287179),
        (0.0, 0.0),
        (45.0, 120.0),
        (-33.9, 151.2),
        (60.0, 10.0),
    ],
)
def test_gauss_roundtrip_under_micrometre(lat: float, lon: float) -> None:
    x, y = gauss_forward(lat, lon)
    lat2, lon2 = gauss_inverse(x, y, lon_hint=lon)
    # 1e-6 m 对应约 1e-11 度；用局部米制近似严格检查。
    north_error = abs(lat2 - lat) * 111_000.0
    east_error = abs(lon2 - lon) * 111_000.0 * math.cos(math.radians(lat))
    assert north_error < 1e-6
    assert east_error < 1e-6


def test_gauss_known_value_matches_proj() -> None:
    # 由 PROJ 9.x（EPSG:4490 → EPSG:4547，CM 117°E）离线复核。
    x, y = gauss_forward(34.2, 117.2, central_meridian=117.0)
    assert x == pytest.approx(3785864.364597953, abs=1e-6)
    assert y == pytest.approx(518433.555427794, abs=1e-6)


def test_gauss_matches_pyproj_if_available() -> None:
    pyproj = pytest.importorskip("pyproj")
    transformer = pyproj.Transformer.from_crs(
        "EPSG:4490", "EPSG:4547", always_xy=True
    )
    easting, northing = transformer.transform(117.2, 34.2)
    x, y = gauss_forward(34.2, 117.2, central_meridian=117.0)
    assert y == pytest.approx(easting, abs=1e-6)
    assert x == pytest.approx(northing, abs=1e-6)


def test_gauss_zone_number_and_500km() -> None:
    x, y = gauss_forward(34.2, 117.2)
    assert central_meridian(117.2) == 117.0
    assert y > 500_000.0  # 东偏移
    x2, y2 = gauss_forward(34.2, 117.2, central_meridian=117.0)
    assert (x, y) == (x2, y2)


def test_gauss_inverse_auto_zone_prefix() -> None:
    x, y = gauss_forward(34.2, 117.2)
    lat, lon = gauss_inverse(x, 39_000_000.0 + y)
    assert lat == pytest.approx(34.2, abs=1e-10)
    assert lon == pytest.approx(117.2, abs=1e-10)


def test_gauss_inverse_requires_meridian_without_zone() -> None:
    with pytest.raises(ValueError):
        gauss_inverse(3785864.364597953, 518433.555427794)


# ---------------------------------------------------------------------------
# 椭球面距离/方位角
# ---------------------------------------------------------------------------


def test_geodesic_equator_known_value() -> None:
    result = geodesic_inverse(0.0, 0.0, 0.0, 1.0)
    assert result.distance == pytest.approx(111319.49079327357, rel=1e-10)
    assert result.azimuth == pytest.approx(90.0, abs=1e-10)
    assert result.back_azimuth == pytest.approx(270.0, abs=1e-8)


def test_geodesic_meridian_and_back_azimuth() -> None:
    result = geodesic_inverse(34.0, 117.0, 34.1, 117.0)
    assert result.azimuth == pytest.approx(0.0, abs=1e-10)
    assert result.back_azimuth == pytest.approx(180.0, abs=1e-10)
    assert result.distance == pytest.approx(11092.33, rel=1e-4)


def test_geodesic_and_plane_comparison_short_line() -> None:
    comparison = compare_geodesic_and_plane(34.2, 117.2, 34.21, 117.21)
    assert abs(comparison.distance_difference) < 0.1  # m
    assert abs(comparison.azimuth_difference) < 0.5  # °
    assert comparison.plane_distance > 0.0


# ---------------------------------------------------------------------------
# 等级表与测距先验
# ---------------------------------------------------------------------------


def test_grade_table_values() -> None:
    expected = {
        "二等": (9.0, 1.0, 10.0, 2.0, 120000),
        "三等": (5.0, 1.8, 10.0, 5.0, 80000),
        "四等": (2.0, 2.5, 10.0, 10.0, 45000),
        "一级": (1.0, 5.0, 10.0, 10.0, 20000),
        "二级": (None, 10.0, 15.0, 20.0, 10000),
    }
    for name, values in expected.items():
        grade = get_grade(name)
        assert grade.mean_side_km == values[0]
        assert grade.angle_sigma_arcsec == values[1]
        assert grade.a_mm == values[2]
        assert grade.b_ppm == values[3]
        assert grade.max_relative_denominator == values[4]


@pytest.mark.parametrize(
    "mean_side_m,expected",
    [
        (9500.0, "二等"),
        (9000.0, "二等"),
        (7000.0, "三等"),
        (3000.0, "四等"),
        (1500.0, "一级"),
        (800.0, "二级"),
    ],
)
def test_suggest_grade_by_mean_side(mean_side_m: float, expected: str) -> None:
    assert suggest_grade(mean_side_m).name == expected


def test_linear_and_quadrature_sigma_models() -> None:
    assert distance_sigma_mm(1000.0, a_mm=15.0, b_ppm=20.0, model="linear") == pytest.approx(35.0)
    assert distance_sigma_mm(1000.0, a_mm=15.0, b_ppm=20.0, model="quadrature") == pytest.approx(25.0)
    assert distance_weight(1000.0, a_mm=15.0, b_ppm=20.0, model="linear") == pytest.approx(1.0 / 35.0**2)


def test_distance_model_field() -> None:
    linear = Distance("A", "B", a=0.015, b_ppm=20.0, sigma_model="linear")
    quadrature = Distance("A", "B", a=0.015, b_ppm=20.0)
    assert linear.sigma(1000.0) == pytest.approx(0.035)
    assert quadrature.sigma(1000.0) == pytest.approx(0.025)
    assert linear.variance(1000.0) == pytest.approx(0.035**2)
    with pytest.raises(ValueError):
        Distance("A", "B", sigma_model="bogus")


# ---------------------------------------------------------------------------
# 文本导出/解析
# ---------------------------------------------------------------------------


def test_angle_topology_roundtrip_station_first() -> None:
    angles = parse_angle_topology(
        EXAMPLE1_TOPOLOGY, known_names=("8", "9"), order="station_first"
    )
    assert len(angles) == 14
    assert angles[0] == ("1", "8", "2")
    assert export_angle_topology(
        angles, known_names=("8", "9"), order="station_first"
    ) == EXAMPLE1_TOPOLOGY


def test_angle_topology_backsight_first() -> None:
    angles = parse_angle_topology(
        "[-1,1,2]", known_names=("8", "9"), order="backsight_first"
    )
    assert angles == [("8", "1", "2")]
    assert export_angle_topology(
        angles, known_names=("8", "9"), order="backsight_first"
    ) == "[-1,1,2]"


def test_coordinate_text_roundtrip() -> None:
    text = export_coordinate_text(EXAMPLE1_POINTS, names=["1", "8"], precision=9)
    assert text.splitlines()[0] == "点1；3784503.204274250，523065.320310928"
    parsed = parse_coordinate_text(text)
    assert parsed["1"] == pytest.approx(EXAMPLE1_POINTS["1"], abs=1e-9)
    assert parsed["8"] == pytest.approx(EXAMPLE1_POINTS["8"], abs=1e-9)


# ---------------------------------------------------------------------------
# 误差椭圆
# ---------------------------------------------------------------------------


def test_error_ellipse_diagonal() -> None:
    ellipse = error_ellipse(4.0, 1.0, 0.0, mw=2.0)
    assert ellipse.E == pytest.approx(4.0)
    assert ellipse.F == pytest.approx(2.0)
    assert ellipse.phi_E_deg == pytest.approx(0.0)
    ellipse2 = error_ellipse(1.0, 4.0, 0.0, mw=1.0)
    assert ellipse2.phi_E_deg == pytest.approx(90.0)


def test_error_ellipse_formula_3_39() -> None:
    qxx, qyy, qxy = 2.0, 1.0, 0.5
    k = math.sqrt((qxx - qyy) ** 2 + 4 * qxy * qxy)
    ellipse = error_ellipse(qxx, qyy, qxy, mw=1.0)
    assert ellipse.K == pytest.approx(k)
    assert ellipse.QEE == pytest.approx(0.5 * (qxx + qyy + k))
    assert ellipse.QFF == pytest.approx(0.5 * (qxx + qyy - k))
    phi = math.degrees(0.5 * math.atan2(2 * qxy, qxx - qyy)) % 180.0
    assert ellipse.phi_E_deg == pytest.approx(phi)


# ---------------------------------------------------------------------------
# 算例 1 黄金值
# ---------------------------------------------------------------------------


def test_example1_order_probe_finds_station_first() -> None:
    rows = example1_order_probe()
    matches = [row for row in rows if row.get("matches_paper")]
    # 交换后视/前视只改变角的符号，法方程相同，因此有两组等价排列。
    assert {row["permutation"] for row in matches} == {(1, 0, 2), (2, 0, 1)}
    station_first = next(row for row in matches if row["permutation"] == (1, 0, 2))
    assert station_first["role_order"] == "(测站,后视,前视)"


def test_example1_golden_q_paper_units() -> None:
    result = example1_result()
    qxx, qyy, _ = result.paper_q("1")
    assert result.weakest_point() == "1"
    # 论文四位小数
    assert round(qxx, 4) == pytest.approx(0.6502, abs=5e-5)
    assert round(qyy, 4) == pytest.approx(0.3039, abs=5e-5)
    # 严格 mm²/(″)²
    q_mm = result.q_mm2
    assert q_mm[0, 0] == pytest.approx(65.0191, abs=5e-4)
    assert q_mm[1, 1] == pytest.approx(30.3890, abs=5e-4)


def test_example1_paper_mp_numeric() -> None:
    result = example1_result()
    assert result.paper_mp_mm("1") == pytest.approx(9.768, abs=5e-4)
    # 严格单位下为 97.68 mm；论文的 0.97 cm 是 cm↔mm 口径差。
    assert result.mp_mm("1") == pytest.approx(97.677, abs=5e-3)


@pytest.mark.xfail(
    reason="论文称 19 个角，但公布 Q 精确等于 14 个已给角的解；"
    "任何真实新增角都会改善 Q，无法同时得到 0.6502/0.3039。",
    strict=False,
)
def test_example1_19_angles_exact_xfail() -> None:
    extra = example1_missing_triangle_angles()[:5]
    result = example1_result(list(example1_angles()) + list(extra))
    qxx, qyy, _ = result.paper_q("1")
    assert qxx == pytest.approx(0.6502, abs=5e-5)
    assert qyy == pytest.approx(0.3039, abs=5e-5)


@pytest.mark.xfail(
    reason="27 角优化的新增角未公布；正确 P=I 最小二乘下无法从线库拓扑"
    "唯一确定，搜索结果与 0.4636/0.1861 不符。",
    strict=False,
)
def test_example1_optimized_27_exact_xfail() -> None:
    extra = example1_missing_triangle_angles()
    result = example1_result(list(example1_angles()) + list(extra))
    qxx, qyy, _ = result.paper_q("1")
    assert qxx == pytest.approx(0.4636, abs=5e-5)
    assert qyy == pytest.approx(0.1861, abs=5e-5)


def test_example1_paper_edge_denominator_algorithm() -> None:
    # 反推：分母 = S / 0.01 m = 100·S；论文表值即线库 S 的 100 倍，
    # 个别差异来自截图转录（线 1/3 差 0.2 m、线 6 差 2 m）。
    published = EXAMPLE1_PUBLISHED["edge_denominators"]
    mismatches = 0
    max_rel = 0.0
    for (number, a, b, length, azimuth), table in zip(EXAMPLE1_LINES, published):
        model = thesis_edge_denominator(length)
        rel = abs(model - table) / table
        max_rel = max(max_rel, rel)
        if rel > 1e-3:
            mismatches += 1
        assert rel < 0.006
    assert max_rel < 0.006
    assert mismatches <= 3


def test_tolerance_check() -> None:
    ok, text = check_tolerance(9.77, tolerance_mm=20.0)
    assert ok and "满足" in text
    ok, text = check_tolerance(25.0, tolerance_mm=20.0)
    assert not ok and "不满足" in text


# ---------------------------------------------------------------------------
# 算例 2 近似复现
# ---------------------------------------------------------------------------


def test_example2_approximate_q_and_weakest_point() -> None:
    result = example2_result()
    assert result.weakest_point() == "7"
    qxx, qyy, _ = result.paper_q("7")
    assert round(qxx, 4) == pytest.approx(0.1715, abs=5e-5)
    assert round(qyy, 4) == pytest.approx(0.1575, abs=5e-5)
    assert result.paper_mp_mm("7") == pytest.approx(5.74, abs=0.05)
    assert result.metadata["n_rows"] == 21
    assert result.metadata["rank"] == 14


def test_example2_uses_grade2_linear_sigma() -> None:
    from ctrlnet.thesis_examples import example2_edge_sigmas

    rows = example2_edge_sigmas()
    assert len(rows) == 17
    for row in rows:
        assert row["sigma_mm"] == pytest.approx(
            15.0 + 20.0 * row["length"] / 1000.0, abs=1e-12
        )
    assert get_grade("二级").a_mm == 15.0
    assert get_grade("二级").b_ppm == 20.0
