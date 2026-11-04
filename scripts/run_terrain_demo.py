#!/usr/bin/env python3
"""B2 DEM 通视分析与地形渲染演示。

流程
----
1. 读取 ``data/sample/dem_sample.tif``（北京西山 Copernicus GLO-30 小样本，
   已重投影到 UTM 50N）；
2. 在 5×5 分块中取局部最高点作为候选，搜索 7 个高点的通视连通网；
3. 对全部点对做曲率/折光通视分析；
4. 只用通视的距离/角度边构建设计态平面网，求协方差与 95% 误差椭圆；
5. 输出晕渲+等高线+观测线、代表性剖面、CSV、误差椭圆图与示例工程 JSON。

运行::

    .venv/bin/python scripts/run_terrain_demo.py

依赖：``pip install -e ".[terrain]"``；DEM 小样本已提交。若缺失，先运行
``.venv/bin/python scripts/fetch_dem.py``。
"""

from __future__ import annotations

import csv
import itertools
import json
import os
from datetime import datetime, timezone
from math import atan2, degrees, floor, log10, pi
from pathlib import Path
from typing import Any, Iterable, Sequence

try:
    ROOT = Path(__file__).resolve().parents[1]
except NameError:  # pragma: no cover - notebook
    ROOT = Path.cwd()
    if ROOT.name == "notebooks":
        ROOT = ROOT.parent

os.environ.setdefault(
    "MPLCONFIGDIR", str(Path(os.environ.get("TMPDIR", "/tmp")) / "ctrlnet-mplconfig")
)
Path(os.environ["MPLCONFIGDIR"]).mkdir(parents=True, exist_ok=True)

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from matplotlib import font_manager
from matplotlib.lines import Line2D
from matplotlib.patches import Ellipse

from ctrlnet import (
    Angle,
    DEM,
    Distance,
    IntervisibilityResult,
    Network,
    Point,
    analyze_precision,
    contours,
    hillshade,
    line_of_sight_height,
    solve,
)

OUTPUTS = ROOT / "outputs"
OUTPUTS.mkdir(parents=True, exist_ok=True)
SAMPLE_DIR = ROOT / "data" / "sample"
DEM_PATH = SAMPLE_DIR / "dem_sample.tif"
PROJECT_PATH = SAMPLE_DIR / "terrain_project.json"

INSTRUMENT_HEIGHT = 1.5
TARGET_HEIGHT = 1.5
REFRACTION_K = 0.13
EARTH_RADIUS = 6_371_000.0
CLEARANCE_THRESHOLD = 0.0
CONFIDENCE = 0.95
N_POINTS = 7

# 有中文字体时用中文图题，否则退回英文，避免方框乱码。
_available_fonts = {f.name for f in font_manager.fontManager.ttflist}
_CJK_CANDIDATES = [
    "Noto Sans CJK SC",
    "Noto Sans CJK JP",
    "WenQuanYi Zen Hei",
    "Droid Sans Fallback",
]
_CJK_FONT = next((name for name in _CJK_CANDIDATES if name in _available_fonts), None)
if _CJK_FONT:
    plt.rcParams["font.family"] = "sans-serif"
    plt.rcParams["font.sans-serif"] = [_CJK_FONT, "DejaVu Sans"]
plt.rcParams["axes.unicode_minus"] = False

COLOR_VISIBLE = "#1a9850"
COLOR_BLOCKED = "#d73027"
COLOR_MARGINAL = "#f39c12"
COLOR_POINT = "#08306b"
COLOR_ELLIPSE = "#6a3d9a"


def T(zh: str, en: str) -> str:
    return zh if _CJK_FONT else en


# ---------------------------------------------------------------------------
# 1. 选点与通视分析
# ---------------------------------------------------------------------------
def block_maxima(dem: DEM, rows: int = 5, cols: int = 5, margin: float = 0.10) -> list[dict]:
    """在每个分块内取有效最高点，作为“高处”控制点候选。"""
    height, width = dem.shape
    margin_r = int(height * margin)
    margin_c = int(width * margin)
    row_edges = np.linspace(margin_r, height - margin_r, rows + 1, dtype=int)
    col_edges = np.linspace(margin_c, width - margin_c, cols + 1, dtype=int)

    candidates: list[dict] = []
    for ri, (r0, r1) in enumerate(zip(row_edges[:-1], row_edges[1:])):
        for ci, (c0, c1) in enumerate(zip(col_edges[:-1], col_edges[1:])):
            block = dem.array[r0:r1, c0:c1]
            valid = np.isfinite(block) & (block > -1000.0)
            if not valid.any():
                continue
            rr, cc = np.unravel_index(np.argmax(np.where(valid, block, -1e9)), block.shape)
            row, col = int(r0 + rr), int(c0 + cc)
            E, N = dem.transform.xy(col + 0.5, row + 0.5)
            candidates.append(
                {
                    "block": f"R{ri}C{ci}",
                    "row": row,
                    "col": col,
                    "E": float(E),
                    "N": float(N),
                    "elevation": float(dem.elevation(E, N)),
                }
            )
    return candidates


def _visibility_matrix(
    dem: DEM,
    candidates: Sequence[dict],
) -> tuple[np.ndarray, dict[tuple[int, int], IntervisibilityResult]]:
    n = len(candidates)
    visible = np.zeros((n, n), dtype=bool)
    results: dict[tuple[int, int], IntervisibilityResult] = {}
    for i, j in itertools.combinations(range(n), 2):
        a, b = candidates[i], candidates[j]
        result = dem.intervisibility(
            (a["E"], a["N"]),
            (b["E"], b["N"]),
            inst_h=INSTRUMENT_HEIGHT,
            target_h=TARGET_HEIGHT,
            k=REFRACTION_K,
            R=EARTH_RADIUS,
            clearance=CLEARANCE_THRESHOLD,
        )
        results[(i, j)] = result
        visible[i, j] = visible[j, i] = result.visible
    return visible, results


def select_high_points(dem: DEM, n_points: int = 7) -> list[dict]:
    """搜索一处空间展开、通视连通且尽量多边的 7 点高地位网。"""
    raw = sorted(block_maxima(dem), key=lambda c: -c["elevation"])
    candidates: list[dict] = []
    for item in raw:
        if all(
            np.hypot(item["E"] - other["E"], item["N"] - other["N"]) > 800.0
            for other in candidates
        ):
            candidates.append(item)
    if len(candidates) < n_points:
        n_points = len(candidates)
    candidates = candidates[:12]
    visible, _ = _visibility_matrix(dem, candidates)

    left, bottom, right, top = dem.bounds
    span_e_min = 0.55 * (right - left)
    span_n_min = 0.45 * (top - bottom)

    best: tuple[tuple[float, float, float], tuple[int, ...]] | None = None
    for size in (n_points,):
        for combo in itertools.combinations(range(len(candidates)), size):
            sub = visible[np.ix_(combo, combo)]
            degrees = sub.sum(axis=1)
            if degrees.min() < 2:
                continue
            # 连通性检查
            seen = {0}
            stack = [0]
            while stack:
                u = stack.pop()
                for v in range(size):
                    if sub[u, v] and v not in seen:
                        seen.add(v)
                        stack.append(v)
            if len(seen) < size:
                continue
            E = [candidates[i]["E"] for i in combo]
            N = [candidates[i]["N"] for i in combo]
            span_e, span_n = max(E) - min(E), max(N) - min(N)
            if span_e < span_e_min or span_n < span_n_min:
                continue
            score = (
                float(sub.sum() // 2),
                float(span_e + span_n),
                sum(candidates[i]["elevation"] for i in combo),
            )
            if best is None or score > best[0]:
                best = (score, combo)

    if best is None:
        # 退化数据（例如全为平地或小 DEM）时退回到最高的 n_points 个候选。
        selected = candidates[:n_points]
    else:
        selected = [dict(candidates[i]) for i in best[1]]

    selected.sort(key=lambda c: (-c["elevation"], c["E"], c["N"]))
    for index, item in enumerate(selected, start=1):
        item["name"] = f"P{index}"
        item["fixed"] = index <= 2
    return selected


def all_pair_visibility(
    dem: DEM, points: Sequence[dict]
) -> dict[tuple[int, int], IntervisibilityResult]:
    results: dict[tuple[int, int], IntervisibilityResult] = {}
    for i, j in itertools.combinations(range(len(points)), 2):
        a, b = points[i], points[j]
        results[(i, j)] = dem.intervisibility(
            (a["E"], a["N"]),
            (b["E"], b["N"]),
            inst_h=INSTRUMENT_HEIGHT,
            target_h=TARGET_HEIGHT,
            k=REFRACTION_K,
            R=EARTH_RADIUS,
            clearance=CLEARANCE_THRESHOLD,
        )
    return results


# ---------------------------------------------------------------------------
# 2. 平面网（只使用通视的距离/角度边）
# ---------------------------------------------------------------------------
def _azimuth(point_from: dict, point_to: dict) -> float:
    return atan2(point_to["E"] - point_from["E"], point_to["N"] - point_from["N"])


def angle_deg(points: Sequence[dict], backsight: int, station: int, foresight: int) -> float:
    """与 ``Angle`` 模型一致：前视方位角 − 后视方位角，归化到 (−180, 180]。"""
    beta = _azimuth(points[station], points[foresight]) - _azimuth(
        points[station], points[backsight]
    )
    beta = (beta + pi) % (2.0 * pi) - pi
    return degrees(beta)


def build_network(
    points: Sequence[dict],
    visibility: dict[tuple[int, int], IntervisibilityResult],
) -> tuple[Network, Any, Any, list[Distance], list[Angle]]:
    nodes = [
        Point(p["name"], p["E"], p["N"], fixed=bool(p["fixed"])) for p in points
    ]
    distances: list[Distance] = []
    angles: list[Angle] = []
    visible_pairs = [
        (i, j) for (i, j), result in visibility.items() if result.visible
    ]
    for i, j in visible_pairs:
        distances.append(Distance(points[i]["name"], points[j]["name"]))

    neighbors: dict[int, list[int]] = {i: [] for i in range(len(points))}
    for i, j in visible_pairs:
        neighbors[i].append(j)
        neighbors[j].append(i)
    for station in range(len(points)):
        # 按方位角排序后对所有可见方向两两组角，保证只用通视的边。
        ordered = sorted(neighbors[station], key=lambda target: _azimuth(points[station], points[target]))
        for u, v in itertools.combinations(ordered, 2):
            angles.append(
                Angle(
                    points[u]["name"],
                    points[station]["name"],
                    points[v]["name"],
                    sigma_arcsec=1.0,
                )
            )

    network = Network(nodes, list(distances) + list(angles), name="DEM 通视边角网")
    result = solve(network)
    precision = analyze_precision(result, confidence=CONFIDENCE)
    return network, result, precision, distances, angles


# ---------------------------------------------------------------------------
# 3. 图件
# ---------------------------------------------------------------------------
def _plot_hillshade(ax: Any, dem: DEM, alpha: float = 1.0) -> None:
    left, bottom, right, top = dem.bounds
    shade = hillshade(dem, azimuth=315.0, altitude=45.0)
    ax.imshow(
        shade,
        extent=(left, right, bottom, top),
        origin="upper",
        cmap="gray",
        vmin=0.0,
        vmax=1.0,
        interpolation="bilinear",
        alpha=alpha,
        zorder=0,
    )


def _contour_levels(dem: DEM, interval: float = 50.0) -> np.ndarray:
    valid = dem.array[dem.valid_mask]
    low = floor(float(valid.min()) / interval) * interval
    high = float(valid.max())
    return np.arange(low, high + interval, interval)


def _label_points(ax: Any, points: Sequence[dict], *, with_mp: dict[str, float] | None = None) -> None:
    for p in points:
        text = p["name"]
        if with_mp is not None:
            text += f"\n±{with_mp[p['name']]:.1f} mm"
        ax.annotate(
            text,
            (p["E"], p["N"]),
            xytext=(7, 7),
            textcoords="offset points",
            fontsize=8.5,
            color="black",
            bbox=dict(boxstyle="round,pad=0.18", fc="white", ec="none", alpha=0.82),
            zorder=8,
        )


def plot_overview(
    dem: DEM,
    points: Sequence[dict],
    visibility: dict[tuple[int, int], IntervisibilityResult],
    output: Path,
) -> None:
    fig, ax = plt.subplots(figsize=(10.5, 10.0))
    _plot_hillshade(ax, dem)
    contours(
        dem,
        ax=ax,
        levels=_contour_levels(dem),
        colors="#3a3a3a",
        linewidths=0.35,
        alpha=0.52,
        zorder=1,
    )

    n_visible = 0
    for (i, j), result in visibility.items():
        a, b = points[i], points[j]
        if result.visible:
            n_visible += 1
            color, style, width = COLOR_VISIBLE, "-", 1.35
        elif result.status == "marginal":
            color, style, width = COLOR_MARGINAL, "-.", 1.25
        else:
            color, style, width = COLOR_BLOCKED, "--", 1.15
        ax.plot(
            [a["E"], b["E"]],
            [a["N"], b["N"]],
            color=color,
            ls=style,
            lw=width,
            alpha=0.9,
            zorder=3,
        )

    for p in points:
        marker = "^" if p["fixed"] else "o"
        ax.scatter(
            p["E"],
            p["N"],
            marker=marker,
            s=110,
            c=COLOR_POINT,
            edgecolors="white",
            linewidths=1.1,
            zorder=6,
        )
    _label_points(ax, points)

    handles = [
        Line2D([0], [0], color=COLOR_VISIBLE, lw=2.0, label=T("通视", "Visible")),
        Line2D([0], [0], color=COLOR_BLOCKED, lw=2.0, ls="--", label=T("遮挡", "Blocked")),
        Line2D([0], [0], marker="^", color="none", markerfacecolor=COLOR_POINT,
               markeredgecolor="white", markersize=10, label=T("固定点", "Fixed point")),
        Line2D([0], [0], marker="o", color="none", markerfacecolor=COLOR_POINT,
               markeredgecolor="white", markersize=8, label=T("待定点", "Unknown point")),
    ]
    ax.legend(handles=handles, loc="upper left", framealpha=0.9)
    ax.set_aspect("equal", adjustable="box")
    ax.set_xlabel(T("东坐标 E / m（UTM 50N）", "Easting E / m (UTM 50N)"))
    ax.set_ylabel(T("北坐标 N / m（UTM 50N）", "Northing N / m (UTM 50N)"))
    ax.set_title(
        T(
            f"北京西山 DEM 通视分析：{len(points)} 点 / "
            f"{len(visibility)} 对（通视 {n_visible}）",
            f"Beijing Xishan DEM intervisibility: {len(points)} points / "
            f"{len(visibility)} pairs ({n_visible} visible)",
        )
    )
    ax.text(
        0.01,
        0.01,
        T(
            "Copernicus GLO-30 DSM · 30 m · UTM 50N\n"
            f"k={REFRACTION_K}，R={EARTH_RADIUS:.0f} m，i=t={INSTRUMENT_HEIGHT:.1f} m",
            "Copernicus GLO-30 DSM · 30 m · UTM 50N\n"
            f"k={REFRACTION_K}, R={EARTH_RADIUS:.0f} m, i=t={INSTRUMENT_HEIGHT:.1f} m",
        ),
        transform=ax.transAxes,
        fontsize=7.5,
        va="bottom",
        ha="left",
        bbox=dict(boxstyle="round,pad=0.28", fc="white", ec="#cccccc", alpha=0.88),
    )
    fig.tight_layout()
    fig.savefig(output, dpi=200, bbox_inches="tight")
    plt.close(fig)


def choose_representative_profiles(
    points: Sequence[dict],
    visibility: dict[tuple[int, int], IntervisibilityResult],
    limit: int = 6,
) -> list[tuple[tuple[int, int], IntervisibilityResult]]:
    items = list(visibility.items())
    visible = sorted([item for item in items if item[1].visible], key=lambda it: it[1].distance)
    blocked = sorted([item for item in items if not item[1].visible], key=lambda item: item[1].distance)
    chosen: list[tuple[tuple[int, int], IntervisibilityResult]] = []

    def add(item: tuple[tuple[int, int], IntervisibilityResult] | None) -> None:
        if item is None:
            return
        if item[0] not in {key for key, _ in chosen}:
            chosen.append(item)

    if visible:
        add(visible[0])
        add(visible[-1])
    if blocked:
        add(blocked[0])
        add(blocked[-1])
    add(min(items, key=lambda it: it[1].min_clearance))
    add(max(items, key=lambda it: it[1].distance))
    for item in sorted(items, key=lambda it: it[1].distance):
        if len(chosen) >= limit:
            break
        add(item)
    return chosen[:limit]


def plot_profiles(
    points: Sequence[dict],
    visibility: dict[tuple[int, int], IntervisibilityResult],
    output: Path,
) -> None:
    chosen = choose_representative_profiles(points, visibility)
    fig, axes = plt.subplots(2, 3, figsize=(14.0, 8.2), squeeze=False)
    for ax, ((i, j), result) in zip(axes.ravel(), chosen):
        prof = result.profile
        d = prof.distance
        terrain = prof.elevation
        color = COLOR_VISIBLE if result.visible else (
            COLOR_MARGINAL if result.status == "marginal" else COLOR_BLOCKED
        )

        base = float(np.nanmin(terrain)) - 5.0
        ax.fill_between(
            d / 1000.0, base, terrain, color="#d8c7a5", alpha=0.85, zorder=1
        )
        ax.plot(
            d / 1000.0,
            terrain,
            color="#7f5a24",
            lw=1.1,
            zorder=2,
            label=T("地形", "Terrain"),
        )

        h1, h2 = result.h1, result.h2
        chord = h1 + (h2 - h1) * d / result.distance
        los = line_of_sight_height(
            d, result.distance, h1, h2, k=REFRACTION_K, R=EARTH_RADIUS
        )
        ax.plot(d / 1000.0, chord, color="#777777", lw=0.9, ls=":", zorder=3,
                label=T("两端连线", "Chord"))
        ax.plot(d / 1000.0, los, color=color, lw=1.8, zorder=4,
                label=T("曲率折光视线", "Curved LOS"))

        if result.obstruction_position is not None:
            ax.scatter(
                [result.min_distance / 1000.0],
                [result.min_terrain_elevation],
                marker="x",
                s=70,
                color=COLOR_BLOCKED,
                linewidths=2.0,
                zorder=6,
                label=T("遮挡点", "Obstruction"),
            )
            ax.annotate(
                f"{result.min_distance/1000.0:.2f} km\n{result.min_clearance:+.2f} m",
                xy=(result.min_distance / 1000.0, result.min_terrain_elevation),
                xytext=(8, 8),
                textcoords="offset points",
                fontsize=7.5,
                color=COLOR_BLOCKED,
                bbox=dict(boxstyle="round,pad=0.18", fc="white", ec=COLOR_BLOCKED, alpha=0.85),
            )

        a, b = points[i], points[j]
        status_cn = {
            "visible": "通视",
            "blocked": "遮挡",
            "marginal": "临界",
            "unknown": "不确定",
        }.get(result.status, result.status)
        ax.set_title(
            T(
                f"{a['name']}–{b['name']}  {result.distance/1000:.2f} km  {status_cn}",
                f"{a['name']}–{b['name']}  {result.distance/1000:.2f} km  {result.status}",
            ),
            fontsize=9.5,
        )
        ax.set_xlabel(T("距离 / km", "Distance / km"), fontsize=8)
        ax.set_ylabel(T("高程 / m", "Elevation / m"), fontsize=8)
        ax.grid(alpha=0.18, lw=0.5)
        ax.tick_params(labelsize=7.5)
        ymax = max(float(np.nanmax(terrain)), float(np.nanmax(los))) + 8.0
        ymin = min(float(np.nanmin(los)), float(np.nanmin(terrain))) - 8.0
        ax.set_ylim(ymin, ymax)
        ax.legend(fontsize=6.5, loc="best", framealpha=0.8)

    for ax in axes.ravel()[len(chosen) :]:
        ax.axis("off")
    fig.suptitle(
        T(
            "代表性 DEM 剖面：地形、曲率/折光视线与遮挡点",
            "Representative DEM profiles: terrain, curved LOS, obstructions",
        ),
        fontsize=12,
    )
    fig.tight_layout(rect=(0, 0, 1, 0.96))
    fig.savefig(output, dpi=190, bbox_inches="tight")
    plt.close(fig)


def _nice_scale(value: float) -> float:
    if not np.isfinite(value) or value <= 0.0:
        return 1.0
    exponent = floor(log10(value))
    base = 10.0**exponent
    fraction = value / base
    for candidate in (1.0, 2.0, 2.5, 5.0, 10.0):
        if fraction <= candidate:
            return candidate * base
    return 10.0 * base


def plot_network_ellipses(
    dem: DEM,
    points: Sequence[dict],
    visibility: dict[tuple[int, int], IntervisibilityResult],
    precision: Any,
    result: Any,
    output: Path,
) -> float:
    fig, ax = plt.subplots(figsize=(10.5, 10.0))
    _plot_hillshade(ax, dem, alpha=0.92)
    contours(
        dem,
        ax=ax,
        levels=_contour_levels(dem),
        colors="#4a4a4a",
        linewidths=0.3,
        alpha=0.42,
        zorder=1,
    )

    for (i, j), visibility_result in visibility.items():
        if not visibility_result.visible:
            continue
        a, b = points[i], points[j]
        ax.plot(
            [a["E"], b["E"]],
            [a["N"], b["N"]],
            color=COLOR_VISIBLE,
            lw=1.3,
            alpha=0.85,
            zorder=2,
        )

    unknown = [p for p in points if not p["fixed"]]
    max_major = max(
        (precision.point(p["name"]).ellipse.a for p in unknown), default=0.0
    )
    left, bottom, right, top = dem.bounds
    target_size = 0.045 * max(right - left, top - bottom)
    scale = _nice_scale(target_size / max_major) if max_major > 0.0 else 1.0

    mp_by_name: dict[str, float] = {}
    for p in points:
        pp = precision.point(p["name"])
        mp_by_name[p["name"]] = pp.mp_mm
        if not p["fixed"] and pp.ellipse.a > 0.0:
            ell = pp.ellipse
            patch = Ellipse(
                (p["E"], p["N"]),
                width=2.0 * ell.a * scale,
                height=2.0 * ell.b * scale,
                angle=90.0 - ell.azimuth_deg,
                facecolor="none",
                edgecolor=COLOR_ELLIPSE,
                lw=1.5,
                alpha=0.95,
                zorder=5,
            )
            ax.add_patch(patch)
        marker = "^" if p["fixed"] else "o"
        ax.scatter(
            p["E"],
            p["N"],
            marker=marker,
            s=100,
            c=COLOR_POINT,
            edgecolors="white",
            linewidths=1.0,
            zorder=6,
        )
    _label_points(ax, points, with_mp=mp_by_name)

    handles = [
        Line2D([0], [0], color=COLOR_VISIBLE, lw=1.6, label=T("通视距离边", "Visible distance")),
        Line2D([0], [0], color=COLOR_ELLIPSE, lw=1.5, label=T(f"95% 误差椭圆 ×{scale:g}", f"95% ellipse ×{scale:g}")),
        Line2D([0], [0], marker="^", color="none", markerfacecolor=COLOR_POINT,
               markeredgecolor="white", markersize=10, label=T("固定点", "Fixed point")),
        Line2D([0], [0], marker="o", color="none", markerfacecolor=COLOR_POINT,
               markeredgecolor="white", markersize=8, label=T("待定点", "Unknown point")),
    ]
    ax.legend(handles=handles, loc="upper left", framealpha=0.9)
    ax.set_aspect("equal", adjustable="box")
    ax.set_xlabel(T("东坐标 E / m（UTM 50N）", "Easting E / m (UTM 50N)"))
    ax.set_ylabel(T("北坐标 N / m（UTM 50N）", "Northing N / m (UTM 50N)"))
    ax.set_title(
        T(
            "通视边角网的 95% 误差椭圆（只使用通视的距离/角度）",
            "95% error ellipses of the visible distance/angle network",
        )
    )
    unknown_mp = [precision.point(p["name"]).mp_mm for p in unknown]
    ax.text(
        0.01,
        0.01,
        T(
            f"未知点 {len(unknown)}，观测 {result.n_observations}，"
            f"rank={result.rank}，冗余={result.redundancy}\n"
            f"最大 mp={max(unknown_mp) if unknown_mp else 0.0:.2f} mm；"
            f"椭圆放大 {scale:g}×",
            f"Unknowns {len(unknown)}, observations {result.n_observations}, "
            f"rank={result.rank}, redundancy={result.redundancy}\n"
            f"max mp={max(unknown_mp) if unknown_mp else 0.0:.2f} mm; "
            f"ellipses ×{scale:g}",
        ),
        transform=ax.transAxes,
        fontsize=7.5,
        va="bottom",
        ha="left",
        bbox=dict(boxstyle="round,pad=0.28", fc="white", ec="#cccccc", alpha=0.9),
    )
    fig.tight_layout()
    fig.savefig(output, dpi=200, bbox_inches="tight")
    plt.close(fig)
    return scale


# ---------------------------------------------------------------------------
# 4. CSV / 工程 JSON
# ---------------------------------------------------------------------------
def write_csv(
    points: Sequence[dict],
    visibility: dict[tuple[int, int], IntervisibilityResult],
    output: Path,
) -> None:
    fieldnames = [
        "from",
        "to",
        "status",
        "visible",
        "distance_m",
        "min_clearance_m",
        "min_distance_m",
        "obstruction_e_m",
        "obstruction_n_m",
        "obstruction_elevation_m",
        "ground_from_m",
        "ground_to_m",
        "instrument_height_m",
        "target_height_m",
        "k",
        "R_m",
        "clearance_threshold_m",
        "nodata_count",
        "samples",
    ]
    with output.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        for (i, j), result in sorted(visibility.items()):
            a, b = points[i], points[j]
            pos = result.obstruction_position
            writer.writerow(
                {
                    "from": a["name"],
                    "to": b["name"],
                    "status": result.status,
                    "visible": int(result.visible),
                    "distance_m": f"{result.distance:.3f}",
                    "min_clearance_m": f"{result.min_clearance:.4f}",
                    "min_distance_m": f"{result.min_distance:.3f}",
                    "obstruction_e_m": "" if pos is None else f"{pos[0]:.3f}",
                    "obstruction_n_m": "" if pos is None else f"{pos[1]:.3f}",
                    "obstruction_elevation_m": ""
                    if pos is None or result.min_terrain_elevation is None
                    else f"{result.min_terrain_elevation:.3f}",
                    "ground_from_m": f"{result.ground_start:.3f}",
                    "ground_to_m": f"{result.ground_end:.3f}",
                    "instrument_height_m": f"{result.instrument_height:.3f}",
                    "target_height_m": f"{result.target_height:.3f}",
                    "k": f"{result.k:.4f}",
                    "R_m": f"{result.radius:.1f}",
                    "clearance_threshold_m": f"{result.clearance_threshold:.3f}",
                    "nodata_count": result.nodata_count,
                    "samples": result.profile.sample_count,
                }
            )


def utm_to_lonlat(dem: DEM, points: Sequence[dict]) -> list[tuple[float, float]]:
    try:
        from rasterio.warp import transform as warp_transform
    except ImportError as exc:  # pragma: no cover
        raise ImportError("需要 rasterio 做 UTM→WGS84 转换") from exc
    if not dem.crs:
        raise ValueError("DEM 缺少 CRS，无法转换为经纬度")
    east = [p["E"] for p in points]
    north = [p["N"] for p in points]
    lons, lats = warp_transform(dem.crs, "EPSG:4326", east, north)
    return list(zip(lons, lats))


def write_project_json(
    dem: DEM,
    points: Sequence[dict],
    visibility: dict[tuple[int, int], IntervisibilityResult],
    distances: Sequence[Distance],
    angles: Sequence[Angle],
    precision: Any,
    result: Any,
    ellipse_scale: float,
    output: Path,
) -> None:
    lonlat = utm_to_lonlat(dem, points)
    dem_meta: dict[str, Any] = {}
    sidecar = DEM_PATH.with_suffix(".json")
    if sidecar.exists():
        dem_meta = json.loads(sidecar.read_text(encoding="utf-8"))

    point_payload = []
    for index, (p, (lon, lat)) in enumerate(zip(points, lonlat)):
        pp = precision.point(p["name"])
        ell = pp.ellipse
        point_payload.append(
            {
                "name": p["name"],
                "lon": float(lon),
                "lat": float(lat),
                "E": float(p["E"]),
                "N": float(p["N"]),
                "elevation_m": float(p["elevation"]),
                "crs": dem.crs,
                "fixed": bool(p["fixed"]),
                "sigma_E_mm": float(pp.sigma_E_mm),
                "sigma_N_mm": float(pp.sigma_N_mm),
                "mp_mm": float(pp.mp_mm),
                "ellipse_95": {
                    "a_m": float(ell.a),
                    "b_m": float(ell.b),
                    "azimuth_deg": float(ell.azimuth_deg),
                    "confidence": CONFIDENCE,
                },
            }
        )

    distance_payload = []
    for obs in distances:
        a = next(p for p in points if p["name"] == obs.frm)
        b = next(p for p in points if p["name"] == obs.to)
        distance_payload.append(
            {
                "from": obs.frm,
                "to": obs.to,
                "value_m": float(np.hypot(b["E"] - a["E"], b["N"] - a["N"])),
                "sigma_a_m": float(obs.a),
                "sigma_b_ppm": float(obs.b_ppm),
            }
        )

    angle_payload = []
    for obs in angles:
        backsight = next(p for p in points if p["name"] == obs.backsight)
        station = next(p for p in points if p["name"] == obs.station)
        foresight = next(p for p in points if p["name"] == obs.foresight)
        angle_payload.append(
            {
                "backsight": obs.backsight,
                "station": obs.station,
                "foresight": obs.foresight,
                "value_deg": angle_deg(
                    points,
                    points.index(backsight),
                    points.index(station),
                    points.index(foresight),
                ),
                "sigma_arcsec": float(obs.sigma_arcsec),
            }
        )

    visibility_payload = []
    for (i, j), vis in sorted(visibility.items()):
        a, b = points[i], points[j]
        pos = vis.obstruction_position
        visibility_payload.append(
            {
                "from": a["name"],
                "to": b["name"],
                "distance_m": float(vis.distance),
                "status": vis.status,
                "visible": bool(vis.visible),
                "min_clearance_m": float(vis.min_clearance),
                "min_distance_m": float(vis.min_distance),
                "obstruction": None
                if pos is None
                else {
                    "E": float(pos[0]),
                    "N": float(pos[1]),
                    "elevation_m": float(vis.min_terrain_elevation),
                },
                "k": float(vis.k),
                "R_m": float(vis.radius),
                "clearance_threshold_m": float(vis.clearance_threshold),
                "samples": int(vis.profile.sample_count),
                "nodata_count": int(vis.nodata_count),
            }
        )

    payload = {
        "schema": "ctrlnet.terrain_project/1",
        "generated_by": "scripts/run_terrain_demo.py",
        "generated_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "description": "DEM intervisibility + visible-edge plane network demo",
        "dem": {
            "path": str(DEM_PATH.relative_to(ROOT)),
            "crs": dem.crs,
            "shape": [dem.height, dem.width],
            "resolution_m": [dem.xres, dem.yres],
            "bounds_native": list(dem.bounds),
            "source": dem_meta.get("source", "Copernicus GLO-30 DSM"),
            "vertical_datum": dem_meta.get(
                "vertical_datum", "EGM2008 orthometric height"
            ),
            "surface_type": dem_meta.get("surface_type", "DSM"),
            "source_url": dem_meta.get("source_url"),
            "md5_sha256": dem_meta.get("sha256"),
        },
        "analysis": {
            "instrument_height_m": INSTRUMENT_HEIGHT,
            "target_height_m": TARGET_HEIGHT,
            "k": REFRACTION_K,
            "R_m": EARTH_RADIUS,
            "clearance_threshold_m": CLEARANCE_THRESHOLD,
            "confidence": CONFIDENCE,
            "formula": "h_LOS(x)=h1+(h2-h1)*x/d-(1-k)*x*(d-x)/(2R)",
            "ellipse_scale": float(ellipse_scale),
        },
        "points": point_payload,
        "observations": {
            "distances": distance_payload,
            "angles": angle_payload,
        },
        "visibility": visibility_payload,
        "network": {
            "name": result.network.name,
            "n_points": len(points),
            "n_fixed": sum(1 for p in points if p["fixed"]),
            "n_observations": int(result.n_observations),
            "n_distances": len(distances),
            "n_angles": len(angles),
            "n_visible_pairs": sum(1 for vis in visibility.values() if vis.visible),
            "n_params": int(result.n_params),
            "rank": int(result.rank),
            "redundancy": int(result.redundancy),
            "condition_number": float(result.condition_number),
            "max_mp_mm": float(
                max(
                    (precision.point(p["name"]).mp_mm for p in points if not p["fixed"]),
                    default=0.0,
                )
            ),
        },
    }
    output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


# ---------------------------------------------------------------------------
# 5. main
# ---------------------------------------------------------------------------
def main() -> int:
    if not DEM_PATH.exists():
        print(f"[error] 缺少 {DEM_PATH}")
        print("请先运行：.venv/bin/python scripts/fetch_dem.py")
        return 2

    dem = DEM.from_geotiff(DEM_PATH)
    left, bottom, right, top = dem.bounds
    print(
        f"[DEM] {DEM_PATH.relative_to(ROOT)}  {dem.width}×{dem.height} @ "
        f"{dem.xres:.1f} m  bounds={left:.0f},{bottom:.0f},{right:.0f},{top:.0f}  "
        f"crs={dem.crs}"
    )
    print(
        f"[DEM] 有效像素 {dem.valid_fraction*100:.2f}%，"
        f"高程 {np.nanmin(dem.array[dem.valid_mask]):.1f}–"
        f"{np.nanmax(dem.array[dem.valid_mask]):.1f} m"
    )

    points = select_high_points(dem, n_points=N_POINTS)
    print(f"[选点] {len(points)} 个高地控制点：")
    for p in points:
        print(
            f"  {p['name']}{'*' if p['fixed'] else ' '} "
            f"H={p['elevation']:.1f} m  E={p['E']:.1f} N={p['N']:.1f}"
        )

    visibility = all_pair_visibility(dem, points)
    n_visible = sum(1 for result in visibility.values() if result.visible)
    print(
        f"[通视] {len(visibility)} 对：通视 {n_visible}，"
        f"遮挡 {len(visibility)-n_visible}"
    )
    for (i, j), result in sorted(visibility.items()):
        print(
            f"  {points[i]['name']}-{points[j]['name']}  "
            f"{result.distance/1000:5.2f} km  {result.status:8s} "
            f"min_clearance={result.min_clearance:+8.2f} m"
        )

    network, result, precision, distances, angles = build_network(points, visibility)
    print(
        f"[平差] 观测 {result.n_observations}（距离 {len(distances)} + "
        f"角度 {len(angles)}），参数 {result.n_params}，rank={result.rank}，"
        f"冗余 {result.redundancy}，条件数 {result.condition_number:.2f}"
    )
    for p in points:
        pp = precision.point(p["name"])
        print(
            f"  {p['name']}: σE={pp.sigma_E_mm:6.2f} mm σN={pp.sigma_N_mm:6.2f} mm "
            f"mp={pp.mp_mm:6.2f} mm  95%椭圆 a={pp.ellipse.a*1000:7.2f} mm "
            f"b={pp.ellipse.b*1000:7.2f} mm az={pp.ellipse.azimuth_deg:6.1f}°"
        )

    overview_path = OUTPUTS / "dem_hillshade_contours.png"
    profiles_path = OUTPUTS / "intervisibility_profiles.png"
    csv_path = OUTPUTS / "intervisibility.csv"
    ellipse_path = OUTPUTS / "dem_network_ellipses.png"

    plot_overview(dem, points, visibility, overview_path)
    plot_profiles(points, visibility, profiles_path)
    write_csv(points, visibility, csv_path)
    ellipse_scale = plot_network_ellipses(
        dem, points, visibility, precision, result, ellipse_path
    )
    write_project_json(
        dem,
        points,
        visibility,
        distances,
        angles,
        precision,
        result,
        ellipse_scale,
        PROJECT_PATH,
    )

    print("[输出]")
    for path in (overview_path, profiles_path, csv_path, ellipse_path, PROJECT_PATH):
        size = path.stat().st_size
        print(f"  {path.relative_to(ROOT)}  ({size/1024:.1f} KiB)")
    print(f"[椭圆] 95% 误差椭圆放大 {ellipse_scale:g}×")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
