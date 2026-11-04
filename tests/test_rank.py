"""基准、秩亏、退化与非法精度的诊断测试。"""

from __future__ import annotations

import numpy as np
import pytest

from ctrlnet import (
    Angle,
    Distance,
    FreeDatum,
    GnssBaseline2D,
    MinimalDatum,
    Network,
    Point,
    WeightedDatum,
    analyze_reliability,
    section13_base,
    solve,
)
from ctrlnet.exceptions import (
    InvalidGeometryError,
    InvalidPrecisionError,
    RankDeficientError,
)


def _base_network() -> Network:
    return section13_base().network


def test_missing_one_fixed_point_raises_rank_error() -> None:
    base = _base_network()
    # 只保留 B 固定；A 变成待定点。距离+角度不足以定义旋转，秩亏 1。
    points = [
        Point("A", 0.0, 0.0, fixed=False),
        Point("B", 100.0, 0.0, fixed=True),
        Point("C", 0.0, 100.0),
        Point("D", 100.0, 100.0),
    ]
    network = Network(points, list(base.observations))
    with pytest.raises(RankDeficientError) as caught:
        solve(network)
    exc = caught.value
    assert exc.rank == 5
    assert exc.n_params == 6
    assert exc.null_space is not None and exc.null_space.shape[1] == 1
    assert "秩亏" in str(exc) and "零空间" in str(exc)
    assert exc.diagnostics
    # 诊断应能定位到参数/点，而不是只报“矩阵奇异”。
    assert any(name in str(exc) for name in ("A", "C", "D", "旋转", "基准"))


def test_unknown_point_with_single_observation_raises() -> None:
    base = _base_network()
    points = [Point(p.name, p.E, p.N, fixed=p.fixed) for p in base.points]
    points.append(Point("E", 10.0, 10.0))
    observations = list(base.observations) + [Distance("A", "E")]
    with pytest.raises(RankDeficientError) as caught:
        solve(Network(points, observations))
    exc = caught.value
    assert exc.rank == 5
    assert exc.n_params == 6
    assert "E" in str(exc)
    assert "观测不足" in str(exc) or "局部" in str(exc)


@pytest.mark.parametrize("datum", [MinimalDatum(), FreeDatum(origin="A")])
def test_minimal_free_network_solves_with_rank_handling(datum: object) -> None:
    base = _base_network()
    # 全部点自由：距离定尺度，角度定形状；2 平移 + 1 旋转 = 3 个基准缺陷。
    points = [Point(p.name, p.E, p.N, fixed=False) for p in base.points]
    network = Network(points, list(base.observations))
    result = solve(network, datum=datum)

    assert result.rank == 5
    assert result.n_params == 8
    assert result.redundancy == 2
    assert result.null_space.shape == (8, 3)
    assert result.datum_transform is not None
    assert result.datum_transform.shape == (8, 8)
    assert result.datum_kind in ("minimal", "free")

    assert float(np.max(np.abs(result.Cx - result.Cx.T))) < 1e-12
    assert float(np.linalg.eigvalsh(result.Cx).min()) >= -1e-10
    assert np.linalg.matrix_rank(result.Cx, tol=1e-12) == 5

    reliability = analyze_reliability(result)
    assert reliability.sum_r == pytest.approx(2.0, abs=1e-9)
    assert reliability.trace_r == pytest.approx(2.0, abs=1e-9)


def test_weighted_datum_keeps_parameters_and_constraints() -> None:
    base = _base_network()
    points = [Point(p.name, p.E, p.N, fixed=p.fixed) for p in base.points]
    for point in points:
        if not point.fixed:
            point.sigma_E = 0.0005
            point.sigma_N = 0.0005
    result = solve(Network(points, list(base.observations)), datum=WeightedDatum())
    assert result.rank == 4
    assert result.n_params == 4
    assert result.n_rows == 11  # 7 条观测 + 4 条坐标伪观测
    assert result.metadata["datum_kind"] == "weighted"
    assert np.allclose(result.point_covariance("A"), 0.0)
    # 待定点仍保留参数，且先验约束使其协方差有限、正定。
    assert float(np.linalg.eigvalsh(result.point_covariance("C")).min()) > 0.0


def test_zero_or_negative_sigma_raises_invalid_precision() -> None:
    with pytest.raises(InvalidPrecisionError):
        solve(
            Network(
                [Point("A", 0.0, 0.0, fixed=True), Point("B", 1.0, 0.0)],
                [Distance("A", "B", a=0.0, b_ppm=0.0)],
            )
        )
    with pytest.raises(InvalidPrecisionError):
        solve(
            Network(
                [Point("A", 0.0, 0.0, fixed=True), Point("B", 1.0, 0.0)],
                [Distance("A", "B", a=-0.001)],
            )
        )
    with pytest.raises(InvalidPrecisionError):
        solve(
            Network(
                [
                    Point("A", 0.0, 0.0, fixed=True),
                    Point("B", 10.0, 0.0, fixed=True),
                    Point("C", 0.0, 10.0),
                ],
                [Angle("B", "A", "C", sigma_arcsec=0.0)],
            )
        )


def test_nan_coordinate_raises_invalid_precision() -> None:
    with pytest.raises(InvalidPrecisionError):
        solve(
            Network(
                [Point("A", 0.0, 0.0, fixed=True), Point("B", float("nan"), 0.0)],
                [Distance("A", "B")],
            )
        )


def test_coincident_points_raise_invalid_geometry() -> None:
    with pytest.raises(InvalidGeometryError):
        solve(
            Network(
                [Point("A", 0.0, 0.0, fixed=True), Point("B", 0.0, 0.0)],
                [Distance("A", "B")],
            )
        )
    # 角度后视与前视重合。
    with pytest.raises(InvalidGeometryError):
        solve(
            Network(
                [
                    Point("A", 0.0, 0.0, fixed=True),
                    Point("B", 10.0, 0.0, fixed=True),
                    Point("C", 0.0, 10.0),
                ],
                [Angle("B", "A", "B")],
            )
        )


def test_invalid_gnss_correlation_raises() -> None:
    with pytest.raises(InvalidPrecisionError):
        solve(
            Network(
                [Point("A", 0.0, 0.0, fixed=True), Point("B", 10.0, 0.0)],
                [GnssBaseline2D("A", "B", 0.002, 0.002, correlation=1.0)],
            )
        )
