"""观测方案优化：贪心、局部搜索、精确分支定界与 MILP 代理。

准则统一为 ``criterion="A" / "D" / "E" / "max_mp" / "worst_rel"``：

* ``A``：最小化 ``trace(Cx)``（A 最优）；
* ``D``：最小化 ``log det(Cx)``（D 最优）；
* ``E``：最小化 ``lambda_max(Cx)``（E 最优）；
* ``max_mp``：最小化最大点位中误差；
* ``worst_rel``：最小化最弱边相对精度 ``max(sigma_s / s)``。

成本模型为“每条观测成本 + 新设站固定成本”。设站成本只对候选观测首次使用的
测站计一次；默认不把既有基准网的测站视为已建站，可通过
``existing_stations`` 显式声明。该约定使优化预算能够独立于基准网成本核算。
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from math import hypot, isfinite
from typing import Any, Dict, FrozenSet, Iterable, List, Mapping, Optional, Sequence, Tuple

import numpy as np

from .adjustment import AdjustmentResult, solve
from .datum import normalize_datum
from .design import build_design, build_parameter_index, whiten
from .model import (
    Angle,
    Direction,
    Distance,
    GnssBaseline2D,
    Network,
    Observation,
    Scenario,
)
from .precision import PrecisionResult, analyze_precision

CRITERIA = ("A", "D", "E", "max_mp", "worst_rel")


# ---------------------------------------------------------------------------
# 数据模型与成本
# ---------------------------------------------------------------------------
@dataclass
class Candidate:
    """候选观测及其成本、可选测站集合。

    ``stations`` 为空时按观测类型推断：角度/方向取测站；距离/GNSS 取全部
    引用点（仪器站与目标/接收机）。显式传入 ``stations`` 可覆盖该推断。
    """

    observation: Observation
    cost: float = 1.0
    stations: Optional[Sequence[str]] = None

    def __post_init__(self) -> None:
        self.cost = float(self.cost)
        if not isfinite(self.cost) or self.cost <= 0.0:
            raise ValueError(f"候选观测成本必须为正的有限值，收到 {self.cost!r}")
        if self.stations is not None:
            if isinstance(self.stations, str):
                raw = (self.stations,)
            else:
                raw = tuple(self.stations)
            seen: set = set()
            stations: List[str] = []
            for item in raw:
                name = str(item)
                if name not in seen:
                    stations.append(name)
                    seen.add(name)
            self.stations = tuple(stations)

    @property
    def station_names(self) -> Tuple[str, ...]:
        """本候选观测涉及的测站集合（去重、保序）。"""
        if self.stations is not None:
            return tuple(self.stations)
        obs = self.observation
        if isinstance(obs, (Angle, Direction)):
            return (obs.station,)
        if isinstance(obs, (Distance, GnssBaseline2D)):
            return tuple(dict.fromkeys(obs.referenced_points()))
        return tuple(dict.fromkeys(obs.referenced_points()))


@dataclass(frozen=True)
class CostModel:
    """观测成本 + 测站首次使用固定成本。

    ``station_costs`` 为点名到固定成本的映射，未列出的测站使用
    ``default_station_cost``。``existing_stations`` 中的测站视为已建站，
    首次使用不再收费。
    """

    station_costs: Mapping[str, float] = field(default_factory=dict)
    default_station_cost: float = 0.0
    existing_stations: FrozenSet[str] = frozenset()

    def __post_init__(self) -> None:
        costs: Dict[str, float] = {}
        for name, value in dict(self.station_costs).items():
            v = float(value)
            if not isfinite(v) or v < 0.0:
                raise ValueError(f"测站 {name!r} 的固定成本必须为非负有限值")
            costs[str(name)] = v
        default = float(self.default_station_cost)
        if not isfinite(default) or default < 0.0:
            raise ValueError("default_station_cost 必须为非负有限值")
        object.__setattr__(self, "station_costs", costs)
        object.__setattr__(self, "default_station_cost", default)
        object.__setattr__(
            self, "existing_stations", frozenset(str(s) for s in self.existing_stations)
        )

    @classmethod
    def coerce(
        cls,
        value: Any = None,
        *,
        default_station_cost: float = 0.0,
        existing_stations: Iterable[str] = (),
    ) -> "CostModel":
        if isinstance(value, cls):
            return value
        if value is None:
            costs: Mapping[str, float] = {}
            default = default_station_cost
        elif isinstance(value, Mapping):
            costs = value
            default = default_station_cost
        elif isinstance(value, (int, float, np.integer, np.floating)):
            costs = {}
            default = float(value)
        else:
            raise TypeError("station_costs 必须是数字、映射或 CostModel")
        return cls(costs, default, frozenset(existing_stations))

    def station_cost(self, station: str) -> float:
        return float(self.station_costs.get(str(station), self.default_station_cost))

    def total_cost(
        self,
        candidates: Sequence[Candidate],
        selected: Iterable[int],
        existing_stations: Optional[Iterable[str]] = None,
    ) -> float:
        active = set(
            self.existing_stations
            if existing_stations is None
            else (str(s) for s in existing_stations)
        )
        total = 0.0
        for idx in selected:
            cand = candidates[int(idx)]
            total += cand.cost
            for station in cand.station_names:
                if station not in active:
                    total += self.station_cost(station)
                    active.add(station)
        return float(total)

    def marginal_cost(
        self, candidate: Candidate, active_stations: Iterable[str]
    ) -> float:
        active = {str(s) for s in active_stations}
        extra = 0.0
        for station in candidate.station_names:
            if station not in active:
                extra += self.station_cost(station)
                active.add(station)
        return float(candidate.cost + extra)


@dataclass
class ObjectiveMetrics:
    objective: float
    max_mp: float
    trace_Cx: float
    worst_relative: float
    weakest_edge: Optional[str]
    result: AdjustmentResult
    precision: PrecisionResult
    log_det_Cx: float = float("nan")
    lambda_max_Cx: float = float("nan")


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
    def criterion(self) -> str:
        return self.objective

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
            f"优化准则：{self.objective}；预算：{self.budget}；目标阈值：{self.target}",
            f"初始目标：{self.initial_metrics.objective:.6g}；"
            f"最终目标：{self.final_metrics.objective:.6g}；"
            f"成本：{self.spent:.6g}；达标：{'是' if self.reached else '否'}",
            "",
            "| 步 | 新增观测 | 边际成本 | 累计成本 | 目标值 | 收益 | 最大 mp/mm | 最弱边 |",
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


@dataclass
class ExactOptimizationResult:
    """精确/近似优化结果。

    ``exact=True`` 表示在给定候选集与预算下已证明全局最优；``method`` 为
    ``branch_bound``、``exhaustive`` 或 ``milp_proxy`` 等。
    """

    criterion: str
    budget: Optional[float]
    target: Optional[float]
    selected: List[Candidate]
    spent: float
    objective_value: float
    initial_metrics: ObjectiveMetrics
    final_metrics: ObjectiveMetrics
    network: Network
    result: AdjustmentResult
    candidates: List[Candidate]
    method: str
    exact: bool
    nodes: int
    elapsed: float
    lower_bound: Optional[float]
    optimality_gap: Optional[float]
    reached: bool = False
    proxy_objective: Optional[float] = None
    notes: str = ""

    @property
    def objective(self) -> str:
        return self.criterion

    @property
    def steps(self) -> List[OptimizationStep]:
        """精确结果没有逐步贪心过程，保留空列表以兼容通用展示代码。"""
        return []

    @property
    def swaps(self) -> List[SwapStep]:
        return []

    @property
    def selected_labels(self) -> List[str]:
        return [c.observation.label for c in self.selected]

    @property
    def selected_observations(self) -> List[Observation]:
        return [c.observation for c in self.selected]

    def to_text(self) -> str:
        lines = [
            f"优化准则：{self.criterion}；方法：{self.method}；"
            f"精确：{'是' if self.exact else '否'}；预算：{self.budget}",
            f"初始目标：{self.initial_metrics.objective:.6g}；"
            f"最终目标：{self.objective_value:.6g}；成本：{self.spent:.6g}；"
            f"节点：{self.nodes}；耗时：{self.elapsed:.3f} s",
        ]
        if self.selected_labels:
            lines.append("选中观测：" + "、".join(self.selected_labels))
        else:
            lines.append("选中观测：无")
        if self.notes:
            lines.append("说明：" + self.notes)
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# 准则、候选与评价
# ---------------------------------------------------------------------------
_CRITERION_ALIASES = {
    "a": "A",
    "a_opt": "A",
    "a-optimal": "A",
    "aoptimal": "A",
    "trace": "A",
    "trace_cx": "A",
    "min_trace": "A",
    "a最优": "A",
    "a-最优": "A",
    "d": "D",
    "d_opt": "D",
    "d-optimal": "D",
    "doptimal": "D",
    "logdet": "D",
    "log_det": "D",
    "log_det_cx": "D",
    "d最优": "D",
    "d-最优": "D",
    "e": "E",
    "e_opt": "E",
    "e-optimal": "E",
    "eoptimal": "E",
    "lambda_max": "E",
    "lambdamax": "E",
    "e最优": "E",
    "e-最优": "E",
    "max_mp": "max_mp",
    "min_max_mp": "max_mp",
    "mp": "max_mp",
    "最大点位中误差": "max_mp",
    "worst_rel": "worst_rel",
    "worst_relative": "worst_rel",
    "relative": "worst_rel",
    "weakest_edge": "worst_rel",
    "max_relative": "worst_rel",
    "最弱边": "worst_rel",
    "最弱边相对精度": "worst_rel",
}


def _normalize_criterion(value: Any) -> str:
    key = str(value).strip().lower()
    if key not in _CRITERION_ALIASES:
        raise ValueError(f"未知优化准则 {value!r}；可选 " + "、".join(CRITERIA))
    return _CRITERION_ALIASES[key]


def _coerce_criterion(criterion: Optional[Any], objective: Optional[Any]) -> str:
    if criterion is not None and objective is not None:
        c = _normalize_criterion(criterion)
        o = _normalize_criterion(objective)
        if c != o:
            raise ValueError(f"criterion={criterion!r} 与 objective={objective!r} 冲突")
        return c
    if criterion is not None:
        return _normalize_criterion(criterion)
    if objective is not None:
        return _normalize_criterion(objective)
    return "max_mp"


def _parse_candidates(
    candidates: Sequence[Any], costs: Optional[Mapping[Any, float]] = None
) -> List[Candidate]:
    out: List[Candidate] = []
    for i, item in enumerate(candidates):
        if isinstance(item, Candidate):
            cand = item
        elif isinstance(item, tuple) and len(item) in (2, 3) and isinstance(item[0], Observation):
            stations = item[2] if len(item) == 3 else None
            cand = Candidate(item[0], item[1], stations)
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


def _resolve_cost_model(
    cost_model: Optional[CostModel],
    station_costs: Any,
    default_station_cost: float,
    existing_stations: Iterable[str],
) -> CostModel:
    if cost_model is not None:
        if not isinstance(cost_model, CostModel):
            raise TypeError("cost_model 必须是 CostModel")
        return cost_model
    return CostModel.coerce(
        station_costs,
        default_station_cost=default_station_cost,
        existing_stations=existing_stations,
    )


def _scale_vector(parameter_scales: Optional[Any], names: Sequence[str]) -> np.ndarray:
    size = len(names)
    scales = np.ones(size, dtype=float)
    if parameter_scales is None:
        return scales
    if isinstance(parameter_scales, Mapping):
        for j, name in enumerate(names):
            if name in parameter_scales:
                scales[j] = float(parameter_scales[name])
        return scales
    values = np.asarray(parameter_scales, dtype=float).ravel()
    if values.size != size:
        raise ValueError(
            f"parameter_scales 长度 {values.size} 与参数数 {size} 不一致"
        )
    scales[:] = values
    return scales


def _scaled_covariance(Cx: np.ndarray, scales: np.ndarray) -> np.ndarray:
    if Cx.size == 0 or np.allclose(scales, 1.0):
        return Cx
    return Cx / np.outer(scales, scales)


def _evaluate(
    network: Network,
    datum: Any,
    criterion: str,
    parameter_order: Optional[Sequence[Any]],
    parameter_scales: Optional[Any] = None,
) -> ObjectiveMetrics:
    result = solve(network, datum=datum, parameter_order=parameter_order)
    precision = analyze_precision(result)
    unknown = [p for p in network.points if not p.fixed]
    max_mp = max((precision.points[p.name].mp for p in unknown), default=0.0)
    trace = float(np.trace(result.Cx)) if result.n_params else 0.0
    worst = precision.worst_relative

    Cx = result.Cx
    if Cx.size:
        sign, logdet = np.linalg.slogdet(Cx)
        if sign > 0.0:
            log_det = float(logdet)
        elif sign == 0.0:
            log_det = float("-inf")
        else:
            log_det = float("inf")
        eigen = np.linalg.eigvalsh(Cx)
        lambda_max = float(eigen[-1]) if eigen.size else 0.0
    else:
        log_det = 0.0
        lambda_max = 0.0

    scales = _scale_vector(parameter_scales, result.index.names)
    Cx_scaled = _scaled_covariance(Cx, scales)
    if criterion == "A":
        value = float(np.trace(Cx_scaled)) if Cx_scaled.size else 0.0
    elif criterion == "D":
        value = log_det
    elif criterion == "E":
        value = float(np.linalg.eigvalsh(Cx_scaled)[-1]) if Cx_scaled.size else 0.0
    elif criterion == "max_mp":
        value = max_mp
    elif criterion == "worst_rel":
        value = worst
    else:  # pragma: no cover - 由 _normalize_criterion 保证
        raise ValueError(criterion)

    return ObjectiveMetrics(
        objective=float(value),
        max_mp=float(max_mp),
        trace_Cx=trace,
        worst_relative=float(worst),
        weakest_edge=precision.weakest_edge,
        result=result,
        precision=precision,
        log_det_Cx=log_det,
        lambda_max_Cx=lambda_max,
    )


def _network_with(base: Network, selected: Sequence[Candidate]) -> Network:
    obs = list(base.observations) + [c.observation for c in selected]
    return Network(list(base.points), obs, name=base.name)


def _selected_cost(
    cost_model: CostModel,
    candidates: Sequence[Candidate],
    selected: Sequence[int],
) -> float:
    return cost_model.total_cost(candidates, selected)


def _gain(current: float, trial: float) -> float:
    if trial == float("inf"):
        return float("-inf")
    if current == float("inf"):
        return float("inf")
    return float(current - trial)


# ---------------------------------------------------------------------------
# 贪心 + 局部搜索
# ---------------------------------------------------------------------------
def optimize(
    base: Any,
    candidates: Sequence[Any],
    objective: Optional[str] = None,
    budget: Optional[float] = None,
    target: Optional[float] = None,
    costs: Optional[Mapping[Any, float]] = None,
    local_search: bool = False,
    max_steps: Optional[int] = None,
    max_local_iterations: int = 20,
    min_gain: float = 1e-15,
    datum: Any = None,
    parameter_order: Optional[Sequence[Any]] = None,
    criterion: Optional[str] = None,
    parameter_scales: Optional[Any] = None,
    cost_model: Optional[CostModel] = None,
    station_costs: Any = None,
    default_station_cost: float = 0.0,
    existing_stations: Iterable[str] = (),
) -> OptimizationResult:
    """贪心加入单位成本收益最大的候选观测，可选 1 换 1 局部搜索。

    ``criterion``/``objective`` 二者等价，支持 ``A``、``D``、``E``、
    ``max_mp``、``worst_rel``。旧别名 ``trace``、``relative`` 等仍然可用。

    ``station_costs`` 可为数字（所有测站统一固定成本）或“点名→固定成本”
    映射；``cost_model`` 优先。测站在候选集合中首次使用时才计一次固定成本。
    """
    if isinstance(base, Scenario):
        net = base.network
        if datum is None:
            datum = base.datum
    elif isinstance(base, Network):
        net = base
    else:
        raise TypeError("base 必须是 Scenario 或 Network")

    obj = _coerce_criterion(criterion, objective)
    cands = _parse_candidates(candidates, costs)
    model = _resolve_cost_model(
        cost_model, station_costs, default_station_cost, existing_stations
    )
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

    initial = _evaluate(net, datum, obj, parameter_order, parameter_scales)
    current = initial
    selected: List[Candidate] = []
    selected_idx: set = set()
    selected_order: List[int] = []
    active_stations: set = set(model.existing_stations)
    spent = 0.0
    steps: List[OptimizationStep] = []
    reached = target is not None and current.objective <= target

    while len(steps) < max_steps and not reached:
        best = None  # (key, idx, metrics, gain, marginal)
        for i, cand in enumerate(cands):
            if i in selected_idx:
                continue
            marginal = model.marginal_cost(cand, active_stations)
            if budget is not None and spent + marginal > budget + 1e-12:
                continue
            trial_net = _network_with(net, selected + [cand])
            try:
                metrics = _evaluate(
                    trial_net, datum, obj, parameter_order, parameter_scales
                )
            except Exception:
                continue
            gain = current.objective - metrics.objective
            if gain <= min_gain:
                continue
            utility = gain / marginal if marginal > 0.0 else gain
            key = (utility, gain, -marginal)
            if best is None or key > best[0]:
                best = (key, i, metrics, gain, marginal)

        if best is None:
            break
        _key, idx, metrics, gain, marginal = best
        cand = cands[idx]
        selected_idx.add(idx)
        selected.append(cand)
        selected_order.append(idx)
        spent += marginal
        for station in cand.station_names:
            active_stations.add(station)
        current = metrics
        steps.append(
            OptimizationStep(
                step=len(steps) + 1,
                added=cand.observation,
                added_label=cand.observation.label,
                cost=marginal,
                total_cost=spent,
                objective=current.objective,
                gain=gain,
                max_mp=current.max_mp,
                trace_Cx=current.trace_Cx,
                worst_relative=current.worst_relative,
                weakest_edge=current.weakest_edge,
                selected_labels=[c.observation.label for c in selected],
                explanation=(
                    f"边际收益 {gain:.6g}，单位成本收益 "
                    f"{(gain / marginal if marginal > 0 else gain):.6g}"
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
            current_indices = list(selected_order)
            current_set = set(current_indices)
            best_swap = None
            for pos, si in enumerate(current_indices):
                removed = cands[si]
                for ui, cand in enumerate(cands):
                    if ui in current_set:
                        continue
                    trial_indices = list(current_indices)
                    trial_indices[pos] = ui
                    new_spent = _selected_cost(model, cands, trial_indices)
                    if budget is not None and new_spent > budget + 1e-12:
                        continue
                    trial_selected = [cands[j] for j in trial_indices]
                    try:
                        metrics = _evaluate(
                            _network_with(net, trial_selected),
                            datum,
                            obj,
                            parameter_order,
                            parameter_scales,
                        )
                    except Exception:
                        continue
                    gain = current.objective - metrics.objective
                    if gain <= min_gain:
                        continue
                    key = (gain, -new_spent)
                    if best_swap is None or key > best_swap[0]:
                        best_swap = (
                            key,
                            si,
                            ui,
                            metrics,
                            gain,
                            new_spent,
                            trial_indices,
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
                trial_indices,
            ) = best_swap
            removed = cands[si]
            added = cands[ui]
            selected_order = list(trial_indices)
            selected = [cands[j] for j in selected_order]
            selected_idx = set(selected_order)
            old_spent = spent
            spent = new_spent
            current = metrics
            swaps.append(
                SwapStep(
                    iteration=iteration,
                    removed_label=removed.observation.label,
                    added_label=added.observation.label,
                    cost_delta=spent - old_spent,
                    total_cost=spent,
                    objective=current.objective,
                    gain=gain,
                )
            )
            if target is not None and current.objective <= target:
                reached = True

    final_net = _network_with(net, selected)
    final = _evaluate(final_net, datum, obj, parameter_order, parameter_scales)
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
    kwargs.setdefault("local_search", False)
    return optimize(*args, **kwargs)


def local_search_optimize(*args: Any, **kwargs: Any) -> OptimizationResult:
    kwargs["local_search"] = True
    return optimize(*args, **kwargs)


# ---------------------------------------------------------------------------
# 快速评价器（精确搜索用）
# ---------------------------------------------------------------------------
def _edge_geometry(
    index: Any, network: Network, frm: str, to: str
) -> Tuple[np.ndarray, float]:
    p = network.point(frm)
    q = network.point(to)
    dE, dN = q.E - p.E, q.N - p.N
    length = hypot(dE, dN)
    g = np.zeros(index.size, dtype=float)
    if length <= 0.0:
        return g, 0.0
    for name, sign in ((frm, -1.0), (to, 1.0)):
        cols = index.point_columns.get(name)
        if cols is None:
            continue
        g[cols[0]] += sign * dE / length
        g[cols[1]] += sign * dN / length
    return g, float(length)


class _FastEvaluator:
    """在固定参数空间内用正规矩阵快速评价候选子集。

    正规矩阵 ``N = AᵀPA`` 按“基准观测 + 所有候选观测”的参数索引组装；
    对方向观测的定向未知数按子集是否含该测站方向动态启用。该评价器与
    ``solve``+``analyze_precision`` 在满秩子集上一致，供分支定界使用。
    """

    def __init__(
        self,
        base: Network,
        candidates: Sequence[Candidate],
        datum: Any,
        criterion: str,
        parameter_order: Optional[Sequence[Any]],
        parameter_scales: Optional[Any],
        cost_model: CostModel,
    ) -> None:
        self.base = base
        self.candidates = list(candidates)
        self.criterion = criterion
        self.cost_model = cost_model
        self.n = len(self.candidates)

        universe_obs = list(base.observations) + [c.observation for c in self.candidates]
        universe = Network(list(base.points), universe_obs, name=base.name)
        self.index = build_parameter_index(universe, parameter_order=parameter_order)

        datum_obj = normalize_datum(datum)
        constraints = datum_obj.constraints(base, self.index)
        base_design = build_design(base, self.index, constraints=constraints)
        Aw0, _ = whiten(base_design.A, base_design.Ql)
        self.N0 = Aw0.T @ Aw0

        self.G: List[np.ndarray] = []
        self.cand_edge_masks: List[int] = []
        self.cand_orient_masks: List[int] = []
        for cand in self.candidates:
            one = Network(list(base.points), [cand.observation], name=base.name)
            design = build_design(one, self.index)
            Aw, _ = whiten(design.A, design.Ql)
            self.G.append(Aw.T @ Aw)

        # 坐标参数（全部未知点）始终启用。
        self.coord_cols: List[int] = []
        for name in self.index.point_order:
            self.coord_cols.extend(self.index.point_columns[name])
        self.point_cols = {
            name: tuple(cols) for name, cols in self.index.point_columns.items()
        }

        self.orientation_order: List[str] = list(self.index.orientation_order)
        self.orientation_bit = {
            name: bit for bit, name in enumerate(self.orientation_order)
        }
        self.orientation_cols = dict(self.index.orientation_columns)
        self.base_orient_mask = 0
        for obs in base.observations:
            if isinstance(obs, Direction):
                bit = self.orientation_bit.get(obs.station)
                if bit is not None:
                    self.base_orient_mask |= 1 << bit

        # 距离边：基准网边 + 候选距离边，去重并保持首次方向。
        self.edge_gradients: List[np.ndarray] = []
        self.edge_lengths: List[float] = []
        self.edge_labels: List[str] = []
        self.edge_key_to_index: Dict[Tuple[str, str], int] = {}
        self.base_edge_mask = 0

        def add_edge(frm: str, to: str) -> int:
            key = tuple(sorted((frm, to)))
            if key in self.edge_key_to_index:
                return self.edge_key_to_index[key]
            g, length = _edge_geometry(self.index, base, frm, to)
            idx = len(self.edge_gradients)
            self.edge_key_to_index[key] = idx
            self.edge_gradients.append(g)
            self.edge_lengths.append(length)
            self.edge_labels.append(f"{frm}{to}")
            return idx

        for frm, to in base.distance_edges():
            idx = add_edge(frm, to)
            self.base_edge_mask |= 1 << idx
        for cand in self.candidates:
            mask = 0
            if isinstance(cand.observation, Distance):
                obs = cand.observation
                mask |= 1 << add_edge(obs.frm, obs.to)
            self.cand_edge_masks.append(mask)

        for cand in self.candidates:
            mask = 0
            obs = cand.observation
            if isinstance(obs, Direction):
                bit = self.orientation_bit.get(obs.station)
                if bit is not None:
                    mask |= 1 << bit
            self.cand_orient_masks.append(mask)

        # 若候选方向不引入新定向参数，A/D/E 的 Cx 维数固定，单调下界有效。
        self.orientation_stable = all(
            (mask & ~self.base_orient_mask) == 0
            for mask in self.cand_orient_masks
        )

        # 测站位掩码与固定成本。
        station_names = sorted(
            {station for cand in self.candidates for station in cand.station_names}
        )
        self.station_bit = {name: bit for bit, name in enumerate(station_names)}
        self.station_names = station_names
        self.station_cost_by_bit = [
            self.cost_model.station_cost(name) for name in station_names
        ]
        self.cand_station_masks: List[int] = []
        for cand in self.candidates:
            mask = 0
            for station in cand.station_names:
                mask |= 1 << self.station_bit[station]
            self.cand_station_masks.append(mask)
        self.base_station_mask = 0
        for station in self.cost_model.existing_stations:
            bit = self.station_bit.get(station)
            if bit is not None:
                self.base_station_mask |= 1 << bit

        self.scale_vec = _scale_vector(parameter_scales, self.index.names)

    # -- 子集信息 ---------------------------------------------------
    def active_cols(self, orient_mask: int) -> List[int]:
        if not self.orientation_order:
            return self.coord_cols
        cols = list(self.coord_cols)
        for station in self.orientation_order:
            bit = self.orientation_bit[station]
            if orient_mask & (1 << bit):
                cols.append(self.orientation_cols[station])
        return cols

    def edge_mask(self, selected_mask: int) -> int:
        mask = self.base_edge_mask
        for i in range(self.n):
            if selected_mask & (1 << i):
                mask |= self.cand_edge_masks[i]
        return mask

    def marginal_cost(self, idx: int, station_mask: int) -> float:
        new_bits = self.cand_station_masks[idx] & ~station_mask
        extra = 0.0
        while new_bits:
            bit = new_bits & -new_bits
            extra += self.station_cost_by_bit[bit.bit_length() - 1]
            new_bits ^= bit
        return float(self.candidates[idx].cost + extra)

    # -- 目标函数 ---------------------------------------------------
    def objective(self, N: np.ndarray, orient_mask: int, edge_mask: int) -> float:
        cols = self.active_cols(orient_mask)
        size = len(cols)
        if size == 0:
            return 0.0
        Na = N[np.ix_(cols, cols)]
        eigen = np.linalg.eigvalsh(Na)
        if eigen.size == 0:
            return 0.0
        tol = max(
            np.finfo(float).eps * max(size, 10) * max(float(eigen[-1]), 1.0),
            1e-15,
        )
        if float(eigen[0]) <= tol:
            return float("inf")
        try:
            C = np.linalg.inv(Na)
        except np.linalg.LinAlgError:  # pragma: no cover
            return float("inf")
        C = 0.5 * (C + C.T)
        scales = self.scale_vec[cols]
        Cs = _scaled_covariance(C, scales)

        if self.criterion == "A":
            return float(np.trace(Cs))
        if self.criterion == "D":
            sign, logdet = np.linalg.slogdet(C)
            if sign > 0.0:
                return float(logdet)
            return float("-inf") if sign == 0.0 else float("inf")
        if self.criterion == "E":
            return float(np.linalg.eigvalsh(Cs)[-1])
        if self.criterion == "max_mp":
            pos = {col: j for j, col in enumerate(cols)}
            best = 0.0
            for _name, (ie, inn) in self.point_cols.items():
                le, ln = pos[ie], pos[inn]
                mp2 = float(C[le, le] + C[ln, ln])
                best = max(best, mp2 ** 0.5 if mp2 > 0.0 else 0.0)
            return float(best)
        if self.criterion == "worst_rel":
            if edge_mask == 0:
                return 0.0
            worst = 0.0
            mask = edge_mask
            while mask:
                bit = mask & -mask
                k = bit.bit_length() - 1
                mask ^= bit
                length = self.edge_lengths[k]
                if length <= 0.0:
                    continue
                g = self.edge_gradients[k][cols]
                var = float(g @ C @ g)
                rel = (max(var, 0.0) ** 0.5) / length
                if rel > worst:
                    worst = rel
            return float(worst)
        raise ValueError(self.criterion)  # pragma: no cover

    def cost_of(self, selected_mask: int) -> float:
        indices = [i for i in range(self.n) if selected_mask & (1 << i)]
        return self.cost_model.total_cost(self.candidates, indices)


def _greedy_incumbent(
    evaluator: _FastEvaluator, budget: Optional[float]
) -> Tuple[int, float, float, List[int]]:
    selected_mask = 0
    N = evaluator.N0
    orient = evaluator.base_orient_mask
    edge = evaluator.base_edge_mask
    station_mask = evaluator.base_station_mask
    cost = 0.0
    current = evaluator.objective(N, orient, edge)
    order: List[int] = []

    while True:
        best = None
        for i in range(evaluator.n):
            bit = 1 << i
            if selected_mask & bit:
                continue
            marginal = evaluator.marginal_cost(i, station_mask)
            if budget is not None and cost + marginal > budget + 1e-12:
                continue
            trial = evaluator.objective(
                N + evaluator.G[i],
                orient | evaluator.cand_orient_masks[i],
                edge | evaluator.cand_edge_masks[i],
            )
            gain = _gain(current, trial)
            if gain <= 0.0:
                continue
            utility = gain / marginal if marginal > 0.0 else gain
            key = (utility, gain, -marginal, -i)
            if best is None or key > best[0]:
                best = (key, i, trial, gain, marginal)

        if best is None:
            break
        _key, i, trial, _gain_value, marginal = best
        selected_mask |= 1 << i
        N = N + evaluator.G[i]
        orient |= evaluator.cand_orient_masks[i]
        edge |= evaluator.cand_edge_masks[i]
        station_mask |= evaluator.cand_station_masks[i]
        cost += marginal
        current = trial
        order.append(i)

    return selected_mask, cost, current, order


def _run_exact(
    base: Network,
    candidates: Sequence[Candidate],
    criterion: str,
    budget: Optional[float],
    datum: Any,
    parameter_order: Optional[Sequence[Any]],
    parameter_scales: Optional[Any],
    cost_model: CostModel,
    *,
    use_bound: bool,
    method: str,
    max_nodes: Optional[int] = None,
    time_limit: Optional[float] = None,
    gap_tol: float = 1e-10,
) -> Dict[str, Any]:
    datum_obj = normalize_datum(datum)
    if datum_obj.is_minimal:
        raise ValueError(
            "精确分支定界/穷举暂不支持自由网/最小约束基准；"
            "该类基准的伪逆协方差不能直接由正规矩阵求逆。"
            "请改用 greedy_optimize/local_search_optimize 或固定/加权基准。"
        )
    evaluator = _FastEvaluator(
        base,
        candidates,
        datum,
        criterion,
        parameter_order,
        parameter_scales,
        cost_model,
    )
    started = time.perf_counter()
    empty_obj = evaluator.objective(
        evaluator.N0, evaluator.base_orient_mask, evaluator.base_edge_mask
    )
    greedy_mask, greedy_cost, greedy_obj, greedy_order = _greedy_incumbent(
        evaluator, budget
    )

    best_mask = greedy_mask
    best_cost = greedy_cost
    best_obj = greedy_obj
    if empty_obj < best_obj:
        best_mask, best_cost, best_obj = 0, 0.0, empty_obj

    # 把贪心选中的候选放在前面，其余按单条边际收益/成本排序。
    remaining = [i for i in range(evaluator.n) if not (greedy_mask & (1 << i))]

    def static_score(i: int) -> Tuple[float, float, int]:
        marginal = evaluator.marginal_cost(i, evaluator.base_station_mask)
        trial = evaluator.objective(
            evaluator.N0 + evaluator.G[i],
            evaluator.base_orient_mask | evaluator.cand_orient_masks[i],
            evaluator.base_edge_mask | evaluator.cand_edge_masks[i],
        )
        gain = _gain(empty_obj, trial)
        if gain == float("inf"):
            utility = float("inf")
        elif marginal > 0.0:
            utility = gain / marginal
        else:
            utility = gain
        return (utility, gain, -i)

    remaining.sort(key=static_score, reverse=True)
    order = list(dict.fromkeys(greedy_order + remaining))
    order.extend(i for i in range(evaluator.n) if i not in order)

    n = evaluator.n
    suffix_N: List[np.ndarray] = [
        np.zeros_like(evaluator.N0) for _ in range(n + 1)
    ]
    suffix_orient = [0] * (n + 1)
    for k in range(n - 1, -1, -1):
        i = order[k]
        suffix_N[k] = suffix_N[k + 1] + evaluator.G[i]
        suffix_orient[k] = suffix_orient[k + 1] | evaluator.cand_orient_masks[i]

    nodes = 0
    timed_out = False
    limit = float("inf") if time_limit is None else float(time_limit)

    def objective_tol() -> float:
        if best_obj == float("inf") or not isfinite(best_obj):
            return 0.0
        return gap_tol * max(1.0, abs(best_obj))

    def consider(obj: float, cost: float, mask: int) -> None:
        nonlocal best_mask, best_cost, best_obj
        if budget is not None and cost > budget + 1e-12:
            return
        tol = objective_tol()
        if best_obj == float("inf"):
            if obj < float("inf"):
                best_mask, best_cost, best_obj = mask, cost, obj
            return
        if obj == float("inf"):
            return
        if obj < best_obj - tol:
            best_mask, best_cost, best_obj = mask, cost, obj
        elif abs(obj - best_obj) <= tol and cost < best_cost - 1e-12:
            best_mask, best_cost, best_obj = mask, cost, obj

    def bound(pos: int, N: np.ndarray, orient: int, edge_mask: int) -> Optional[float]:
        if not use_bound or pos >= n:
            return None
        N_bound = N + suffix_N[pos]
        orient_bound = orient | suffix_orient[pos]
        if criterion == "worst_rel":
            # 任何完成方案都包含基准边；其相对精度是完成方案最弱边的下界。
            return evaluator.objective(N_bound, orient_bound, evaluator.base_edge_mask)
        if criterion in ("A", "D", "E") and not evaluator.orientation_stable:
            # 新定向未知数会改变 Cx 维数，A/D/E 的简单单调下界不适用。
            return None
        return evaluator.objective(N_bound, orient_bound, edge_mask)

    def dfs(
        pos: int,
        N: np.ndarray,
        orient: int,
        edge_mask: int,
        station_mask: int,
        cost: float,
        mask: int,
    ) -> None:
        nonlocal nodes, timed_out
        if timed_out:
            return
        nodes += 1
        if max_nodes is not None and nodes > int(max_nodes):
            timed_out = True
            return
        if time_limit is not None and (nodes & 255) == 0:
            if time.perf_counter() - started > limit:
                timed_out = True
                return
        obj = evaluator.objective(N, orient, edge_mask)
        consider(obj, cost, mask)
        if pos >= n:
            return

        lower = bound(pos, N, orient, edge_mask)
        if lower is not None and best_obj != float("inf"):
            if lower >= best_obj - objective_tol():
                return

        i = order[pos]
        marginal = evaluator.marginal_cost(i, station_mask)
        if budget is None or cost + marginal <= budget + 1e-12:
            dfs(
                pos + 1,
                N + evaluator.G[i],
                orient | evaluator.cand_orient_masks[i],
                edge_mask | evaluator.cand_edge_masks[i],
                station_mask | evaluator.cand_station_masks[i],
                cost + marginal,
                mask | (1 << i),
            )
        dfs(pos + 1, N, orient, edge_mask, station_mask, cost, mask)

    dfs(
        0,
        evaluator.N0,
        evaluator.base_orient_mask,
        evaluator.base_edge_mask,
        evaluator.base_station_mask,
        0.0,
        0,
    )
    elapsed = time.perf_counter() - started
    return {
        "evaluator": evaluator,
        "best_mask": best_mask,
        "best_cost": best_cost,
        "best_obj": best_obj,
        "nodes": nodes,
        "elapsed": elapsed,
        "timed_out": timed_out,
        "method": method,
    }


def _build_exact_result(
    base: Network,
    candidates: Sequence[Candidate],
    criterion: str,
    budget: Optional[float],
    target: Optional[float],
    datum: Any,
    parameter_order: Optional[Sequence[Any]],
    parameter_scales: Optional[Any],
    cost_model: CostModel,
    search: Mapping[str, Any],
    *,
    method: str,
    exact: bool,
    proxy_objective: Optional[float] = None,
    notes: str = "",
) -> ExactOptimizationResult:
    best_mask = int(search["best_mask"])
    selected_indices = [i for i in range(len(candidates)) if best_mask & (1 << i)]
    selected = [candidates[i] for i in selected_indices]
    initial = _evaluate(base, datum, criterion, parameter_order, parameter_scales)
    final_net = _network_with(base, selected)
    final = _evaluate(final_net, datum, criterion, parameter_order, parameter_scales)
    spent = cost_model.total_cost(candidates, selected_indices)
    reached = target is not None and final.objective <= target
    if exact:
        lower_bound = final.objective
        gap = 0.0
    else:
        lower_bound = None
        gap = None
    return ExactOptimizationResult(
        criterion=criterion,
        budget=budget,
        target=target,
        selected=selected,
        spent=spent,
        objective_value=final.objective,
        initial_metrics=initial,
        final_metrics=final,
        network=final_net,
        result=final.result,
        candidates=list(candidates),
        method=method,
        exact=exact,
        nodes=int(search.get("nodes", 0)),
        elapsed=float(search.get("elapsed", 0.0)),
        lower_bound=lower_bound,
        optimality_gap=gap,
        reached=reached,
        proxy_objective=proxy_objective,
        notes=notes,
    )


def _prepare_base(base: Any, datum: Any) -> Tuple[Network, Any]:
    if isinstance(base, Scenario):
        net = base.network
        if datum is None:
            datum = base.datum
    elif isinstance(base, Network):
        net = base
    else:
        raise TypeError("base 必须是 Scenario 或 Network")
    return net, datum


def exact_optimize(
    base: Any,
    candidates: Sequence[Any],
    criterion: str = "max_mp",
    budget: Optional[float] = None,
    target: Optional[float] = None,
    costs: Optional[Mapping[Any, float]] = None,
    datum: Any = None,
    parameter_order: Optional[Sequence[Any]] = None,
    parameter_scales: Optional[Any] = None,
    cost_model: Optional[CostModel] = None,
    station_costs: Any = None,
    default_station_cost: float = 0.0,
    existing_stations: Iterable[str] = (),
    max_candidates: Optional[int] = 20,
    time_limit: Optional[float] = None,
    gap_tol: float = 1e-10,
    method: str = "branch_bound",
) -> ExactOptimizationResult:
    """预算约束下的全局最优（候选数 ≤ ``max_candidates``）。

    使用分支定界，并以“加入全部剩余观测后的目标值”为单调下界；因为增加
    独立观测不会使 ``Cx`` 变差（A/D/E 在定向参数维数不变时；max_mp 对坐标
    边缘协方差恒成立），该下界可用于安全剪枝。候选数很小时可用
    :func:`exhaustive_optimize` 交叉验证；``method="exhaustive"`` 时直接转交
    穷举实现。
    """
    if str(method).strip().lower() in ("exhaustive", "brute", "brute_force"):
        return exhaustive_optimize(
            base,
            candidates,
            criterion=criterion,
            budget=budget,
            target=target,
            costs=costs,
            datum=datum,
            parameter_order=parameter_order,
            parameter_scales=parameter_scales,
            cost_model=cost_model,
            station_costs=station_costs,
            default_station_cost=default_station_cost,
            existing_stations=existing_stations,
            max_candidates=max_candidates,
            time_limit=time_limit,
            gap_tol=gap_tol,
        )
    net, datum = _prepare_base(base, datum)
    cands = _parse_candidates(candidates, costs)
    criterion = _normalize_criterion(criterion)
    if max_candidates is not None and len(cands) > int(max_candidates):
        raise ValueError(
            f"精确搜索候选数 {len(cands)} 超过上限 {max_candidates}；"
            "请缩小候选集或使用 milp_optimize/greedy_optimize"
        )
    model = _resolve_cost_model(
        cost_model, station_costs, default_station_cost, existing_stations
    )
    if budget is not None:
        budget = float(budget)
        if not isfinite(budget) or budget < 0.0:
            raise ValueError("budget 必须为非负有限值")
    if target is not None:
        target = float(target)
        if not isfinite(target):
            raise ValueError("target 必须为有限值")
    search = _run_exact(
        net,
        cands,
        criterion,
        budget,
        datum,
        parameter_order,
        parameter_scales,
        model,
        use_bound=True,
        method="branch_bound",
        time_limit=time_limit,
        gap_tol=gap_tol,
    )
    exact = not bool(search["timed_out"])
    method = "branch_bound" if exact else "branch_bound_timeout"
    notes = (
        "分支定界；单调性下界 + 预算剪枝；已证明全局最优"
        if exact
        else "达到时间/节点上限，返回当前最好解，未证明全局最优"
    )
    return _build_exact_result(
        net,
        cands,
        criterion,
        budget,
        target,
        datum,
        parameter_order,
        parameter_scales,
        model,
        search,
        method=method,
        exact=exact,
        notes=notes,
    )


def exhaustive_optimize(
    base: Any,
    candidates: Sequence[Any],
    criterion: str = "max_mp",
    budget: Optional[float] = None,
    target: Optional[float] = None,
    costs: Optional[Mapping[Any, float]] = None,
    datum: Any = None,
    parameter_order: Optional[Sequence[Any]] = None,
    parameter_scales: Optional[Any] = None,
    cost_model: Optional[CostModel] = None,
    station_costs: Any = None,
    default_station_cost: float = 0.0,
    existing_stations: Iterable[str] = (),
    max_candidates: Optional[int] = 20,
    time_limit: Optional[float] = None,
    gap_tol: float = 1e-10,
) -> ExactOptimizationResult:
    """穷举全部预算可行子集，返回与分支定界相同的全局最优。"""
    net, datum = _prepare_base(base, datum)
    cands = _parse_candidates(candidates, costs)
    criterion = _normalize_criterion(criterion)
    if max_candidates is not None and len(cands) > int(max_candidates):
        raise ValueError(
            f"穷举候选数 {len(cands)} 超过上限 {max_candidates}；请缩小候选集"
        )
    model = _resolve_cost_model(
        cost_model, station_costs, default_station_cost, existing_stations
    )
    if budget is not None:
        budget = float(budget)
        if not isfinite(budget) or budget < 0.0:
            raise ValueError("budget 必须为非负有限值")
    search = _run_exact(
        net,
        cands,
        criterion,
        budget,
        datum,
        parameter_order,
        parameter_scales,
        model,
        use_bound=False,
        method="exhaustive",
        time_limit=time_limit,
        gap_tol=gap_tol,
    )
    exact = not bool(search["timed_out"])
    return _build_exact_result(
        net,
        cands,
        criterion,
        budget,
        target,
        datum,
        parameter_order,
        parameter_scales,
        model,
        search,
        method="exhaustive" if exact else "exhaustive_timeout",
        exact=exact,
        notes=(
            "穷举全部预算可行子集；已证明全局最优"
            if exact
            else "达到时间/节点上限，返回当前最好解，未证明全局最优"
        ),
    )


def brute_force_optimize(*args: Any, **kwargs: Any) -> ExactOptimizationResult:
    return exhaustive_optimize(*args, **kwargs)


# ---------------------------------------------------------------------------
# MILP 线性代理（SciPy HiGHS）
# ---------------------------------------------------------------------------
def milp_available() -> bool:
    try:
        import scipy.optimize
    except Exception:
        return False
    return hasattr(scipy.optimize, "milp")


def _indices_for_selected(
    candidates: Sequence[Candidate], selected: Sequence[Candidate]
) -> List[int]:
    ids = {id(c) for c in selected}
    indices = [i for i, c in enumerate(candidates) if id(c) in ids]
    if len(indices) == len(selected):
        return indices
    # 回退到值相等（重复候选时按顺序消费）。
    remaining = list(range(len(candidates)))
    out: List[int] = []
    for cand in selected:
        for i in remaining:
            if candidates[i] == cand:
                out.append(i)
                remaining.remove(i)
                break
    return out


def _local_search_indices(
    base: Network,
    candidates: Sequence[Candidate],
    initial_indices: Sequence[int],
    criterion: str,
    budget: Optional[float],
    datum: Any,
    parameter_order: Optional[Sequence[Any]],
    parameter_scales: Optional[Any],
    cost_model: CostModel,
    max_iterations: int = 10,
    min_gain: float = 1e-15,
) -> Tuple[List[int], float, ObjectiveMetrics, int]:
    selected = list(dict.fromkeys(int(i) for i in initial_indices))
    spent = cost_model.total_cost(candidates, selected)
    if budget is not None and spent > budget + 1e-12:
        selected = []
        spent = 0.0
    current = _evaluate(
        _network_with(base, [candidates[i] for i in selected]),
        datum,
        criterion,
        parameter_order,
        parameter_scales,
    )
    iterations = 0
    while iterations < max_iterations:
        iterations += 1
        selected_set = set(selected)
        best = None
        # 只加一条。
        for ui in range(len(candidates)):
            if ui in selected_set:
                continue
            trial = selected + [ui]
            new_cost = cost_model.total_cost(candidates, trial)
            if budget is not None and new_cost > budget + 1e-12:
                continue
            try:
                metrics = _evaluate(
                    _network_with(base, [candidates[i] for i in trial]),
                    datum,
                    criterion,
                    parameter_order,
                    parameter_scales,
                )
            except Exception:
                continue
            gain = current.objective - metrics.objective
            if gain <= min_gain:
                continue
            key = (gain, -new_cost)
            if best is None or key > best[0]:
                best = (key, trial, new_cost, metrics, gain)
        # 1 换 1。
        for pos in range(len(selected)):
            for ui in range(len(candidates)):
                if ui in selected_set:
                    continue
                trial = list(selected)
                trial[pos] = ui
                new_cost = cost_model.total_cost(candidates, trial)
                if budget is not None and new_cost > budget + 1e-12:
                    continue
                try:
                    metrics = _evaluate(
                        _network_with(base, [candidates[i] for i in trial]),
                        datum,
                        criterion,
                        parameter_order,
                        parameter_scales,
                    )
                except Exception:
                    continue
                gain = current.objective - metrics.objective
                if gain <= min_gain:
                    continue
                key = (gain, -new_cost)
                if best is None or key > best[0]:
                    best = (key, trial, new_cost, metrics, gain)
        if best is None:
            break
        _key, trial, new_cost, metrics, _gain_value = best
        selected = list(dict.fromkeys(trial))
        spent = new_cost
        current = metrics
    return selected, spent, current, iterations


def milp_optimize(
    base: Any,
    candidates: Sequence[Any],
    criterion: str = "max_mp",
    budget: Optional[float] = None,
    target: Optional[float] = None,
    costs: Optional[Mapping[Any, float]] = None,
    datum: Any = None,
    parameter_order: Optional[Sequence[Any]] = None,
    parameter_scales: Optional[Any] = None,
    cost_model: Optional[CostModel] = None,
    station_costs: Any = None,
    default_station_cost: float = 0.0,
    existing_stations: Iterable[str] = (),
    max_local_iterations: int = 10,
    time_limit: Optional[float] = None,
    gap_tol: float = 1e-10,
) -> ExactOptimizationResult:
    """MILP 线性代理 + 精确评价校正（近似，不保证全局最优）。

    代理模型把每个候选对目标（A/D/E 的标量目标，或 max_mp/最弱边的逐点
    贡献）的一阶收益线性化，建立带预算与设站 0-1 变量的 MILP；SciPy HiGHS
    求解后，用真实平差目标评价并做 1 加/1 换 1 局部搜索。结果对象
    ``exact=False``，并给出代理目标值。
    """
    try:
        from scipy.optimize import Bounds, LinearConstraint, milp
        from scipy.sparse import csr_matrix
    except Exception as exc:  # pragma: no cover - 取决于可选依赖
        raise RuntimeError(
            "MILP 近似需要 scipy>=1.11；请运行 pip install -e '.[opt]'"
        ) from exc

    net, datum = _prepare_base(base, datum)
    cands = _parse_candidates(candidates, costs)
    criterion = _normalize_criterion(criterion)
    model = _resolve_cost_model(
        cost_model, station_costs, default_station_cost, existing_stations
    )
    if budget is not None:
        budget = float(budget)
        if not isfinite(budget) or budget < 0.0:
            raise ValueError("budget 必须为非负有限值")
    if not cands:
        search = {"best_mask": 0, "nodes": 0, "elapsed": 0.0}
        return _build_exact_result(
            net,
            cands,
            criterion,
            budget,
            target,
            datum,
            parameter_order,
            parameter_scales,
            model,
            search,
            method="milp_proxy",
            exact=False,
            notes="无候选观测",
        )

    initial = _evaluate(net, datum, criterion, parameter_order, parameter_scales)
    if not isfinite(initial.objective):
        raise ValueError("MILP 代理要求基准网目标值有限（满秩）")

    point_names = [p.name for p in net.points if not p.fixed]
    universal_edges: List[Tuple[str, str]] = []
    seen_edges: set = set()
    for frm, to in net.distance_edges():
        key = tuple(sorted((frm, to)))
        if key not in seen_edges:
            seen_edges.add(key)
            universal_edges.append((frm, to))
    for cand in cands:
        if isinstance(cand.observation, Distance):
            obs = cand.observation
            key = tuple(sorted((obs.frm, obs.to)))
            if key not in seen_edges:
                seen_edges.add(key)
                universal_edges.append((obs.frm, obs.to))

    base_mp = np.array(
        [initial.precision.points[name].mp for name in point_names], dtype=float
    )
    if criterion == "worst_rel":
        base_edges = analyze_precision(initial.result, edges=universal_edges)
        base_edge_rel = np.array(
            [
                base_edges.edges[f"{frm}{to}"].relative
                if f"{frm}{to}" in base_edges.edges
                else base_edges.edges[f"{to}{frm}"].relative
                for frm, to in universal_edges
            ],
            dtype=float,
        )
    else:
        base_edge_rel = np.zeros(0, dtype=float)

    scalar_gains: List[float] = []
    point_gains: List[np.ndarray] = []
    edge_gains: List[np.ndarray] = []
    for cand in cands:
        trial = _evaluate(
            _network_with(net, [cand]),
            datum,
            criterion,
            parameter_order,
            parameter_scales,
        )
        if criterion in ("A", "D", "E"):
            scalar_gains.append(max(0.0, initial.objective - trial.objective))
        elif criterion == "max_mp":
            trial_mp = np.array(
                [trial.precision.points[name].mp for name in point_names],
                dtype=float,
            )
            point_gains.append(np.maximum(0.0, base_mp - trial_mp))
        else:
            trial_edges = analyze_precision(trial.result, edges=universal_edges)
            trial_rel = np.array(
                [
                    trial_edges.edges[f"{frm}{to}"].relative
                    if f"{frm}{to}" in trial_edges.edges
                    else trial_edges.edges[f"{to}{frm}"].relative
                    for frm, to in universal_edges
                ],
                dtype=float,
            )
            edge_gains.append(np.maximum(0.0, base_edge_rel - trial_rel))

    n = len(cands)
    new_stations = sorted(
        {
            station
            for cand in cands
            for station in cand.station_names
            if station not in model.existing_stations
        }
    )
    station_index = {name: n + j for j, name in enumerate(new_stations)}
    pointwise = criterion in ("max_mp", "worst_rel")
    z_index = n + len(new_stations)
    nvars = n + len(new_stations) + (1 if pointwise else 0)

    rows: List[np.ndarray] = []
    lower: List[float] = []
    upper: List[float] = []

    def add_row(values: Mapping[int, float], lo: float, hi: float) -> None:
        row = np.zeros(nvars, dtype=float)
        for j, value in values.items():
            row[j] += float(value)
        rows.append(row)
        lower.append(float(lo))
        upper.append(float(hi))

    # 预算：观测成本 + 新设站固定成本。
    if budget is not None:
        values: Dict[int, float] = {}
        for i, cand in enumerate(cands):
            values[i] = cand.cost
        for name in new_stations:
            values[station_index[name]] = model.station_cost(name)
        add_row(values, -np.inf, budget)

    # y_s ≥ x_e（y 为 1 表示该站被使用）。
    for i, cand in enumerate(cands):
        for station in cand.station_names:
            j = station_index.get(station)
            if j is not None:
                add_row({i: 1.0, j: -1.0}, -np.inf, 0.0)

    # 线性代理目标：逐点/逐边贡献约束。
    if criterion == "max_mp":
        for p, value in enumerate(base_mp):
            values = {z_index: -1.0}
            for i in range(n):
                values[i] = -float(point_gains[i][p])
            add_row(values, -np.inf, -float(value))
    elif criterion == "worst_rel":
        for e, value in enumerate(base_edge_rel):
            values = {z_index: -1.0}
            for i in range(n):
                values[i] = -float(edge_gains[i][e])
            add_row(values, -np.inf, -float(value))

    c = np.zeros(nvars, dtype=float)
    if pointwise:
        c[z_index] = 1.0
        for i, cand in enumerate(cands):
            c[i] = 1e-6 * cand.cost
    else:
        for i, cand in enumerate(cands):
            c[i] = -float(scalar_gains[i]) + 1e-6 * cand.cost
    for name in new_stations:
        c[station_index[name]] = 1e-9 * model.station_cost(name)

    integrality = np.zeros(nvars, dtype=int)
    integrality[: n + len(new_stations)] = 1
    lb = np.zeros(nvars, dtype=float)
    ub = np.ones(nvars, dtype=float)
    if pointwise:
        ub[z_index] = np.inf
    bounds = Bounds(lb, ub)
    constraints = []
    if rows:
        constraints.append(
            LinearConstraint(
                csr_matrix(np.vstack(rows)),
                np.asarray(lower),
                np.asarray(upper),
            )
        )

    options: Dict[str, Any] = {}
    if time_limit is not None:
        options["time_limit"] = float(time_limit)
    result = milp(
        c,
        integrality=integrality,
        bounds=bounds,
        constraints=constraints,
        options=options or None,
    )
    if result.x is None:
        # 求解失败时退回贪心 + 局部搜索，仍标记为近似。
        greedy = optimize(
            net,
            cands,
            criterion=criterion,
            budget=budget,
            datum=datum,
            parameter_order=parameter_order,
            parameter_scales=parameter_scales,
            cost_model=model,
            local_search=True,
            max_local_iterations=max_local_iterations,
        )
        selected = _indices_for_selected(cands, greedy.selected)
        search = {
            "best_mask": sum(1 << i for i in selected),
            "nodes": 0,
            "elapsed": 0.0,
        }
        return _build_exact_result(
            net,
            cands,
            criterion,
            budget,
            target,
            datum,
            parameter_order,
            parameter_scales,
            model,
            search,
            method="milp_fallback_greedy",
            exact=False,
            proxy_objective=None,
            notes=f"MILP 求解失败（{result.message}），退回贪心局部搜索",
        )

    selected = [i for i in range(n) if float(result.x[i]) > 0.5]
    milp_selected, milp_cost, milp_metrics, _iters = _local_search_indices(
        net,
        cands,
        selected,
        criterion,
        budget,
        datum,
        parameter_order,
        parameter_scales,
        model,
        max_iterations=max_local_iterations,
        min_gain=gap_tol,
    )

    greedy = optimize(
        net,
        cands,
        criterion=criterion,
        budget=budget,
        datum=datum,
        parameter_order=parameter_order,
        parameter_scales=parameter_scales,
        cost_model=model,
        local_search=True,
        max_local_iterations=max_local_iterations,
    )
    greedy_selected = _indices_for_selected(cands, greedy.selected)
    if greedy.final_metrics.objective < milp_metrics.objective - gap_tol * max(
        1.0, abs(greedy.final_metrics.objective)
    ):
        chosen = greedy_selected
        chosen_cost = greedy.spent
        chosen_metrics = greedy.final_metrics
        source = "MILP 代理解经局部搜索后仍劣于贪心局部搜索，取后者"
    else:
        chosen = milp_selected
        chosen_cost = milp_cost
        chosen_metrics = milp_metrics
        source = "MILP 线性代理 + 真实目标评价 + 1 加/1 换 1 局部搜索"

    search = {
        "best_mask": sum(1 << i for i in chosen),
        "nodes": int(getattr(result, "mip_node_count", 0) or 0),
        "elapsed": 0.0,
    }
    built = _build_exact_result(
        net,
        cands,
        criterion,
        budget,
        target,
        datum,
        parameter_order,
        parameter_scales,
        model,
        search,
        method="milp_proxy",
        exact=False,
        proxy_objective=float(result.fun),
        notes=source + "；线性代理为近似，不保证全局最优",
    )
    # 选用精确评价后的成本/目标，避免代理与真实目标混淆。
    built.spent = chosen_cost
    built.objective_value = chosen_metrics.objective
    return built


__all__ = [
    "CRITERIA",
    "Candidate",
    "CostModel",
    "ObjectiveMetrics",
    "OptimizationStep",
    "SwapStep",
    "OptimizationResult",
    "ExactOptimizationResult",
    "optimize",
    "greedy_optimize",
    "local_search_optimize",
    "exact_optimize",
    "exhaustive_optimize",
    "brute_force_optimize",
    "milp_optimize",
    "milp_available",
]
