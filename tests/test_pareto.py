"""Pareto 非支配性、单调性及独立子集穷举验证。"""
from itertools import combinations

import pytest

from ctrlnet import (Angle, Candidate, CostModel, Distance, exhaustive_optimize,
                     pareto_frontier, section13_base)


def candidates():
    return [Candidate(Angle("A", "C", "D"), 1.3),
            Candidate(Angle("B", "D", "C"), 2.1),
            Candidate(Angle("D", "C", "A"), 0.7),
            Candidate(Distance("A", "B"), 0.5)]


@pytest.mark.parametrize("criterion", ["A", "D", "E", "max_mp"])
@pytest.mark.parametrize("station_cost", [0.0, 1.2])
def test_complete_frontier_matches_subsets(criterion, station_cost):
    base, cands = section13_base(), candidates()
    model = CostModel(default_station_cost=station_cost)
    front = pareto_frontier(base, cands, criterion, cost_model=model)
    assert front.complete
    # 不以预算最优作为参考：独立评价每个子集，并直接判断支配关系。
    all_points = []
    for size in range(len(cands) + 1):
        for subset in combinations(range(len(cands)), size):
            selected = [cands[i] for i in subset]
            r = exhaustive_optimize(base, selected, criterion=criterion,
                                    gap_tol=0.0)
            all_points.append((model.total_cost(cands, subset), r.objective_value))
    expected = sorted(set(p for p in all_points if not any(
        q[0] <= p[0] and q[1] <= p[1] + 1e-12 * abs(p[1])
        and (q[0] < p[0] or q[1] < p[1] - 1e-12 * abs(p[1]))
        for q in all_points)))
    actual = [(r.spent, r.objective_value) for r in front.points]
    assert len(actual) == len(expected)
    for a, e in zip(actual, expected):
        assert a == pytest.approx(e, rel=1e-12, abs=1e-15)
    for a, b in zip(front.points, front.points[1:]):
        assert a.spent < b.spent
        assert a.objective_value > b.objective_value
    for p in front.points:
        assert not any(q.spent <= p.spent and q.objective_value <= p.objective_value
                       and (q.spent < p.spent or q.objective_value < p.objective_value)
                       for q in front.points)


def test_sampled_empty_and_validation():
    base = section13_base()
    front = pareto_frontier(base, candidates(), budgets=[4, 0, 2, 2])
    assert not front.complete
    assert front.budgets == [0, 2, 4]
    assert pareto_frontier(base, []).points[0].spent == 0
    for budgets in ([], [-1], [float("nan")], [float("inf")]):
        with pytest.raises(ValueError):
            pareto_frontier(base, [], budgets=budgets)
    with pytest.raises(ValueError):
        pareto_frontier(base, candidates(), max_candidates=2)
