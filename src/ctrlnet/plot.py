"""matplotlib 网图与误差椭圆绘制。"""

from __future__ import annotations

from math import atan2, degrees, hypot
from typing import Any, Dict, Optional, Tuple

from .adjustment import AdjustmentResult, solve
from .model import Angle, Direction, Distance, GnssBaseline2D, Network, Scenario
from .precision import analyze_precision, confidence_scale

# 观测线：深色、线宽 >= 1.5，并用颜色 + 线型区分类型。
OBS_STYLE: Dict[str, Dict[str, Any]] = {
    "distance": {"color": "#1f1f1f", "lw": 1.7, "ls": "-"},
    "direction": {"color": "#d95f02", "lw": 1.7, "ls": "--"},
    "angle": {"color": "#1b7f4b", "lw": 1.6, "ls": "-."},
    "gnss": {"color": "#6a3d9a", "lw": 1.8, "ls": (0, (5, 2))},
}
OBS_LABEL = {
    "distance": "Distance",
    "direction": "Direction",
    "angle": "Angle",
    "gnss": "GNSS baseline",
}


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


def _network_extent(net: Network) -> float:
    if not net.points:
        return 1.0
    es = [p.E for p in net.points]
    ns = [p.N for p in net.points]
    return max(max(es) - min(es), max(ns) - min(ns), 1.0)


def _point_label_position(
    point: Any,
    centroid: Tuple[float, float],
    ellipse_radius: float,
    pad: float,
) -> Tuple[float, float, str, str]:
    """把点名放在误差椭圆外侧，并按径向选择对齐方式。"""
    dx = point.E - centroid[0]
    dy = point.N - centroid[1]
    norm = hypot(dx, dy)
    if norm < 1e-9:
        ux = uy = 0.7071067811865476
    else:
        ux, uy = dx / norm, dy / norm
    distance = ellipse_radius + pad
    tx = point.E + ux * distance
    ty = point.N + uy * distance
    ha = "left" if ux >= 0.0 else "right"
    va = "bottom" if uy >= 0.0 else "top"
    return tx, ty, ha, va


def _draw_angle_arc(
    ax: Any,
    station: Any,
    backsight: Any,
    foresight: Any,
    radius: float,
    color: str,
    lw: float,
    ls: Any,
) -> None:
    """在测站处画两条方向线之间的小圆弧。"""
    from matplotlib.patches import Arc

    az_b = atan2(backsight.E - station.E, backsight.N - station.N)
    az_f = atan2(foresight.E - station.E, foresight.N - station.N)
    th_b = (90.0 - degrees(az_b)) % 360.0
    th_f = (90.0 - degrees(az_f)) % 360.0
    delta = (th_f - th_b) % 360.0
    if delta > 180.0:  # 取两条方向线之间的较小夹角
        th_b, th_f = th_f, th_b
        delta = (th_f - th_b) % 360.0
    arc = Arc(
        (station.E, station.N),
        width=2.0 * radius,
        height=2.0 * radius,
        theta1=th_b,
        theta2=th_b + delta,
        color=color,
        lw=lw,
        ls=ls,
        zorder=2,
    )
    ax.add_patch(arc)


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
    legend_outside: bool = True,
) -> Tuple[Any, Any]:
    """绘制平面控制网。

    固定点用三角形、待定点用圆点；距离/方向/角度/GNSS 基线画成观测线；
    误差椭圆按 ``scale`` 放大绘制，置信水平 confidence=None 表示标准椭圆，
    0.95 表示 95% 置信椭圆。

    图例默认放在坐标轴右侧外部，避免遮挡点位和椭圆；点名标签沿从网形中心
    向外的径向放置，并位于误差椭圆之外。
    """
    import matplotlib.pyplot as plt
    from matplotlib.patches import Ellipse

    res, net = _resolve(obj, result)
    if ax is None:
        fig, ax = plt.subplots(figsize=figsize)
    else:
        fig = ax.figure

    extent = _network_extent(net)
    labeled_kinds: set[str] = set()
    obs_label_bbox = dict(boxstyle="round,pad=0.16", fc="white", ec="none", alpha=0.85)

    # 观测线
    for obs in net.observations:
        if isinstance(obs, Distance):
            p, q = net.point(obs.frm), net.point(obs.to)
            style = OBS_STYLE["distance"]
            ax.plot(
                [p.E, q.E],
                [p.N, q.N],
                color=style["color"],
                lw=style["lw"],
                ls=style["ls"],
                zorder=1,
                label=None if "distance" in labeled_kinds else OBS_LABEL["distance"],
            )
            labeled_kinds.add("distance")
            if show_observation_labels:
                ax.text(
                    (p.E + q.E) / 2.0,
                    (p.N + q.N) / 2.0,
                    obs.label,
                    fontsize=7,
                    color=style["color"],
                    ha="center",
                    va="bottom",
                    zorder=6,
                    bbox=obs_label_bbox,
                )
        elif isinstance(obs, Direction):
            p, q = net.point(obs.station), net.point(obs.target)
            style = OBS_STYLE["direction"]
            ax.annotate(
                "",
                xy=(q.E, q.N),
                xytext=(p.E, p.N),
                arrowprops=dict(
                    arrowstyle="->",
                    color=style["color"],
                    lw=style["lw"],
                    ls=style["ls"],
                    shrinkA=3.0,
                    shrinkB=3.0,
                ),
                zorder=1,
            )
            if "direction" not in labeled_kinds:
                ax.plot(
                    [],
                    [],
                    color=style["color"],
                    lw=style["lw"],
                    ls=style["ls"],
                    label=OBS_LABEL["direction"],
                )
            labeled_kinds.add("direction")
            if show_observation_labels:
                ax.text(
                    (p.E + q.E) / 2.0,
                    (p.N + q.N) / 2.0,
                    obs.label,
                    fontsize=7,
                    color=style["color"],
                    ha="center",
                    va="bottom",
                    zorder=6,
                    bbox=obs_label_bbox,
                )
        elif isinstance(obs, Angle):
            s = net.point(obs.station)
            b = net.point(obs.backsight)
            f = net.point(obs.foresight)
            style = OBS_STYLE["angle"]
            for target in (b, f):
                ax.annotate(
                    "",
                    xy=(target.E, target.N),
                    xytext=(s.E, s.N),
                    arrowprops=dict(
                        arrowstyle="->",
                        color=style["color"],
                        lw=style["lw"],
                        ls=style["ls"],
                        shrinkA=3.0,
                        shrinkB=3.0,
                    ),
                    zorder=2,
                )
            radius = max(
                0.03 * extent,
                min(
                    0.20 * min(hypot(b.E - s.E, b.N - s.N), hypot(f.E - s.E, f.N - s.N)),
                    0.30 * extent,
                ),
            )
            _draw_angle_arc(
                ax,
                s,
                b,
                f,
                radius,
                color=style["color"],
                lw=style["lw"],
                ls=style["ls"],
            )
            if "angle" not in labeled_kinds:
                ax.plot(
                    [],
                    [],
                    color=style["color"],
                    lw=style["lw"],
                    ls=style["ls"],
                    label=OBS_LABEL["angle"],
                )
            labeled_kinds.add("angle")
            if show_observation_labels:
                ax.text(
                    s.E + 0.012 * extent,
                    s.N + 0.012 * extent,
                    obs.label,
                    fontsize=7,
                    color=style["color"],
                    ha="left",
                    va="bottom",
                    zorder=6,
                    bbox=obs_label_bbox,
                )
        elif isinstance(obs, GnssBaseline2D):
            p, q = net.point(obs.frm), net.point(obs.to)
            style = OBS_STYLE["gnss"]
            ax.plot(
                [p.E, q.E],
                [p.N, q.N],
                color=style["color"],
                lw=style["lw"],
                ls=style["ls"],
                zorder=1,
                label=None if "gnss" in labeled_kinds else OBS_LABEL["gnss"],
            )
            labeled_kinds.add("gnss")
            if show_observation_labels:
                ax.text(
                    (p.E + q.E) / 2.0,
                    (p.N + q.N) / 2.0,
                    obs.label,
                    fontsize=7,
                    color=style["color"],
                    ha="center",
                    va="bottom",
                    zorder=6,
                    bbox=obs_label_bbox,
                )

    # 点与误差椭圆
    precision = analyze_precision(res)
    factor = confidence_scale(confidence)
    labeled_fixed = False
    labeled_unknown = False
    cx = sum(p.E for p in net.points) / max(len(net.points), 1)
    cy = sum(p.N for p in net.points) / max(len(net.points), 1)
    label_pad = max(1.2, 0.018 * extent)
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

        ellipse_radius = 0.0
        if show_ellipses and not p.fixed and pp.ellipse.standard_major > 0.0:
            a = pp.ellipse.standard_major * factor * scale
            b = pp.ellipse.standard_minor * factor * scale
            ellipse_radius = max(a, b)
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

        if show_labels:
            tx, ty, ha, va = _point_label_position(
                p, (cx, cy), ellipse_radius, label_pad
            )
            ax.text(
                tx,
                ty,
                p.name,
                fontsize=9,
                ha=ha,
                va=va,
                zorder=7,
                bbox=dict(
                    boxstyle="round,pad=0.18", fc="white", ec="none", alpha=0.85
                ),
            )

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
        if legend_outside:
            ax.legend(
                handles,
                labels,
                loc="upper left",
                bbox_to_anchor=(1.02, 1.0),
                fontsize=8,
                borderaxespad=0.0,
                frameon=True,
            )
            fig.tight_layout()
        else:
            ax.legend(loc="best", fontsize=8)
            fig.tight_layout()
    return fig, ax


__all__ = ["plot_network"]
