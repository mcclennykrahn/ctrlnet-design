"""DEM 采样、剖面、曲率折光通视与晕渲的合成算例测试。"""

from __future__ import annotations

from math import exp, sin, radians

import numpy as np
import pytest

from ctrlnet import (
    AffineTransform,
    DEM,
    contours,
    curvature_refraction_correction,
    hillshade,
    line_of_sight_height,
)

RES = 10.0
X0 = 500_000.0


def _make_dem(z: np.ndarray, *, res: float = RES) -> DEM:
    height, width = z.shape
    north = height * res
    return DEM(
        z,
        AffineTransform.from_origin(X0, north, res, res),
        metadata={"resolution": [res, res], "name": "synthetic"},
    )


def _centers(z: np.ndarray, *, res: float = RES) -> tuple[np.ndarray, np.ndarray]:
    height, width = z.shape
    north = height * res
    rows, cols = np.mgrid[0:height, 0:width]
    E = X0 + (cols + 0.5) * res
    N = north - (rows + 0.5) * res
    return E, N


def test_bilinear_interpolation_is_exact_for_plane() -> None:
    height, width = 60, 80
    zeros = np.zeros((height, width))
    E, N = _centers(zeros)
    north = height * RES
    z = 100.0 + 0.5 * (E - X0) + 0.2 * (N - north)
    dem = _make_dem(z)

    rng = np.random.default_rng(20261104)
    # 避开最外半像素，保证查询位于像素中心凸包内。
    qe = rng.uniform(X0 + 2 * RES, X0 + (width - 2) * RES, size=40)
    qn = rng.uniform(2 * RES, (height - 2) * RES, size=40)
    expected = 100.0 + 0.5 * (qe - X0) + 0.2 * (qn - north)
    got = dem.elevation(qe, qn)
    assert np.allclose(got, expected, atol=1e-9)

    # 标量接口、双线性权重与中心点读取。
    col, row = 13, 17
    ce = X0 + (col + 0.5) * RES
    cn = north - (row + 0.5) * RES
    assert dem.elevation(ce, cn) == pytest.approx(z[row, col], abs=1e-12)
    assert np.isfinite(dem.elevation(float(ce), float(cn)))


def test_profile_has_endpoints_and_steps() -> None:
    z = np.full((100, 100), 50.0)
    dem = _make_dem(z)
    p1 = (X0 + 100.0, 900.0)
    p2 = (X0 + 700.0, 900.0)
    prof = dem.profile(p1, p2, step=37.0)
    assert prof.length == pytest.approx(600.0)
    assert prof.distance[0] == pytest.approx(0.0)
    assert prof.distance[-1] == pytest.approx(600.0)
    assert prof.x[0] == pytest.approx(p1[0])
    assert prof.y[-1] == pytest.approx(p2[1])
    assert np.allclose(prof.elevation, 50.0)
    assert not prof.nodata.any()
    # 实际步长不超过请求步长，且样本覆盖全长。
    assert 0.0 < prof.step <= 37.0 + 1e-12
    assert prof.sample_count == 600 // 37 + 1 + (1 if 600 % 37 else 0)


def test_flat_dem_is_visible() -> None:
    z = np.full((200, 401), 100.0)
    dem = _make_dem(z)
    p1 = (X0 + 5.0, 1_000.0)
    p2 = (X0 + 4_005.0, 1_000.0)
    result = dem.intervisibility(p1, p2, inst_h=2.0, target_h=2.0, step=10.0)

    assert result.status == "visible"
    assert result.visible is True
    assert result.distance == pytest.approx(4_000.0)
    assert result.min_clearance > 0.0
    assert result.obstruction_position is None
    # 平地剖面的最小净空出现在曲率/折光改正最大的跨中。
    correction = (1.0 - 0.13) * result.distance**2 / (8.0 * 6_371_000.0)
    assert result.min_clearance == pytest.approx(2.0 - correction, abs=1e-9)
    assert result.line_height[0] == pytest.approx(102.0)
    assert result.line_height[-1] == pytest.approx(102.0)


def test_sloped_dem_profile_matches_plane() -> None:
    height, width = 80, 120
    zeros = np.zeros((height, width))
    E, N = _centers(zeros)
    north = height * RES
    # 东高西低、北高南低的均匀斜面。
    z = 300.0 + 0.08 * (E - X0) + 0.05 * (N - north)
    dem = _make_dem(z)

    p1 = (X0 + 500.0, 400.0)
    p2 = (X0 + 1_000.0, 400.0)
    prof = dem.profile(p1, p2, step=25.0)
    expected = 300.0 + 0.08 * (prof.x - X0) + 0.05 * (prof.y - north)
    assert np.allclose(prof.elevation, expected, atol=1e-9)

    result = dem.intervisibility(p1, p2, inst_h=2.0, target_h=2.0, step=25.0)
    assert result.distance == pytest.approx(np.hypot(500.0, 0.0))
    assert result.ground_start == pytest.approx(
        300.0 + 0.08 * 500.0 + 0.05 * (400.0 - north), abs=1e-9
    )
    assert result.visible is True
    assert result.line_height[0] == pytest.approx(result.ground_start + 2.0)

def test_ridge_blocks_then_high_instrument_restores_visibility() -> None:
    height, width = 201, 401
    z = np.full((height, width), 100.0)
    E, N = _centers(z)
    ridge_center = X0 + 2_000.0
    z += 30.0 * np.exp(-(((E - ridge_center) / 90.0) ** 2))
    dem = _make_dem(z)

    p1 = (X0 + 1_000.0, 1_000.0)
    p2 = (X0 + 3_000.0, 1_000.0)
    blocked = dem.intervisibility(p1, p2, inst_h=1.5, target_h=1.5, step=5.0)
    assert blocked.status == "blocked"
    assert blocked.visible is False
    assert blocked.min_clearance < 0.0
    assert blocked.obstruction_position is not None
    ox, _ = blocked.obstruction_position
    assert ox == pytest.approx(ridge_center, abs=10.0)
    assert blocked.min_terrain_elevation is not None
    assert blocked.min_terrain_elevation > 125.0

    visible = dem.intervisibility(p1, p2, inst_h=70.0, target_h=1.5, step=5.0)
    assert visible.status == "visible"
    assert visible.visible is True
    assert visible.min_clearance > 0.0
    assert visible.line_height[0] == pytest.approx(z[100, 100] + 70.0)


def test_curvature_and_refraction_drop_matches_formula_at_long_distance() -> None:
    distance = 30_000.0
    width = int(distance / RES) + 1
    z = np.full((5, width), 100.0)
    dem = _make_dem(z)
    p1 = (X0 + 0.5 * RES, 25.0)
    p2 = (X0 + (width - 0.5) * RES, 25.0)

    result = dem.intervisibility(p1, p2, inst_h=2.0, target_h=2.0, step=10.0)
    assert result.distance == pytest.approx(distance)
    assert result.status == "blocked"
    assert result.visible is False

    mid = distance / 2.0
    expected_drop = (1.0 - 0.13) * distance**2 / (8.0 * 6_371_000.0)
    assert curvature_refraction_correction(mid, distance) == pytest.approx(
        expected_drop, abs=1e-9
    )
    assert line_of_sight_height(mid, distance, 102.0, 102.0) == pytest.approx(
        102.0 - expected_drop, abs=1e-9
    )
    assert result.min_clearance == pytest.approx(2.0 - expected_drop, abs=1e-6)
    assert result.min_distance == pytest.approx(mid, abs=1e-9)
    assert result.line_height[0] == pytest.approx(102.0)
    assert result.line_height[-1] == pytest.approx(102.0)


def test_clearance_threshold_marks_marginal_and_nodata_unknown() -> None:
    z = np.full((100, 301), 100.0)
    dem = _make_dem(z)
    p1 = (X0 + 5.0, 500.0)
    p2 = (X0 + 2_995.0, 500.0)
    # 3 km 跨中最大下沉约 0.154 m；仪器/目标各 0.5 m 时净空约 0.346 m。
    marginal = dem.intervisibility(
        p1, p2, inst_h=0.5, target_h=0.5, clearance=0.8, step=10.0
    )
    assert marginal.status == "marginal"
    assert marginal.visible is False
    assert 0.0 < marginal.min_clearance < 0.8

    z_nodata = z.copy()
    z_nodata[:, 150] = np.nan
    dem_nodata = _make_dem(z_nodata)
    unknown = dem_nodata.intervisibility(p1, p2, clearance=0.0, step=10.0)
    assert unknown.status == "unknown"
    assert unknown.visible is False
    assert unknown.nodata_count > 0
    assert np.isnan(dem_nodata.elevation(X0 + 1_500.0, 500.0))


def test_hillshade_range_flat_reference_and_nodata() -> None:
    z = np.full((80, 100), 250.0)
    dem = _make_dem(z)
    shade = hillshade(dem, azimuth=315.0, altitude=45.0)
    assert shade.shape == z.shape
    assert float(shade.min()) >= 0.0
    assert float(shade.max()) <= 1.0
    assert np.allclose(shade, sin(radians(45.0)), atol=1e-12)

    slope = 40.0 * np.exp(
        -((np.arange(100)[None, :] - 50.0) ** 2 + (np.arange(80)[:, None] - 40.0) ** 2)
        / 250.0
    )
    shade_slope = hillshade(_make_dem(slope), azimuth=270.0, altitude=30.0)
    assert np.all(shade_slope >= 0.0) and np.all(shade_slope <= 1.0)
    assert float(shade_slope.std()) > 1e-3

    z_nodata = z.copy()
    z_nodata[10:20, 10:20] = np.nan
    shade_nodata = hillshade(_make_dem(z_nodata))
    assert np.allclose(shade_nodata[10:20, 10:20], 0.0)


def test_contours_smoke() -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    z = np.add.outer(np.linspace(0.0, 10.0, 40), np.linspace(0.0, 20.0, 50))
    dem = _make_dem(z)
    fig, ax = plt.subplots()
    cs = contours(dem, ax=ax, levels=5)
    assert cs is not None
    assert len(ax.collections) >= 1
    plt.close(fig)
