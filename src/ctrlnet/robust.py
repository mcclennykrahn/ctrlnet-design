"""模拟观测、数据探测（Baarda w / Pope τ）与稳健估计（Huber / IGG-III）。

本模块对应 ``docs/redesign_plan.md`` §5.4、§5.10：

- 由设计网的真实坐标生成带先验随机误差的观测值，并可向指定观测注入粗差；
- 非线性平面网用高斯-牛顿迭代从近似坐标求解，水准网为线性迭代；
- Baarda w 检验（σ0 已知）、Pope τ 检验（σ0 未知）与 χ² 整体模型检验；
- Huber / IGG-III 迭代重加权最小二乘，标准化残差 + MAD 尺度。

单位约定与其余模块一致：内部长度/高程为米、角度为弧度；显示时距离/高差
用 mm、角度用角秒。所有观测残差、w 统计量与权因子均按“设计矩阵行”存储；
GNSS 2D 基线占两行，按观测分组时取组内最小权因子/最大检验量。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from math import atan2, exp, hypot, isfinite, lgamma, log, pi, sqrt
from statistics import NormalDist
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple, Union

import numpy as np

from .datum import Datum, FixedDatum, FreeDatum, MinimalDatum, WeightedDatum, normalize_datum
from .design import ParameterIndex, build_design, build_parameter_index
from .exceptions import AdjustmentError, InvalidPrecisionError, RankDeficientError
from .leveling import LevelingNetwork, LevelingPoint
from .model import (
    Angle,
    CoordinateConstraint,
    Direction,
    Distance,
    GnssBaseline2D,
    Network,
    Observation,
    Point,
)

TWO_PI = 2.0 * pi

# §5.10.2 默认 α0=0.001 的双侧临界值。
DEFAULT_ALPHA = 0.001
DEFAULT_W_CRITICAL = 3.29
DEFAULT_HUBER_C = 1.345
DEFAULT_IGG_K0 = 1.5
DEFAULT_IGG_K1 = 3.0
DEFAULT_MAX_ITER = 50
DEFAULT_TOL = 1e-8


# ---------------------------------------------------------------------------
# 基础工具
# ---------------------------------------------------------------------------


def _wrap_angle(value: Any) -> np.ndarray:
    """把角度差包裹到 (-π, π]。"""
    arr = np.asarray(value, dtype=float)
    return (arr + pi) % TWO_PI - pi


def _wrap_positive(value: Any) -> np.ndarray:
    """把方向/角度包裹到 [0, 2π)。"""
    return np.mod(np.asarray(value, dtype=float), TWO_PI)


def _as_vector(value: Any, what: str) -> np.ndarray:
    arr = np.asarray(value, dtype=float).reshape(-1)
    if arr.size == 0:
        raise InvalidPrecisionError(f"{what} 不能为空")
    if not np.all(np.isfinite(arr)):
        raise InvalidPrecisionError(f"{what} 含非有限值")
    return arr


def _point_ref_name(ref: Any) -> str:
    if isinstance(ref, str):
        return ref
    name = getattr(ref, "name", None)
    if isinstance(name, str):
        return name
    raise TypeError(f"点引用必须是 str 或带 name 属性的对象，收到 {type(ref)!r}")


def _mad_scale(values: Any) -> float:
    """MAD 稳健尺度，归一到标准差（1.4826·MAD）。"""
    arr = np.asarray(values, dtype=float).reshape(-1)
    arr = arr[np.isfinite(arr)]
    if arr.size == 0:
        return 1.0
    med = float(np.median(arr))
    scale = 1.4826 * float(np.median(np.abs(arr - med)))
    if not isfinite(scale) or scale <= 1e-12:
        scale = 1.4826 * float(np.median(np.abs(arr)))
    if not isfinite(scale) or scale <= 1e-12:
        scale = 1.0
    return scale


# ---------------------------------------------------------------------------
# χ² / t 分布（纯 Python，避免新增 scipy 依赖）
# ---------------------------------------------------------------------------


def _gammaincc(a: float, x: float) -> float:
    """正则化上不完全 Gamma 函数 Q(a, x)。"""
    if x <= 0.0:
        return 1.0
    if not isfinite(x):
        return 0.0
    gln = lgamma(a)
    eps = 1e-14
    if x < a + 1.0:
        # 级数展开
        ap = a
        total = 1.0 / a
        delta = total
        for _ in range(1000):
            ap += 1.0
            delta *= x / ap
            total += delta
            if abs(delta) < abs(total) * eps:
                break
        return max(0.0, 1.0 - total * exp(-x + a * log(x) - gln))
    # 连分式（Lentz）
    tiny = 1e-300
    b = x + 1.0 - a
    c = 1.0 / tiny
    d = 1.0 / b
    h = d
    for i in range(1, 1000):
        an = -i * (i - a)
        b += 2.0
        d = an * d + b
        if abs(d) < tiny:
            d = tiny
        c = b + an / c
        if abs(c) < tiny:
            c = tiny
        d = 1.0 / d
        delta = d * c
        h *= delta
        if abs(delta - 1.0) < eps:
            break
    return max(0.0, min(1.0, exp(-x + a * log(x) - gln) * h))


def chi2_cdf(value: float, dof: int) -> float:
    """χ² 分布 CDF。"""
    if dof <= 0:
        raise ValueError("dof 必须为正整数")
    return 1.0 - _gammaincc(0.5 * float(dof), 0.5 * float(value))


def chi2_sf(value: float, dof: int) -> float:
    """χ² 分布上尾概率 P(χ²_dof ≥ value)。"""
    if dof <= 0:
        raise ValueError("dof 必须为正整数")
    return _gammaincc(0.5 * float(dof), 0.5 * float(value))


def chi2_critical(dof: int, alpha: float = 0.05) -> float:
    """χ² 上尾临界值，使 ``P(χ²_dof ≥ crit) = alpha``。"""
    dof = int(dof)
    alpha = float(alpha)
    if dof <= 0:
        raise ValueError("dof 必须为正整数")
    if not (0.0 < alpha < 1.0):
        raise ValueError("alpha 必须满足 0 < alpha < 1")
    lo, hi = 0.0, max(100.0, 10.0 * dof + 50.0)
    while chi2_sf(hi, dof) > alpha:
        hi *= 2.0
    for _ in range(200):
        mid = 0.5 * (lo + hi)
        if chi2_sf(mid, dof) > alpha:
            lo = mid
        else:
            hi = mid
    return 0.5 * (lo + hi)


def _betacf(a: float, b: float, x: float) -> float:
    """正则化不完全 Beta 函数的连分式。"""
    tiny = 1e-300
    eps = 1e-14
    qab = a + b
    qap = a + 1.0
    qam = a - 1.0
    c = 1.0
    d = 1.0 - qab * x / qap
    if abs(d) < tiny:
        d = tiny
    d = 1.0 / d
    h = d
    for m in range(1, 1000):
        m2 = 2 * m
        aa = m * (b - m) * x / ((qam + m2) * (a + m2))
        d = 1.0 + aa * d
        if abs(d) < tiny:
            d = tiny
        c = 1.0 + aa / c
        if abs(c) < tiny:
            c = tiny
        d = 1.0 / d
        h *= d * c
        aa = -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2))
        d = 1.0 + aa * d
        if abs(d) < tiny:
            d = tiny
        c = 1.0 + aa / c
        if abs(c) < tiny:
            c = tiny
        d = 1.0 / d
        delta = d * c
        h *= delta
        if abs(delta - 1.0) < eps:
            break
    return h


def _betai(a: float, b: float, x: float) -> float:
    """正则化不完全 Beta 函数 I_x(a, b)。"""
    if x <= 0.0:
        return 0.0
    if x >= 1.0:
        return 1.0
    bt = exp(
        lgamma(a + b)
        - lgamma(a)
        - lgamma(b)
        + a * log(x)
        + b * log(1.0 - x)
    )
    if x < (a + 1.0) / (a + b + 2.0):
        return bt * _betacf(a, b, x) / a
    return 1.0 - bt * _betacf(b, a, 1.0 - x) / b


def student_t_sf(value: float, dof: int) -> float:
    """Student-t 上尾概率（value ≥ 0）。"""
    dof = int(dof)
    if dof <= 0:
        raise ValueError("dof 必须为正整数")
    value = float(value)
    if value <= 0.0:
        return 0.5
    return 0.5 * _betai(0.5 * dof, 0.5, dof / (dof + value * value))


def t_critical(dof: int, alpha: float = 0.05) -> float:
    """双侧 t 临界值 ``t_{1-α/2, dof}``。"""
    dof = int(dof)
    alpha = float(alpha)
    if dof <= 0:
        raise ValueError("dof 必须为正整数")
    if not (0.0 < alpha < 1.0):
        raise ValueError("alpha 必须满足 0 < alpha < 1")
    target = alpha / 2.0
    lo, hi = 0.0, 1.0
    while student_t_sf(hi, dof) > target:
        hi *= 2.0
        if hi > 1e8:
            break
    for _ in range(200):
        mid = 0.5 * (lo + hi)
        if student_t_sf(mid, dof) > target:
            lo = mid
        else:
            hi = mid
    return 0.5 * (lo + hi)


# ---------------------------------------------------------------------------
# 模拟观测
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class BlunderSpec:
    """粗差注入规格。

    ``observation`` 可为观测序号、观测标签或观测对象；
    ``magnitude`` 为标量或按设计矩阵行给出的序列；
    ``unit='sigma'`` 表示 k·σ（默认），``unit='absolute'`` 表示观测值单位。
    """

    observation: Union[int, str, Observation]
    magnitude: Union[float, Sequence[float]]
    unit: str = "sigma"

    def __post_init__(self) -> None:
        if self.unit not in ("sigma", "absolute"):
            raise ValueError("BlunderSpec.unit 只能是 'sigma' 或 'absolute'")


@dataclass
class SimulatedObservation:
    """一条模拟观测（GNSS 基线包含两行）。"""

    index: int
    observation: Any
    label: str
    kind: str
    values: np.ndarray
    truth: np.ndarray
    sigma: np.ndarray
    blunder: np.ndarray
    rows: Tuple[int, ...]

    @property
    def n_rows(self) -> int:
        return int(self.values.size)

    @property
    def outlier(self) -> bool:
        return bool(np.any(np.abs(self.blunder) > 0.0))

    @property
    def blunder_sigma_ratio(self) -> float:
        mask = self.sigma > 0.0
        if not np.any(mask):
            return 0.0
        return float(np.max(np.abs(self.blunder[mask] / self.sigma[mask])))


@dataclass
class ObservationDataset:
    """由真值坐标模拟得到的观测集。"""

    network: Any
    records: List[SimulatedObservation]
    kind: str
    true_coordinates: Dict[str, Tuple[float, ...]]
    seed: Optional[int] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def n_observations(self) -> int:
        return len(self.records)

    @property
    def row_count(self) -> int:
        return sum(rec.n_rows for rec in self.records)

    @property
    def labels(self) -> List[str]:
        return [rec.label for rec in self.records]

    @property
    def observations(self) -> List[Any]:
        return [rec.observation for rec in self.records]

    @property
    def outlier_indices(self) -> List[int]:
        return [rec.index for rec in self.records if rec.outlier]

    @property
    def outlier_labels(self) -> List[str]:
        return [rec.label for rec in self.records if rec.outlier]

    def record(self, ref: Union[int, str, Observation]) -> SimulatedObservation:
        idx = _resolve_observation_key(self.records, ref)
        return self.records[idx]

    def values(self, ref: Union[int, str, Observation]) -> np.ndarray:
        return self.record(ref).values.copy()

    def sigma(self, ref: Union[int, str, Observation]) -> np.ndarray:
        return self.record(ref).sigma.copy()

    def __getitem__(self, ref: Union[int, str, Observation]) -> SimulatedObservation:
        return self.record(ref)


def _resolve_observation_key(
    records: Sequence[SimulatedObservation],
    ref: Union[int, str, Observation],
) -> int:
    if isinstance(ref, (int, np.integer)):
        idx = int(ref)
        if idx < 0 or idx >= len(records):
            raise KeyError(f"观测序号越界：{idx}，共 {len(records)} 条")
        return idx
    if isinstance(ref, str):
        matches = [rec.index for rec in records if rec.label == ref]
        if not matches:
            raise KeyError(f"观测标签不存在：{ref!r}")
        if len(matches) > 1:
            raise ValueError(f"观测标签不唯一：{ref!r}，请改用观测序号")
        return matches[0]
    for rec in records:
        if rec.observation is ref:
            return rec.index
    raise KeyError(f"观测对象不在数据集中：{ref!r}")


def _planar_truth(network: Network, obs: Any) -> Tuple[np.ndarray, np.ndarray, bool]:
    """返回 (当前坐标下的观测真值, 先验 σ, 是否为角度型观测)。"""
    if isinstance(obs, Distance):
        p1 = network.point(obs.frm)
        p2 = network.point(obs.to)
        s = hypot(p2.E - p1.E, p2.N - p1.N)
        if s <= 0.0:
            raise InvalidPrecisionError(f"{obs.label} 两端点重合")
        return np.array([s]), np.array([obs.sigma(s)]), False
    if isinstance(obs, Direction):
        p1 = network.point(obs.station)
        p2 = network.point(obs.target)
        alpha = atan2(p2.E - p1.E, p2.N - p1.N)
        return (
            _wrap_positive([alpha]),
            np.array([obs.sigma_rad]),
            True,
        )
    if isinstance(obs, Angle):
        ps = network.point(obs.station)
        pb = network.point(obs.backsight)
        pf = network.point(obs.foresight)
        alpha_b = atan2(pb.E - ps.E, pb.N - ps.N)
        alpha_f = atan2(pf.E - ps.E, pf.N - ps.N)
        return (
            _wrap_positive([alpha_f - alpha_b]),
            np.array([obs.sigma_rad]),
            True,
        )
    if isinstance(obs, GnssBaseline2D):
        p1 = network.point(obs.frm)
        p2 = network.point(obs.to)
        return (
            np.array([p2.E - p1.E, p2.N - p1.N], dtype=float),
            np.array([obs.sigma_E, obs.sigma_N], dtype=float),
            False,
        )
    raise TypeError(f"不支持的平面观测类型：{type(obs)!r}")


def _leveling_truth(network: LevelingNetwork, obs: Any) -> Tuple[np.ndarray, np.ndarray, bool]:
    h1 = network.point(obs.frm).H
    h2 = network.point(obs.to).H
    return np.array([h2 - h1], dtype=float), np.array([float(obs.sigma)]), False


def _observation_truth(
    network: Any, obs: Any
) -> Tuple[np.ndarray, np.ndarray, bool]:
    if isinstance(network, LevelingNetwork):
        return _leveling_truth(network, obs)
    return _planar_truth(network, obs)


def _blunder_offsets(
    magnitude: Any,
    unit: str,
    sigma: np.ndarray,
    what: str,
) -> np.ndarray:
    values = np.asarray(magnitude, dtype=float)
    if values.ndim == 0:
        values = np.full(sigma.shape, float(values), dtype=float)
    else:
        values = values.reshape(-1)
        if values.size == 1:
            values = np.full(sigma.shape, float(values[0]), dtype=float)
        elif values.size != sigma.size:
            raise ValueError(
                f"{what} 的粗差向量长度应为 1 或 {sigma.size}，收到 {values.size}"
            )
    if not np.all(np.isfinite(values)):
        raise InvalidPrecisionError(f"{what} 的粗差含非有限值")
    if unit == "sigma":
        return values * sigma
    if unit == "absolute":
        return values
    raise ValueError("粗差单位只能是 'sigma' 或 'absolute'")


def simulate_observations(
    network: Any,
    *,
    seed: Optional[int] = None,
    blunders: Optional[
        Union[
            Mapping[Union[int, str, Observation], Union[float, Sequence[float]]],
            Iterable[BlunderSpec],
        ]
    ] = None,
    blunder_unit: str = "sigma",
    noise: bool = True,
) -> ObservationDataset:
    """由设计网真值坐标生成带随机误差的观测值。

    Parameters
    ----------
    network:
        :class:`ctrlnet.Network`（平面）或 :class:`ctrlnet.LevelingNetwork`。
        点坐标/高程被视为真值。
    seed:
        随机种子；固定种子可复现。
    blunders:
        粗差注入。dict 的键为观测序号/标签/观测对象，值为 k（默认 k·σ）
        或按行给出的序列；也可传 :class:`BlunderSpec` 序列逐条指定单位。
    blunder_unit:
        dict 形式的默认单位，``'sigma'`` 或 ``'absolute'``。
    noise:
        False 时只保留粗差，不加随机噪声。
    """
    if blunder_unit not in ("sigma", "absolute"):
        raise ValueError("blunder_unit 只能是 'sigma' 或 'absolute'")
    if isinstance(network, LevelingNetwork):
        kind = "leveling"
        observations = list(network.observations)
    elif isinstance(network, Network):
        kind = "planar"
        observations = list(network.observations)
    else:
        raise TypeError("network 必须是 Network 或 LevelingNetwork")

    # 统一解析粗差规格。
    specs: Dict[int, Tuple[Any, str]] = {}

    def _put(ref: Any, magnitude: Any, unit: str) -> None:
        records_stub = [
            SimulatedObservation(
                index=i,
                observation=obs,
                label=obs.label,
                kind=obs.kind,
                values=np.zeros(1),
                truth=np.zeros(1),
                sigma=np.ones(1),
                blunder=np.zeros(1),
                rows=(),
            )
            for i, obs in enumerate(observations)
        ]
        idx = _resolve_observation_key(records_stub, ref)
        if idx in specs:
            raise ValueError(f"观测 {idx} 的粗差被重复指定")
        specs[idx] = (magnitude, unit)

    if blunders is not None:
        if isinstance(blunders, Mapping):
            for ref, magnitude in blunders.items():
                _put(ref, magnitude, blunder_unit)
        else:
            for spec in blunders:
                if not isinstance(spec, BlunderSpec):
                    raise TypeError("blunders 序列的元素必须是 BlunderSpec")
                _put(spec.observation, spec.magnitude, spec.unit)

    rng = np.random.default_rng(seed)
    records: List[SimulatedObservation] = []
    row = 0
    for i, obs in enumerate(observations):
        truth, sigma, is_angle = _observation_truth(network, obs)
        sigma = _as_vector(sigma, f"{obs.label} 的先验 σ")
        truth = _as_vector(truth, f"{obs.label} 的真值")
        if truth.size != sigma.size:
            raise InvalidPrecisionError(f"{obs.label} 的真值与 σ 长度不一致")
        offset = np.zeros_like(truth)
        if i in specs:
            magnitude, unit = specs[i]
            offset = _blunder_offsets(
                magnitude, unit, sigma, f"{obs.label} 的粗差"
            )
        random_part = rng.normal(0.0, sigma) if noise else np.zeros_like(truth)
        values = truth + random_part + offset
        if is_angle:
            values = _wrap_positive(values)
        n_rows = int(truth.size)
        records.append(
            SimulatedObservation(
                index=i,
                observation=obs,
                label=obs.label,
                kind=obs.kind,
                values=values,
                truth=truth.copy(),
                sigma=sigma.copy(),
                blunder=offset.copy(),
                rows=tuple(range(row, row + n_rows)),
            )
        )
        row += n_rows

    if kind == "leveling":
        truth_coords = {
            p.name: (float(p.H),) for p in network.points
        }
    else:
        truth_coords = {
            p.name: (float(p.E), float(p.N)) for p in network.points
        }

    return ObservationDataset(
        network=network,
        records=records,
        kind=kind,
        true_coordinates=truth_coords,
        seed=seed,
        metadata={
            "noise": bool(noise),
            "blunder_unit": blunder_unit,
            "blunder_labels": [records[i].label for i in specs],
        },
    )


def simulate_planar(network: Network, **kwargs: Any) -> ObservationDataset:
    return simulate_observations(network, **kwargs)


def simulate_leveling(network: LevelingNetwork, **kwargs: Any) -> ObservationDataset:
    return simulate_observations(network, **kwargs)


# ---------------------------------------------------------------------------
# 估计结果
# ---------------------------------------------------------------------------


@dataclass
class EstimationResult:
    """实测观测的最小二乘 / 稳健估计结果。"""

    dataset: ObservationDataset
    kind: str
    method: str
    parameter_names: List[str]
    x: np.ndarray
    coordinates: Dict[str, Tuple[float, ...]]
    active_indices: List[int]
    active_labels: List[str]
    A: np.ndarray
    Ql: np.ndarray
    P: np.ndarray
    Cx: np.ndarray
    Qv: np.ndarray
    residuals: np.ndarray
    normalized_residuals: np.ndarray
    standardized_residuals: np.ndarray
    w_statistics: np.ndarray
    row_labels: List[str]
    row_record_indices: np.ndarray
    row_sigma: np.ndarray
    row_weight_factors: np.ndarray
    sigma0_hat: float
    chi_square: float
    dof: int
    chi_square_p_value: float
    rank: int
    n_rows: int
    n_params: int
    iterations: int
    converged: bool
    max_update: float
    history: List[Dict[str, float]]
    outlier_labels: List[str] = field(default_factory=list)
    suspected_labels: List[str] = field(default_factory=list)
    observation_weight_factors: Optional[np.ndarray] = None
    robust_scale: Optional[float] = None
    robust_history: List[Dict[str, float]] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def redundancy(self) -> int:
        return int(self.dof)

    @property
    def labels(self) -> List[str]:
        return list(self.row_labels)

    @property
    def n_observations(self) -> int:
        return len(self.active_indices)

    @property
    def w_by_label(self) -> Dict[str, float]:
        out: Dict[str, float] = {}
        for label in self.active_labels:
            mask = self.row_labels == np.asarray(label)
            if np.any(mask):
                out[label] = float(np.max(np.abs(self.w_statistics[mask])))
        return out

    @property
    def residual_by_label(self) -> Dict[str, np.ndarray]:
        out: Dict[str, np.ndarray] = {}
        for label in self.active_labels:
            idx = [i for i, item in enumerate(self.row_labels) if item == label]
            out[label] = self.residuals[np.asarray(idx, dtype=int)]
        return out

    def coordinate(self, ref: Any) -> Tuple[float, ...]:
        name = _point_ref_name(ref)
        if name not in self.coordinates:
            raise KeyError(f"结果中不存在点 {name!r}")
        return tuple(float(v) for v in self.coordinates[name])

    def truth_coordinate(self, ref: Any) -> Tuple[float, ...]:
        name = _point_ref_name(ref)
        return tuple(self.dataset.true_coordinates[name])

    def deviation(self, ref: Any) -> np.ndarray:
        name = _point_ref_name(ref)
        return np.asarray(self.coordinates[name], dtype=float) - np.asarray(
            self.dataset.true_coordinates[name], dtype=float
        )

    def deviation_mm(self, ref: Any) -> np.ndarray:
        return self.deviation(ref) * 1000.0

    def point_deviation_mm(self, ref: Any) -> float:
        """点坐标偏差向量范数（平面 E/N；水准为高程差绝对值），mm。"""
        return float(np.linalg.norm(self.deviation_mm(ref)))

    def max_deviation_mm(self) -> float:
        vals = [self.point_deviation_mm(name) for name in self.coordinates]
        return max(vals, default=0.0)

    def rms_deviation_mm(self) -> float:
        vals = np.asarray(
            [self.point_deviation_mm(name) for name in self.coordinates], dtype=float
        )
        return float(np.sqrt(np.mean(vals * vals))) if vals.size else 0.0

    def observation_weight(self, ref: Union[int, str, Observation]) -> float:
        idx = _resolve_observation_key(self.dataset.records, ref)
        if self.observation_weight_factors is None:
            return 1.0
        if idx not in self.active_indices:
            # 被数据 snooping 剔除的观测等价于权因子 0。
            return 0.0
        pos = self.active_indices.index(idx)
        return float(self.observation_weight_factors[pos])


@dataclass
class GlobalTestResult:
    """χ² 整体模型检验结果。"""

    statistic: float
    dof: int
    p_value: float
    critical_value: float
    alpha: float
    passed: bool
    sigma0_hat: float
    sigma0_prior: float

    @property
    def rejected(self) -> bool:
        return not self.passed


@dataclass
class SnoopingRound:
    """数据 snooping 的一轮记录。"""

    iteration: int
    statistic_name: str
    labels: List[str]
    active_indices: List[int]
    statistics: np.ndarray
    max_abs_statistic: float
    critical_value: float
    removed_label: Optional[str]
    removed_index: Optional[int]
    sigma0_hat: float
    chi_square: float
    chi_square_p_value: float
    n_active: int
    removed_before: List[str] = field(default_factory=list)
    stopped_by_limit: bool = False

    @property
    def removed(self) -> bool:
        return self.removed_index is not None

    @property
    def by_label(self) -> Dict[str, float]:
        return {
            label: float(value)
            for label, value in zip(self.labels, self.statistics)
        }


@dataclass
class DataSnoopingResult:
    """迭代数据探测结果。"""

    dataset: ObservationDataset
    rounds: List[SnoopingRound]
    final_estimate: EstimationResult
    initial_estimate: EstimationResult
    removed_indices: List[int]
    removed_labels: List[str]
    threshold: float
    alpha: float
    test: str
    detected: bool

    @property
    def outliers(self) -> List[str]:
        return list(self.removed_labels)

    @property
    def outlier_labels(self) -> List[str]:
        return list(self.removed_labels)

    @property
    def n_removed(self) -> int:
        return len(self.removed_indices)

    @property
    def final(self) -> EstimationResult:
        return self.final_estimate

    @property
    def by_label(self) -> Dict[str, SnoopingRound]:
        out: Dict[str, SnoopingRound] = {}
        for rnd in self.rounds:
            for label in rnd.labels:
                out.setdefault(label, rnd)
        return out


# ---------------------------------------------------------------------------
# 线性化系统与最小二乘
# ---------------------------------------------------------------------------


@dataclass
class _System:
    A: np.ndarray
    Ql: np.ndarray
    P: np.ndarray
    misclosure: np.ndarray
    row_labels: List[str]
    row_record_indices: np.ndarray
    index: Any
    n_rows: int
    n_constraints: int
    kind: str
    current_points: Any

    @property
    def n_observation_rows(self) -> int:
        return self.n_rows - self.n_constraints


@dataclass
class _Step:
    dx: np.ndarray
    Cx: np.ndarray
    residuals: np.ndarray
    Qv: np.ndarray
    w_statistics: np.ndarray
    standardized_residuals: np.ndarray
    rank: int
    redundancy: int
    P_eff: np.ndarray


def _initial_planar_network(
    dataset: ObservationDataset,
    approximate: Optional[Mapping[Any, Sequence[float]]],
) -> Network:
    coords = {
        name: [float(v[0]), float(v[1])]
        for name, v in dataset.true_coordinates.items()
    }
    if approximate:
        for ref, value in approximate.items():
            name = _point_ref_name(ref)
            if name not in coords:
                raise KeyError(f"近似坐标引用了不存在的点 {name!r}")
            arr = _as_vector(value, f"点 {name} 的近似坐标")
            if arr.size != 2:
                raise ValueError(f"点 {name} 的近似坐标必须是 (E, N)")
            coords[name] = [float(arr[0]), float(arr[1])]
    points = [
        Point(
            p.name,
            coords[p.name][0],
            coords[p.name][1],
            fixed=p.fixed,
            sigma_E=p.sigma_E,
            sigma_N=p.sigma_N,
        )
        for p in dataset.network.points
    ]
    return Network(points, list(dataset.network.observations), name=dataset.network.name)


def _initial_leveling_network(
    dataset: ObservationDataset,
    approximate: Optional[Mapping[Any, Union[float, Sequence[float]]]],
) -> LevelingNetwork:
    heights = {
        name: float(v[0]) for name, v in dataset.true_coordinates.items()
    }
    if approximate:
        for ref, value in approximate.items():
            name = _point_ref_name(ref)
            if name not in heights:
                raise KeyError(f"近似高程引用了不存在的点 {name!r}")
            if isinstance(value, (int, float, np.number)):
                heights[name] = float(value)
            else:
                arr = _as_vector(value, f"点 {name} 的近似高程")
                if arr.size != 1:
                    raise ValueError(f"点 {name} 的近似高程必须是标量")
                heights[name] = float(arr[0])
    points = [
        LevelingPoint(
            p.name,
            heights[p.name],
            fixed=p.fixed,
            sigma_H=p.sigma_H,
            height_type=p.height_type,
        )
        for p in dataset.network.points
    ]
    return LevelingNetwork(
        points,
        list(dataset.network.observations),
        name=dataset.network.name,
    )


def _constraint_target(
    dataset: ObservationDataset,
    constraint: CoordinateConstraint,
    current_network: Network,
) -> float:
    true_coords = dataset.true_coordinates.get(constraint.point)
    if true_coords is not None:
        component = 0 if constraint.component == "E" else 1
        if component < len(true_coords):
            return float(true_coords[component])
    if constraint.value is not None:
        return float(constraint.value)
    point = current_network.point(constraint.point)
    return float(point.E if constraint.component == "E" else point.N)


def _planar_system(
    network: Network,
    dataset: ObservationDataset,
    active_indices: Sequence[int],
    datum: Datum,
) -> _System:
    active_obs = [dataset.records[i].observation for i in active_indices]
    active_net = Network(list(network.points), active_obs, name=network.name)
    index = build_parameter_index(active_net)
    constraints = datum.constraints(active_net, index)
    design = build_design(active_net, index, constraints)

    mis_parts: List[np.ndarray] = []
    row_labels: List[str] = []
    row_record: List[int] = []
    for i in active_indices:
        rec = dataset.records[i]
        pred, _sigma, is_angle = _planar_truth(active_net, rec.observation)
        diff = rec.values - pred
        if is_angle:
            diff = _wrap_angle(diff)
        mis_parts.append(diff)
        row_labels.extend([rec.label] * rec.n_rows)
        row_record.extend([i] * rec.n_rows)

    for con in constraints:
        target = _constraint_target(dataset, con, active_net)
        point = active_net.point(con.point)
        current = point.E if con.component == "E" else point.N
        mis_parts.append(np.array([target - current], dtype=float))
        row_labels.append(con.label)
        row_record.append(-1)

    misclosure = (
        np.concatenate(mis_parts)
        if mis_parts
        else np.zeros(0, dtype=float)
    )
    if misclosure.size != design.n_rows:
        raise AdjustmentError("内部错误：残差向量与设计矩阵行数不一致")
    Ql = np.asarray(design.Ql, dtype=float)
    try:
        P = np.linalg.inv(Ql)
    except np.linalg.LinAlgError as exc:  # pragma: no cover - 防御性
        raise InvalidPrecisionError("观测协方差矩阵不可逆") from exc
    return _System(
        A=np.asarray(design.A, dtype=float),
        Ql=Ql,
        P=P,
        misclosure=misclosure,
        row_labels=row_labels,
        row_record_indices=np.asarray(row_record, dtype=int),
        index=index,
        n_rows=int(design.n_rows),
        n_constraints=len(constraints),
        kind="planar",
        current_points=active_net,
    )


def _leveling_datum_mode(datum: Any) -> str:
    if datum is None:
        return "auto"
    if isinstance(datum, str):
        key = datum.strip().lower()
        if key in ("", "auto"):
            return "auto"
        if key in ("fixed", "fix", "固定"):
            return "fixed"
        if key in ("weighted", "weight", "加权"):
            return "weighted"
        if key in ("free", "minimal", "自由", "最小"):
            raise NotImplementedError(
                "稳健/实测模块暂不支持水准自由网；请使用固定或加权高程基准"
            )
        raise ValueError(f"未知水准基准类型：{datum!r}")
    if isinstance(datum, (MinimalDatum, FreeDatum)):
        raise NotImplementedError(
            "稳健/实测模块暂不支持水准自由网；请使用固定或加权高程基准"
        )
    if isinstance(datum, WeightedDatum):
        return "weighted"
    if isinstance(datum, FixedDatum):
        return "fixed"
    if isinstance(datum, Datum):
        return "auto"
    raise TypeError(f"datum 必须是字符串、Datum 或 None，收到 {type(datum)!r}")


def _leveling_system(
    network: LevelingNetwork,
    dataset: ObservationDataset,
    active_indices: Sequence[int],
    datum: Any,
) -> _System:
    mode = _leveling_datum_mode(datum)
    unknown = [p for p in network.points if not p.fixed]
    unknown_names = [p.name for p in unknown]
    index = {name: i for i, name in enumerate(unknown_names)}
    u = len(unknown_names)
    current_x = np.asarray([p.H for p in unknown], dtype=float)

    rows: List[np.ndarray] = []
    mis_parts: List[np.ndarray] = []
    row_labels: List[str] = []
    row_record: List[int] = []
    sigmas: List[float] = []
    for i in active_indices:
        rec = dataset.records[i]
        row = np.zeros(u, dtype=float)
        pred = 0.0
        for ref, sign in ((rec.observation.frm, -1.0), (rec.observation.to, 1.0)):
            if ref in index:
                row[index[ref]] += sign
                pred += sign * current_x[index[ref]]
            else:
                pred += sign * network.point(ref).H
        rows.append(row)
        mis_parts.append(np.array([rec.values[0] - pred], dtype=float))
        row_labels.append(rec.label)
        row_record.append(i)
        sigmas.append(float(rec.sigma[0]))

    constraints: List[Tuple[str, float, float]] = []
    for p in unknown:
        if mode in ("auto", "weighted") and p.sigma_H is not None:
            constraints.append((p.name, float(p.sigma_H), float(p.H)))
    if mode == "weighted" and not constraints:
        raise InvalidPrecisionError(
            "加权高程基准未找到任何 sigma_H；请设置加权点或改用 fixed"
        )

    for point_name, sigma_h, current_h in constraints:
        row = np.zeros(u, dtype=float)
        row[index[point_name]] = 1.0
        rows.append(row)
        target = float(dataset.true_coordinates[point_name][0])
        mis_parts.append(np.array([target - current_h], dtype=float))
        row_labels.append(f"H:{point_name}")
        row_record.append(-1)
        sigmas.append(sigma_h)

    m = len(rows)
    if m == 0:
        raise AdjustmentError("没有可用观测，无法估计")
    A = np.vstack(rows)
    Ql = np.diag(np.square(np.asarray(sigmas, dtype=float)))
    P = np.diag(1.0 / np.square(np.asarray(sigmas, dtype=float)))
    misclosure = np.concatenate(mis_parts)
    return _System(
        A=A,
        Ql=Ql,
        P=P,
        misclosure=misclosure,
        row_labels=row_labels,
        row_record_indices=np.asarray(row_record, dtype=int),
        index=index,
        n_rows=m,
        n_constraints=len(constraints),
        kind="leveling",
        current_points=network,
    )


def _augment_gamma(system: _System, gamma_obs: Optional[np.ndarray]) -> np.ndarray:
    if gamma_obs is None:
        return np.ones(system.n_rows, dtype=float)
    gamma = np.asarray(gamma_obs, dtype=float).reshape(-1)
    if gamma.size != system.n_observation_rows:
        raise ValueError(
            f"权因子长度应为 {system.n_observation_rows}，收到 {gamma.size}"
        )
    if not np.all(np.isfinite(gamma)) or np.any(gamma < 0.0):
        raise InvalidPrecisionError("权因子必须为非负有限值")
    return np.concatenate([gamma, np.ones(system.n_constraints, dtype=float)])


def _solve_step(system: _System, gamma_full: np.ndarray) -> _Step:
    A = system.A
    Ql = system.Ql
    P = system.P
    m, u = A.shape
    gamma_full = np.asarray(gamma_full, dtype=float).reshape(-1)
    if gamma_full.size != m:
        raise ValueError("权因子长度与设计矩阵行数不一致")
    sqrt_g = np.sqrt(np.maximum(gamma_full, 0.0))
    P_eff = sqrt_g[:, None] * P * sqrt_g[None, :]

    if u == 0:
        dx = np.zeros(0, dtype=float)
        Cx = np.zeros((0, 0), dtype=float)
        residuals = system.misclosure.copy()
        Qv = Ql.copy()
        rank = 0
    else:
        N = A.T @ P_eff @ A
        rhs = A.T @ (P_eff @ system.misclosure)
        N = 0.5 * (N + N.T)
        try:
            Cx = np.linalg.inv(N)
        except np.linalg.LinAlgError as exc:
            raise RankDeficientError(
                "稳健/实测平差法方程奇异，观测不足以确定全部参数；"
                "请检查基准、网形或剔除的观测"
            ) from exc
        Cx = 0.5 * (Cx + Cx.T)
        dx = Cx @ rhs
        residuals = system.misclosure - A @ dx
        Qv = Ql - A @ Cx @ A.T
        Qv = 0.5 * (Qv + Qv.T)
        rank = u

    redundancy = int(m - rank)
    Ql_inv = P
    K = Ql_inv @ Qv @ Ql_inv
    K = 0.5 * (K + K.T)
    diag_k = np.clip(np.diag(K), 0.0, None)
    denom = np.sqrt(diag_k)
    w = np.zeros(m, dtype=float)
    good = denom > 1e-15
    w[good] = (Ql_inv @ residuals)[good] / denom[good]
    # 标准化残差使用“先验权”下的残差协方差 Qv0，而不是当前稳健权下的 Qv。
    # 否则被淘汰观测（权因子 0）的 Qv_ii 会退化为 0，残差被错误放大。
    if u == 0:
        Qv_prior = Ql.copy()
    else:
        N0 = A.T @ P @ A
        N0 = 0.5 * (N0 + N0.T)
        try:
            Cx0 = np.linalg.inv(N0)
            Qv_prior = Ql - A @ Cx0 @ A.T
            Qv_prior = 0.5 * (Qv_prior + Qv_prior.T)
        except np.linalg.LinAlgError:
            Qv_prior = Ql.copy()
    diag_qv = np.clip(np.diag(Qv_prior), 1e-30, None)
    standardized = residuals / np.sqrt(diag_qv)
    return _Step(
        dx=dx,
        Cx=Cx,
        residuals=residuals,
        Qv=Qv,
        w_statistics=w,
        standardized_residuals=standardized,
        rank=rank,
        redundancy=redundancy,
        P_eff=P_eff,
    )


def _update_planar_network(network: Network, index: ParameterIndex, dx: np.ndarray) -> Network:
    points: List[Point] = []
    for p in network.points:
        cols = index.point_columns.get(p.name)
        if cols is None:
            points.append(
                Point(
                    p.name,
                    p.E,
                    p.N,
                    fixed=p.fixed,
                    sigma_E=p.sigma_E,
                    sigma_N=p.sigma_N,
                )
            )
        else:
            points.append(
                Point(
                    p.name,
                    p.E + float(dx[cols[0]]),
                    p.N + float(dx[cols[1]]),
                    fixed=p.fixed,
                    sigma_E=p.sigma_E,
                    sigma_N=p.sigma_N,
                )
            )
    return Network(points, list(network.observations), name=network.name)


def _update_leveling_network(
    network: LevelingNetwork, index: Dict[str, int], dx: np.ndarray
) -> LevelingNetwork:
    from .leveling import LevelingPoint

    points = [
        LevelingPoint(
            p.name,
            p.H + (float(dx[index[p.name]]) if p.name in index else 0.0),
            fixed=p.fixed,
            sigma_H=p.sigma_H,
            height_type=p.height_type,
        )
        for p in network.points
    ]
    return LevelingNetwork(points, list(network.observations), name=network.name)


def _planar_parameter_vector(
    network: Network, index: ParameterIndex, step: _Step
) -> np.ndarray:
    x = np.zeros(index.size, dtype=float)
    for name, (ie, inn) in index.point_columns.items():
        p = network.point(name)
        x[ie] = p.E
        x[inn] = p.N
    for station, col in index.orientation_columns.items():
        # 每次线性化以 omega=0 为基准；最终步的 dx 即绝对定向改正。
        x[col] = float(step.dx[col]) if col < step.dx.size else 0.0
    return x


def _build_result(
    dataset: ObservationDataset,
    kind: str,
    method: str,
    network: Any,
    system: _System,
    step: _Step,
    active_indices: Sequence[int],
    x: np.ndarray,
    coordinates: Dict[str, Tuple[float, ...]],
    iterations: int,
    converged: bool,
    max_update: float,
    history: List[Dict[str, float]],
    gamma_obs: Optional[np.ndarray],
) -> EstimationResult:
    gamma_full = _augment_gamma(system, gamma_obs)
    row_sigma = np.sqrt(np.clip(np.diag(system.Ql), 0.0, None))
    chi2 = float(step.residuals @ system.P @ step.residuals)
    dof = int(max(system.n_rows - step.rank, 0))
    sigma0_hat = sqrt(chi2 / dof) if dof > 0 else 1.0
    p_value = chi2_sf(chi2, dof) if dof > 0 else 1.0

    obs_weights: List[float] = []
    for i in active_indices:
        rec = dataset.records[i]
        mask = system.row_record_indices == i
        obs_weights.append(
            float(np.min(gamma_full[mask])) if np.any(mask) else 1.0
        )

    return EstimationResult(
        dataset=dataset,
        kind=kind,
        method=method,
        parameter_names=list(system.index.names)
        if kind == "planar"
        else list(system.index.keys()),
        x=np.asarray(x, dtype=float),
        coordinates=coordinates,
        active_indices=[int(i) for i in active_indices],
        active_labels=[dataset.records[i].label for i in active_indices],
        A=system.A.copy(),
        Ql=system.Ql.copy(),
        P=system.P.copy(),
        Cx=step.Cx.copy(),
        Qv=step.Qv.copy(),
        residuals=step.residuals.copy(),
        normalized_residuals=step.residuals / np.where(row_sigma > 0, row_sigma, 1.0),
        standardized_residuals=step.standardized_residuals.copy(),
        w_statistics=step.w_statistics.copy(),
        row_labels=list(system.row_labels),
        row_record_indices=system.row_record_indices.copy(),
        row_sigma=row_sigma,
        row_weight_factors=gamma_full,
        sigma0_hat=float(sigma0_hat),
        chi_square=chi2,
        dof=dof,
        chi_square_p_value=float(p_value),
        rank=int(step.rank),
        n_rows=int(system.n_rows),
        n_params=int(step.rank),
        iterations=int(iterations),
        converged=bool(converged),
        max_update=float(max_update),
        history=list(history),
        observation_weight_factors=np.asarray(obs_weights, dtype=float),
    )


def _estimate_planar(
    dataset: ObservationDataset,
    active_indices: Sequence[int],
    *,
    approximate: Optional[Mapping[Any, Sequence[float]]],
    datum: Datum,
    gamma_obs: Optional[np.ndarray],
    max_iter: int,
    tol: float,
    method: str,
) -> EstimationResult:
    network = _initial_planar_network(dataset, approximate)
    history: List[Dict[str, float]] = []
    converged = False
    max_update = float("inf")
    step: Optional[_Step] = None
    system: Optional[_System] = None
    iterations = 0

    for it in range(1, max_iter + 1):
        iterations = it
        system = _planar_system(network, dataset, active_indices, datum)
        gamma_full = _augment_gamma(system, gamma_obs)
        step = _solve_step(system, gamma_full)
        cols = [
            c
            for (_e, n) in system.index.point_columns.values()
            for c in (_e, n)
        ]
        max_update = (
            float(np.max(np.abs(step.dx[cols]))) if cols else 0.0
        )
        network = _update_planar_network(network, system.index, step.dx)
        history.append(
            {
                "iteration": float(it),
                "max_coordinate_update": float(max_update),
                "max_abs_residual": float(np.max(np.abs(step.residuals)))
                if step.residuals.size
                else 0.0,
            }
        )
        if max_update <= tol:
            converged = True
            # 在最终坐标处再解一次，使残差、Cx 与定向未知数一致。
            system = _planar_system(network, dataset, active_indices, datum)
            gamma_full = _augment_gamma(system, gamma_obs)
            step = _solve_step(system, gamma_full)
            network = _update_planar_network(network, system.index, step.dx)
            break

    assert system is not None and step is not None
    x = _planar_parameter_vector(network, system.index, step)
    coordinates = {
        p.name: (float(p.E), float(p.N)) for p in network.points
    }
    return _build_result(
        dataset,
        "planar",
        method,
        network,
        system,
        step,
        active_indices,
        x,
        coordinates,
        iterations,
        converged,
        max_update,
        history,
        gamma_obs,
    )


def _estimate_leveling(
    dataset: ObservationDataset,
    active_indices: Sequence[int],
    *,
    approximate: Optional[Mapping[Any, Union[float, Sequence[float]]]],
    datum: Any,
    gamma_obs: Optional[np.ndarray],
    max_iter: int,
    tol: float,
    method: str,
) -> EstimationResult:
    network = _initial_leveling_network(dataset, approximate)
    history: List[Dict[str, float]] = []
    converged = False
    max_update = float("inf")
    step: Optional[_Step] = None
    system: Optional[_System] = None
    iterations = 0

    for it in range(1, max_iter + 1):
        iterations = it
        system = _leveling_system(network, dataset, active_indices, datum)
        gamma_full = _augment_gamma(system, gamma_obs)
        step = _solve_step(system, gamma_full)
        max_update = (
            float(np.max(np.abs(step.dx))) if step.dx.size else 0.0
        )
        network = _update_leveling_network(network, system.index, step.dx)
        history.append(
            {
                "iteration": float(it),
                "max_coordinate_update": float(max_update),
                "max_abs_residual": float(np.max(np.abs(step.residuals)))
                if step.residuals.size
                else 0.0,
            }
        )
        if max_update <= tol:
            converged = True
            system = _leveling_system(network, dataset, active_indices, datum)
            gamma_full = _augment_gamma(system, gamma_obs)
            step = _solve_step(system, gamma_full)
            network = _update_leveling_network(network, system.index, step.dx)
            break

    assert system is not None and step is not None
    x = np.asarray(
        [network.point(name).H for name in system.index], dtype=float
    )
    coordinates = {p.name: (float(p.H),) for p in network.points}
    return _build_result(
        dataset,
        "leveling",
        method,
        network,
        system,
        step,
        active_indices,
        x,
        coordinates,
        iterations,
        converged,
        max_update,
        history,
        gamma_obs,
    )


def estimate_network(
    dataset: ObservationDataset,
    *,
    approximate: Optional[Mapping[Any, Any]] = None,
    datum: Any = None,
    active_indices: Optional[Sequence[int]] = None,
    weight_factors: Optional[Sequence[float]] = None,
    max_iter: int = DEFAULT_MAX_ITER,
    tol: float = DEFAULT_TOL,
    method: str = "ls",
) -> EstimationResult:
    """对模拟/实测观测做（加权）最小二乘，平面网用高斯-牛顿迭代。

    Parameters
    ----------
    dataset:
        :func:`simulate_observations` 返回的观测集。
    approximate:
        平面网为 ``{点名: (E, N)}``；水准网为 ``{点名: H}``。缺省时从真值
        坐标出发，便于测试；实际应用应传入近似坐标以检验迭代收敛。
    datum:
        平面网基准（默认固定点）；水准网支持 None/'auto'/'fixed'/'weighted'。
    active_indices:
        参与估计的观测序号；默认全部。数据 snooping 用它剔除观测。
    weight_factors:
        按设计矩阵行给出的先验权因子（稳健估计使用）；缺省全 1。
    """
    if not isinstance(dataset, ObservationDataset):
        raise TypeError("dataset 必须是 ObservationDataset")
    if method not in ("ls", "huber", "igg3"):
        raise ValueError("method 只能是 'ls'、'huber' 或 'igg3'")
    if active_indices is None:
        active = list(range(dataset.n_observations))
    else:
        active = [int(i) for i in active_indices]
        if not active:
            raise AdjustmentError("active_indices 不能为空")
        if len(active) != len(set(active)):
            raise ValueError("active_indices 含重复序号")
        if any(i < 0 or i >= dataset.n_observations for i in active):
            raise KeyError("active_indices 含越界序号")
        active = sorted(active)

    if dataset.kind == "planar":
        datum_obj = normalize_datum(datum)
        return _estimate_planar(
            dataset,
            active,
            approximate=approximate,
            datum=datum_obj,
            gamma_obs=None if weight_factors is None else np.asarray(weight_factors),
            max_iter=int(max_iter),
            tol=float(tol),
            method=method,
        )
    if dataset.kind == "leveling":
        return _estimate_leveling(
            dataset,
            active,
            approximate=approximate,
            datum=datum,
            gamma_obs=None if weight_factors is None else np.asarray(weight_factors),
            max_iter=int(max_iter),
            tol=float(tol),
            method=method,
        )
    raise ValueError(f"未知观测集类型：{dataset.kind!r}")


least_squares = estimate_network
estimate = estimate_network


# ---------------------------------------------------------------------------
# 整体模型检验与数据探测
# ---------------------------------------------------------------------------


def global_model_test(
    result_or_dataset: Union[EstimationResult, ObservationDataset],
    *,
    sigma0: float = 1.0,
    alpha: float = 0.05,
    approximate: Optional[Mapping[Any, Any]] = None,
    datum: Any = None,
) -> GlobalTestResult:
    """χ² 整体模型检验。

    统计量 ``vᵀPv/σ0²``，自由度取 ``n-rank``；p 值为上尾概率。
    ``passed`` 表示在显著性 ``alpha`` 下不拒绝原假设（模型/先验 σ 相容）。
    """
    if isinstance(result_or_dataset, ObservationDataset):
        result = estimate_network(result_or_dataset, approximate=approximate, datum=datum)
    elif isinstance(result_or_dataset, EstimationResult):
        result = result_or_dataset
    else:
        raise TypeError("需要 EstimationResult 或 ObservationDataset")
    sigma0 = float(sigma0)
    if not isfinite(sigma0) or sigma0 <= 0.0:
        raise ValueError("sigma0 必须为正的有限值")
    if result.dof <= 0:
        return GlobalTestResult(
            statistic=float("nan"),
            dof=0,
            p_value=1.0,
            critical_value=float("inf"),
            alpha=float(alpha),
            passed=True,
            sigma0_hat=float(result.sigma0_hat),
            sigma0_prior=sigma0,
        )
    statistic = float(result.chi_square / (sigma0 * sigma0))
    p_value = chi2_sf(statistic, result.dof)
    critical = chi2_critical(result.dof, alpha)
    return GlobalTestResult(
        statistic=statistic,
        dof=int(result.dof),
        p_value=float(p_value),
        critical_value=float(critical),
        alpha=float(alpha),
        passed=bool(statistic <= critical),
        sigma0_hat=float(result.sigma0_hat),
        sigma0_prior=sigma0,
    )


def _record_statistics(
    result: EstimationResult, test: str
) -> Tuple[List[str], np.ndarray, np.ndarray]:
    """按观测分组的检验量；返回 (标签, 统计量, 对应观测序号)。"""
    if test == "w":
        row_stats = result.w_statistics
    elif test == "tau":
        if result.sigma0_hat <= 0.0 or not isfinite(result.sigma0_hat):
            row_stats = np.full(result.w_statistics.shape, np.inf)
        else:
            row_stats = result.w_statistics / result.sigma0_hat
    else:
        raise ValueError("test 只能是 'w' 或 'tau'")

    labels: List[str] = []
    stats: List[float] = []
    indices: List[int] = []
    for idx in result.active_indices:
        rec = result.dataset.records[idx]
        mask = result.row_record_indices == idx
        if not np.any(mask):
            continue
        labels.append(rec.label)
        indices.append(idx)
        stats.append(float(np.max(np.abs(row_stats[mask]))))
    return labels, np.asarray(stats, dtype=float), np.asarray(indices, dtype=int)


def data_snooping(
    dataset: ObservationDataset,
    *,
    threshold: Optional[float] = None,
    alpha: float = DEFAULT_ALPHA,
    test: str = "w",
    max_remove: Optional[int] = None,
    approximate: Optional[Mapping[Any, Any]] = None,
    datum: Any = None,
    max_iter: int = DEFAULT_MAX_ITER,
    tol: float = DEFAULT_TOL,
) -> DataSnoopingResult:
    """迭代数据 snooping：每轮剔除 |w| 或 |τ| 最大的超限观测。

    ``test='w'`` 使用 σ0 已知的 Baarda w 检验，默认临界值 3.29
    （α0=0.001 双侧）；``test='tau'`` 使用 Pope τ 检验，σ0 由残差估计，
    默认临界值取相应自由度的 t 分布分位数。阈值可用 ``threshold`` 覆盖。
    """
    if not isinstance(dataset, ObservationDataset):
        raise TypeError("dataset 必须是 ObservationDataset")
    test = str(test).lower()
    if test not in ("w", "tau"):
        raise ValueError("test 只能是 'w' 或 'tau'")
    alpha = float(alpha)
    if not (0.0 < alpha < 1.0):
        raise ValueError("alpha 必须满足 0 < alpha < 1")

    active = list(range(dataset.n_observations))
    removed_indices: List[int] = []
    removed_labels: List[str] = []
    rounds: List[SnoopingRound] = []
    initial = estimate_network(
        dataset,
        approximate=approximate,
        datum=datum,
        max_iter=max_iter,
        tol=tol,
    )
    if max_remove is None:
        max_remove = max(1, int(initial.redundancy))
    max_remove = int(max_remove)
    if max_remove < 0:
        raise ValueError("max_remove 不能为负")

    estimate = initial
    while True:
        labels, stats, indices = _record_statistics(estimate, test)
        if threshold is not None:
            critical = float(threshold)
        elif test == "w":
            critical = DEFAULT_W_CRITICAL
        else:
            critical = t_critical(max(estimate.dof, 1), alpha)
        if stats.size:
            best_pos = int(np.argmax(stats))
            max_abs = float(stats[best_pos])
            candidate_label = labels[best_pos]
            candidate_index = int(indices[best_pos])
        else:
            best_pos = -1
            max_abs = 0.0
            candidate_label = None
            candidate_index = None

        should_remove = (
            candidate_index is not None
            and max_abs > critical
            and len(removed_indices) < max_remove
        )
        round_item = SnoopingRound(
            iteration=len(rounds) + 1,
            statistic_name=test,
            labels=list(labels),
            active_indices=[int(i) for i in indices],
            statistics=stats.copy(),
            max_abs_statistic=max_abs,
            critical_value=critical,
            removed_label=candidate_label if should_remove else None,
            removed_index=candidate_index if should_remove else None,
            sigma0_hat=float(estimate.sigma0_hat),
            chi_square=float(estimate.chi_square),
            chi_square_p_value=float(estimate.chi_square_p_value),
            n_active=len(active),
            removed_before=list(removed_labels),
            stopped_by_limit=bool(
                candidate_index is not None
                and max_abs > critical
                and len(removed_indices) >= max_remove
            ),
        )
        rounds.append(round_item)
        if not should_remove:
            break
        assert candidate_index is not None and candidate_label is not None
        removed_indices.append(candidate_index)
        removed_labels.append(candidate_label)
        active.remove(candidate_index)
        if not active:
            break
        estimate = estimate_network(
            dataset,
            approximate=approximate,
            datum=datum,
            active_indices=active,
            max_iter=max_iter,
            tol=tol,
        )

    return DataSnoopingResult(
        dataset=dataset,
        rounds=rounds,
        final_estimate=estimate,
        initial_estimate=initial,
        removed_indices=removed_indices,
        removed_labels=removed_labels,
        threshold=float(rounds[-1].critical_value) if rounds else DEFAULT_W_CRITICAL,
        alpha=alpha,
        test=test,
        detected=bool(removed_indices),
    )


# ---------------------------------------------------------------------------
# 稳健估计
# ---------------------------------------------------------------------------


def _weight_function(u: np.ndarray, method: str, k0: float, k1: float, c: float) -> np.ndarray:
    abs_u = np.abs(u)
    if method == "huber":
        out = np.ones_like(abs_u)
        mask = abs_u > c
        out[mask] = c / abs_u[mask]
        return out
    if method == "igg3":
        out = np.ones_like(abs_u)
        mask1 = (abs_u > k0) & (abs_u <= k1)
        out[mask1] = (k0 / abs_u[mask1]) * (
            (k1 - abs_u[mask1]) / (k1 - k0)
        ) ** 2
        out[abs_u > k1] = 0.0
        return out
    raise ValueError("method 只能是 'huber' 或 'igg3'")


def _group_weight_factors(
    dataset: ObservationDataset, row_gamma: np.ndarray
) -> np.ndarray:
    """同一观测的多行（GNSS 基线）取组内最小权因子，保持块内一致。"""
    out = np.asarray(row_gamma, dtype=float).copy()
    for rec in dataset.records:
        if rec.n_rows <= 1:
            continue
        rows = np.asarray(rec.rows, dtype=int)
        factor = float(np.min(out[rows]))
        out[rows] = factor
    return out


def robust_estimate(
    dataset: ObservationDataset,
    *,
    method: str = "igg3",
    k0: float = DEFAULT_IGG_K0,
    k1: float = DEFAULT_IGG_K1,
    c: float = DEFAULT_HUBER_C,
    approximate: Optional[Mapping[Any, Any]] = None,
    datum: Any = None,
    max_iter: int = DEFAULT_MAX_ITER,
    tol: float = DEFAULT_TOL,
    weight_tol: float = 1e-6,
) -> EstimationResult:
    """Huber / IGG-III 迭代重加权最小二乘。

    - 标准化残差：``z_i = v_i/sqrt(diag(Qv))``；
    - 尺度：``s = 1.4826·MAD(z)``，``u_i = z_i/s``；
    - Huber：``|u|≤c`` 原权，否则 ``c/|u|``（默认 c=1.345）；
    - IGG-III：``|u|≤k0`` 原权；``k0<|u|≤k1`` 降权；``|u|>k1`` 淘汰
      （默认 k0=1.5、k1=3.0）。

    返回最终权因子、收敛历史与按观测分组识别出的粗差标签。
    """
    method = str(method).lower()
    if method not in ("huber", "igg3"):
        raise ValueError("method 只能是 'huber' 或 'igg3'")
    k0 = float(k0)
    k1 = float(k1)
    c = float(c)
    if not (0.0 < k0 < k1):
        raise ValueError("IGG-III 要求 0 < k0 < k1")
    if c <= 0.0:
        raise ValueError("Huber c 必须为正")
    active = list(range(dataset.n_observations))
    gamma = np.ones(dataset.row_count, dtype=float)
    history: List[Dict[str, float]] = []
    converged = False
    scale = 1.0

    for it in range(1, max_iter + 1):
        estimate = estimate_network(
            dataset,
            approximate=approximate,
            datum=datum,
            active_indices=active,
            weight_factors=gamma,
            max_iter=max_iter,
            tol=tol,
            method=method,
        )
        z = estimate.standardized_residuals
        scale = _mad_scale(z)
        new_gamma = _weight_function(z / scale, method, k0, k1, c)
        new_gamma = _group_weight_factors(dataset, new_gamma)
        change = float(np.max(np.abs(new_gamma - gamma))) if gamma.size else 0.0
        history.append(
            {
                "iteration": float(it),
                "scale": float(scale),
                "max_weight_change": float(change),
                "max_coordinate_update": float(estimate.max_update),
            }
        )
        gamma = new_gamma
        if change <= weight_tol:
            converged = True
            break

    final = estimate_network(
        dataset,
        approximate=approximate,
        datum=datum,
        active_indices=active,
        weight_factors=gamma,
        max_iter=max_iter,
        tol=tol,
        method=method,
    )
    final_scale = _mad_scale(final.standardized_residuals)
    z_final = final.standardized_residuals
    outlier_labels: List[str] = []
    suspected: List[str] = []
    obs_weights = final.observation_weight_factors
    assert obs_weights is not None
    for pos, idx in enumerate(final.active_indices):
        rec = dataset.records[idx]
        mask = final.row_record_indices == idx
        zmax = float(np.max(np.abs(z_final[mask]))) if np.any(mask) else 0.0
        if zmax > k1:
            outlier_labels.append(rec.label)
        elif obs_weights[pos] < 1.0 - 1e-9:
            suspected.append(rec.label)
    final.outlier_labels = outlier_labels
    final.suspected_labels = suspected
    final.robust_scale = float(final_scale)
    final.robust_history = history
    final.max_update = float(final.max_update)
    final.converged = bool(converged)
    final.iterations = int(len(history))
    return final


def huber_estimate(dataset: ObservationDataset, **kwargs: Any) -> EstimationResult:
    kwargs.setdefault("method", "huber")
    return robust_estimate(dataset, **kwargs)


def igg3_estimate(dataset: ObservationDataset, **kwargs: Any) -> EstimationResult:
    kwargs.setdefault("method", "igg3")
    return robust_estimate(dataset, **kwargs)


__all__ = [
    "DEFAULT_ALPHA",
    "DEFAULT_W_CRITICAL",
    "DEFAULT_HUBER_C",
    "DEFAULT_IGG_K0",
    "DEFAULT_IGG_K1",
    "BlunderSpec",
    "SimulatedObservation",
    "ObservationDataset",
    "simulate_observations",
    "simulate_planar",
    "simulate_leveling",
    "EstimationResult",
    "estimate_network",
    "least_squares",
    "estimate",
    "GlobalTestResult",
    "global_model_test",
    "SnoopingRound",
    "DataSnoopingResult",
    "data_snooping",
    "robust_estimate",
    "huber_estimate",
    "igg3_estimate",
    "chi2_cdf",
    "chi2_sf",
    "chi2_critical",
    "student_t_sf",
    "t_critical",
]
