"""独立观测组的经典 Helmert 方差分量估计（固定线性化、固定基准）。"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

import numpy as np


class VCEError(ValueError):
    """方差分量不可辨识、奇异或非正。"""


class VCEConvergenceError(RuntimeError):
    """迭代在给定次数内未收敛。"""


@dataclass
class VCEResult:
    variance_factors: dict
    history: list
    parameters: np.ndarray
    residuals: dict
    covariance: np.ndarray
    precision_summary: dict
    updated_weights: dict


def estimate(groups: Mapping, *, initial_factors=None, tol=1e-7, max_iterations=100):
    """估计 Cov(l_g)=σ²_g P_g⁻¹；groups={名称: (A_g, P_g, l_g)}。

    各组独立，P 可为正对角向量或对称正定阵，l 是观测减计算值。
    每次令 W_g=P_g/σ²_g，N_g=A_gᵀW_g A_g，Q=(ΣN_g)⁻¹，
    x=QΣA_gᵀW_g l_g，v_g=l_g−A_g x。经典 Helmert 方程为
    S θ=q，其中 q_g=v_gᵀW_g v_g，
    S_gh=δ_gh(n_g−2 tr(Q N_g))+tr(Q N_g Q N_h)。
    更新 σ²_g ← σ²_g θ_g；max|θ_g−1|≤tol 时收敛，随后重新平差。
    单组即 vᵀPv/(n−u)。历史记录更新后的因子与相对变化。
    精度为更新权后的 Q（不再乘后验单位权方差），摘要含参数标准差、
    冗余数和后验单位权方差。固定线性模型；不支持跨组相关或自由网。
    奇异/非正分量抛 VCEError；超限抛 VCEConvergenceError。
    """
    if not groups or not np.isfinite(tol) or tol <= 0 or not isinstance(max_iterations, int) or max_iterations < 1:
        raise ValueError("需要非空分组、正 tol 和正整数 max_iterations")
    names = list(groups)
    data, weights = [], []
    columns = None
    for name in names:
        a, p, l = (np.asarray(z, dtype=float) for z in groups[name])
        if p.ndim == 1:
            p = np.diag(p)
        if a.ndim != 2 or not a.shape[0] or not a.shape[1] or l.shape != (a.shape[0],) or p.shape != (len(l), len(l)):
            raise ValueError("分组 A/P/l 维数不匹配或为空")
        if columns is not None and columns != a.shape[1]:
            raise ValueError("各组必须共享参数列")
        columns = a.shape[1]
        if not all(np.all(np.isfinite(z)) for z in (a, p, l)) or not np.allclose(p, p.T, rtol=1e-12, atol=0):
            raise ValueError("输入必须有限，P 必须对称")
        try:
            root = np.linalg.cholesky(p)
        except np.linalg.LinAlgError as exc:
            raise VCEError("权阵必须正定") from exc
        data.append((root.T @ a, root.T @ l))
        weights.append(p)
    factors = np.array([1.0 if initial_factors is None else initial_factors[n] for n in names], dtype=float)
    if not np.all(np.isfinite(factors)) or np.any(factors <= 0):
        raise ValueError("初始方差因子必须有限且为正")
    # 列归一化避免坐标、角度等参数单位影响秩判断。
    scale = np.linalg.norm(np.vstack([a for a, _ in data]), axis=0)
    if np.any(scale == 0):
        raise VCEError("设计矩阵奇异（秩亏）")
    data = [(a / scale, l) for a, l in data]

    def fit(f):
        aw = np.vstack([a / np.sqrt(t) for (a, _), t in zip(data, f)])
        if np.linalg.matrix_rank(aw) < columns:
            raise VCEError("设计矩阵奇异（秩亏）")
        normals = [a.T @ a / t for (a, _), t in zip(data, f)]
        try:
            qxx = np.linalg.inv(sum(normals))
        except np.linalg.LinAlgError as exc:
            raise VCEError("正规方程奇异") from exc
        x = qxx @ sum(a.T @ l / t for (a, l), t in zip(data, f))
        residual = [l - a @ x for a, l in data]
        return normals, qxx, x, residual

    history = []
    for iteration in range(1, max_iterations + 1):
        normals, qxx, x, residual = fit(factors)
        products = [qxx @ n for n in normals]
        s = np.array([[np.trace(b @ c) for c in products] for b in products])
        s += np.diag([len(l) - 2 * np.trace(b) for (_, l), b in zip(data, products)])
        rhs = np.array([v @ v / t for v, t in zip(residual, factors)])
        if np.linalg.matrix_rank(s) < len(names):
            raise VCEError("Helmert 分量方程奇异：组冗余不足或分量不可辨识")
        theta = np.linalg.solve(s, rhs)
        if not np.all(np.isfinite(theta)) or np.any(theta <= 0):
            raise VCEError("Helmert 估计得到非正方差分量")
        change = float(np.max(np.abs(theta - 1)))
        factors *= theta
        history.append(dict(iteration=iteration, variance_factors=dict(zip(names, factors.copy())), relative_change=change))
        if change <= tol:
            break
    else:
        raise VCEConvergenceError(f"VCE 在 {max_iterations} 次迭代内未收敛")
    _, qxx, x, residual = fit(factors)
    covariance = qxx / scale[:, None] / scale[None, :]
    dof = sum(len(l) for _, l in data) - columns
    return VCEResult(dict(zip(names, factors)), history, x / scale,
                     {n: np.asarray(groups[n][2]) - np.asarray(groups[n][0]) @ (x / scale) for n in names},
                     covariance, dict(parameter_std=np.sqrt(np.diag(covariance)), redundancy=dof,
                                      sigma0_sq=float(sum(v @ v / t for v, t in zip(residual, factors)) / dof)),
                     {n: p / t for n, p, t in zip(names, weights, factors)})


def estimate_gnss_ground(adjustment, misclosures, **options):
    """把现有 solve_gnss/solve 结果与同 A 行序的实测减计算值接入两组 VCE。

    返回 VCEResult，parameters 为坐标改正量、covariance 为更新后参数精度。
    不修改原设计态结果；GNSS 块归 gnss，distance 块归 ground。
    为避免错误随机模型，拒绝角度、水准、伪约束及跨组协方差。
    """
    design = adjustment.design
    rows = {"gnss": [], "ground": []}
    for block in design.blocks:
        if block.kind not in ("gnss", "distance"):
            raise ValueError("两组桥接仅支持 GNSS 基线和地面距离，且必须使用固定基准")
        rows["gnss" if block.kind == "gnss" else "ground"].extend(block.rows)
    l = np.asarray(misclosures, dtype=float)
    if l.shape != (len(design.A),) or sorted(rows['gnss'] + rows['ground']) != list(range(len(l))):
        raise ValueError("misclosures 必须覆盖全部设计行")
    if not all(rows.values()):
        raise ValueError("需要 GNSS 和地面距离两组")
    if np.any(design.Ql[np.ix_(rows['gnss'], rows['ground'])] != 0):
        raise ValueError("不支持跨组相关")
    groups = {n: (design.A[r], np.linalg.inv(design.Ql[np.ix_(r, r)]), l[r]) for n, r in rows.items()}
    return estimate(groups, **options)
