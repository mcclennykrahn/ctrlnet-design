"""C2 精确优化器测试：分支定界/穷举、预算、设站成本、五种准则与 MILP。"""

from __future__ import annotations

from math import isfinite

import pytest

from ctrlnet import (
    CRITERIA,
    Angle,
    Candidate,
    CostModel,
    Direction,
    Distance,
    FixedDatum,
    Network,
    Point,
    Scenario,
    exact_optimize,
    exhaustive_optimize,
    greedy_optimize,
    milp_available,
    milp_optimize,
    section13_base,
)


def _observations() -> list[object]:
    return [
        Angle("A", "C", "D"),
        Angle("B", "D", "C"),
        Angle("D", "C", "A"),
        Angle("C", "B", "D"),
        Angle("D", "A", "C"),
        # A、B 均为固定点，AB 距离不提供待定点信息。
        Distance("A", "B"),
    ]


def _same_station_candidates() -> list[Candidate]:
    return [
        Candidate(Angle("D", "C", "A"), 1.0, stations=("C",)),
        Candidate(Angle("B", "C", "D"), 1.0, stations=("C",)),
        Candidate(Angle("A", "C", "B"), 1.0, stations=("C",)),
        Candidate(Angle("B", "C", "A"), 1.0, stations=("C",)),
    ]


@pytest.mark.parametrize("criterion", CRITERIA)
def test_branch_bound_matches_exhaustive(criterion: str) -> None:
    """小例子中分支定界与穷举必须得到同一全局最优目标值。"""
    base = section13_base()
    candidates = _observations()

    bb = exact_optimize(base, candidates, criterion=criterion, budget=3.0)
    ex = exhaustive_optimize(base, candidates, criterion=criterion, budget=3.0)

    assert bb.exact
    assert ex.exact
    assert bb.spent <= 3.0 + 1e-12
    assert ex.spent <= 3.0 + 1e-12
    assert bb.objective_value == pytest.approx(
        ex.objective_value, rel=1e-12, abs=1e-15
    )
    assert bb.final_metrics.objective == pytest.approx(bb.objective_value)


@pytest.mark.parametrize("criterion", CRITERIA)
def test_exact_is_not_worse_than_greedy(criterion: str) -> None:
    base = section13_base()
    candidates = _observations()
    budget = 3.0

    greedy = greedy_optimize(
        base, candidates, criterion=criterion, budget=budget
    )
    exact = exact_optimize(
        base, candidates, criterion=criterion, budget=budget
    )
    tolerance = 1e-12 * max(1.0, abs(greedy.final_metrics.objective))
    assert exact.objective_value <= greedy.final_metrics.objective + tolerance
    assert exact.exact
    assert exact.spent <= budget + 1e-12


def test_exact_returns_a_real_adjustment_result() -> None:
    base = section13_base()
    result = exact_optimize(
        base, _observations(), criterion="max_mp", budget=3.0
    )
    assert result.result.n_params == 4
    assert result.final_metrics.max_mp == pytest.approx(result.objective_value)
    assert result.selected_labels == [
        c.observation.label for c in result.selected
    ]
    assert result.to_text()


def test_budget_is_monotone_for_exact_objective() -> None:
    base = section13_base()
    candidates = _observations()
    previous = float("inf")
    for budget in (0.0, 1.5, 3.0, 5.0):
        result = exact_optimize(
            base, candidates, criterion="max_mp", budget=budget
        )
        assert result.spent <= budget + 1e-12
        assert result.objective_value <= previous + 1e-15
        previous = result.objective_value


def test_station_cost_counts_only_first_use() -> None:
    candidates = _same_station_candidates()
    model = CostModel({"C": 5.0})

    # 两条同站观测：观测 1+1，设站 5，共 7；若每条都收设站费则为 12。
    assert model.total_cost(candidates, [0, 1]) == pytest.approx(7.0)
    assert model.total_cost(candidates, [0, 2, 3]) == pytest.approx(8.0)
    assert model.marginal_cost(candidates[0], set()) == pytest.approx(6.0)
    assert model.marginal_cost(candidates[1], {"C"}) == pytest.approx(1.0)

    base = section13_base()
    result = exact_optimize(
        base,
        candidates,
        criterion="max_mp",
        budget=7.0,
        cost_model=model,
    )
    brute = exhaustive_optimize(
        base,
        candidates,
        criterion="max_mp",
        budget=7.0,
        cost_model=model,
    )
    assert result.spent == pytest.approx(7.0)
    assert len(result.selected) == 2
    assert {s for c in result.selected for s in c.station_names} == {"C"}
    assert result.objective_value == pytest.approx(brute.objective_value)


def test_station_cost_can_make_budget_infeasible() -> None:
    base = section13_base()
    candidates = _same_station_candidates()
    result = exact_optimize(
        base,
        candidates,
        criterion="max_mp",
        budget=5.5,
        station_costs={"C": 5.0},
    )
    assert result.selected == []
    assert result.spent == 0.0
    assert result.exact


def test_station_cost_spans_multiple_stations() -> None:
    base = section13_base()
    candidates = [
        Candidate(Angle("D", "C", "A"), 1.0, stations=("C",)),
        Candidate(Angle("C", "D", "A"), 1.0, stations=("D",)),
    ]
    model = CostModel({"C": 5.0, "D": 5.0})
    assert model.total_cost(candidates, [0, 1]) == pytest.approx(12.0)
    result = exact_optimize(
        base,
        candidates,
        criterion="max_mp",
        budget=11.0,
        cost_model=model,
    )
    assert result.spent <= 11.0 + 1e-12
    assert len(result.selected) == 1


def test_all_criteria_run_and_are_finite() -> None:
    base = section13_base()
    candidates = _observations()
    for criterion in CRITERIA:
        greedy = greedy_optimize(
            base, candidates, criterion=criterion, budget=3.0
        )
        local = greedy_optimize(
            base,
            candidates,
            criterion=criterion,
            budget=3.0,
            local_search=True,
        )
        exact = exact_optimize(
            base, candidates, criterion=criterion, budget=3.0
        )
        for result in (greedy, local, exact):
            assert isfinite(result.final_metrics.objective)
            assert result.spent <= 3.0 + 1e-12
        assert exact.objective_value <= local.objective_value + 1e-12


def test_direction_orientation_parameters() -> None:
    """候选方向引入新定向未知数时，精确解仍与穷举一致。"""
    network = Network(
        [
            Point("A", 0.0, 0.0, fixed=True),
            Point("B", 100.0, 0.0, fixed=True),
            Point("C", 50.0, 80.0),
        ],
        [
            Direction("A", "B"),
            Direction("A", "C"),
            Distance("B", "C"),
        ],
    )
    scenario = Scenario("方向网", network, datum=FixedDatum())
    candidates = [
        Candidate(Direction("B", "A"), 1.0, stations=("B",)),
        Candidate(Direction("B", "C"), 1.0, stations=("B",)),
        Candidate(Direction("C", "A"), 1.0, stations=("C",)),
        Candidate(Distance("A", "C"), 1.0),
        Candidate(Angle("A", "C", "B"), 1.0),
    ]
    for criterion in ("A", "D", "E", "max_mp", "worst_rel"):
        bb = exact_optimize(
            scenario, candidates, criterion=criterion, budget=3.0
        )
        ex = exhaustive_optimize(
            scenario, candidates, criterion=criterion, budget=3.0
        )
        assert bb.objective_value == pytest.approx(
            ex.objective_value, rel=1e-11, abs=1e-15
        )


@pytest.mark.parametrize("criterion", CRITERIA)
def test_milp_proxy_runs_and_respects_budget(criterion: str) -> None:
    pytest.importorskip("scipy")
    if not milp_available():
        pytest.skip("SciPy milp 不可用")
    base = section13_base()
    candidates = _same_station_candidates()
    result = milp_optimize(
        base,
        candidates,
        criterion=criterion,
        budget=7.0,
        cost_model=CostModel({"C": 5.0}),
        max_local_iterations=3,
    )
    assert result.exact is False
    assert result.method.startswith("milp")
    assert result.spent <= 7.0 + 1e-12
    assert isfinite(result.objective_value)
    assert result.objective_value <= result.initial_metrics.objective + 1e-12
    # 线性代理只提供近似，不要求与精确解相同，但必须用真实目标复算。
    assert result.final_metrics.objective == pytest.approx(result.objective_value)


def test_exact_rejects_too_many_candidates() -> None:
    base = section13_base()
    candidates = _observations()
    with pytest.raises(ValueError, match="超过上限"):
        exact_optimize(base, candidates, criterion="A", max_candidates=3)
