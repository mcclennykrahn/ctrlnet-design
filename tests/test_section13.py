"""第 13 节黄金算例：精度、相对精度、结构、可靠性与偏导校验。"""

from __future__ import annotations

from math import atan2, pi
from typing import Any, Dict, Iterable, Tuple

import numpy as np
import pytest

from ctrlnet import (
    Angle,
    Direction,
    Distance,
    Network,
    Point,
    analyze_precision,
    analyze_reliability,
    noncentrality,
    section13_added,
    section13_base,
    solve,
)
from ctrlnet.design import build_design, build_parameter_index

# 期望值来自 docs/redesign_plan.md §10.2.2 / §5.4.6。
BASE_POINTS = {
    "C": (0.468, 1.651, 1.716, 1.652, 0.466),
    "D": (0.468, 1.651, 1.716, 1.652, 0.466),
}
ADDED_POINTS = {
    "C": (0.464, 1.225, 1.310, 1.231, 0.448),
    "D": (0.467, 1.199, 1.287, 1.200, 0.465),
}

BASE_EDGES = {
    "AC": (1.651, 60565),
    "BC": (1.183, 119522),
    "AD": (1.183, 119522),
    "BD": (1.651, 60565),
    "CD": (0.643, 155427),
}
ADDED_EDGES = {
    "AC": (1.225, 81608),
    "BC": (0.849, 166638),
    "AD": (0.886, 159530),
    "BD": (1.199, 83407),
    "CD": (0.638, 156844),
}

BASE_R = {
    "AC": 0.3252,
    "BC": 0.6569,
    "AD": 0.6569,
    "BD": 0.3252,
    "CD": 0.8975,
    "∠C-A-B": 0.0692,
    "∠A-B-D": 0.0692,
}
ADDED_R = {
    "AC": 0.6283,
    "BC": 0.8235,
    "AD": 0.8074,
    "BD": 0.6442,
    "CD": 0.8994,
    "∠C-A-B": 0.0842,
    "∠A-B-D": 0.0722,
    "∠D-C-A": 0.0408,
}
# 距离为 mm，角度为角秒。
BASE_MDB = {"AC": 9.875, "BC": 6.982, "CD": 5.944, "∠C-A-B": 10.653}
ADDED_MDB = {"AC": 7.104, "CD": 5.938, "∠D-C-A": 13.864}
BASE_EXTERNAL = {"AC": 6.663, "BC": 3.211, "CD": 0.305, "∠C-A-B": 4.807}
ADDED_EXTERNAL = {"AC": 2.640, "CD": 0.301, "∠D-C-A": 3.180}


def _check_points(precision: Any, expected: Dict[str, Tuple[float, ...]]) -> None:
    for name, (sE, sN, mp, a, b) in expected.items():
        p = precision.points[name]
        assert p.sigma_E_mm == pytest.approx(sE, abs=1e-3)
        assert p.sigma_N_mm == pytest.approx(sN, abs=1e-3)
        assert p.mp_mm == pytest.approx(mp, abs=1e-3)
        assert p.ellipse.standard_major * 1000.0 == pytest.approx(a, abs=1e-3)
        assert p.ellipse.standard_minor * 1000.0 == pytest.approx(b, abs=1e-3)


def _check_edges(precision: Any, expected: Dict[str, Tuple[float, int]]) -> None:
    for label, (sigma_mm, denominator) in expected.items():
        edge = precision.edges[label]
        assert edge.sigma_s_mm == pytest.approx(sigma_mm, abs=1e-3)
        # 相对精度分母必须与文档给定的整数完全一致。
        assert edge.ratio_denominator == denominator
        assert round(edge.length / edge.sigma_s) == denominator


def _check_reliability(
    reliability: Any,
    expected_r: Dict[str, float],
    expected_mdb: Dict[str, float],
    expected_external: Dict[str, float],
) -> None:
    by_label = reliability.by_label
    for label, value in expected_r.items():
        assert by_label[label].r_i == pytest.approx(value, abs=1e-3)
    for label, value in expected_mdb.items():
        row = by_label[label]
        if row.kind in ("distance", "gnss"):
            assert row.mdb * 1000.0 == pytest.approx(value, rel=1e-3)
        else:
            assert row.mdb_display == pytest.approx(value, rel=1e-3)
    for label, value in expected_external.items():
        assert by_label[label].external_max_mm == pytest.approx(value, abs=0.002)


@pytest.mark.parametrize(
    "scenario_factory, expected_points",
    [(section13_base, BASE_POINTS), (section13_added, ADDED_POINTS)],
)
def test_point_precision(scenario_factory: Any, expected_points: Dict[str, Tuple[float, ...]]) -> None:
    result = solve(scenario_factory())
    precision = analyze_precision(result)
    _check_points(precision, expected_points)


@pytest.mark.parametrize(
    "scenario_factory, expected_edges",
    [(section13_base, BASE_EDGES), (section13_added, ADDED_EDGES)],
)
def test_edge_precision(scenario_factory: Any, expected_edges: Dict[str, Tuple[float, int]]) -> None:
    result = solve(scenario_factory())
    precision = analyze_precision(result)
    _check_edges(precision, expected_edges)


@pytest.mark.parametrize(
    "scenario_factory, redundancy",
    [(section13_base, 3), (section13_added, 4)],
)
def test_structure(scenario_factory: Any, redundancy: int) -> None:
    result = solve(scenario_factory())
    reliability = analyze_reliability(result)

    assert result.rank == 4
    assert result.n_params == 4
    assert result.redundancy == redundancy
    assert result.n_rows - result.rank == redundancy
    assert reliability.expected_redundancy == redundancy
    assert reliability.lambda0_value == pytest.approx(7.849, abs=1e-12)

    # Cx 对称、半正定，固定点协方差为零。
    assert result.Cx.shape == (4, 4)
    assert float(np.max(np.abs(result.Cx - result.Cx.T))) < 1e-12
    assert float(np.linalg.eigvalsh(result.Cx).min()) >= -1e-12
    assert np.allclose(result.point_covariance("A"), 0.0)
    assert np.allclose(result.point_covariance("B"), 0.0)

    # trace(R) = n - rank，即冗余数；按观测求和同样成立。
    assert float(np.trace(reliability.R)) == pytest.approx(redundancy, abs=1e-9)
    assert reliability.sum_r == pytest.approx(redundancy, abs=1e-9)
    assert float(np.trace(reliability.Qv @ np.linalg.inv(result.Ql))) == pytest.approx(
        redundancy, abs=1e-9
    )


@pytest.mark.parametrize(
    "scenario_factory, expected_r, expected_mdb, expected_external",
    [
        (section13_base, BASE_R, BASE_MDB, BASE_EXTERNAL),
        (section13_added, ADDED_R, ADDED_MDB, ADDED_EXTERNAL),
    ],
)
def test_reliability(
    scenario_factory: Any,
    expected_r: Dict[str, float],
    expected_mdb: Dict[str, float],
    expected_external: Dict[str, float],
) -> None:
    result = solve(scenario_factory())
    reliability = analyze_reliability(result, alpha=0.05, power=0.80)
    _check_reliability(reliability, expected_r, expected_mdb, expected_external)
    # λ0 = (z_{0.975} + z_{0.80})² ≈ 7.849。
    assert noncentrality(0.05, 0.80) == pytest.approx(7.849, abs=1e-3)


def _azimuth(network: Network, station: str, target: str) -> float:
    p, q = network.point(station), network.point(target)
    return atan2(q.E - p.E, q.N - p.N)


def _predict(network: Network, obs: Any) -> float:
    if isinstance(obs, Distance):
        p, q = network.point(obs.frm), network.point(obs.to)
        return float(np.hypot(q.E - p.E, q.N - p.N))
    if isinstance(obs, Direction):
        return _azimuth(network, obs.station, obs.target)
    if isinstance(obs, Angle):
        beta = _azimuth(network, obs.station, obs.foresight) - _azimuth(
            network, obs.station, obs.backsight
        )
        return (beta + pi) % (2.0 * pi) - pi
    raise TypeError(obs)


def _numeric_row(network: Network, index: Any, obs: Any, h: float = 1e-6) -> np.ndarray:
    """对距离/方向/角度预测值做中心差分，返回对坐标参数的数值偏导。"""
    row = np.zeros(index.size, dtype=float)
    for name, (ie, inn) in index.point_columns.items():
        point = network.point(name)
        original = (point.E, point.N)
        for column, component in ((ie, 0), (inn, 1)):
            plus = list(original)
            minus = list(original)
            plus[component] += h
            minus[component] -= h
            point.E, point.N = plus
            f_plus = _predict(network, obs)
            point.E, point.N = minus
            f_minus = _predict(network, obs)
            point.E, point.N = original
            delta = f_plus - f_minus
            if isinstance(obs, (Direction, Angle)):
                delta = (delta + pi) % (2.0 * pi) - pi
            row[column] = delta / (2.0 * h)
    return row


def test_analytic_derivatives_vs_central_difference() -> None:
    network = Network(
        [
            Point("A", 0.0, 0.0, fixed=True),
            Point("B", 100.0, 0.0),
            Point("C", 20.0, 70.0),
            Point("D", 90.0, 80.0),
        ],
        [
            Distance("A", "C"),
            Direction("B", "C"),
            Angle("C", "A", "B"),
        ],
    )
    index = build_parameter_index(network)
    design = build_design(network, index)
    assert index.names[:6] == ["E_B", "N_B", "E_C", "N_C", "E_D", "N_D"]
    assert index.orientation_order == ["B"]

    for row, obs in enumerate(network.observations):
        analytic = design.A[row].copy()
        if isinstance(obs, Direction):
            # 定向未知数不属于坐标偏导，差分只校验坐标列。
            analytic[index.orientation_columns[obs.station]] = 0.0
        numeric = _numeric_row(network, index, obs)
        np.testing.assert_allclose(
            analytic,
            numeric,
            rtol=1e-6,
            atol=1e-9,
            err_msg=f"{obs.label} 的解析偏导与中心差分不一致",
        )


def _reordered_network(reverse: bool = True) -> Network:
    base = section13_base().network
    observations = list(reversed(base.observations)) if reverse else list(base.observations)
    return Network(list(base.points), observations, name="scrambled")


def test_observation_order_does_not_change_results() -> None:
    base = section13_base()
    scrambled = _reordered_network(reverse=True)
    r1 = solve(base)
    r2 = solve(scrambled)

    np.testing.assert_allclose(r1.Cx, r2.Cx, rtol=1e-12, atol=1e-18)
    assert r1.rank == r2.rank
    assert r1.redundancy == r2.redundancy

    p1 = analyze_precision(r1)
    p2 = analyze_precision(r2)
    for name in base.network.point_names:
        assert p2.points[name].mp == pytest.approx(p1.points[name].mp, rel=1e-12)
        assert p2.points[name].sigma_E == pytest.approx(
            p1.points[name].sigma_E, rel=1e-12
        )
        assert p2.points[name].sigma_N == pytest.approx(
            p1.points[name].sigma_N, rel=1e-12
        )

    rel1 = analyze_reliability(r1).by_label
    rel2 = analyze_reliability(r2).by_label
    for label in rel1:
        assert rel2[label].r_i == pytest.approx(rel1[label].r_i, abs=1e-12)
        assert rel2[label].mdb == pytest.approx(rel1[label].mdb, rel=1e-12)


def test_parameter_order_permutation() -> None:
    base = section13_base()
    r1 = solve(base)
    r2 = solve(base, parameter_order=["D", "C"])
    assert r2.parameter_order == ["D", "C"]
    for name in ("C", "D"):
        np.testing.assert_allclose(
            r1.point_covariance(name),
            r2.point_covariance(name),
            rtol=1e-12,
            atol=1e-18,
        )
