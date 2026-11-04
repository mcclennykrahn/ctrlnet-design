"""模拟观测、粗差探测与稳健估计测试（C1）。"""

from __future__ import annotations

import numpy as np
import pytest

from ctrlnet import (
    HeightDifference,
    LevelingNetwork,
    LevelingPoint,
    analyze_reliability,
    chi2_critical,
    chi2_sf,
    data_snooping,
    estimate_network,
    global_model_test,
    huber_estimate,
    igg3_estimate,
    robust_estimate,
    section13_added,
    section13_base,
    simulate_observations,
    solve,
    t_critical,
)

SEED = 30
BLUNDER_LABEL = "CD"


def _clean():
    scenario = section13_added()
    dataset = simulate_observations(scenario.network, seed=SEED)
    return scenario, dataset


def _contaminated(k: float = 10.0):
    scenario = section13_added()
    dataset = simulate_observations(
        scenario.network,
        seed=SEED,
        blunders={BLUNDER_LABEL: k},
    )
    return scenario, dataset


def test_chi_square_and_t_distribution_helpers() -> None:
    # χ²(1) 的 95% 上尾临界值为 3.8415；χ²(4) 为 9.4877。
    assert chi2_critical(1, 0.05) == pytest.approx(3.84146, abs=1e-4)
    assert chi2_critical(4, 0.05) == pytest.approx(9.48773, abs=1e-4)
    assert chi2_sf(3.84146, 1) == pytest.approx(0.05, abs=1e-6)
    # t 双侧临界值：t_{0.975,10}=2.2281，t_{0.9995,4}=8.6103。
    assert t_critical(10, 0.05) == pytest.approx(2.22814, abs=1e-4)
    assert t_critical(4, 0.001) == pytest.approx(8.6103, abs=1e-3)


def test_simulation_and_gauss_newton_from_approximate_coordinates() -> None:
    scenario, dataset = _clean()
    assert dataset.kind == "planar"
    assert dataset.labels == [
        "AC",
        "BC",
        "AD",
        "BD",
        "CD",
        "∠C-A-B",
        "∠A-B-D",
        "∠D-C-A",
    ]
    assert dataset.outlier_indices == []
    assert dataset.row_count == 8
    # 观测值 = 真值 + 先验随机误差（固定种子可复现）。
    assert dataset.values("AC")[0] != dataset.record("AC").truth[0]
    again = simulate_observations(scenario.network, seed=SEED)
    assert np.allclose(dataset.values("CD"), again.values("CD"))

    result = estimate_network(
        dataset,
        approximate={"C": (0.35, 100.25), "D": (99.75, 100.30)},
    )
    assert result.converged
    assert result.iterations >= 2
    assert result.max_update < 1e-7
    # 高斯-牛顿应从约 0.3 m 的近似坐标收敛到毫米级真值附近。
    assert result.point_deviation_mm("C") < 5.0
    assert result.point_deviation_mm("D") < 5.0
    assert np.allclose(result.coordinate("A"), (0.0, 0.0))

    # 基准固定的点不进入参数。
    assert "A" not in result.parameter_names
    assert "B" not in result.parameter_names
    assert result.n_params == 4


def test_global_test_passes_and_no_false_detection_without_blunder() -> None:
    _, dataset = _clean()
    result = estimate_network(dataset)
    test = global_model_test(result, alpha=0.05)
    assert test.passed
    assert test.p_value > 0.05
    assert test.statistic <= test.critical_value
    assert test.sigma0_hat == pytest.approx(result.sigma0_hat)

    snooping = data_snooping(dataset)
    assert snooping.detected is False
    assert snooping.removed_labels == []
    assert snooping.final_estimate.outlier_labels == []
    assert max(snooping.final_estimate.w_by_label.values()) < 3.29
    # 无粗差时迭代稳健估计不应把任何观测判为异常。
    for method, estimator in (("huber", huber_estimate), ("igg3", igg3_estimate)):
        robust = estimator(dataset)
        assert robust.method == method
        assert robust.outlier_labels == []
        assert np.all(robust.observation_weight_factors > 0.9)


def test_ten_sigma_blunder_detected_by_w_and_igg3() -> None:
    scenario, contaminated_dataset = _contaminated(10.0)
    clean_dataset = simulate_observations(scenario.network, seed=SEED)
    clean = estimate_network(clean_dataset)
    contaminated = estimate_network(contaminated_dataset)

    # 注入的 CD 粗差应能在原始 LS 的 w 统计量中看到，并被 snooping 剔除。
    assert contaminated.w_by_label[BLUNDER_LABEL] > 3.29
    snooping = data_snooping(contaminated_dataset)
    assert snooping.detected
    assert snooping.removed_labels == [BLUNDER_LABEL]
    assert snooping.initial_estimate.w_by_label[BLUNDER_LABEL] > 3.29
    assert snooping.rounds[0].removed_label == BLUNDER_LABEL

    igg = robust_estimate(contaminated_dataset, method="igg3")
    assert BLUNDER_LABEL in igg.outlier_labels
    assert igg.observation_weight(BLUNDER_LABEL) == pytest.approx(0.0, abs=1e-9)
    assert igg.converged
    assert igg.robust_scale > 0.0

    # 稳健解应接近无粗差解，并优于被粗差污染的原始 LS。
    clean_positions = {name: clean.coordinate(name) for name in ("C", "D")}
    igg_positions = {name: igg.coordinate(name) for name in ("C", "D")}
    ls_positions = {name: contaminated.coordinate(name) for name in ("C", "D")}
    igg_gap_mm = max(
        float(np.linalg.norm(np.asarray(igg_positions[name]) - np.asarray(clean_positions[name])) * 1e3)
        for name in clean_positions
    )
    ls_gap_mm = max(
        float(np.linalg.norm(np.asarray(ls_positions[name]) - np.asarray(clean_positions[name])) * 1e3)
        for name in clean_positions
    )
    assert igg_gap_mm < 0.5
    assert igg.max_deviation_mm() < contaminated.max_deviation_mm()
    # LS 被 10σ 粗差污染，偏离无粗差解应显著大于稳健解。
    assert ls_gap_mm > igg_gap_mm

    # Huber 也应识别异常方向并把 CD 降权，坐标结果接近无粗差解。
    huber = huber_estimate(contaminated_dataset)
    assert BLUNDER_LABEL in huber.outlier_labels
    assert huber.observation_weight(BLUNDER_LABEL) < 1.0
    huber_gap_mm = max(
        float(np.linalg.norm(huber.deviation(name) - clean.deviation(name)) * 1e3)
        for name in ("C", "D")
    )
    assert huber_gap_mm < 1.0


def test_small_redundancy_is_harder_to_detect() -> None:
    # 第 13 节基准方案（冗余 3）与增补方案（冗余 4）都应满足同一规律。
    for factory in (section13_base, section13_added):
        scenario = factory()
        reliability = analyze_reliability(solve(scenario))
        r_cd = reliability[BLUNDER_LABEL].r_i
        r_angle = reliability["∠C-A-B"].r_i
        assert r_cd > 0.85
        assert r_angle < 0.10
        assert r_cd > r_angle

        # 无随机噪声时，w 检验近似服从 w_i ≈ (∇_i/σ_i)·sqrt(r_i)：
        # 角度 10σ 的期望 |w|≈2.6～2.9 < 3.29，CD 4σ 的期望 |w|≈3.79 > 3.29。
        angle_case = simulate_observations(
            scenario.network,
            seed=1,
            noise=False,
            blunders={"∠C-A-B": 10.0},
        )
        angle_ls = estimate_network(angle_case)
        angle_snoop = data_snooping(angle_case)
        assert angle_ls.w_by_label["∠C-A-B"] < 3.29
        assert angle_snoop.removed_labels == []
        assert angle_snoop.rounds[0].max_abs_statistic < 3.29

        cd_case = simulate_observations(
            scenario.network,
            seed=1,
            noise=False,
            blunders={BLUNDER_LABEL: 4.0},
        )
        cd_ls = estimate_network(cd_case)
        cd_snoop = data_snooping(cd_case)
        assert cd_ls.w_by_label[BLUNDER_LABEL] > 3.29
        assert cd_snoop.removed_labels == [BLUNDER_LABEL]

        # 内部可靠性也给出相同结论：r_i 越小，MDB/σ 越大。
        assert (
            reliability["∠C-A-B"].mdb_sigma_ratio
            > reliability[BLUNDER_LABEL].mdb_sigma_ratio
        )


def _leveling_loop() -> LevelingNetwork:
    points = [
        LevelingPoint("A", 10.0, fixed=True),
        LevelingPoint("B", 11.0),
        LevelingPoint("C", 12.0),
        LevelingPoint("D", 13.0),
    ]
    observations = [
        HeightDifference("A", "B", 1.0, length_km=1.0, sigma_per_km_mm=1.0),
        HeightDifference("B", "C", 1.0, length_km=1.0, sigma_per_km_mm=1.0),
        HeightDifference("C", "D", 1.0, length_km=1.0, sigma_per_km_mm=1.0),
        HeightDifference("D", "A", -3.0, length_km=1.0, sigma_per_km_mm=1.0),
    ]
    return LevelingNetwork(points, observations, name="leveling-loop")


def test_leveling_simulation_and_estimation() -> None:
    network = _leveling_loop()
    dataset = simulate_observations(network, seed=SEED)
    assert dataset.kind == "leveling"
    assert dataset.row_count == 4

    result = estimate_network(
        dataset,
        approximate={"B": 10.8, "C": 12.3, "D": 12.8},
    )
    assert result.converged
    assert result.parameter_names == ["B", "C", "D"]
    for name in ("B", "C", "D"):
        assert result.point_deviation_mm(name) < 5.0
    assert result.coordinate("A")[0] == pytest.approx(10.0, abs=1e-12)
    assert result.dof == 1
    assert 0.0 <= result.chi_square_p_value <= 1.0
    assert global_model_test(result).dof == 1

    # 水准网同样支持稳健估计；单环一个粗差不可唯一归因，这里只检查接口与
    # 权因子结构，不强行断言被剔除的具体测段。
    robust = robust_estimate(dataset, method="igg3")
    assert robust.method == "igg3"
    assert robust.observation_weight_factors is not None
    assert len(robust.observation_weight_factors) == 4


def test_gnss_2d_and_direction_observation_support() -> None:
    from ctrlnet import Direction, Distance, GnssBaseline2D, Network, Point

    gnss_net = Network(
        [
            Point("A", 0.0, 0.0, fixed=True),
            Point("B", 100.0, 0.0, fixed=True),
            Point("C", 50.0, 80.0),
        ],
        [
            GnssBaseline2D("A", "C", sigma_E=0.003, sigma_N=0.003),
            GnssBaseline2D("B", "C", sigma_E=0.004, sigma_N=0.004),
        ],
    )
    gnss_data = simulate_observations(gnss_net, seed=5)
    assert gnss_data.row_count == 4
    assert all(rec.n_rows == 2 for rec in gnss_data.records)
    gnss = estimate_network(gnss_data, approximate={"C": (50.2, 79.8)})
    assert gnss.converged
    assert gnss.point_deviation_mm("C") < 5.0
    assert gnss.n_rows == 4
    assert gnss.dof == 2

    direction_net = Network(
        [
            Point("A", 0.0, 0.0, fixed=True),
            Point("B", 100.0, 0.0, fixed=True),
            Point("C", 50.0, 80.0),
        ],
        [
            Direction("A", "B", sigma_arcsec=1.0),
            Direction("A", "C", sigma_arcsec=1.0),
            Distance("A", "C", a=0.002, b_ppm=2.0),
            Distance("B", "C", a=0.002, b_ppm=2.0),
        ],
    )
    direction_data = simulate_observations(direction_net, seed=6)
    direction = estimate_network(direction_data, approximate={"C": (50.2, 79.8)})
    assert direction.converged
    assert "omega_A" in direction.parameter_names
    assert direction.point_deviation_mm("C") < 5.0
