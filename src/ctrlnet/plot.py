"""matplotlib 网图与误差椭圆绘制。"""

from __future__ import annotations

from math import atan2, cos, degrees, hypot, radians, sin
from typing import Any, Optional, Tuple

import numpy as np

from .adjustment import AdjustmentResult, solve
from .model import Angle, Direction, Distance, GnssBaseline2D, Network, Scenario
from .precision import analyze_precision, confidence_scale


def _resolve(obj: Any, result: Any = None) -> Tuple[AdjustmentResult, Network]:
    if isinstance(obj, AdjustmentResult):
        return obj, obj.network
    if isinstance(obj, Scenario):
        if result is None:
            result = obj.solve()
        return result, obj.network
    if isinstance(obj, Network):
        if result is None:
            result = solve(obj)
        return result, obj
    if result is not None:
        return result, result.network
    raise TypeError("plot_network 需要 AdjustmentResult、Scenario 或 Network")


def plot_network(
    obj: Any,
    result: Optional[AdjustmentResult] = None,
    ax: Any = None,
    scale: float = 1.0,
    confidence: Optional[float] = None,
    show_labels: bool = True,
    show_observation_labels: bool = False,
    show_ellipses: bool = True,
    figsize: Tuple[float, float] = (7.0, 7.0),
    title: Optional[str] = None,
) -> Tuple[Any, Any]:
    """绘制平面控制网。

    固定点用三角形、待定点用圆点；距离/方向/角度/GNSS 基线画成观测线；
    误差椭圆按 ``scale`` 放大绘制，置信水平 confidence=None 表示标准椭圆，
    0.95 表示 95% 置信椭圆。
    """
    import matplotlib.pyplot as plt
    from matplotlib.patches import Ellipse

    res, net = _resolve(obj, result)
    if ax is None:
        fig, ax = plt.subplots(figsize=figsize)
    else:
        fig = ax.figure

    # 观测线
    for obs in net.observations:
        if isinstance(obs, Distance):
            p, q = net.point(obs.frm), net.point(obs.to)
            ax.plot([p.E, q.E], [p.N, q.N], color="0.35", lw=1.0, zorder=1)
            if show_observation_labels:
                ax.text(
                    (p.E + q.E) / 2.0,
                    (p.N + q.N) / 2.0,
                    obs.label,
                    fontsize=7,
                    color="0.35",
                    ha="center",
                    va="bottom",
                )
        elif isinstance(obs, Direction):
            p, q = net.point(obs.station), net.point(obs.target)
            ax.annotate(
                "",
                xy=(q.E, q.N),
                xytext=(p.E, p.N),
                arrowprops=dict(arrowstyle="->", color="tab:orange", lw=1.0),
                zorder=1,
            )
            if show_observation_labels:
                ax.text(
                    (p.E + q.E) / 2.0,
                    (p.N + q.N) / 2.0,
                    obs.label,
                    fontsize=7,
                    color="tab:orange",
                    ha="center",
                    va="bottom",
                )
        elif isinstance(obs, Angle):
            s = net.point(obs.station)
            b = net.point(obs.backsight)
            f = net.point(obs.foresight)
            ax.plot([s.E, b.E], [s.N, b.N], color="tab:green", lw=0.9, ls="-", zorder=1)
            ax.plot([s.E, f.E], [s.N, f.N], color="tab:green", lw=0.9, ls="-", zorder=1)
            if show_observation_labels:
                ax.text(
                    s.E,
                    s.N,
                    obs.label,
                    fontsize=7,
                    color="tab:green",
                    ha="left",
                    va="bottom",
                )
        elif isinstance(obs, GnssBaseline2D):
            p, q = net.point(obs.frm), net.point(obs.to)
            ax.plot(
                [p.E, q.E],
                [p.N, q.N],
                color="tab:purple",
                lw=1.3,
                ls="--",
                zorder=1,
            )
            if show_observation_labels:
                ax.text(
                    (p.E + q.E) / 2.0,
                    (p.N + q.N) / 2.0,
                    obs.label,
                    fontsize=7,
                    color="tab:purple",
                    ha="center",
                    va="bottom",
                )

    # 点与误差椭圆
    precision = analyze_precision(res)
    factor = confidence_scale(confidence)
    labeled_fixed = False
    labeled_unknown = False
    for p in net.points:
        pp = precision.points[p.name]
        if p.fixed:
            ax.scatter(
                [p.E],
                [p.N],
                marker="^",
                s=65,
                facecolors="white",
                edgecolors="black",
                zorder=5,
                label=None if labeled_fixed else "Fixed point",
            )
            labeled_fixed = True
        else:
            ax.scatter(
                [p.E],
                [p.N],
                marker="o",
                s=45,
                facecolors="tab:blue",
                edgecolors="black",
                zorder=5,
                label=None if labeled_unknown else "Unknown point",
            )
            labeled_unknown = True
        if show_labels:
            ax.text(
                p.E,
                p.N,
                f" {p.name}",
                fontsize=9,
                ha="left",
                va="bottom",
                zorder=6,
            )
        if show_ellipses and not p.fixed and pp.ellipse.standard_major > 0.0:
            a = pp.ellipse.standard_major * factor * scale
            b = pp.ellipse.standard_minor * factor * scale
            # 方位角从北起顺时针；matplotlib 的角度从 +E 轴逆时针。
            angle = 90.0 - pp.ellipse.azimuth_deg
            e = Ellipse(
                (p.E, p.N),
                width=2.0 * a,
                height=2.0 * b,
                angle=angle,
                facecolor="tab:blue",
                alpha=0.12,
                edgecolor="tab:blue",
                lw=0.9,
                zorder=3,
            )
            ax.add_patch(e)

    ax.set_aspect("equal", adjustable="box")
    ax.set_xlabel("E / m")
    ax.set_ylabel("N / m")
    ax.grid(True, color="0.9", zorder=0)
    if title is None:
        conf = f", {confidence:g} confidence" if confidence else ", standard"
        title = f"Control network (ellipse {scale:g}x{conf})"
    ax.set_title(title)
    handles, labels = ax.get_legend_handles_labels()
    if handles:
        ax.legend(loc="best", fontsize=8)
    fig.tight_layout()
    return fig, ax


__all__ = ["plot_network"]
