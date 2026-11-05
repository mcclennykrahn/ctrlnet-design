"""小规模成本—精度 Pareto 前沿，复用现有精确优化器。"""
from dataclasses import dataclass
from math import isfinite
from typing import Any, List, Optional, Sequence

from .optimize import (
    Candidate, CostModel, ExactOptimizationResult, _parse_candidates,
    exact_optimize,
)


@dataclass
class ParetoResult:
    criterion: str
    points: List[ExactOptimizationResult]
    budgets: List[float]
    complete: bool


def pareto_frontier(
    base: Any,
    candidates: Sequence[Any],
    criterion: str = "max_mp",
    budgets: Optional[Sequence[float]] = None,
    cost_model: Optional[CostModel] = None,
    max_candidates: int = 12,
    **kwargs: Any,
) -> ParetoResult:
    """以成本为 ε 约束，最小化 A/D/E/max_mp（均越小越好）。

    默认枚举全部子集成本作为预算，得到完整的目标空间前沿；同成本或
    同精度（相对容差 1e-12）只保留一个代表。显式 budgets 返回采样预算中的非支配解，
    complete=False，不声称覆盖预算间的折中点。默认最多 12 个候选，
    避免非整数成本导致指数级预算扫描。cost_model 支持一次性设站成本；
    边长代价可直接作为 Candidate.cost 输入。kwargs 透传 datum 等参数。
    """
    cands = _parse_candidates(candidates, None)
    if len(cands) > max_candidates:
        raise ValueError(f"Pareto 候选数超过上限 {max_candidates}")
    model = cost_model or CostModel()
    complete = budgets is None
    if complete:
        scan = sorted({model.total_cost(cands, [i for i in range(len(cands))
                       if mask & (1 << i)]) for mask in range(1 << len(cands))})
    else:
        scan = sorted(set(float(b) for b in budgets))
        if not scan or any(not isfinite(b) or b < 0 for b in scan):
            raise ValueError("budgets 必须包含非负有限预算")
    results = [exact_optimize(base, cands, criterion=criterion, budget=b,
               cost_model=model, max_candidates=max_candidates, gap_tol=0.0,
               **kwargs) for b in scan]
    # 按真实花费排序，而非预算；删除重复解及所有弱劣解。
    points = []
    best = float("inf")
    for result in sorted(results, key=lambda r: (r.spent, r.objective_value)):
        if not points or result.objective_value < best - 1e-12 * max(abs(best), 1e-30):
            points.append(result)
            best = result.objective_value
    return ParetoResult(results[0].criterion, points, scan,
                        complete and all(r.exact for r in results))
