"""贪心观测增补优化与简单 1 换 1 局部搜索。"""

from __future__ import annotations

from dataclasses import dataclass, field
from math import isfinite
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

import numpy as np

from .adjustment import AdjustmentResult, solve
from .model import Network, Observation, Scenario
from .precision import PrecisionResult, analyze_precision


@dataclass
class Candidate:
    observation: Observation
    cost: float = 1.0

    def __post_init__(self) -> None:
        self.cost = float(self.cost)
        if not isfinite(self.cost) or self.cost <= 0.0:
            raise ValueError(f"候选观测成本必须为正的有限值，收到 {self.cost!r}")


@dataclass
class ObjectiveMetrics:
    objective: float
    max_mp: float
    trace_Cx: float
    worst_relative: float
    weakest_edge: Optional[str]
    result: AdjustmentResult
    precision: PrecisionResult


@dataclass
class OptimizationStep:
    step: int
    added: Observation
    added_label: str
    cost: float
    total_cost: float
    objective: float
    gain: float
    max_mp: float
    trace_Cx: float
    worst_relative: float
    weakest_edge: Optional[str]
    selected_labels: List[str]
    explanation: str = ""


@dataclass
class SwapStep:
    iteration: int
    removed_label: str
    added_label: str
    cost_delta: float
    total_cost: float
    objective: float
    gain: float


@dataclass
class OptimizationResult:
    objective: str
    budget: Optional[float]
    target: Optional[float]
    steps: List[OptimizationStep]
    swaps: List[SwapStep]
    selected: List[Candidate]
    spent: float
    initial_metrics: ObjectiveMetrics
    final_metrics: ObjectiveMetrics
    reached: bool
    network: Network
    result: AdjustmentResult
    candidates: List[Candidate]

    @property
    def objective_value(self) -> float:
        return self.final_metrics.objective

    @property
    def selected_labels(self) -> List[str]:
        return [c.observation.label for c in self.selected]

    @property
    def selected_observations(self) -> List[Observation]:
        return [c.observation for c in self.selected]

    def to_text(self) -> str:
        lines = [
            f"优化目标：{self.objective}；预算：{self.budget}；目标阈值：{self.target}",
            f"初始目标：{self.initial_metrics.objective:.6g}；"
            f"最终目标：{self.final_metrics.objective:.6g}；"
            f"成本：{self.spent:.6g}；达标：{'是' if self.reached else '否'}",
            "",
            "| 步 | 新增观测 | 成本 | 累计成本 | 目标值 | 收益 | 最大 mp/mm | 最弱边 |",
            "|---:|---|---:|---:|---:|---:|---:|---|",
        ]
        for s in self.steps:
            lines.append(
                f"| {s.step} | {s.added_label} | {s.cost:g} | {s.total_cost:g} | "
                f"{s.objective:.6g} | {s.gain:.6g} | {s.max_mp * 1000.0:.3f} | "
                f"{s.weakest_edge or '—'} |"
            )
        if self.swaps:
            lines.append("")
            lines.append("| 局部交换 | 移除 | 新增 | 成本变化 | 目标值 | 收益 |")
            lines.append("|---:|---|---|---:|---:|---:|")
            for s in self.swaps:
                lines.append(
                    f"| {s.iteration} | {s.removed_label} | {s.added_label} | "
                    f"{s.cost_delta:+g} | {s.objective:.6g} | {s.gain:.6g} |"
                )
        return "\n".join(lines)


_OBJECTIVE_ALIASES = {
    "max_mp": "max_mp",
    "min_max_mp": "max_mp",
    "mp": "max_mp",
    "最大点位中误差": "max_mp",
    "trace": "trace",
    "trace_cx": "trace",
    "min_trace": "trace",
    "a_opt": "trace",
    "a-optimal": "trace",
    "relative": "relative",
    "weakest_edge": "relative",
    "max_relative": "relative",
    "最弱边": "relative",
}


def _normalize_objective(objective: str) -> str:
    key = str(objective).strip().lower()
    if key not in _OBJECTIVE_ALIASES:
        raise ValueError(
            f"未知优化目标 {objective!r}；可选 max_mp、trace、relative"
        )
    return _OBJECTIVE_ALIASES[key]


def _parse_candidates(
    candidates: Sequence[Any], costs: Optional[Mapping[Any, float]] = None
) -> List[Candidate]:
    out: List[Candidate] = []
    for i, item in enumerate(candidates):
        if isinstance(item, Candidate):
            cand = item
        elif isinstance(item, tuple) and len(item) == 2 and isinstance(item[0], Observation):
            cand = Candidate(item[0], item[1])
        elif isinstance(item, Observation):
            cost = 1.0
            if costs is not None:
                if isinstance(costs, Mapping):
                    if i in costs:
                        cost = costs[i]
                    elif item.label in costs:
                        cost = costs[item.label]
                else:
                    cost = costs[i]
            cand = Candidate(item, cost)
        else:
            raise TypeError(f"无法解析候选观测：{item!r}")
        out.append(cand)
    return out


def _evaluate(
    network: Network, datum: Any, objective: str, parameter_order: Optional[Sequence[Any]]
) -> ObjectiveMetrics:
    result = solve(network, datum=datum, parameter_order=parameter_order)
    precision = analyze_precision(result)
    unknown = [p for p in network.points if not p.fixed]
    max_mp = max((precision.points[p.name].mp for p in unknown), default=0.0)
    trace = float(np.trace(result.Cx)) if result.n_params else 0.0
    worst = precision.worst_relative
    if objective == "max_mp":
        value = max_mp
    elif objective == "trace":
        value = trace
    else:
        value = worst
    return ObjectiveMetrics(
        objective=float(value),
        max_mp=float(max_mp),
        trace_Cx=trace,
        worst_relative=float(worst),
        weakest_edge=precision.weakest_edge,
        result=result,
        precision=precision,
    )


def _network_with(base: Network, selected: Sequence[Candidate]) -> Network:
    obs = list(base.observations) + [c.observation for c in selected]
    return Network(list(base.points), obs, name=base.name)


def optimize(
    base: Any,
    candidates: Sequence[Any],
    objective: str = "max_mp",
    budget: Optional[float] = None,
    target: Optional[float] = None,
    costs: Optional[Mapping[Any, float]] = None,
    local_search: bool = False,
    max_steps: Optional[int] = None,
    max_local_iterations: int = 20,
    min_gain: float = 1e-15,
    datum: Any = None,
    parameter_order: Optional[Sequence[Any]] = None,
) -> OptimizationResult:
    """贪心加入收益/成本最大的候选观测。

    objective:
        ``max_mp`` 最小化最大点位中误差；``trace`` 最小化 trace(Cx)（A 最优）；
        ``relative`` 最小化最弱边 σs/s（即最大化最弱边相对精度）。
    budget:
        新增候选观测的成本上限（默认无上限）。
    target:
        目标阈值（内部 SI 单位：mp 为米，trace 为米²，relative 为无量纲比值）。
    local_search:
        贪心结束后做 1 换 1 交换，只接受目标严格改善且预算可行的交换。
    """
    if isinstance(base, Scenario):
        net = base.network
        if datum is None:
            datum = base.datum
    elif isinstance(base, Network):
        net = base
    else:
        raise TypeError("base 必须是 Scenario 或 Network")

    obj = _normalize_objective(objective)
    cands = _parse_candidates(candidates, costs)
    if budget is not None:
        budget = float(budget)
        if not isfinite(budget) or budget < 0.0:
            raise ValueError("budget 必须为非负有限值")
    if target is not None:
        target = float(target)
        if not isfinite(target):
            raise ValueError("target 必须为有限值")
    if max_steps is None:
        max_steps = len(cands)
    max_steps = int(max_steps)

    initial = _evaluate(net, datum, obj, parameter_order)
    current = initial
    selected: List[Candidate] = []
    selected_idx: set = set()
    selected_order: List[int] = []
    spent = 0.0
    steps: List[OptimizationStep] = []
    reached = target is not None and current.objective <= target

    while len(steps) < max_steps and not reached:
        best = None  # (utility, gain, idx, metrics)
        for i, cand in enumerate(cands):
            if i in selected_idx:
                continue
            if budget is not None and spent + cand.cost > budget + 1e-12:
                continue
            trial_net = _network_with(net, selected + [cand])
            try:
                metrics = _evaluate(trial_net, datum, obj, parameter_order)
            except Exception:
                continue
            gain = current.objective - metrics.objective
            if gain <= min_gain:
                continue
            utility = gain / cand.cost
            key = (utility, gain, -cand.cost)
            if best is None or key > best[0]:
                best = (key, i, metrics, gain)

        if best is None:
            break
        _key, idx, metrics, gain = best
        cand = cands[idx]
        selected_idx.add(idx)
        selected.append(cand)
        selected_order.append(idx)
        spent += cand.cost
        current = metrics
        steps.append(
            OptimizationStep(
                step=len(steps) + 1,
                added=cand.observation,
                added_label=cand.observation.label,
                cost=cand.cost,
                total_cost=spent,
                objective=current.objective,
                gain=gain,
                max_mp=current.max_mp,
                trace_Cx=current.trace_Cx,
                worst_relative=current.worst_relative,
                weakest_edge=current.weakest_edge,
                selected_labels=[c.observation.label for c in selected],
                explanation=(
                    f"边际收益 {gain:.6g}，单位成本收益 {gain / cand.cost:.6g}"
                ),
            )
        )
        if target is not None and current.objective <= target:
            reached = True

    swaps: List[SwapStep] = []
    if local_search:
        iteration = 0
        while iteration < max_local_iterations:
            iteration += 1
            best_swap = None
            for pos, si in enumerate(list(selected_order)):
                removed = cands[si]
                for ui, cand in enumerate(cands):
                    if ui in selected_idx:
                        continue
                    new_spent = spent - removed.cost + cand.cost
                    if budget is not None and new_spent > budget + 1e-12:
                        continue
                    trial_selected = [
                        c for j, c in enumerate(selected) if j != pos
                    ] + [cand]
                    trial_order = [
                        j for k, j in enumerate(selected_order) if k != pos
                    ] + [ui]
                    try:
                        metrics = _evaluate(
                            _network_with(net, trial_selected),
                            datum,
                            obj,
                            parameter_order,
                        )
                    except Exception:
                        continue
                    gain = current.objective - metrics.objective
                    if gain <= min_gain:
                        continue
                    key = (gain, -cand.cost)
                    if best_swap is None or key > best_swap[0]:
                        best_swap = (
                            key,
                            si,
                            ui,
                            metrics,
                            gain,
                            new_spent,
                            trial_selected,
                            trial_order,
                        )
            if best_swap is None:
                break
            (
                _key,
                si,
                ui,
                metrics,
                gain,
                new_spent,
                trial_selected,
                trial_order,
            ) = best_swap
            removed = cands[si]
            added = cands[ui]
            selected = trial_selected
            selected_order = trial_order
            selected_idx.remove(si)
            selected_idx.add(ui)
            spent = new_spent
            current = metrics
            swaps.append(
                SwapStep(
                    iteration=iteration,
                    removed_label=removed.observation.label,
                    added_label=added.observation.label,
                    cost_delta=added.cost - removed.cost,
                    total_cost=spent,
                    objective=current.objective,
                    gain=gain,
                )
            )
            if target is not None and current.objective <= target:
                reached = True

    final_net = _network_with(net, selected)
    final = _evaluate(final_net, datum, obj, parameter_order)
    if target is not None and final.objective <= target:
        reached = True
    return OptimizationResult(
        objective=obj,
        budget=budget,
        target=target,
        steps=steps,
        swaps=swaps,
        selected=selected,
        spent=spent,
        initial_metrics=initial,
        final_metrics=final,
        reached=reached,
        network=final_net,
        result=final.result,
        candidates=cands,
    )


def greedy_optimize(*args: Any, **kwargs: Any) -> OptimizationResult:
    return optimize(*args, **kwargs)


__all__ = [
    "Candidate",
    "ObjectiveMetrics",
    "OptimizationStep",
    "SwapStep",
    "OptimizationResult",
    "optimize",
    "greedy_optimize",
]
