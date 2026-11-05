"""计算核心的自定义异常。

所有异常都携带可读的中文说明，并尽量附带可定位的实体信息。
"""

from __future__ import annotations

from typing import Any, Iterable, Optional


class CtrlnetError(Exception):
    """包内异常基类。"""


class AdjustmentError(CtrlnetError):
    """平差解算相关错误。"""


class RankDeficientError(AdjustmentError):
    """设计矩阵秩亏，通常意味着基准不足或局部网形不可解。"""

    def __init__(
        self,
        message: str,
        *,
        rank: Optional[int] = None,
        n_params: Optional[int] = None,
        null_space: Any = None,
        parameter_names: Optional[Iterable[str]] = None,
        diagnostics: Optional[Iterable[str]] = None,
    ) -> None:
        super().__init__(message)
        self.rank = rank
        self.n_params = n_params
        self.null_space = null_space
        self.parameter_names = list(parameter_names) if parameter_names is not None else []
        self.diagnostics = list(diagnostics) if diagnostics is not None else []


class InvalidPrecisionError(AdjustmentError):
    """精度/协方差参数非法（非有限值、非正、非正定等）。"""


class InvalidGeometryError(AdjustmentError):
    """几何退化（重合点、零长度边、无法定义的角等）。"""


class RegistrationError(CtrlnetError, ValueError):
    """影像仿射配准失败（控制点不足、共线、坐标非法等）。"""


class PackageError(CtrlnetError, ValueError):
    """工程包格式、版本、哈希或内容校验失败。"""


__all__ = [
    "CtrlnetError",
    "AdjustmentError",
    "RankDeficientError",
    "InvalidPrecisionError",
    "InvalidGeometryError",
    "RegistrationError",
    "PackageError",
]
