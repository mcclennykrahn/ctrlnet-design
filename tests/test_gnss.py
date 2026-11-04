"""GNSS 三维基线网、局部 ENU 联合平差与高程异常近似的解析/数值校验。"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from ctrlnet import (
    Angle,
    Distance,
    GnssBaseline,
    GnssNetwork,
    GnssPoint,
    HeightDifference,
    covariance_ecef_to_enu,
    covariance_enu_to_ecef,
    ecef_to_enu,
    ecef_to_enu_matrix,
    ecef_to_geodetic,
    enu_to_ecef_matrix,
    fit_height_anomaly,
    geodetic_to_ecef,
    geodetic_to_enu,
    solve_gnss,
)
from ctrlnet.exceptions import InvalidGeometryError, RankDeficientError
from ctrlnet.gnss import EGMGrid, GeoidControlPoint


# ---------------------------------------------------------------------------
# 坐标转换
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "lat,lon,h",
    [
        (39.9, 116.0, 100.0),
        (0.0, 0.0, 0.0),
        (-33.86, 151.21, -12.5),
        (89.999, -179.999, 8500.0),
        (-89.999, 45.0, 120.0),
    ],
)
def test_geodetic_ecef_roundtrip(lat: float, lon: float, h: float) -> None:
    xyz = geodetic_to_ecef(lat, lon, h)
    lat2, lon2, h2 = ecef_to_geodetic(xyz)
    xyz2 = geodetic_to_ecef(lat2, lon2, h2)
    assert np.linalg.norm(xyz - xyz2) < 1e-6
    assert h2 == pytest.approx(h, abs=1e-6)
    # 经纬度在极点附近对经度不敏感，只检查纬度与回代 ECEF。
    if abs(abs(lat) - 90.0) > 1e-6:
        assert lat2 == pytest.approx(lat, abs=1e-9)
        assert lon2 == pytest.approx(lon, abs=1e-9)


def test_known_enu_values_and_rotation_orthonormality() -> None:
    # 赤道/本初子午线：ENU 的 E=+Y, N=+Z, U=+X。
    origin_xyz = np.array([6378137.0, 0.0, 0.0], dtype=float)
    assert np.allclose(ecef_to_enu(origin_xyz + [0.0, 100.0, 0.0], 0.0, 0.0), [100.0, 0.0, 0.0], atol=1e-9)
    assert np.allclose(ecef_to_enu(origin_xyz + [0.0, 0.0, 100.0], 0.0, 0.0), [0.0, 100.0, 0.0], atol=1e-9)
    assert np.allclose(ecef_to_enu(origin_xyz + [100.0, 0.0, 0.0], 0.0, 0.0), [0.0, 0.0, 100.0], atol=1e-9)

    assert np.allclose(geodetic_to_enu(0.0, 0.0, 100.0, 0.0, 0.0, 0.0), [0.0, 0.0, 100.0], atol=1e-9)
    r = ecef_to_enu_matrix(39.9, 116.0)
    assert np.allclose(r @ r.T, np.eye(3), atol=1e-15)
    assert np.linalg.det(r) == pytest.approx(1.0, abs=1e-15)
    assert np.allclose(r.T, enu_to_ecef_matrix(39.9, 116.0), atol=0.0)


def test_covariance_rotation_preserves_trace_and_eigenvalues() -> None:
    rng = np.random.default_rng(20261104)
    a = rng.normal(size=(3, 3))
    c_enu = a @ a.T + np.eye(3) * 1e-6
    c_ecef = covariance_enu_to_ecef(c_enu, 39.9, 116.0)
    assert np.trace(c_ecef) == pytest.approx(np.trace(c_enu), rel=1e-14)
    assert np.allclose(np.linalg.eigvalsh(c_ecef), np.linalg.eigvalsh(c_enu), rtol=1e-12, atol=1e-12)
    back = covariance_ecef_to_enu(c_ecef, 39.9, 116.0)
    assert np.allclose(back, c_enu, atol=1e-15)


# ---------------------------------------------------------------------------
# 纯 GNSS 网精度与解析解
# ---------------------------------------------------------------------------
def _two_baseline_network() -> tuple[GnssNetwork, np.ndarray, np.ndarray]:
    a = GnssPoint("A", 39.9, 116.0, 100.0, fixed=True)
    b = GnssPoint("B", 39.9008, 116.0010, 110.0)
    c = GnssPoint("C", 39.9015, 116.0018, 120.0)
    q1 = np.array(
        [[4e-4, 3e-5, 1e-5], [3e-5, 5e-4, 2e-5], [1e-5, 2e-5, 9e-4]],
        dtype=float,
    )
    q2 = np.array(
        [[6e-4, -2e-5, 0.0], [-2e-5, 3e-4, 1e-5], [0.0, 1e-5, 1.2e-3]],
        dtype=float,
    )
    net = GnssNetwork(
        [a, b, c],
        [
            GnssBaseline("A", "B", b.ecef - a.ecef, q1),
            GnssBaseline("B", "C", c.ecef - b.ecef, q2),
        ],
    )
    return net, q1, q2


def test_pure_gnss_cx_matches_analytic_normal_equations() -> None:
    net, q1, q2 = _two_baseline_network()
    result = solve_gnss(net, datum="fixed")

    # 参数顺序 [B(XYZ), C(XYZ)]；A 三行 = [I,0]，B-C 三行 = [-I,I]。
    A = np.zeros((6, 6), dtype=float)
    A[0:3, 0:3] = np.eye(3)
    A[3:6, 0:3] = -np.eye(3)
    A[3:6, 3:6] = np.eye(3)
    Q = np.zeros((6, 6), dtype=float)
    Q[0:3, 0:3] = q1
    Q[3:6, 3:6] = q2
    expected = np.linalg.inv(A.T @ np.linalg.inv(Q) @ A)
    assert result.rank == 6
    assert result.n_params == 6
    assert result.redundancy == 0
    assert np.allclose(result.Cx, expected, rtol=1e-12, atol=1e-14)
    assert np.allclose(result.A, A, atol=0.0)
    assert np.allclose(result.Ql, Q, atol=0.0)
    # Cholesky 白化：AwᵀAw = AᵀQ⁻¹A。
    assert np.allclose(result.Aw.T @ result.Aw, A.T @ np.linalg.inv(Q) @ A, rtol=1e-12, atol=1e-14)

    # 点 B 的边缘协方差就是第一条基线协方差。
    assert np.allclose(result.points["B"].covariance_ecef, q1, atol=1e-14)
    assert result.points["A"].m3D == pytest.approx(0.0, abs=1e-15)
    assert result.max_m3D == pytest.approx(np.sqrt(np.trace(expected[3:6, 3:6])), abs=1e-12)
    assert result.max_mp == pytest.approx(
        np.hypot(
            result.points["B"].sigma_E,
            result.points["B"].sigma_N,
        )
        if result.points["B"].mp_horizontal >= result.points["C"].mp_horizontal
        else np.hypot(result.points["C"].sigma_E, result.points["C"].sigma_N),
        abs=1e-12,
    )


def test_enu_baseline_covariance_is_rotated_to_ecef() -> None:
    a = GnssPoint("A", 39.9, 116.0, 100.0, fixed=True)
    b = GnssPoint("B", 39.9008, 116.0010, 110.0)
    delta_ecef = b.ecef - a.ecef
    c_enu = np.array(
        [[4e-4, 1e-4, 3e-5], [1e-4, 6e-4, 4e-5], [3e-5, 4e-5, 9e-4]],
        dtype=float,
    )
    delta_enu = ecef_to_enu(delta_ecef, a.lat, a.lon, a.h)
    net = GnssNetwork(
        [a, b],
        [GnssBaseline("A", "B", delta_enu, c_enu, frame="ENU")],
    )
    result = solve_gnss(net, datum="fixed")
    expected = covariance_enu_to_ecef(c_enu, a.lat, a.lon)
    assert np.allclose(result.points["B"].covariance_ecef, expected, rtol=1e-13, atol=1e-15)
    assert np.trace(result.points["B"].covariance_ecef) == pytest.approx(np.trace(c_enu), rel=1e-13)

    # 参数在 ENU 框架时，同一观测应给出 C_ENU = c_enu。
    result_enu = solve_gnss(net, datum="fixed", parameter_frame="ENU")
    assert result_enu.parameter_names == ["E_B", "N_B", "U_B"]
    assert np.allclose(result_enu.points["B"].covariance_enu, c_enu, rtol=1e-13, atol=1e-15)
    assert np.allclose(result_enu.points["B"].covariance_ecef, expected, rtol=1e-13, atol=1e-15)


def test_free_network_minimal_constraint_reports_translation_nullspace() -> None:
    a = GnssPoint("A", 39.9, 116.0, 100.0)
    b = GnssPoint("B", 39.9008, 116.0010, 110.0)
    c = GnssPoint("C", 39.9015, 116.0018, 120.0)
    q = np.eye(3) * 1e-4
    net = GnssNetwork(
        [a, b, c],
        [
            GnssBaseline("A", "B", b.ecef - a.ecef, q),
            GnssBaseline("B", "C", c.ecef - b.ecef, q),
        ],
    )
    with pytest.raises(RankDeficientError):
        solve_gnss(net, datum="fixed")
    result = solve_gnss(net, datum="minimal")
    # 基线三分量已观测，自由网零空间只有 3 个整体平移。
    assert result.rank == result.n_params - 3
    assert result.null_space.shape == (result.n_params, 3)
    assert np.all(np.isfinite(result.Cx))
    assert result.max_m3D > 0.0


# ---------------------------------------------------------------------------
# 联合平差
# ---------------------------------------------------------------------------
def _joint_network() -> tuple[GnssNetwork, GnssNetwork]:
    a = GnssPoint("A", 39.9, 116.0, 100.0, fixed=True)
    b = GnssPoint("B", 39.9, 116.001, 110.0, fixed=True)
    c = GnssPoint("C", 39.901, 116.001, 120.0)
    d = GnssPoint("D", 39.902, 116.002, 130.0)
    q = np.diag([2e-4, 2e-4, 5e-4])
    baselines = [
        GnssBaseline("A", "C", c.ecef - a.ecef, q),
        GnssBaseline("B", "C", c.ecef - b.ecef, q),
        GnssBaseline("C", "D", d.ecef - c.ecef, q),
        GnssBaseline("A", "B", b.ecef - a.ecef, q),
    ]
    gnss_only = GnssNetwork([a, b, c, d], baselines)
    joint = GnssNetwork(
        [a, b, c, d],
        baselines,
        distances=[Distance("A", "C"), Distance("B", "C"), Distance("C", "D"), Distance("A", "D")],
        angles=[Angle("A", "C", "D"), Angle("C", "D", "A")],
        leveling=[
            HeightDifference("A", "C", 20.0, length_km=1.0, sigma_per_km_mm=1.0),
            HeightDifference("C", "D", 10.0, length_km=1.0, sigma_per_km_mm=1.0),
            HeightDifference("A", "D", 30.0, length_km=1.0, sigma_per_km_mm=1.0),
        ],
    )
    return gnss_only, joint


def test_joint_adjustment_with_ground_observations_does_not_degrade_precision() -> None:
    gnss_only, joint = _joint_network()
    r0 = solve_gnss(gnss_only, datum="fixed")
    r1 = solve_gnss(joint, datum="fixed")
    assert r1.rank == r1.n_params
    assert r1.redundancy > 0
    # 增加观测只会增加法方程信息；Cx 的 Loewner 差应为半负定。
    assert np.max(np.linalg.eigvalsh(r1.Cx - r0.Cx)) <= 1e-12
    assert r1.max_mp <= r0.max_mp + 1e-12
    assert r1.max_m3D <= r0.max_m3D + 1e-12
    assert r1.max_sigma_U <= r0.max_sigma_U + 1e-12
    # 复用 reliability：r_i∈[0,1]，MDB 为正有限值。
    records = r1.reliability.records
    assert records
    for row in records:
        assert -1e-12 <= row.r_i <= row.r_components.size + 1e-12
        assert all(-1e-12 <= value <= 1.0 + 1e-12 for value in row.r_components)
    assert any(row.kind == "leveling" and np.isfinite(row.mdb) and row.mdb > 0.0 for row in records)
    assert r1.reliability.sum_r == pytest.approx(r1.redundancy, abs=1e-9)
    # 水平/垂直中误差与协方差对角一致。
    for name in ("C", "D"):
        p = r1.points[name]
        assert p.sigma_E**2 == pytest.approx(p.covariance_enu[0, 0], rel=1e-13)
        assert p.sigma_U**2 == pytest.approx(p.covariance_enu[2, 2], rel=1e-13)
        assert p.mp_horizontal == pytest.approx(np.hypot(p.sigma_E, p.sigma_N), rel=1e-13)
        assert p.m3D == pytest.approx(np.sqrt(np.trace(p.covariance_ecef)), rel=1e-13)
    # 基线相对精度可复算。
    base = r1.baselines["C-D"]
    delta = base.delta_enu
    g = delta / np.linalg.norm(delta)
    assert base.sigma_3d == pytest.approx(np.sqrt(g @ base.covariance_enu @ g), rel=1e-13)
    assert base.relative_3d == pytest.approx(base.sigma_3d / base.length_3d, rel=1e-13)


# ---------------------------------------------------------------------------
# 高程异常拟合
# ---------------------------------------------------------------------------
def test_plane_height_anomaly_recovers_known_parameters_and_normal_height() -> None:
    a0, b0, c0 = 12.5, 2.0e-5, -3.0e-5
    samples = []
    for i, (E, N) in enumerate(
        [(0.0, 0.0), (1000.0, 0.0), (0.0, 1000.0), (2000.0, 500.0), (500.0, 2500.0), (3000.0, 3000.0)]
    ):
        zeta = a0 + b0 * E + c0 * N
        samples.append(GeoidControlPoint(f"P{i}", E, N, 80.0 + zeta, 80.0))
    fit = fit_height_anomaly(samples, mode="plane", variance_factor=4e-6)
    assert fit.a == pytest.approx(a0, abs=1e-10)
    assert fit.b == pytest.approx(b0, abs=1e-13)
    assert fit.c == pytest.approx(c0, abs=1e-13)
    assert fit.rms < 1e-10
    assert fit.max_abs_residual < 1e-10
    assert fit.zeta(1234.0, 2345.0) == pytest.approx(a0 + b0 * 1234.0 + c0 * 2345.0, abs=1e-10)
    assert np.allclose(fit.parameter_sigmas, np.sqrt(np.diag(fit.covariance)), rtol=1e-12, atol=0.0)
    assert np.all(fit.parameter_sigmas > 0.0)
    assert "近似" in fit.applicability_note

    h = 80.0 + fit.zeta(1234.0, 2345.0) + 1.5
    H, sig = fit.normal_height(h, 1234.0, 2345.0, sigma_h=0.004)
    assert H == pytest.approx(81.5, abs=1e-10)
    assert sig >= 0.004
    assert fit.ellipsoidal_height(H, 1234.0, 2345.0) == pytest.approx(h, abs=1e-10)


def test_constant_height_anomaly_and_degenerate_plane_rejected() -> None:
    samples = [GeoidControlPoint(f"P{i}", i * 100.0, i * 50.0, 10.0 + 3.0, 10.0) for i in range(4)]
    fit = fit_height_anomaly(samples, mode="constant")
    assert fit.mode == "constant"
    assert fit.a == pytest.approx(3.0, abs=1e-12)
    assert fit.b == 0.0 and fit.c == 0.0
    assert fit.zeta(1.0, 2.0) == pytest.approx(3.0, abs=1e-12)

    collinear = [
        GeoidControlPoint("A", 0.0, 0.0, 1.0, 0.0),
        GeoidControlPoint("B", 100.0, 100.0, 2.0, 0.0),
        GeoidControlPoint("C", 200.0, 200.0, 3.0, 0.0),
    ]
    with pytest.raises(InvalidGeometryError):
        fit_height_anomaly(collinear, mode="plane")


def test_egm_grid_interpolation_optional_sample() -> None:
    pytest.importorskip("rasterio")
    path = Path(__file__).resolve().parents[1] / "data" / "sample" / "egm96_beijing.tif"
    if not path.exists():
        pytest.skip("未提供裁剪后的 EGM96 样本")
    grid = EGMGrid.from_geotiff(path)
    value = grid.undulation(116.03, 39.94)
    assert np.isfinite(value)
    assert -30.0 < value < 0.0
    assert grid.zeta(116.03, 39.94) == pytest.approx(value, abs=0.0)
