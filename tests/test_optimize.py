"""贪心观测增补优化测试。"""

from __future__ import annotations

import pytest

from ctrlnet import Angle, Distance, greedy_optimize, section13_base


def _candidates() -> list[object]:
    return [
        Angle("A", "C", "D"),
        Angle("B", "D", "C"),
        Angle("D", "C", "A"),
        Angle("C", "B", "D"),
        Angle("D", "A", "C"),
        # A、B 均为固定点，这条距离不提供任何关于待定点的信息。
        Distance("A", "B"),
    ]


def test_greedy_reduces_max_mp_and_is_monotone() -> None:
    base = section13_base()
    result = greedy_optimize(base, _candidates(), objective="max_mp")

    assert result.initial_metrics.objective == pytest.approx(0.0017160837620434295)
    assert result.steps, "贪心优化应至少选择一个有收益的观测"
    assert result.final_metrics.objective < result.initial_metrics.objective
    assert result.final_metrics.objective <= result.initial_metrics.objective
    assert result.spent == pytest.approx(float(len(result.steps)))
    assert len(result.selected) == len(result.steps)

    previous = result.initial_metrics.objective
    for step in result.steps:
        assert step.gain > 0.0
        assert step.objective <= previous + 1e-15
        assert step.max_mp <= previous + 1e-15
        previous = step.objective

    # 每一步新增的观测必须来自候选集，且固定点之间的 AB 距离不应被选中。
    labels = {c.observation.label for c in result.candidates}
    assert all(step.added_label in labels for step in result.steps)
    assert "AB" not in result.selected_labels


def test_greedy_respects_budget() -> None:
    base = section13_base()
    result = greedy_optimize(base, _candidates(), objective="max_mp", budget=2.0)
    assert result.spent <= 2.0 + 1e-12
    assert len(result.selected) <= 2
    assert result.final_metrics.objective <= result.initial_metrics.objective
    assert result.final_metrics.objective < result.initial_metrics.objective


def test_greedy_stops_at_target() -> None:
    base = section13_base()
    target = 0.0011  # 1.100 mm；第 1 步后仍高于阈值，第 2 步后达标。
    result = greedy_optimize(
        base, _candidates(), objective="max_mp", target=target, max_steps=10
    )
    assert result.reached
    assert result.final_metrics.objective <= target + 1e-15
    # 达到阈值后不应继续加入观测。
    assert result.steps
    for step in result.steps[:-1]:
        assert step.objective > target


def test_greedy_trace_objective_monotone() -> None:
    base = section13_base()
    result = greedy_optimize(base, _candidates(), objective="trace")
    previous = result.initial_metrics.objective
    for step in result.steps:
        assert step.objective <= previous + 1e-18
        previous = step.objective
    assert result.final_metrics.objective <= result.initial_metrics.objective
