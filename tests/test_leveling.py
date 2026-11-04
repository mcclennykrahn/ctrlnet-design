"""1D 水准/高程网与三角高程的解析/数值校验。"""

from __future__ import annotations

from math import cos, degrees, pi, radians, sin, sqrt, tan

import numpy as np
import pytest

from ctrlnet import (
    HeightDifference,
    LevelingNetwork,
    LevelingPoint,
    TrigHeight,
    analyze_leveling_reliability,
    solve_leveling,
)
from ctrlnet.exceptions import (
    InvalidGeometryError,
    InvalidPrecisionError,
    RankDeficientError,
)

ARCSEC = pi / (180.0 * 3600.0)


def _square_loop(fixed: bool = True, *, sigma_km: float = 1.0) -> LevelingNetwork:
    points = [
        LevelingPoint("A", 10.0, fixed=fixed),
        LevelingPoint("B", 11.0),
        LevelingPoint("C", 12.0),
        LevelingPoint("D", 13.0),
    ]
    observations = [
        HeightDifference("A", "B", 1.0, length_km=1.0, sigma_per_km_mm=sigma_km),
        HeightDifference("B", "C", 1.0, length_km=1.0, sigma_per_km_mm=sigma_km),
        HeightDifference("C", "D", 1.0, length_km=1.0, sigma_per_km_mm=sigma_km),
        HeightDifference("D", "A", -3.0, length_km=1.0, sigma_per_km_mm=sigma_km),
    ]
    return LevelingNetwork(points, observations, name="square-loop")


def test_single_route_sigma_and_station_mode() -> None:
    # 单条支线：A 固定，B 待定，σ_H(B) = σ_km·sqrt(L)。
    net = LevelingNetwork(
        [LevelingPoint("A", 0.0, fixed=True), LevelingPoint("B", 1.0)],
        [HeightDifference("A", "B", 1.0, length_km=4.0, sigma_per_km_mm=2.0)],
    )
    result = solve_leveling(net)
    assert result.rank == 1
    assert result.redundancy == 0
    assert result.sigma_H_mm("B") == pytest.approx(4.0, abs=1e-12)
    assert net.observations[0].sigma == pytest.approx(0.004, abs=1e-15)
    assert result.records[0].r_i == pytest.approx(0.0, abs=1e-12)
    assert result.records[0].mdb == float("inf")
    assert result.records[0].undetectable

    # 改变 σ_km 应按线性比例传播。
    net2 = LevelingNetwork(
        [LevelingPoint("A", 0.0, fixed=True), LevelingPoint("B", 1.0)],
        [HeightDifference("A", "B", 1.0, length_km=4.0, sigma_per_km_mm=4.0)],
    )
    assert solve_leveling(net2).sigma_H_mm("B") == pytest.approx(8.0, abs=1e-12)

    # 按测站数：σ = σ_station·sqrt(n)。
    net3 = LevelingNetwork(
        [LevelingPoint("A", 0.0, fixed=True), LevelingPoint("B", 1.0)],
        [
            HeightDifference(
                "A",
                "B",
                1.0,
                n_stations=9,
                sigma_per_station_mm=0.5,
            )
        ],
    )
    result3 = solve_leveling(net3)
    assert net3.observations[0].mode == "station"
    assert net3.observations[0].sigma == pytest.approx(0.0015, abs=1e-15)
    assert result3.sigma_H_mm("B") == pytest.approx(1.5, abs=1e-12)


def test_closed_loop_cx_and_redundancy_match_analytic_solution() -> None:
    net = _square_loop()
    result = solve_leveling(net)

    # 4 条独立高差、1 个固定点，未知数 3，冗余数 1。
    assert result.rank == 3
    assert result.n_params == 3
    assert result.redundancy == 1
    assert result.datum_kind == "fixed"
    assert result.height("A") == pytest.approx(10.0)
    assert np.allclose(result.heights, [10.0, 11.0, 12.0, 13.0], atol=1e-12)
    assert np.allclose(result.residuals, 0.0, atol=1e-12)

    # 解析 Cx = N^-1，N=[[2,-1,0],[-1,2,-1],[0,-1,2]]（单位 mm²）。
    expected_mm2 = np.array(
        [[0.75, 0.50, 0.25], [0.50, 1.00, 0.50], [0.25, 0.50, 0.75]]
    )
    assert np.allclose(result.Cx * 1e6, expected_mm2, atol=1e-12)
    assert np.allclose(result.Cx, result.Cx.T, atol=1e-18)

    assert result.sigma_H_mm("B") == pytest.approx(sqrt(0.75), abs=1e-12)
    assert result.sigma_H_mm("C") == pytest.approx(1.0, abs=1e-12)
    assert result.sigma_H_mm("D") == pytest.approx(sqrt(0.75), abs=1e-12)
    # 相对高差：var(H_D-H_B)=0.75+0.75-2*0.25=1 mm²。
    relative = result.relative_height("B", "D")
    assert relative.delta_h == pytest.approx(2.0, abs=1e-12)
    assert relative.sigma_mm == pytest.approx(1.0, abs=1e-12)

    # 闭合环冗余数 1，四个测段 r_i 均为 1/4，和为 1。
    assert result.reliability is not None
    assert result.reliability.sum_r == pytest.approx(1.0, abs=1e-12)
    assert result.reliability.trace_r == pytest.approx(1.0, abs=1e-12)
    assert result.reliability.redundancy == 1
    for record in result.records:
        assert record.r_i == pytest.approx(0.25, abs=1e-12)
        assert record.mdb > 0.0
        assert record.external_max >= 0.0
    assert sum(obs.delta_h for obs in net.observations) == pytest.approx(0.0)


def test_connecting_route_between_two_fixed_benchmarks() -> None:
    # 附合水准路线：A、D 为已知高程，B/C 待定，三段各 1 km。
    net = LevelingNetwork(
        [
            LevelingPoint("A", 10.0, fixed=True),
            LevelingPoint("B", 11.0),
            LevelingPoint("C", 12.0),
            LevelingPoint("D", 13.0, fixed=True),
        ],
        [
            HeightDifference("A", "B", +1.0, length_km=1.0, sigma_per_km_mm=1.0),
            HeightDifference("B", "C", +1.0, length_km=1.0, sigma_per_km_mm=1.0),
            HeightDifference("C", "D", +1.0, length_km=1.0, sigma_per_km_mm=1.0),
        ],
    )
    result = solve_leveling(net)
    assert result.rank == 2
    assert result.redundancy == 1
    assert np.allclose(result.heights, [10.0, 11.0, 12.0, 13.0], atol=1e-12)
    # N=[[2,-1],[-1,2]] mm^-2 => Cx=1/3[[2,1],[1,2]] mm²。
    assert np.allclose(result.Cx * 1e6, [[2 / 3, 1 / 3], [1 / 3, 2 / 3]], atol=1e-12)
    assert result.sigma_H_mm("B") == pytest.approx(sqrt(2 / 3), abs=1e-12)
    assert result.sigma_H_mm("C") == pytest.approx(sqrt(2 / 3), abs=1e-12)
    assert result.relative_sigma_mm("B", "C") == pytest.approx(sqrt(2 / 3), abs=1e-12)
    assert result.reliability is not None
    assert result.reliability.sum_r == pytest.approx(1.0, abs=1e-12)
    for record in result.records:
        assert record.r_i == pytest.approx(1 / 3, abs=1e-12)


def test_no_vertical_datum_raises_rank_deficient() -> None:
    net = _square_loop(fixed=False)
    with pytest.raises(RankDeficientError) as caught:
        solve_leveling(net)
    exc = caught.value
    assert exc.rank == 3
    assert exc.n_params == 4
    assert exc.null_space is not None and exc.null_space.shape == (4, 1)
    assert "秩亏" in str(exc)
    assert "高程基准" in str(exc)
    assert exc.diagnostics
    assert any("零空间" in item for item in exc.diagnostics)


def test_free_network_minimal_constraint() -> None:
    net = _square_loop(fixed=False)
    result = solve_leveling(net, datum="free")
    assert result.rank == 3
    assert result.n_params == 4
    assert result.redundancy == 1
    assert result.datum_kind == "minimal"
    assert result.null_space.shape == (4, 1)

    # 自由网协方差应为半正定，且与整体高程平移方向正交。
    assert float(np.linalg.eigvalsh(result.Cx).min()) >= -1e-18
    assert np.allclose(result.Cx @ np.ones(4), 0.0, atol=1e-15)
    # 相对高差与基准无关，仍为解析值 1 mm。
    assert result.relative_sigma_mm("B", "D") == pytest.approx(1.0, abs=1e-12)
    assert result.reliability is not None
    assert result.reliability.sum_r == pytest.approx(1.0, abs=1e-12)

    # 自由网不能同时带固定点/加权约束，避免基准定义冲突。
    with pytest.raises(InvalidPrecisionError):
        solve_leveling(_square_loop(fixed=True), datum="minimal")


def test_weighted_height_constraint_controls_datum() -> None:
    points = [
        LevelingPoint("A", 10.0, sigma_H=0.002),
        LevelingPoint("B", 11.0),
        LevelingPoint("C", 12.0),
        LevelingPoint("D", 13.0),
    ]
    observations = list(_square_loop(fixed=False).observations)
    net = LevelingNetwork(points, observations)
    result = solve_leveling(net)  # 默认 auto 使用 sigma_H
    assert result.datum_kind == "weighted"
    assert result.constrained_names == ["A"]
    assert result.n_constraints == 1
    assert result.n_rows == 5
    assert result.rank == 4
    assert result.redundancy == 1
    assert result.sigma_H_mm("A") == pytest.approx(2.0, abs=1e-12)
    assert result.point_precision("A").constrained
    assert result.reliability is not None
    assert result.reliability.sum_r == pytest.approx(1.0, abs=1e-12)
    assert len(result.reliability.observation_records) == 4
    assert len(result.reliability.constraint_records) == 1
    assert result.records[-1].kind == "constraint"

    with pytest.raises(InvalidPrecisionError):
        solve_leveling(_square_loop(fixed=False), datum="weighted")


def _trig_slope(s: float, z: float, i: float, v: float, k: float, radius: float) -> float:
    return s * cos(z) + (1.0 - k) * s * s * sin(z) ** 2 / (2.0 * radius) + i - v


def _trig_horizontal(d: float, z: float, i: float, v: float, k: float, radius: float) -> float:
    return d / tan(z) + (1.0 - k) * d * d / (2.0 * radius) + i - v


def test_trig_height_formula_and_spherical_refraction_term() -> None:
    # S=1000 m、天顶距 90°：球气差项 (1-k)S²/(2R)。
    trig = TrigHeight(
        "A",
        "B",
        slope_distance=1000.0,
        zenith_deg=90.0,
        instrument_height=1.5,
        target_height=1.5,
        k=0.13,
        R=6371000.0,
    )
    expected_correction = (1.0 - 0.13) * 1000.0**2 / (2.0 * 6371000.0)
    assert expected_correction == pytest.approx(0.0682781353006, abs=1e-12)
    assert trig.curvature_correction == pytest.approx(expected_correction, abs=1e-15)
    assert trig.delta_h == pytest.approx(expected_correction, abs=1e-12)
    assert 0.0682 < trig.delta_h < 0.0684

    # 一般斜距情形与独立数值计算一致。
    z = radians(80.0)
    s, i, v, radius = 1234.5, 1.62, 2.10, 6371000.0
    trig2 = TrigHeight(
        "A",
        "B",
        slope_distance=s,
        zenith_deg=80.0,
        instrument_height=i,
        target_height=v,
        k=0.13,
        R=radius,
    )
    independent = s * cos(z) + 0.87 * s * s * sin(z) ** 2 / (2.0 * radius) + i - v
    assert trig2.delta_h == pytest.approx(independent, abs=1e-14)

    # 平距形式与等价的斜距形式一致。
    d = 1000.0
    trig_h = TrigHeight(
        "A",
        "B",
        horizontal_distance=d,
        zenith_deg=80.0,
        instrument_height=i,
        target_height=v,
        k=0.13,
        R=radius,
    )
    trig_s = TrigHeight(
        "A",
        "B",
        slope_distance=d / sin(z),
        zenith_deg=80.0,
        instrument_height=i,
        target_height=v,
        k=0.13,
        R=radius,
    )
    assert trig_h.delta_h == pytest.approx(trig_s.delta_h, abs=1e-12)
    assert trig_h.delta_h == pytest.approx(
        _trig_horizontal(d, z, i, v, 0.13, radius), abs=1e-14
    )
    # 曲率/折光改正为正，抬高目标点高差。
    assert trig_h.curvature_correction == pytest.approx(
        0.87 * d * d / (2.0 * radius), abs=1e-15
    )


def _central_diff(func: Any, x: float, step: float) -> float:
    return (func(x + step) - func(x - step)) / (2.0 * step)


@pytest.mark.parametrize("mode", ["slope", "horizontal"])
def test_trig_height_error_propagation_matches_finite_difference(mode: str) -> None:
    z = radians(82.0)
    s, d, i, v, k, radius = 850.0, 700.0, 1.55, 1.70, 0.13, 6371000.0
    sigma_z = 2.0 * ARCSEC
    sigma_dist = 0.002
    sigma_i = 0.001
    sigma_v = 0.001
    sigma_k = 0.010

    if mode == "slope":
        trig = TrigHeight(
            "A",
            "B",
            slope_distance=s,
            zenith_deg=degrees(z),
            instrument_height=i,
            target_height=v,
            k=k,
            R=radius,
            sigma_zenith_arcsec=2.0,
            sigma_slope_mm=2.0,
            sigma_instrument_mm=1.0,
            sigma_target_mm=1.0,
            sigma_k=sigma_k,
        )

        def model(ss: float, zz: float, ii: float, vv: float, kk: float) -> float:
            return _trig_slope(ss, zz, ii, vv, kk, radius)

        x0, hx = s, 1e-4
    else:
        trig = TrigHeight(
            "A",
            "B",
            horizontal_distance=d,
            zenith_deg=degrees(z),
            instrument_height=i,
            target_height=v,
            k=k,
            R=radius,
            sigma_zenith_arcsec=2.0,
            sigma_horizontal_mm=2.0,
            sigma_instrument_mm=1.0,
            sigma_target_mm=1.0,
            sigma_k=sigma_k,
        )

        def model(xx: float, zz: float, ii: float, vv: float, kk: float) -> float:
            return _trig_horizontal(xx, zz, ii, vv, kk, radius)

        x0, hx = d, 1e-4

    # 独立中心差分数值导数。
    dx = _central_diff(lambda x: model(x, z, i, v, k), x0, hx)
    dz = _central_diff(lambda zz: model(x0, zz, i, v, k), z, 1e-8)
    di = _central_diff(lambda ii: model(x0, z, ii, v, k), i, 1e-5)
    dv = _central_diff(lambda vv: model(x0, z, i, vv, k), v, 1e-5)
    dk = _central_diff(lambda kk: model(x0, z, i, v, kk), k, 1e-7)
    sigma_numeric = sqrt(
        (dx * sigma_dist) ** 2
        + (dz * sigma_z) ** 2
        + (di * sigma_i) ** 2
        + (dv * sigma_v) ** 2
        + (dk * sigma_k) ** 2
    )

    assert trig.sigma == pytest.approx(sigma_numeric, rel=2e-6, abs=1e-12)
    components = trig.sigma_components()
    assert sqrt(sum(value * value for value in components.values())) == pytest.approx(
        trig.sigma, abs=1e-15
    )
    assert trig.sigma_mm == pytest.approx(trig.sigma * 1e3, abs=1e-15)


def test_trig_height_observation_joins_height_network() -> None:
    trig = TrigHeight(
        "A",
        "B",
        slope_distance=900.0,
        zenith_deg=88.0,
        instrument_height=1.50,
        target_height=1.55,
        sigma_zenith_arcsec=1.0,
        sigma_slope_mm=2.0,
    )
    net = LevelingNetwork(
        [
            LevelingPoint("A", 100.0, fixed=True),
            LevelingPoint("B", 100.0 + trig.delta_h),
        ],
        [trig],
    )
    result = solve_leveling(net)
    assert result.rank == 1
    assert result.redundancy == 0
    assert result.sigma_H("B") == pytest.approx(trig.sigma, abs=1e-15)
    assert result.height("B") == pytest.approx(100.0 + trig.delta_h, abs=1e-12)
    assert result.records[0].kind == "trig_height"
    # 三角高程精度通常明显低于同级水准；报告需单独标注方法。
    assert trig.sigma_mm > 1.0


def test_height_type_is_attribute_only() -> None:
    net = LevelingNetwork(
        [
            LevelingPoint("A", 50.0, fixed=True, height_type="normal"),
            LevelingPoint("B", 51.0, height_type="ellipsoidal"),
        ],
        [HeightDifference("A", "B", 1.0, length_km=1.0, sigma_per_km_mm=1.0)],
    )
    result = solve_leveling(net)
    assert result.point_precision("A").height_type == "normal"
    assert result.point_precision("B").height_type == "ellipsoidal"
    # 不做 geoid 转换：观测高差直接进入高程参数。
    assert result.height("B") == pytest.approx(51.0, abs=1e-12)
    assert result.metadata["height_types"] == {
        "A": "normal",
        "B": "ellipsoidal",
    }


def test_observation_order_does_not_change_cx() -> None:
    net = _square_loop()
    reversed_net = LevelingNetwork(net.points, list(reversed(net.observations)))
    a = solve_leveling(net)
    b = solve_leveling(reversed_net)
    assert np.allclose(a.Cx, b.Cx, atol=1e-18)
    assert np.allclose(a.heights, b.heights, atol=1e-12)
    assert a.reliability is not None and b.reliability is not None
    assert sorted(r.r_i for r in a.records) == pytest.approx(
        sorted(r.r_i for r in b.records), abs=1e-12
    )


def test_invalid_height_observation_inputs() -> None:
    with pytest.raises(InvalidPrecisionError):
        LevelingPoint("A", 0.0, sigma_H=0.0)
    with pytest.raises(InvalidGeometryError):
        HeightDifference("A", "A", 1.0, length_km=1.0)
    with pytest.raises(InvalidPrecisionError):
        # 没有 length/sigma/n_stations 信息，无法形成随机模型。
        HeightDifference("A", "B", 1.0).sigma
    with pytest.raises(InvalidPrecisionError):
        TrigHeight("A", "B", slope_distance=100.0, horizontal_distance=100.0,
                   zenith_deg=80.0)
    with pytest.raises(InvalidPrecisionError):
        TrigHeight("A", "B", slope_distance=100.0, zenith_deg=80.0,
                   zenith_rad=radians(80.0))


def test_reliability_can_be_recomputed_from_result() -> None:
    result = solve_leveling(_square_loop())
    rel = analyze_leveling_reliability(result, alpha=0.05, power=0.80)
    assert rel.lambda0_value == pytest.approx(7.849, abs=1e-12)
    assert rel.sum_r == pytest.approx(result.redundancy, abs=1e-12)
    assert rel["A-B"].r_i == pytest.approx(0.25, abs=1e-12)
