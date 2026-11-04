"""ctrlnet: 平面控制网精度估算与优化设计 MVP 计算核心。"""

from __future__ import annotations

__version__ = "0.1.0"

from .exceptions import CtrlnetError
from .adjustment import (
    AdjustmentResult,
    AdjustmentError,
    RankDeficientError,
    InvalidGeometryError,
    InvalidPrecisionError,
    solve,
)
from .datum import (
    Datum,
    FixedDatum,
    FreeDatum,
    MinimalDatum,
    WeightedDatum,
    normalize_datum,
)
from .design import (
    DesignSystem,
    ObservationBlock,
    ParameterIndex,
    build_design,
    build_parameter_index,
    whiten,
)
from .examples import section13_added, section13_base
from .model import (
    Angle,
    CoordinateConstraint,
    Direction,
    Distance,
    GnssBaseline2D,
    Network,
    Observation,
    Point,
    Scenario,
)
from .precision import (
    CHI2_2_95,
    K95,
    EdgePrecision,
    ErrorEllipse,
    PointPrecision,
    PrecisionResult,
    analyze_precision,
    confidence_scale,
    edge_gradient,
    edge_precision,
    edge_precisions,
    point_precision,
    point_precisions,
    weakest_edge,
    weakest_point,
)
from .reliability import (
    LAMBDA0_DEFAULT,
    ReliabilityRecord,
    ReliabilityResult,
    analyze_reliability,
    mdb_values,
    noncentrality,
    lambda0,
    redundancy_numbers,
    w_test,
)

__all__ = [
    "__version__",
    # model
    "Point",
    "Distance",
    "Direction",
    "Angle",
    "GnssBaseline2D",
    "CoordinateConstraint",
    "Network",
    "Scenario",
    "Observation",
    # design
    "ParameterIndex",
    "ObservationBlock",
    "DesignSystem",
    "build_parameter_index",
    "build_design",
    "whiten",
    # datum
    "Datum",
    "FixedDatum",
    "WeightedDatum",
    "MinimalDatum",
    "FreeDatum",
    "normalize_datum",
    # adjustment
    "AdjustmentResult",
    "AdjustmentError",
    "CtrlnetError",
    "RankDeficientError",
    "InvalidGeometryError",
    "InvalidPrecisionError",
    "solve",
    # precision
    "CHI2_2_95",
    "K95",
    "ErrorEllipse",
    "PointPrecision",
    "EdgePrecision",
    "PrecisionResult",
    "analyze_precision",
    "point_precision",
    "point_precisions",
    "edge_precision",
    "edge_precisions",
    "edge_gradient",
    "confidence_scale",
    "weakest_point",
    "weakest_edge",
    # reliability
    "LAMBDA0_DEFAULT",
    "noncentrality",
    "lambda0",
    "ReliabilityRecord",
    "ReliabilityResult",
    "analyze_reliability",
    "redundancy_numbers",
    "mdb_values",
    "w_test",
    # examples
    "section13_base",
    "section13_added",
]

from .compare import (
    Comparison,
    EdgeComparison,
    PlanMetrics,
    PointComparison,
    compare,
    compare_scenarios,
)
from .optimize import (
    Candidate,
    ObjectiveMetrics,
    OptimizationResult,
    OptimizationStep,
    SwapStep,
    greedy_optimize,
    optimize,
)
from .plot import plot_network
from .report import (
    format_edge_table,
    format_precision_table,
    format_reliability_table,
    format_report,
    report,
)

__all__ += [
    "PlanMetrics",
    "PointComparison",
    "EdgeComparison",
    "Comparison",
    "compare",
    "compare_scenarios",
    "Candidate",
    "ObjectiveMetrics",
    "OptimizationStep",
    "SwapStep",
    "OptimizationResult",
    "optimize",
    "greedy_optimize",
    "plot_network",
    "format_precision_table",
    "format_edge_table",
    "format_reliability_table",
    "format_report",
    "report",
]
