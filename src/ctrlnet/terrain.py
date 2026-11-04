"""DEM 采样、剖面、通视分析与地形渲染。

本模块只依赖 NumPy/Matplotlib 完成计算；读取 GeoTIFF 时通过可选的
``rasterio``（``pip install -e ".[terrain]"``）完成，避免把 GIS 依赖带进
纯计算测试。

坐标约定
--------
* DEM 使用其自身水平 CRS 的米制坐标 ``(E, N)``。真实样例在
  :mod:`scripts.fetch_dem` 中重投影到当地 UTM 带（EPSG:32650）。
* 仿射变换沿用 GeoTIFF/rasterio 的六参数顺序 ``(a, b, c, d, e, f)``：

  ``E = a·col + b·row + c``，``N = d·col + e·row + f``。

* GeoTIFF 的仿射变换把像素**角点**映射到坐标，高程值位于像素中心，因此
  双线性采样先把坐标换算为“中心索引”再减 ``0.5``。
* 视线高度采用设计阶段等效地球半径模型：

  ``h_LOS(x) = h1 + (h2-h1)·x/d − (1−k)·x(d−x)/(2R)``。

  负号表示地球曲率使视线相对两端连线下沉，折光系数 ``k`` 部分抵消该效应。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from math import ceil, floor, hypot, isfinite
from typing import Any, Iterable, Mapping, Optional, Sequence, Tuple, Union

import numpy as np

DEFAULT_K = 0.13
DEFAULT_R = 6_371_000.0
DEFAULT_INSTRUMENT_HEIGHT = 1.5
DEFAULT_TARGET_HEIGHT = 1.5
DEFAULT_CLEARANCE = 0.0
DEFAULT_STEP_LIMITS = (0.5, 10.0)

Number = Union[int, float]
PointLike = Union[Sequence[float], Any]


def _as_en(point: PointLike) -> Tuple[float, float]:
    """把 ``Point``/``(E, N)`` 统一转换为浮点坐标。"""
    if hasattr(point, "E") and hasattr(point, "N"):
        return float(point.E), float(point.N)
    if isinstance(point, (tuple, list, np.ndarray)) and len(point) >= 2:
        return float(point[0]), float(point[1])
    raise TypeError("点必须是 (E, N) 序列或带 E/N 属性的对象")


def _as_resolution(resolution: Union[Number, Sequence[Number]]) -> Tuple[float, float]:
    if np.isscalar(resolution):
        value = float(resolution)
        if not isfinite(value) or value <= 0.0:
            raise ValueError("resolution 必须为正的有限值")
        return value, value
    values = tuple(float(v) for v in resolution)
    if len(values) == 1:
        values = (values[0], values[0])
    if len(values) != 2 or any((not isfinite(v) or v <= 0.0) for v in values):
        raise ValueError("resolution 必须是正数或 (xres, yres)")
    return values[0], values[1]


@dataclass(frozen=True)
class AffineTransform:
    """二维仿射变换（GeoTIFF 六参数顺序）。

    ``E = a·col + b·row + c``，``N = d·col + e·row + f``。
    对常规北向上的栅格，``b = d = 0``、``a > 0``、``e < 0``。
    """

    a: float
    b: float
    c: float
    d: float
    e: float
    f: float

    def __post_init__(self) -> None:
        for name in ("a", "b", "c", "d", "e", "f"):
            value = float(getattr(self, name))
            if not isfinite(value):
                raise ValueError(f"仿射参数 {name} 必须是有限值")
            object.__setattr__(self, name, value)

    # ---- 构造 -----------------------------------------------------
    @classmethod
    def from_gdal(cls, values: Sequence[float]) -> "AffineTransform":
        """由 GDAL ``GetGeoTransform()`` 的 ``(c, a, b, f, d, e)`` 构造。"""
        values = tuple(float(v) for v in values)
        if len(values) != 6:
            raise ValueError("GDAL geotransform 必须包含 6 个参数")
        c, a, b, f, d, e = values
        return cls(a, b, c, d, e, f)

    @classmethod
    def from_origin(
        cls, west: float, north: float, xres: float, yres: float
    ) -> "AffineTransform":
        """由左上角坐标和正分辨率构造北向上变换。"""
        xres, yres = _as_resolution((xres, yres))
        return cls(xres, 0.0, float(west), 0.0, -yres, float(north))

    @classmethod
    def from_bounds(
        cls,
        left: float,
        bottom: float,
        right: float,
        top: float,
        width: int,
        height: int,
    ) -> "AffineTransform":
        if width <= 0 or height <= 0:
            raise ValueError("width/height 必须为正整数")
        return cls.from_origin(left, top, (right - left) / width, (top - bottom) / height)

    @classmethod
    def coerce(cls, transform: Any) -> "AffineTransform":
        """接受本类、rasterio/affine 对象、GDAL 或六个仿射参数。"""
        if isinstance(transform, cls):
            return transform
        if hasattr(transform, "to_gdal"):
            return cls.from_gdal(transform.to_gdal())
        if all(hasattr(transform, name) for name in ("a", "b", "c", "d", "e", "f")):
            return cls(
                transform.a,
                transform.b,
                transform.c,
                transform.d,
                transform.e,
                transform.f,
            )
        values = tuple(transform)
        if len(values) == 6:
            return cls(*values)
        raise TypeError("无法解析仿射变换；需要 AffineTransform、affine 对象或 6 参数")

    # ---- 属性 -----------------------------------------------------
    @property
    def xres(self) -> float:
        return hypot(self.a, self.d)

    @property
    def yres(self) -> float:
        return hypot(self.b, self.e)

    @property
    def resolution(self) -> Tuple[float, float]:
        return self.xres, self.yres

    def to_tuple(self) -> Tuple[float, float, float, float, float, float]:
        return self.a, self.b, self.c, self.d, self.e, self.f

    def to_gdal(self) -> Tuple[float, float, float, float, float, float]:
        return self.c, self.a, self.b, self.f, self.d, self.e

    def __iter__(self):
        return iter(self.to_tuple())

    # ---- 正反算 ---------------------------------------------------
    def xy(self, col: float, row: float) -> Tuple[float, float]:
        return (
            self.a * col + self.b * row + self.c,
            self.d * col + self.e * row + self.f,
        )

    def inverse(self) -> "AffineTransform":
        det = self.a * self.e - self.b * self.d
        if abs(det) < 1e-30:
            raise ValueError("仿射变换不可逆（行列式接近 0）")
        ia = self.e / det
        ib = -self.b / det
        id_ = -self.d / det
        ie = self.a / det
        ic = -(ia * self.c + ib * self.f)
        if_ = -(id_ * self.c + ie * self.f)
        return AffineTransform(ia, ib, ic, id_, ie, if_)

    def rowcol(self, E: float, N: float) -> Tuple[float, float]:
        """返回连续的 ``(col, row)`` 像素角点索引。"""
        inv = self.inverse()
        return (
            inv.a * E + inv.b * N + inv.c,
            inv.d * E + inv.e * N + inv.f,
        )


def _coerce_affine(transform: Any) -> AffineTransform:
    return AffineTransform.coerce(transform)


@dataclass
class Profile:
    """沿两点连线的 DEM 剖面。"""

    start: Tuple[float, float]
    end: Tuple[float, float]
    x: np.ndarray
    y: np.ndarray
    distance: np.ndarray
    elevation: np.ndarray
    nodata: np.ndarray
    step: float

    def __post_init__(self) -> None:
        self.x = np.asarray(self.x, dtype=float)
        self.y = np.asarray(self.y, dtype=float)
        self.distance = np.asarray(self.distance, dtype=float)
        self.elevation = np.asarray(self.elevation, dtype=float)
        self.nodata = np.asarray(self.nodata, dtype=bool)

    def __len__(self) -> int:
        return int(self.distance.size)

    @property
    def length(self) -> float:
        return float(self.distance[-1]) if self.distance.size else 0.0

    @property
    def sample_count(self) -> int:
        return int(self.distance.size)

    @property
    def valid_mask(self) -> np.ndarray:
        return ~self.nodata

    @property
    def terrain(self) -> np.ndarray:
        """剖面高程的常用别名。"""
        return self.elevation

    @property
    def d(self) -> np.ndarray:
        """距起点的水平距离的常用别名。"""
        return self.distance

    def as_dict(self) -> dict:
        return {
            "start": list(self.start),
            "end": list(self.end),
            "step_m": float(self.step),
            "length_m": float(self.length),
            "distance_m": self.distance.tolist(),
            "x": self.x.tolist(),
            "y": self.y.tolist(),
            "elevation_m": self.elevation.tolist(),
            "nodata": self.nodata.tolist(),
        }


@dataclass
class IntervisibilityResult:
    """两点通视结果。

    ``status`` 为 ``visible`` / ``blocked`` / ``marginal`` / ``unknown``；
    ``visible`` 仅在 ``min_clearance >= clearance_threshold`` 且剖面无 NoData
    时为真。默认阈值为 0 m（文档建议光学观测现场按 0.5–1.5 m 复核）。
    """

    profile: Profile
    instrument_height: float
    target_height: float
    k: float
    radius: float
    clearance_threshold: float
    line_height: np.ndarray
    clearance: np.ndarray
    min_clearance: float
    min_index: int
    min_distance: float
    min_position: Optional[Tuple[float, float]]
    min_terrain_elevation: Optional[float]
    status: str
    visible: bool
    ground_start: float
    ground_end: float
    nodata_count: int

    def __post_init__(self) -> None:
        self.line_height = np.asarray(self.line_height, dtype=float)
        self.clearance = np.asarray(self.clearance, dtype=float)

    @property
    def start(self) -> Tuple[float, float]:
        return self.profile.start

    @property
    def end(self) -> Tuple[float, float]:
        return self.profile.end

    @property
    def distance(self) -> float:
        return self.profile.length

    @property
    def min_clearance_m(self) -> float:
        return self.min_clearance

    @property
    def is_visible(self) -> bool:
        return self.visible

    @property
    def obstruction(self) -> Optional[Tuple[float, float]]:
        return self.obstruction_position

    @property
    def profile_data(self) -> Profile:
        return self.profile

    @property
    def blocked(self) -> bool:
        return self.status == "blocked"

    @property
    def obstruction_position(self) -> Optional[Tuple[float, float]]:
        if self.status in ("blocked", "marginal", "unknown"):
            return self.min_position
        return None

    @property
    def obstruction_distance(self) -> Optional[float]:
        if self.status in ("blocked", "marginal", "unknown"):
            return self.min_distance
        return None

    @property
    def obstruction_elevation(self) -> Optional[float]:
        if self.status in ("blocked", "marginal", "unknown"):
            return self.min_terrain_elevation
        return None

    @property
    def h1(self) -> float:
        return float(self.ground_start + self.instrument_height)

    @property
    def h2(self) -> float:
        return float(self.ground_end + self.target_height)

    def as_dict(self, include_profile: bool = False) -> dict:
        data = {
            "from": [float(self.start[0]), float(self.start[1])],
            "to": [float(self.end[0]), float(self.end[1])],
            "distance_m": float(self.distance),
            "status": self.status,
            "visible": bool(self.visible),
            "min_clearance_m": None
            if not isfinite(self.min_clearance)
            else float(self.min_clearance),
            "min_distance_m": None
            if not isfinite(self.min_distance)
            else float(self.min_distance),
            "obstruction_position": None
            if self.obstruction_position is None
            else [float(self.obstruction_position[0]), float(self.obstruction_position[1])],
            "obstruction_elevation_m": self.obstruction_elevation,
            "ground_start_m": float(self.ground_start),
            "ground_end_m": float(self.ground_end),
            "instrument_height_m": float(self.instrument_height),
            "target_height_m": float(self.target_height),
            "k": float(self.k),
            "R_m": float(self.radius),
            "clearance_threshold_m": float(self.clearance_threshold),
            "nodata_count": int(self.nodata_count),
            "samples": int(self.profile.sample_count),
        }
        if include_profile:
            data["profile"] = self.profile.as_dict()
        return data


class DEM:
    """规则格网数字高程模型。

    Parameters
    ----------
    array:
        二维高程数组（米），行向南、列向东增加。
    transform:
        :class:`AffineTransform`、rasterio/affine 对象或 ``(a,b,c,d,e,f)``。
    nodata:
        无效值；``None`` 表示只用非有限值判定 NoData。
    crs:
        水平 CRS 标识（字符串或 rasterio CRS）。
    valid_mask:
        可选布尔掩码，``True`` 表示有效像素。
    """

    def __init__(
        self,
        array: Any,
        transform: Any,
        nodata: Optional[float] = None,
        crs: Any = None,
        metadata: Optional[Mapping[str, Any]] = None,
        valid_mask: Optional[Any] = None,
        name: Optional[str] = None,
    ) -> None:
        arr = np.asarray(array, dtype=float)
        if arr.ndim != 2:
            raise ValueError(f"DEM 数组必须是二维，收到 shape={arr.shape}")
        if arr.shape[0] < 2 or arr.shape[1] < 2:
            raise ValueError("DEM 至少需要 2×2 个格网")
        self.array = arr
        self.transform = _coerce_affine(transform)
        self.nodata = None if nodata is None else float(nodata)
        self.crs = None if crs is None else str(crs)
        self.metadata = dict(metadata or {})
        self.name = name or self.metadata.get("name") or "DEM"

        invalid = ~np.isfinite(arr)
        if self.nodata is not None and isfinite(self.nodata):
            invalid |= arr == self.nodata
        if valid_mask is not None:
            given = np.asarray(valid_mask, dtype=bool)
            if given.shape != arr.shape:
                raise ValueError("valid_mask 形状必须与 DEM 数组一致")
            invalid |= ~given
        self._valid = ~invalid
        self._valid_count = int(self._valid.sum())

    # ---- 构造/读取 ------------------------------------------------
    @classmethod
    def from_geotiff(cls, path: Any) -> "DEM":
        """读取单波段 GeoTIFF（需要可选依赖 ``rasterio``）。"""
        try:
            import rasterio
        except ImportError as exc:  # pragma: no cover - 依赖未安装时
            raise ImportError(
                "读取 GeoTIFF 需要 rasterio：pip install -e '.[terrain]'"
            ) from exc

        with rasterio.open(path) as ds:
            arr = ds.read(1)
            mask = ds.read_masks(1)
            transform = AffineTransform(
                ds.transform.a,
                ds.transform.b,
                ds.transform.c,
                ds.transform.d,
                ds.transform.e,
                ds.transform.f,
            )
            metadata = {str(k): str(v) for k, v in ds.tags().items()}
            metadata.update(
                {
                    "source": str(path),
                    "width": int(ds.width),
                    "height": int(ds.height),
                    "resolution": [float(ds.res[0]), float(ds.res[1])],
                    "driver": ds.driver,
                }
            )
            if ds.crs is not None:
                metadata.setdefault("crs_wkt", ds.crs.to_wkt())
            return cls(
                arr,
                transform,
                nodata=ds.nodata,
                crs=ds.crs,
                metadata=metadata,
                valid_mask=mask > 0,
                name=str(path),
            )

    @classmethod
    def from_npz(
        cls,
        path: Any,
        transform: Optional[Any] = None,
        nodata: Optional[float] = None,
        crs: Any = None,
    ) -> "DEM":
        """读取 ``.npz`` 小样本；可用 ``array``/``elevation`` 键，``transform`` 键。"""
        with np.load(path, allow_pickle=False) as data:
            if "array" in data:
                arr = data["array"]
            elif "elevation" in data:
                arr = data["elevation"]
            else:
                raise KeyError("npz 中需要 'array' 或 'elevation' 数组")
            tf = transform
            if tf is None and "transform" in data:
                tf = tuple(float(v) for v in data["transform"])
            if tf is None:
                raise ValueError("npz 缺少 transform，且未显式提供")
            if nodata is None and "nodata" in data:
                value = float(np.asarray(data["nodata"]).ravel()[0])
                nodata = value
            return cls(arr, tf, nodata=nodata, crs=crs, name=str(path))

    # ---- 基本属性 -------------------------------------------------
    @property
    def shape(self) -> Tuple[int, int]:
        return self.array.shape

    @property
    def height(self) -> int:
        return int(self.array.shape[0])

    @property
    def width(self) -> int:
        return int(self.array.shape[1])

    @property
    def xres(self) -> float:
        return self.transform.xres

    @property
    def yres(self) -> float:
        return self.transform.yres

    @property
    def resolution(self) -> Tuple[float, float]:
        return self.transform.resolution

    @property
    def valid_mask(self) -> np.ndarray:
        return self._valid

    @property
    def nodata_mask(self) -> np.ndarray:
        return ~self._valid

    @property
    def valid_fraction(self) -> float:
        return self._valid_count / float(self.array.size)

    @property
    def bounds(self) -> Tuple[float, float, float, float]:
        """返回 ``(left, bottom, right, top)``（旋转栅格用四角包络）。"""
        cols = [0.0, float(self.width), float(self.width), 0.0]
        rows = [0.0, 0.0, float(self.height), float(self.height)]
        xs = [self.transform.xy(c, r)[0] for c, r in zip(cols, rows)]
        ys = [self.transform.xy(c, r)[1] for c, r in zip(cols, rows)]
        return min(xs), min(ys), max(xs), max(ys)

    @property
    def extent(self) -> Tuple[float, float, float, float]:
        return self.bounds

    def __repr__(self) -> str:  # pragma: no cover - 仅调试
        left, bottom, right, top = self.bounds
        return (
            f"DEM(shape={self.shape}, res={self.resolution}, "
            f"bounds=({left:.1f},{bottom:.1f},{right:.1f},{top:.1f}), "
            f"crs={self.crs!r}, nodata={self.nodata!r})"
        )

    # ---- 采样 -----------------------------------------------------
    def _bilinear_scalar(self, E: float, N: float) -> float:
        inv = self.transform.inverse()
        col = inv.a * E + inv.b * N + inv.c - 0.5
        row = inv.d * E + inv.e * N + inv.f - 0.5
        if not (isfinite(col) and isfinite(row)):
            return float("nan")
        if col < 0.0 or col > self.width - 1 or row < 0.0 or row > self.height - 1:
            return float("nan")

        c0 = int(floor(col))
        r0 = int(floor(row))
        c1 = min(c0 + 1, self.width - 1)
        r1 = min(r0 + 1, self.height - 1)
        fx = col - c0
        fy = row - r0

        weights = (
            ((1.0 - fx) * (1.0 - fy), r0, c0),
            (fx * (1.0 - fy), r0, c1),
            ((1.0 - fx) * fy, r1, c0),
            (fx * fy, r1, c1),
        )
        value = 0.0
        for weight, r, c in weights:
            if weight <= 1e-14:
                continue
            if not self._valid[r, c]:
                return float("nan")
            value += weight * self.array[r, c]
        return float(value)

    def elevation(self, E: Any, N: Any) -> Any:
        """双线性插值高程；NoData/越界返回 ``nan``。

        标量输入返回 ``float``，数组输入返回同形状 ``ndarray``。
        """
        scalar = np.ndim(E) == 0 and np.ndim(N) == 0
        E_arr, N_arr = np.broadcast_arrays(
            np.asarray(E, dtype=float), np.asarray(N, dtype=float)
        )
        if scalar:
            return self._bilinear_scalar(float(E_arr), float(N_arr))

        out = np.full(E_arr.shape, np.nan, dtype=float)
        for index in np.ndindex(E_arr.shape):
            out[index] = self._bilinear_scalar(E_arr[index], N_arr[index])
        return out

    def sample(self, E: Any, N: Any) -> Any:
        """:meth:`elevation` 的别名。"""
        return self.elevation(E, N)

    # ---- 剖面 -----------------------------------------------------
    def default_step(self) -> float:
        """按方案 §5.7.2：``clamp(0.5×resolution, 0.5, 10)`` 米。"""
        base = 0.5 * min(self.xres, self.yres)
        return float(np.clip(base, *DEFAULT_STEP_LIMITS))

    def profile(self, p1: PointLike, p2: PointLike, step: Optional[float] = None) -> Profile:
        """沿 ``p1``→``p2`` 等距采样并返回 :class:`Profile`。"""
        x1, y1 = _as_en(p1)
        x2, y2 = _as_en(p2)
        length = hypot(x2 - x1, y2 - y1)
        if length <= 0.0:
            raise ValueError("剖面起点与终点重合")
        if step is None:
            step = self.default_step()
        step = float(step)
        if not isfinite(step) or step <= 0.0:
            raise ValueError("step 必须为正的有限值")

        intervals = max(1, int(ceil(length / step)))
        distance = np.linspace(0.0, length, intervals + 1)
        x = x1 + (x2 - x1) * distance / length
        y = y1 + (y2 - y1) * distance / length
        elevation = np.asarray(self.elevation(x, y), dtype=float)
        nodata = ~np.isfinite(elevation)
        return Profile(
            start=(x1, y1),
            end=(x2, y2),
            x=x,
            y=y,
            distance=distance,
            elevation=elevation,
            nodata=nodata,
            step=length / intervals,
        )

    # ---- 通视 -----------------------------------------------------
    def intervisibility(
        self,
        p1: PointLike,
        p2: PointLike,
        inst_h: float = DEFAULT_INSTRUMENT_HEIGHT,
        target_h: float = DEFAULT_TARGET_HEIGHT,
        k: float = DEFAULT_K,
        R: float = DEFAULT_R,
        clearance: float = DEFAULT_CLEARANCE,
        step: Optional[float] = None,
    ) -> IntervisibilityResult:
        """两点通视分析（含地球曲率与折光改正）。

        Parameters
        ----------
        inst_h, target_h:
            仪器高与目标高（米），分别加到两端地面高程上。
        k:
            折光系数，默认 0.13。
        R:
            地球平均半径（米），默认 6 371 000。
        clearance:
            通视所需最小净空阈值（米）。默认 0，即 ``min_clearance >= 0``。
        step:
            剖面采样步长；``None`` 时按 DEM 分辨率自动选取。
        """
        if not isfinite(float(inst_h)) or float(inst_h) < 0.0:
            raise ValueError("inst_h 必须为非负有限值")
        if not isfinite(float(target_h)) or float(target_h) < 0.0:
            raise ValueError("target_h 必须为非负有限值")
        if not isfinite(float(k)) or not (0.0 <= float(k) < 1.0):
            raise ValueError("k 必须在 [0, 1) 内")
        if not isfinite(float(R)) or float(R) <= 0.0:
            raise ValueError("R 必须为正的有限值")
        if not isfinite(float(clearance)) or float(clearance) < 0.0:
            raise ValueError("clearance 必须为非负有限值")

        prof = self.profile(p1, p2, step=step)
        d = prof.length
        ground_start = float(prof.elevation[0])
        ground_end = float(prof.elevation[-1])
        h1 = ground_start + float(inst_h)
        h2 = ground_end + float(target_h)

        line = np.asarray(
            line_of_sight_height(prof.distance, d, h1, h2, k=float(k), R=float(R)),
            dtype=float,
        )
        with np.errstate(invalid="ignore"):
            clear = line - prof.elevation

        nodata_count = int(prof.nodata.sum())
        finite = np.isfinite(clear)
        if finite.any():
            work = np.where(finite, clear, np.inf)
            min_index = int(np.argmin(work))
            min_clearance = float(clear[min_index])
            min_distance = float(prof.distance[min_index])
            min_position = (float(prof.x[min_index]), float(prof.y[min_index]))
            min_terrain = float(prof.elevation[min_index])
        else:
            min_index = -1
            min_clearance = float("nan")
            min_distance = float("nan")
            min_position = None
            min_terrain = None

        threshold = float(clearance)
        if nodata_count:
            status = "unknown"
        elif not finite.any():
            status = "unknown"
        elif min_clearance < 0.0:
            status = "blocked"
        elif min_clearance < threshold:
            status = "marginal"
        else:
            status = "visible"

        return IntervisibilityResult(
            profile=prof,
            instrument_height=float(inst_h),
            target_height=float(target_h),
            k=float(k),
            radius=float(R),
            clearance_threshold=threshold,
            line_height=line,
            clearance=clear,
            min_clearance=min_clearance,
            min_index=min_index,
            min_distance=min_distance,
            min_position=min_position,
            min_terrain_elevation=min_terrain,
            status=status,
            visible=status == "visible",
            ground_start=ground_start,
            ground_end=ground_end,
            nodata_count=nodata_count,
        )

    # ---- 渲染便捷入口 ---------------------------------------------
    def hillshade(self, *args: Any, **kwargs: Any):
        return hillshade(self, *args, **kwargs)

    def contours(self, *args: Any, **kwargs: Any):
        return contours(self, *args, **kwargs)


def curvature_refraction_correction(
    x: Any, d: float, k: float = DEFAULT_K, R: float = DEFAULT_R
) -> Any:
    """返回曲率+折光对视线高度的改正量（米，正值表示下沉）。

    ``correction(x) = (1−k)·x·(d−x)/(2R)``。
    """
    d = float(d)
    if not isfinite(d) or d < 0.0:
        raise ValueError("d 必须为非负有限值")
    if not isfinite(float(k)) or not (0.0 <= float(k) < 1.0):
        raise ValueError("k 必须在 [0, 1) 内")
    if not isfinite(float(R)) or float(R) <= 0.0:
        raise ValueError("R 必须为正的有限值")
    x_arr = np.asarray(x, dtype=float)
    value = (1.0 - float(k)) * x_arr * (d - x_arr) / (2.0 * float(R))
    if np.ndim(x) == 0:
        return float(value)
    return value


def line_of_sight_height(
    x: Any,
    d: float,
    h1: float,
    h2: float,
    k: float = DEFAULT_K,
    R: float = DEFAULT_R,
) -> Any:
    """视线高度 ``h_LOS(x)``（米）。

    视线在两端分别通过 ``(0, h1)`` 与 ``(d, h2)``，中间按曲率/折光改正下沉。
    """
    d = float(d)
    if not isfinite(d) or d <= 0.0:
        raise ValueError("d 必须为正的有限值")
    x_arr = np.asarray(x, dtype=float)
    if np.any(x_arr < -1e-9) or np.any(x_arr > d + 1e-9):
        raise ValueError("x 必须位于 [0, d] 内")
    value = (
        float(h1)
        + (float(h2) - float(h1)) * x_arr / d
        - curvature_refraction_correction(x_arr, d, k=k, R=R)
    )
    if np.ndim(x) == 0:
        return float(value)
    return value


def hillshade(
    dem: Union[DEM, Any],
    azimuth: float = 315.0,
    altitude: float = 45.0,
    *,
    resolution: Optional[Union[Number, Sequence[Number]]] = None,
    z_factor: float = 1.0,
) -> np.ndarray:
    """生成地形晕渲，返回 ``[0, 1]`` 浮点数组。

    Parameters
    ----------
    dem:
        :class:`DEM` 或二维高程数组。数组须通过 ``resolution`` 给出格网间距。
    azimuth:
        光源方位角，度，自北顺时针（315 表示西北方向光照）。
    altitude:
        光源高度角，度。
    resolution:
        ``(xres, yres)`` 米；传入 DEM 时默认取仿射变换分辨率。
    z_factor:
        高程夸张系数，默认 1。
    """
    if isinstance(dem, DEM):
        arr = np.asarray(dem.array, dtype=float)
        valid = dem.valid_mask
        default_res = dem.resolution
    else:
        arr = np.asarray(dem, dtype=float)
        if arr.ndim != 2:
            raise ValueError("hillshade 需要二维高程数组")
        valid = np.isfinite(arr)
        default_res = (1.0, 1.0)

    if not isfinite(float(azimuth)):
        raise ValueError("azimuth 必须为有限值")
    if not isfinite(float(altitude)) or not (0.0 <= float(altitude) <= 90.0):
        raise ValueError("altitude 必须在 [0, 90] 度内")
    if not isfinite(float(z_factor)) or float(z_factor) <= 0.0:
        raise ValueError("z_factor 必须为正的有限值")

    xres, yres = _as_resolution(resolution) if resolution is not None else default_res
    if not valid.any():
        return np.zeros(arr.shape, dtype=float)

    fill = float(np.median(arr[valid]))
    filled = np.where(valid, arr, fill)
    dz_drow = np.gradient(filled, axis=0) / yres
    dz_dcol = np.gradient(filled, axis=1) / xres
    # 行号向南增加，因此向北的偏导取负号。
    dz_de = dz_dcol * float(z_factor)
    dz_dn = -dz_drow * float(z_factor)

    normal = np.dstack((-dz_de, -dz_dn, np.ones_like(filled)))
    norm = np.linalg.norm(normal, axis=2)
    norm = np.where(norm > 0.0, norm, 1.0)

    az = np.deg2rad(float(azimuth))
    alt = np.deg2rad(float(altitude))
    sun = np.array(
        [np.sin(az) * np.cos(alt), np.cos(az) * np.cos(alt), np.sin(alt)],
        dtype=float,
    )
    shade = np.sum(normal * sun, axis=2) / norm
    shade = np.clip(shade, 0.0, 1.0)
    shade[~valid] = 0.0
    return shade


def contours(
    dem: Union[DEM, Any],
    ax: Any = None,
    levels: Any = 10,
    *,
    filled: bool = False,
    **kwargs: Any,
):
    """用 Matplotlib 绘制等高线，返回 ``QuadContourSet``。

    传入 :class:`DEM` 时使用其仿射变换生成真实 E/N 坐标；传入数组时使用
    像素索引坐标。NoData 会被掩膜。
    """
    import matplotlib.pyplot as plt

    if isinstance(dem, DEM):
        z = np.ma.masked_invalid(dem.array)
        rows, cols = np.mgrid[0 : dem.height, 0 : dem.width]
        x = dem.transform.a * cols + dem.transform.b * rows + dem.transform.c
        y = dem.transform.d * cols + dem.transform.e * rows + dem.transform.f
    else:
        z = np.ma.masked_invalid(np.asarray(dem, dtype=float))
        if z.ndim != 2:
            raise ValueError("contours 需要二维高程数组")
        rows, cols = np.mgrid[0 : z.shape[0], 0 : z.shape[1]]
        x = cols.astype(float)
        y = rows.astype(float)

    if ax is None:
        _, ax = plt.subplots()
    kwargs.setdefault("linewidths", 0.5)
    if filled:
        return ax.contourf(x, y, z, levels=levels, **kwargs)
    return ax.contour(x, y, z, levels=levels, **kwargs)


__all__ = [
    "DEFAULT_K",
    "DEFAULT_R",
    "DEFAULT_CLEARANCE",
    "DEFAULT_INSTRUMENT_HEIGHT",
    "DEFAULT_TARGET_HEIGHT",
    "AffineTransform",
    "DEM",
    "Profile",
    "IntervisibilityResult",
    "curvature_refraction_correction",
    "line_of_sight_height",
    "hillshade",
    "contours",
]
