"""三维七参数 Helmert 小角相似变换。

参数顺序为 TX, TY, TZ（米）, RX, RY, RZ（弧度）, s（ppm）。采用
右手系主动旋转（position-vector）约定：y = t + (1+s*1e-6)x + r×x。
这是同时忽略角度平方及尺度与角度乘积的一阶近似，不是有限角旋转。
坐标以米表示；逆变换精确求解上述线性模型，不以参数取负近似。
"""

from __future__ import annotations

from typing import NamedTuple

import numpy as np


class HelmertResult(NamedTuple):
    """参数、参数协方差、dst−forward(src) 残差及单位权方差。"""

    params: np.ndarray
    covariance: np.ndarray
    residuals: np.ndarray
    sigma0_sq: float


def _points(points):
    values = np.asarray(points, dtype=float)
    if values.ndim != 2 or values.shape[1] != 3 or not np.all(np.isfinite(values)):
        raise ValueError("坐标必须是有限的 (n, 3) 数组")
    return values


def _transform(params):
    p = np.asarray(params, dtype=float)
    if p.shape != (7,) or not np.all(np.isfinite(p)):
        raise ValueError("params 必须是长度 7 的有限参数向量")
    rx, ry, rz = p[3:6]
    matrix = np.array([[0, -rz, ry], [rz, 0, -rx], [-ry, rx, 0]], dtype=float)
    matrix += (1.0 + p[6] * 1e-6) * np.eye(3)
    return p[:3], matrix


def forward(points, params):
    """将 (n,3) 米制坐标正向变换；参数单位及小角约定见模块说明。"""
    translation, matrix = _transform(params)
    return _points(points) @ matrix.T + translation


def inverse(points, params):
    """将 (n,3) 米制坐标逆变换，精确求逆小角模型的矩阵。"""
    translation, matrix = _transform(params)
    try:
        return np.linalg.solve(matrix, (_points(points) - translation).T).T
    except np.linalg.LinAlgError as exc:
        raise ValueError("变换矩阵不可逆") from exc


def estimate(src, dst, weights=None):
    """以至少三个非共线公共点估计七参数（源坐标视为无误差）。

    src/dst 为 (n,3) 米制坐标。weights 为正的相对逆方差，可为每点
    (n,) 或每分量 (n,3)/(3*n,)；默认等权，不支持相关权阵。
    返回可解包的 HelmertResult，参数顺序及单位见模块说明；协方差
    顺序相同，单位为相应参数单位的乘积，计算为 σ0²(AᵀWA)⁻¹。
    残差为 dst−forward(src)，形状 (n,3)；σ0²=vᵀWv/(3*n−7)。
    点数不足、几何退化或输入无效时抛出 ValueError。
    """
    source, target = _points(src), _points(dst)
    if source.shape != target.shape:
        raise ValueError("src 与 dst 形状必须相同")
    n = len(source)
    if n < 3:
        raise ValueError("至少需要 3 个公共点")
    design = np.zeros((n, 3, 7))
    design[:, :, :3] = np.eye(3)
    x, y, z = source.T
    design[:, 0, 4], design[:, 0, 5] = z, -y
    design[:, 1, 3], design[:, 1, 5] = -z, x
    design[:, 2, 3], design[:, 2, 4] = y, -x
    design[:, :, 6] = source * 1e-6
    design = design.reshape(-1, 7)
    if weights is None:
        weight = np.ones(3 * n)
    else:
        weight = np.asarray(weights, dtype=float)
        if weight.shape == (n,):
            weight = np.repeat(weight, 3)
        elif weight.shape == (n, 3):
            weight = weight.ravel()
        if weight.shape != (3 * n,) or not np.all(np.isfinite(weight)) or np.any(weight <= 0):
            raise ValueError("weights 必须为正的有限每点或每分量权")
    whitened = design * np.sqrt(weight)[:, None]
    observations = (target - source).ravel() * np.sqrt(weight)
    # 列归一化避免米、弧度、ppm 的量级差影响秩判定与求解。
    scales = np.linalg.norm(whitened, axis=0)
    if np.any(scales == 0):
        raise ValueError("公共点几何退化")
    normalized = whitened / scales
    u, singular, vt = np.linalg.svd(normalized, full_matrices=False)
    if singular[-1] <= np.finfo(float).eps * max(normalized.shape) * singular[0]:
        raise ValueError("公共点几何退化（共线或重合）")
    params = (vt.T @ ((u.T @ observations) / singular)) / scales
    residuals = target - forward(source, params)
    sigma0_sq = float(np.dot(residuals.ravel() * weight, residuals.ravel()) / (3 * n - 7))
    factor = vt.T / singular / scales[:, None]
    covariance = sigma0_sq * (factor @ factor.T)
    return HelmertResult(params, covariance, residuals, sigma0_sq)
