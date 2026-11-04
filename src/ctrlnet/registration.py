r"""扫描地形图/影像的六参数仿射配准。

模型
----
像素坐标 ``(col, row)`` 到工程平面坐标 ``(E, N)`` 的六参数仿射：

.. math::

   E = a_0 + a_1\,col + a_2\,row
   N = b_0 + b_1\,col + b_2\,row

像素约定与 GeoTIFF/世界文件一致：``col`` 向右、``row`` 向下，``(0, 0)`` 为
图像左上角像素**角点**；像素中心为 ``(col+0.5, row+0.5)``。控制点至少 3 对，
且不能共线；多于 3 对时按最小二乘求解，可选相对权。

输出世界文件（``.pgw``/``.tfw``）时，按世界文件约定使用左上角**像素中心**，
即第 5、6 行加 ``0.5·(a+b)`` 与 ``0.5·(d+e)``。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from math import isfinite, sqrt
from pathlib import Path
from typing import Any, Iterable, Mapping, Optional, Sequence, Tuple, Union

import numpy as np

from .exceptions import RegistrationError
from .terrain import AffineTransform

Number = Union[int, float]

_SUFFIX_TO_WORLD = {
    ".png": ".pgw",
    ".tif": ".tfw",
    ".tiff": ".tfw",
    ".jpg": ".jgw",
    ".jpeg": ".jgw",
    ".bmp": ".bpw",
    ".gif": ".gfw",
}


@dataclass(frozen=True)
class ControlPoint:
    """一对同名控制点：影像像素 ``(col,row)`` ↔ 工程坐标 ``(E,N)``。"""

    col: float
    row: float
    E: float
    N: float
    label: Optional[str] = None

    def __post_init__(self) -> None:
        for name in ("col", "row", "E", "N"):
            value = float(getattr(self, name))
            if not isfinite(value):
                raise RegistrationError(f"控制点 {name} 必须是有限数值")
            object.__setattr__(self, name, value)

    def as_dict(self) -> dict:
        return {
            "label": self.label,
            "col": self.col,
            "row": self.row,
            "E": self.E,
            "N": self.N,
        }


def _as_float(value: Any, name: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise RegistrationError(f"{name} 必须是数值") from exc
    if not isfinite(number):
        raise RegistrationError(f"{name} 必须是有限数值")
    return number


def _coerce_point(item: Any, index: int) -> ControlPoint:
    if isinstance(item, ControlPoint):
        return item
    label: Optional[str] = None
    if isinstance(item, Mapping):
        lowered = {str(k).lower(): v for k, v in item.items()}
        label_value = lowered.get("label", lowered.get("name"))
        label = None if label_value is None else str(label_value)
        col = lowered.get("col", lowered.get("u", lowered.get("pixel_col")))
        row = lowered.get("row", lowered.get("v", lowered.get("pixel_row")))
        E = lowered.get("e", lowered.get("easting"))
        N = lowered.get("n", lowered.get("northing"))
        if None in (col, row, E, N):
            raise RegistrationError(
                f"第 {index + 1} 个控制点缺少 col/row/E/N 字段"
            )
        return ControlPoint(
            _as_float(col, "col"),
            _as_float(row, "row"),
            _as_float(E, "E"),
            _as_float(N, "N"),
            label,
        )
    if hasattr(item, "col") and hasattr(item, "row") and hasattr(item, "E") and hasattr(item, "N"):
        return ControlPoint(
            _as_float(item.col, "col"),
            _as_float(item.row, "row"),
            _as_float(item.E, "E"),
            _as_float(item.N, "N"),
            getattr(item, "label", None),
        )
    if isinstance(item, (tuple, list, np.ndarray)) and len(item) >= 4:
        label = None if len(item) < 5 else (None if item[4] is None else str(item[4]))
        return ControlPoint(
            _as_float(item[0], "col"),
            _as_float(item[1], "row"),
            _as_float(item[2], "E"),
            _as_float(item[3], "N"),
            label,
        )
    raise RegistrationError(
        f"第 {index + 1} 个控制点格式非法；需要 ControlPoint、(col,row,E,N) 或字典"
    )


def _coerce_points(points: Iterable[Any], *, name: str) -> list[ControlPoint]:
    try:
        values = list(points)
    except TypeError as exc:
        raise RegistrationError(f"{name} 必须是可迭代的控制点集合") from exc
    return [_coerce_point(item, index) for index, item in enumerate(values)]


def _normalisation(points: Sequence[ControlPoint]) -> Tuple[float, float, float]:
    cols = np.asarray([p.col for p in points], dtype=float)
    rows = np.asarray([p.row for p in points], dtype=float)
    col0 = float(cols.mean())
    row0 = float(rows.mean())
    span = max(float(np.ptp(cols)), float(np.ptp(rows)), 1.0)
    return col0, row0, span


def _normal_matrix(points: Sequence[ControlPoint], col0: float, row0: float, span: float) -> np.ndarray:
    return np.column_stack(
        [
            np.ones(len(points), dtype=float),
            (np.asarray([p.col for p in points], dtype=float) - col0) / span,
            (np.asarray([p.row for p in points], dtype=float) - row0) / span,
        ]
    )


@dataclass
class RegistrationResult:
    """六参数仿射配准结果。"""

    transform: AffineTransform
    control_points: list[ControlPoint]
    residual_e: np.ndarray
    residual_n: np.ndarray
    weights: Optional[np.ndarray] = None
    check_points: list[ControlPoint] = field(default_factory=list)
    check_residual_e: Optional[np.ndarray] = None
    check_residual_n: Optional[np.ndarray] = None
    condition_number: float = float("nan")
    image_path: Optional[str] = None
    image_size: Optional[Tuple[int, int]] = None
    world_file: Optional[str] = None

    @property
    def n_points(self) -> int:
        return len(self.control_points)

    @property
    def parameters(self) -> Tuple[float, float, float, float, float, float]:
        """按 ``(a0, a1, a2, b0, b1, b2)`` 返回参数。"""
        t = self.transform
        return t.c, t.a, t.b, t.f, t.d, t.e

    @property
    def radial_residuals(self) -> np.ndarray:
        return np.hypot(self.residual_e, self.residual_n)

    @property
    def rms_e(self) -> float:
        return float(np.sqrt(np.mean(self.residual_e ** 2)))

    @property
    def rms_n(self) -> float:
        return float(np.sqrt(np.mean(self.residual_n ** 2)))

    @property
    def rms(self) -> float:
        """逐点平面残差 RMS：``sqrt(Σ(ΔE²+ΔN²)/k)``（米）。"""
        return float(np.sqrt(np.mean(self.residual_e ** 2 + self.residual_n ** 2)))

    @property
    def max_residual(self) -> float:
        return float(np.max(self.radial_residuals)) if self.n_points else float("nan")

    @property
    def check_rms(self) -> Optional[float]:
        if self.check_residual_e is None or self.check_residual_n is None or not len(self.check_residual_e):
            return None
        return float(
            np.sqrt(np.mean(self.check_residual_e ** 2 + self.check_residual_n ** 2))
        )

    def transform_points(self, cols: Any, rows: Any) -> Tuple[np.ndarray, np.ndarray]:
        cols_arr, rows_arr = np.broadcast_arrays(
            np.asarray(cols, dtype=float), np.asarray(rows, dtype=float)
        )
        return (
            self.transform.a * cols_arr + self.transform.b * rows_arr + self.transform.c,
            self.transform.d * cols_arr + self.transform.e * rows_arr + self.transform.f,
        )

    def as_dict(self) -> dict:
        t = self.transform
        controls = []
        for point, de, dn in zip(self.control_points, self.residual_e, self.residual_n):
            item = point.as_dict()
            item.update(
                {
                    "residual_E_m": float(de),
                    "residual_N_m": float(dn),
                    "residual_m": float(sqrt(float(de) ** 2 + float(dn) ** 2)),
                }
            )
            controls.append(item)

        checks = []
        if self.check_residual_e is not None and self.check_residual_n is not None:
            for point, de, dn in zip(
                self.check_points, self.check_residual_e, self.check_residual_n
            ):
                item = point.as_dict()
                item.update(
                    {
                        "residual_E_m": float(de),
                        "residual_N_m": float(dn),
                        "residual_m": float(sqrt(float(de) ** 2 + float(dn) ** 2)),
                    }
                )
                checks.append(item)

        payload = {
            "model": "6-parameter-affine",
            "convention": "pixel corner; E=a0+a1*col+a2*row, N=b0+b1*col+b2*row; row down",
            "parameters": {
                "a0": t.c,
                "a1": t.a,
                "a2": t.b,
                "b0": t.f,
                "b1": t.d,
                "b2": t.e,
            },
            "affine": list(t.to_tuple()),
            "n_control_points": self.n_points,
            "rms_m": self.rms,
            "rms_e_m": self.rms_e,
            "rms_n_m": self.rms_n,
            "max_residual_m": self.max_residual,
            "condition_number": self.condition_number,
            "control_points": controls,
        }
        if checks:
            payload["check_points"] = checks
            payload["check_rms_m"] = self.check_rms
        if self.image_path is not None:
            payload["image_path"] = self.image_path
        if self.image_size is not None:
            payload["image_size"] = list(self.image_size)
        if self.world_file is not None:
            payload["world_file"] = self.world_file
        return payload


def register_affine(
    control_points: Iterable[Any],
    check_points: Optional[Iterable[Any]] = None,
    *,
    weights: Optional[Sequence[float]] = None,
) -> RegistrationResult:
    """用至少 3 对控制点做六参数最小二乘仿射配准。

    Parameters
    ----------
    control_points:
        ``ControlPoint`` 集合、``(col,row,E,N[,label])`` 序列或含
        ``col/row/E/N`` 的字典序列。
    check_points:
        可选独立检查点，只参与精度统计，不参与参数求解。
    weights:
        可选逐点相对权（越大越可信）。内部按 ``sqrt(w)`` 加权。
    """
    points = _coerce_points(control_points, name="control_points")
    if len(points) < 3:
        raise RegistrationError(f"至少需要 3 对控制点，当前只有 {len(points)} 对")

    if weights is not None:
        w = np.asarray(list(weights), dtype=float)
        if w.shape != (len(points),):
            raise RegistrationError("weights 长度必须与控制点数量一致")
        if np.any(~np.isfinite(w)) or np.any(w <= 0.0):
            raise RegistrationError("weights 必须是正的有限数值")
        w = w / float(np.mean(w))
    else:
        w = np.ones(len(points), dtype=float)

    col0, row0, span = _normalisation(points)
    matrix = _normal_matrix(points, col0, row0, span)
    weighted = matrix * np.sqrt(w)[:, None]

    # 归一化坐标下检查共线/退化：共线时 M 的秩为 2（[1,u,v] 共面）。
    try:
        _, singular, vt = np.linalg.svd(weighted, full_matrices=False)
    except np.linalg.LinAlgError as exc:  # pragma: no cover - 极端数值
        raise RegistrationError("控制点法方程奇异，无法求解仿射参数") from exc
    if singular.size < 3 or singular[0] <= 0.0:
        raise RegistrationError("控制点退化，无法求解仿射参数")
    condition = float(singular[0] / max(singular[-1], 1e-300))
    if singular[-1] / singular[0] < 1e-9:
        raise RegistrationError(
            "控制点共线或近似共线，六参数仿射不可唯一求解；"
            "请在测区四周和内部均匀布设至少 3 个不共线控制点"
        )

    target_e = np.asarray([p.E for p in points], dtype=float)
    target_n = np.asarray([p.N for p in points], dtype=float)
    sqrt_w = np.sqrt(w)

    coef_e, *_ = np.linalg.lstsq(weighted, target_e * sqrt_w, rcond=None)
    coef_n, *_ = np.linalg.lstsq(weighted, target_n * sqrt_w, rcond=None)

    # 把归一化参数还原为原始像素坐标参数。
    e0, eu, ev = (float(v) for v in coef_e)
    n0, nu, nv = (float(v) for v in coef_n)
    a = eu / span
    b = ev / span
    c = e0 - a * col0 - b * row0
    d = nu / span
    e = nv / span
    f = n0 - d * col0 - e * row0
    transform = AffineTransform(a, b, c, d, e, f)

    residual_e = np.asarray([p.E for p in points], dtype=float) - (
        transform.a * np.asarray([p.col for p in points], dtype=float)
        + transform.b * np.asarray([p.row for p in points], dtype=float)
        + transform.c
    )
    residual_n = np.asarray([p.N for p in points], dtype=float) - (
        transform.d * np.asarray([p.col for p in points], dtype=float)
        + transform.e * np.asarray([p.row for p in points], dtype=float)
        + transform.f
    )

    checks = _coerce_points(check_points, name="check_points") if check_points is not None else []
    check_de = check_dn = None
    if checks:
        ce, cn = transform_points(transform, checks)
        check_de = np.asarray([p.E for p in checks], dtype=float) - ce
        check_dn = np.asarray([p.N for p in checks], dtype=float) - cn

    return RegistrationResult(
        transform=transform,
        control_points=points,
        residual_e=residual_e,
        residual_n=residual_n,
        weights=w,
        check_points=checks,
        check_residual_e=check_de,
        check_residual_n=check_dn,
        condition_number=condition,
    )


def transform_points(
    result_or_transform: Union[RegistrationResult, AffineTransform, Sequence[float]],
    points: Iterable[Any],
) -> Tuple[np.ndarray, np.ndarray]:
    """把像素点集合转换到工程坐标，便于检查点/叠加范围计算。"""
    transform = (
        result_or_transform.transform
        if isinstance(result_or_transform, RegistrationResult)
        else AffineTransform.coerce(result_or_transform)
    )
    items = _coerce_points(points, name="points")
    cols = np.asarray([p.col for p in items], dtype=float)
    rows = np.asarray([p.row for p in items], dtype=float)
    return (
        transform.a * cols + transform.b * rows + transform.c,
        transform.d * cols + transform.e * rows + transform.f,
    )


def world_file_path(image_path: Union[str, Path]) -> Path:
    """返回影像对应的世界文件名（PNG→.pgw，GeoTIFF→.tfw）。"""
    path = Path(image_path)
    suffix = path.suffix.lower()
    if suffix not in _SUFFIX_TO_WORLD:
        raise RegistrationError(
            f"不支持的影像扩展名 {suffix!r}；支持 "
            + ", ".join(sorted(_SUFFIX_TO_WORLD))
        )
    return path.with_suffix(_SUFFIX_TO_WORLD[suffix])


def write_world_file(
    image_path: Union[str, Path],
    transform: Union[RegistrationResult, AffineTransform, Sequence[float]],
    output: Optional[Union[str, Path]] = None,
) -> Path:
    """写出世界文件；PNG 默认 ``.pgw``，GeoTIFF 默认 ``.tfw``。

    世界文件使用像素中心坐标：
    ``C = c + 0.5(a+b)``、``F = f + 0.5(d+e)``。
    """
    affine = (
        transform.transform
        if isinstance(transform, RegistrationResult)
        else AffineTransform.coerce(transform)
    )
    target = Path(output) if output is not None else world_file_path(image_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    values = (
        affine.a,
        affine.d,
        affine.b,
        affine.e,
        affine.c + 0.5 * (affine.a + affine.b),
        affine.f + 0.5 * (affine.d + affine.e),
    )
    lines = "\n".join(f"{value:.12g}" for value in values) + "\n"
    target.write_text(lines, encoding="utf-8")
    return target


def read_world_file(path: Union[str, Path]) -> AffineTransform:
    """读取世界文件并还原为像素角点仿射（:class:`AffineTransform`）。"""
    values = Path(path).read_text(encoding="utf-8").split()
    if len(values) < 6:
        raise RegistrationError("世界文件至少需要 6 行数值")
    a, d, b, e, c_center, f_center = (float(v) for v in values[:6])
    return AffineTransform(
        a,
        b,
        c_center - 0.5 * (a + b),
        d,
        e,
        f_center - 0.5 * (d + e),
    )


def register_image(
    image_path: Union[str, Path],
    control_points: Iterable[Any],
    check_points: Optional[Iterable[Any]] = None,
    *,
    weights: Optional[Sequence[float]] = None,
    output_world: Optional[Union[str, Path]] = None,
    write_world: bool = False,
) -> RegistrationResult:
    """配准 PNG/GeoTIFF 并可选输出世界文件。

    ``write_world=True`` 时才写文件；``output_world`` 可指定路径。图像尺寸
    读取依赖 Pillow，缺失时只跳过尺寸检查，不影响参数求解与世界文件输出。
    """
    path = Path(image_path)
    suffix = path.suffix.lower()
    if suffix not in _SUFFIX_TO_WORLD:
        raise RegistrationError(
            f"不支持的影像格式 {suffix!r}；支持 PNG/GeoTIFF/JPEG/BMP/GIF"
        )
    if not path.exists():
        raise RegistrationError(f"影像不存在：{path}")

    result = register_affine(control_points, check_points, weights=weights)
    result.image_path = str(path)
    try:
        from PIL import Image

        with Image.open(path) as image:
            result.image_size = (int(image.width), int(image.height))
    except ImportError:  # pragma: no cover - Pillow 为可选依赖
        pass
    except Exception as exc:  # pragma: no cover - 文件损坏等
        raise RegistrationError(f"无法读取影像 {path}: {exc}") from exc

    if write_world or output_world is not None:
        target = write_world_file(path, result.transform, output_world)
        result.world_file = str(target)
    return result


__all__ = [
    "ControlPoint",
    "RegistrationError",
    "RegistrationResult",
    "read_world_file",
    "register_affine",
    "register_image",
    "transform_points",
    "world_file_path",
    "write_world_file",
]
