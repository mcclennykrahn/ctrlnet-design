#!/usr/bin/env python3
"""C3 GNSS 三维基线网 + 局部 ENU 联合平差 + 高程异常近似演示。

流程
----
1. 读取 ``data/sample/terrain_project.json`` 的 7 个 DEM 控制点（北京西山，
   UTM 50N + EGM2008 正常高）；
2. 用公开 EGM96 15′ 裁剪格网（``data/sample/egm96_beijing.tif``）把正常高
   转成大地高，并叠加毫米级 GNSS 高程噪声；
3. 构造 13 条三维基线（ENU 框架、完整 3×3 协方差），P1/P2 固定；
4. 加入 6 条地面距离、4 个水平角、9 条水准高差，在高程异常平面模型改正后
   做局部 ENU 联合平差；
5. 输出 ``outputs/gnss_network.png``、``outputs/geoid_fit.png``、
   ``outputs/gnss_results.md``、``outputs/gnss_results.csv``。

运行::

    .venv/bin/python scripts/run_gnss_demo.py

本演示是**设计态精度估算**：基线/距离/角度/水准均按先验随机模型计算，
不是实测数据的后验平差。高程异常平面模型是局部近似，不可外推。
"""

from __future__ import annotations

import csv
import json
import os
from math import cos, hypot, sin, sqrt
from pathlib import Path
from typing import Any, Dict, List, Sequence

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
from matplotlib.patches import Ellipse, Patch

from ctrlnet import (
    Angle,
    Distance,
    EGMGrid,
    GeoidControlPoint,
    GnssBaseline,
    GnssNetwork,
    GnssPoint,
    HeightDifference,
    K95,
    ecef_to_enu,
    ecef_to_enu_matrix,
    fit_height_anomaly,
    solve_gnss,
)

OUTPUTS = ROOT / "outputs"
OUTPUTS.mkdir(parents=True, exist_ok=True)
SAMPLE_DIR = ROOT / "data" / "sample"
PROJECT_PATH = SAMPLE_DIR / "terrain_project.json"
EGM_PATH = SAMPLE_DIR / "egm96_beijing.tif"

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

COLOR_GNSS = "#1f77b4"
COLOR_DIST = "#2ca02c"
COLOR_ANGLE = "#ff7f0e"
COLOR_LEVEL = "#9467bd"
COLOR_FIXED = "#d62728"
COLOR_ELLIPSE = "#6a3d9a"
ELLIPSE_SCALE = 10000.0


def T(zh: str, en: str) -> str:
    return zh if _CJK_FONT else en


# ---------------------------------------------------------------------------
# 1. 读取工程点，生成局部 ENU 与大地高
# ---------------------------------------------------------------------------
def synthetic_zeta(E: float, N: float, E0: float, N0: float) -> float:
    """EGM 格网缺失时的平滑替代场（米）。"""
    return (
        -10.0
        + 2.0e-6 * (E - E0)
        - 1.0e-6 * (N - N0)
        + 0.025 * sin((E - E0) / 2800.0) * cos((N - N0) / 3200.0)
    )


def load_demo() -> Dict[str, Any]:
    project = json.loads(PROJECT_PATH.read_text(encoding="utf-8"))
    raw_points = project["points"]
    egm = EGMGrid.from_geotiff(EGM_PATH) if EGM_PATH.exists() else None
    origin_raw = next(p for p in raw_points if p["name"] == "P1")
    origin = (origin_raw["lat"], origin_raw["lon"], 0.0)
    rng = np.random.default_rng(20261104)

    gnss_points: List[GnssPoint] = []
    geoid_samples: List[GeoidControlPoint] = []
    enu_by_name: Dict[str, np.ndarray] = {}
    project_by_name: Dict[str, Dict[str, Any]] = {}
    egm_zeta: Dict[str, float] = {}

    for raw in raw_points:
        name = raw["name"]
        H = float(raw["elevation_m"])
        if egm is not None:
            zeta_ref = float(egm.undulation(raw["lon"], raw["lat"]))
        else:
            zeta_ref = synthetic_zeta(float(raw["E"]), float(raw["N"]), float(origin_raw["E"]), float(origin_raw["N"]))
        # 4 mm 大地高噪声，仅用于让拟合残差可见；正常高保持 DEM 值。
        h = H + zeta_ref + float(rng.normal(0.0, 0.004))
        point = GnssPoint(name, raw["lat"], raw["lon"], h, fixed=bool(raw.get("fixed", False)))
        gnss_points.append(point)
        enu = ecef_to_enu(point.ecef, origin[0], origin[1], origin[2])
        enu_by_name[name] = enu
        project_by_name[name] = raw
        egm_zeta[name] = zeta_ref
        geoid_samples.append(GeoidControlPoint(name, enu[0], enu[1], h, H))

    return {
        "project": project,
        "points": gnss_points,
        "point_by_name": {p.name: p for p in gnss_points},
        "project_by_name": project_by_name,
        "enu": enu_by_name,
        "geoid_samples": geoid_samples,
        "egm": egm,
        "egm_zeta": egm_zeta,
        "origin_name": origin_raw["name"],
    }


# ---------------------------------------------------------------------------
# 2. 构造基线、地面边、水准与联合网
# ---------------------------------------------------------------------------
BASELINE_PAIRS = [
    ("P1", "P2"),
    ("P1", "P3"),
    ("P1", "P5"),
    ("P1", "P7"),
    ("P2", "P3"),
    ("P2", "P4"),
    ("P2", "P5"),
    ("P2", "P7"),
    ("P3", "P4"),
    ("P3", "P6"),
    ("P4", "P5"),
    ("P5", "P6"),
    ("P6", "P7"),
]
DISTANCE_PAIRS = [("P1", "P3"), ("P2", "P4"), ("P3", "P5"), ("P5", "P7"), ("P6", "P7"), ("P2", "P5")]
ANGLE_TRIPLES = [
    ("P2", "P1", "P7"),
    ("P4", "P2", "P3"),
    ("P5", "P3", "P6"),
    ("P7", "P5", "P6"),
]
LEVELING_PAIRS = [
    ("P1", "P3"),
    ("P3", "P5"),
    ("P5", "P7"),
    ("P7", "P6"),
    ("P6", "P2"),
    ("P2", "P4"),
    ("P4", "P5"),
    ("P5", "P2"),
    ("P1", "P5"),
]


def make_baselines(points: Dict[str, GnssPoint]) -> List[GnssBaseline]:
    baselines: List[GnssBaseline] = []
    for frm, to in BASELINE_PAIRS:
        p, q = points[frm], points[to]
        delta_ecef = q.ecef - p.ecef
        # 只旋转基线向量，不能把 ΔX 当作绝对 ECEF 再减测站原点。
        delta_enu = ecef_to_enu_matrix(p.lat, p.lon) @ delta_ecef
        length = float(np.linalg.norm(delta_enu))
        sig_e = sqrt(0.002**2 + (0.5e-6 * length) ** 2)
        sig_n = sqrt(0.002**2 + (0.5e-6 * length) ** 2)
        sig_u = sqrt(0.004**2 + (1.0e-6 * length) ** 2)
        c_enu = np.diag([sig_e**2, sig_n**2, sig_u**2])
        # 轻微的 E/N 相关，体现完整 3×3 VCV 而非只取对角。
        rho = 0.10
        c_enu[0, 1] = c_enu[1, 0] = rho * sig_e * sig_n
        baselines.append(
            GnssBaseline(frm, to, delta_enu, c_enu, frame="ENU", reference=frm)
        )
    return baselines


def make_ground(project: Dict[str, Any], points: Dict[str, GnssPoint]) -> tuple[List[Distance], List[Angle], List[HeightDifference]]:
    distances = [Distance(a, b, a=0.002, b_ppm=2.0) for a, b in DISTANCE_PAIRS]
    angles = [Angle(backsight=b, station=s, foresight=f, sigma_arcsec=1.0) for b, s, f in ANGLE_TRIPLES]
    leveling: List[HeightDifference] = []
    for a, b in LEVELING_PAIRS:
        pa, pb = project["points"], None
        # 用工程 UTM 坐标计算路线长度；高差取 DEM 正常高之差。
        pa = next(p for p in project["points"] if p["name"] == a)
        pb = next(p for p in project["points"] if p["name"] == b)
        length_km = hypot(float(pa["E"]) - float(pb["E"]), float(pa["N"]) - float(pb["N"])) / 1000.0
        delta_h = float(pb["elevation_m"]) - float(pa["elevation_m"])
        leveling.append(
            HeightDifference(
                a,
                b,
                delta_h,
                length_km=max(length_km, 0.1),
                sigma_per_km_mm=1.0,
                height_type="normal",
            )
        )
    return distances, angles, leveling


# ---------------------------------------------------------------------------
# 3. 绘图
# ---------------------------------------------------------------------------
def plot_gnss_network(joint_result: Any, d: Dict[str, Any], baselines: Sequence[GnssBaseline]) -> Path:
    fig, (ax, ax_bar) = plt.subplots(
        1,
        2,
        figsize=(13.5, 6.6),
        gridspec_kw={"width_ratios": [2.4, 1.0]},
    )
    enu = d["enu"]
    fixed = [p for p in d["points"] if p.fixed]

    # 基线
    for i, baseline in enumerate(baselines):
        a, b = enu[baseline.frm], enu[baseline.to]
        ax.plot(
            [a[0], b[0]],
            [a[1], b[1]],
            color=COLOR_GNSS,
            lw=1.25,
            alpha=0.85,
            zorder=1,
            label=T("GNSS 三维基线", "GNSS baseline") if i == 0 else None,
        )
        # 基线名称放在中点，略微偏移，避免压线。
        ax.text(
            (a[0] + b[0]) / 2.0 + 25.0,
            (a[1] + b[1]) / 2.0 + 25.0,
            f"{baseline.frm}-{baseline.to}",
            fontsize=6.5,
            color=COLOR_GNSS,
            ha="center",
            va="bottom",
            zorder=5,
            bbox=dict(boxstyle="round,pad=0.12", fc="white", ec="none", alpha=0.78),
        )

    # 地面距离与角度：用浅色细线表示，避免遮挡基线。
    for a, b in DISTANCE_PAIRS:
        pa, pb = enu[a], enu[b]
        ax.plot(
            [pa[0], pb[0]],
            [pa[1], pb[1]],
            color=COLOR_DIST,
            lw=0.8,
            ls=":",
            alpha=0.65,
            zorder=0,
            label=T("地面距离", "terrestrial distance") if (a, b) == DISTANCE_PAIRS[0] else None,
        )
    for backsight, station, foresight in ANGLE_TRIPLES:
        s = enu[station]
        for target in (backsight, foresight):
            q = enu[target]
            ax.annotate(
                "",
                xy=(q[0], q[1]),
                xytext=(s[0], s[1]),
                arrowprops=dict(arrowstyle="->", color=COLOR_ANGLE, lw=0.7, ls="--", alpha=0.55),
                zorder=0,
            )
    ax.plot([], [], color=COLOR_ANGLE, lw=0.8, ls="--", label=T("水平角方向", "angle sight"))

    # 点、95% 椭圆、垂直精度标注
    for precision in joint_result.points.values():
        p = d["point_by_name"][precision.name]
        color = COLOR_FIXED if p.fixed else COLOR_GNSS
        marker = "^" if p.fixed else "o"
        ax.scatter(precision.E, precision.N, s=95, marker=marker, color=color, edgecolor="white", zorder=6)
        ell = precision.ellipse
        ax.add_patch(
            Ellipse(
                (precision.E, precision.N),
                width=2.0 * ell.standard_major * K95 * ELLIPSE_SCALE,
                height=2.0 * ell.standard_minor * K95 * ELLIPSE_SCALE,
                angle=90.0 - ell.azimuth_deg,
                facecolor=COLOR_ELLIPSE,
                edgecolor=COLOR_ELLIPSE,
                alpha=0.10,
                lw=0.8,
                zorder=2,
            )
        )
        ax.text(
            precision.E + 70.0,
            precision.N - 95.0,
            T(
                f"{precision.name}  σU={precision.sigma_U_mm:.1f} mm",
                f"{precision.name}  σU={precision.sigma_U_mm:.1f} mm",
            ),
            fontsize=7.5,
            color="#333333",
            zorder=7,
            bbox=dict(boxstyle="round,pad=0.16", fc="white", ec="none", alpha=0.82),
        )
        ax.text(
            precision.E - 80.0,
            precision.N + 70.0,
            precision.name,
            fontsize=9.5,
            fontweight="bold",
            color=color,
            ha="right",
            va="bottom",
            zorder=7,
        )

    ax.set_aspect("equal", adjustable="box")
    ax.set_xlabel(T("局部东坐标 E (m)", "local East E (m)"))
    ax.set_ylabel(T("局部北坐标 N (m)", "local North N (m)"))
    ax.set_title(
        T(
            "GNSS + 地面边角 + 水准联合平差：水平精度椭圆（局部 ENU，95% 放大 10 000×）",
            "Joint GNSS + terrestrial + leveling: horizontal ellipses (95%, ×10 000)",
        ),
        fontsize=10.5,
    )
    ax.grid(True, ls=":", lw=0.5, alpha=0.45)
    handles = [
        Line2D([], [], color=COLOR_GNSS, lw=1.25, label=T("GNSS 基线", "GNSS baseline")),
        Line2D([], [], color=COLOR_DIST, lw=0.9, ls=":", label=T("地面距离", "distance")),
        Line2D([], [], color=COLOR_ANGLE, lw=0.8, ls="--", label=T("水平角方向", "angle sight")),
        Line2D([], [], marker="^", color="none", markerfacecolor=COLOR_FIXED, markeredgecolor="white", markersize=8, label=T("固定点", "fixed")),
        Line2D([], [], marker="o", color="none", markerfacecolor=COLOR_GNSS, markeredgecolor="white", markersize=8, label=T("待定点", "unknown")),
        Patch(facecolor=COLOR_ELLIPSE, alpha=0.15, label=T("95% 水平误差椭圆", "95% ellipse")),
    ]
    ax.legend(handles=handles, loc="upper left", fontsize=7.5, framealpha=0.92)

    # 右图：垂直中误差
    unknown = [p for p in joint_result.points.values() if not p.fixed]
    order = sorted(unknown, key=lambda p: p.sigma_U_mm)
    names = [p.name for p in order]
    sigma_u = [p.sigma_U_mm for p in order]
    bars = ax_bar.barh(names, sigma_u, color=COLOR_LEVEL, alpha=0.82)
    for bar, value, p in zip(bars, sigma_u, order):
        ax_bar.text(
            value + 0.15,
            bar.get_y() + bar.get_height() / 2.0,
            f"{value:.2f} mm\n(3D {p.m3D_mm:.2f} mm)",
            va="center",
            fontsize=7.3,
        )
    ax_bar.set_xlabel(T("中误差 (mm)", "standard deviation (mm)"))
    ax_bar.set_title(T("联合平差后的垂直/三维精度", "vertical and 3D precision after joint adjustment"), fontsize=10.5)
    ax_bar.grid(True, axis="x", ls=":", lw=0.5, alpha=0.45)
    ax_bar.set_xlim(0.0, max(sigma_u) * 1.55 if sigma_u else 1.0)

    fig.suptitle(
        T(
            "C3 GNSS 基线网 + 地面边角 + 水准联合平差（设计态，局部 ENU 切平面近似）",
            "C3 GNSS + terrestrial + leveling joint design (local ENU tangent-plane approximation)",
        ),
        fontsize=12.5,
    )
    fig.tight_layout(rect=(0, 0, 1, 0.95))
    path = OUTPUTS / "gnss_network.png"
    fig.savefig(path, dpi=170)
    plt.close(fig)
    return path


def plot_geoid_fit(fit: Any, d: Dict[str, Any], egm_compare: Dict[str, Any]) -> Path:
    fig, (ax_res, ax_zeta) = plt.subplots(1, 2, figsize=(12.5, 5.2))
    residuals_mm = fit.residuals * 1e3
    colors = ["#d62728" if value >= 0 else "#1f77b4" for value in residuals_mm]
    bars = ax_res.bar(fit.point_names, residuals_mm, color=colors, alpha=0.85)
    for bar, value in zip(bars, residuals_mm):
        ax_res.text(
            bar.get_x() + bar.get_width() / 2.0,
            value + (0.05 if value >= 0 else -0.05),
            f"{value:+.2f}",
            ha="center",
            va="bottom" if value >= 0 else "top",
            fontsize=7.5,
        )
    ax_res.axhline(0.0, color="black", lw=0.8)
    ax_res.set_ylabel(T("残差 h−H−zeta_hat (mm)", "residual h−H−zeta_hat (mm)"))
    ax_res.set_title(
        T(
            f"zeta 平面拟合残差：RMS={fit.rms * 1e3:.2f} mm，最大={fit.max_abs_residual * 1e3:.2f} mm",
            f"zeta plane residuals: RMS={fit.rms * 1e3:.2f} mm, max={fit.max_abs_residual * 1e3:.2f} mm",
        ),
        fontsize=10.0,
    )
    ax_res.grid(True, axis="y", ls=":", lw=0.5, alpha=0.45)
    ax_res.set_ylim(min(-1.0, float(np.min(residuals_mm)) * 1.8), max(1.0, float(np.max(residuals_mm)) * 1.8))

    # ζ 观测（h−H）与拟合平面/EGM96 对照
    index = np.arange(fit.n)
    zeta = fit.zeta_values
    ax_zeta.plot(index, zeta * 1e3, "o", color="#1f77b4", label=T("观测 zeta=h−H", "observed zeta"))
    ax_zeta.plot(index, (fit.a + fit.b * fit.E + fit.c * fit.N) * 1e3, "s--", color="#d62728", label=T("平面拟合 zeta_hat", "plane fit"))
    if egm_compare.get("available"):
        ax_zeta.plot(
            index,
            np.asarray(egm_compare["zeta_egm"]) * 1e3,
            "d:",
            color="#2ca02c",
            label=T("EGM96 格网", "EGM96 grid"),
        )
    ax_zeta.set_xticks(index)
    ax_zeta.set_xticklabels(fit.point_names, fontsize=8)
    ax_zeta.set_ylabel(T("zeta (mm)", "zeta (mm)"))
    ax_zeta.set_title(
        T("高程异常样本与平面近似（相对局部 ENU 原点）", "zeta samples and local plane approximation"),
        fontsize=10.0,
    )
    ax_zeta.grid(True, ls=":", lw=0.5, alpha=0.45)
    ax_zeta.legend(fontsize=8, loc="best")
    ax_zeta.text(
        0.02,
        0.02,
        T(
            "近似，仅适用于小范围；不得外推替代 geoid 模型",
            "Approximation only; do not extrapolate",
        ),
        transform=ax_zeta.transAxes,
        fontsize=7.2,
        color="#7f0000",
        va="bottom",
    )
    fig.suptitle(
        T(
            f"高程异常平面拟合 zeta = a + bE + cN；控制点最大间距约 {fit.extent_m / 1e3:.2f} km",
            f"Height-anomaly plane fit zeta = a + bE + cN; max point spacing ≈ {fit.extent_m / 1e3:.2f} km",
        ),
        fontsize=12.0,
    )
    fig.tight_layout(rect=(0, 0, 1, 0.93))
    path = OUTPUTS / "geoid_fit.png"
    fig.savefig(path, dpi=170)
    plt.close(fig)
    return path


# ---------------------------------------------------------------------------
# 4. 表格/CSV/Markdown
# ---------------------------------------------------------------------------
def _fmt_mm(value: float, digits: int = 2) -> str:
    return f"{value * 1e3:.{digits}f}"


def _fmt_ratio(value: float) -> str:
    if not np.isfinite(value) or value <= 0.0:
        return "—"
    return f"1:{1.0 / value:,.0f}"


def write_csv(
    path: Path,
    gnss_result: Any,
    joint_result: Any,
    fit: Any,
    d: Dict[str, Any],
    egm_compare: Dict[str, Any],
) -> None:
    columns = [
        "category",
        "name",
        "frm",
        "to",
        "fixed",
        "project_E_m",
        "project_N_m",
        "E_m",
        "N_m",
        "U_m",
        "lat_deg",
        "lon_deg",
        "h_m",
        "H_normal_m",
        "sigma_E_mm",
        "sigma_N_mm",
        "sigma_U_mm",
        "mp_mm",
        "m3D_mm",
        "ellipse_a95_mm",
        "ellipse_b95_mm",
        "ellipse_az_deg",
        "length_3d_m",
        "sigma_3d_mm",
        "relative_3d",
        "horizontal_length_m",
        "sigma_horizontal_mm",
        "relative_horizontal",
        "r_i",
        "mdb_mm",
        "residual_mm",
        "egm96_zeta_m",
    ]
    rows: List[Dict[str, Any]] = []
    for p in joint_result.points.values():
        raw = d["project_by_name"][p.name]
        rows.append(
            {
                "category": "point",
                "name": p.name,
                "frm": "",
                "to": "",
                "fixed": int(p.fixed),
                "project_E_m": f"{float(raw['E']):.4f}",
                "project_N_m": f"{float(raw['N']):.4f}",
                "E_m": f"{p.E:.4f}",
                "N_m": f"{p.N:.4f}",
                "U_m": f"{p.U:.4f}",
                "lat_deg": f"{p.lat:.12f}",
                "lon_deg": f"{p.lon:.12f}",
                "h_m": f"{p.h:.4f}",
                "H_normal_m": "" if p.H_normal is None else f"{p.H_normal:.4f}",
                "sigma_E_mm": f"{p.sigma_E_mm:.4f}",
                "sigma_N_mm": f"{p.sigma_N_mm:.4f}",
                "sigma_U_mm": f"{p.sigma_U_mm:.4f}",
                "mp_mm": f"{p.mp_mm:.4f}",
                "m3D_mm": f"{p.m3D_mm:.4f}",
                "ellipse_a95_mm": f"{p.ellipse.standard_major * K95 * 1e3:.4f}",
                "ellipse_b95_mm": f"{p.ellipse.standard_minor * K95 * 1e3:.4f}",
                "ellipse_az_deg": f"{p.ellipse.azimuth_deg:.4f}",
                "residual_mm": "",
                "egm96_zeta_m": f"{d['egm_zeta'][p.name]:.6f}" if egm_compare.get("available") else "",
            }
        )
    for b in joint_result.baselines.values():
        rows.append(
            {
                "category": "baseline",
                "name": b.label,
                "frm": b.frm,
                "to": b.to,
                "fixed": "",
                "length_3d_m": f"{b.length_3d:.4f}",
                "sigma_3d_mm": f"{b.sigma_3d_mm:.4f}",
                "relative_3d": f"{b.relative_3d:.9f}",
                "horizontal_length_m": f"{b.horizontal_length:.4f}",
                "sigma_horizontal_mm": f"{b.sigma_horizontal_mm:.4f}",
                "relative_horizontal": f"{b.relative_horizontal:.9f}",
                "sigma_U_mm": f"{b.sigma_vertical_mm:.4f}",
                "r_i": "" if b.r_i is None else f"{b.r_i:.6f}",
                "mdb_mm": "" if b.mdb_mm is None else f"{b.mdb_mm:.4f}",
            }
        )
    for i, name in enumerate(fit.point_names):
        rows.append(
            {
                "category": "geoid_control",
                "name": name,
                "E_m": f"{fit.E[i]:.4f}",
                "N_m": f"{fit.N[i]:.4f}",
                "h_m": f"{fit.h[i]:.4f}",
                "H_normal_m": f"{fit.H[i]:.4f}",
                "residual_mm": f"{fit.residuals[i] * 1e3:.4f}",
                "egm96_zeta_m": f"{egm_compare['zeta_egm'][i]:.6f}" if egm_compare.get("available") else "",
            }
        )
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=columns)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key, "") for key in columns})


def write_markdown(
    path: Path,
    gnss_result: Any,
    joint_result: Any,
    fit: Any,
    d: Dict[str, Any],
    egm_compare: Dict[str, Any],
    paths: Dict[str, Path],
) -> None:
    lines: List[str] = []
    lines.append("# C3 GNSS 基线网、联合平差与高程异常近似")
    lines.append("")
    lines.append("> 本报告为**设计态（先验）精度估算**，不是实测后验平差。")
    lines.append("> 坐标：局部 ENU，原点为 P1；高程异常平面模型是局部近似，仅适用于小范围。")
    lines.append("")
    lines.append("## 1. 数据与模型")
    lines.append("")
    lines.append(f"- 工程点：{len(d['points'])} 个（P1、P2 固定）；来自 `data/sample/terrain_project.json`。")
    lines.append(f"- GNSS 基线：{len(d['points']) and len(BASELINE_PAIRS)} 条，ENU 框架、完整 3×3 协方差；WGS84 ECEF 中平差。")
    lines.append(f"- 地面观测：{len(DISTANCE_PAIRS)} 条距离（2 mm + 2 ppm）、{len(ANGLE_TRIPLES)} 个水平角（1″）。")
    lines.append(f"- 水准：{len(LEVELING_PAIRS)} 条测段，σ=1.0 mm/√km；正常高差经 ζ 平面模型转为椭球高差。")
    if egm_compare.get("available"):
        lines.append("- 大地高：DEM 正常高 + EGM96 15′ 格网 ζ + 4 mm 模拟噪声。")
    else:
        lines.append("- 大地高：DEM 正常高 + 平滑合成 ζ + 4 mm 模拟噪声（EGM 样本缺失）。")
    lines.append("- 假设：局部 ENU 切平面内计算水平距离/角度；测区约 4 km，曲率与投影尺度影响未单独建模。")
    lines.append("")
    lines.append("## 2. GNSS-only 与联合平差")
    lines.append("")
    lines.append("| 指标 | GNSS-only | GNSS + 地面边角 + 水准 |")
    lines.append("|---|---:|---:|")
    lines.append(
        f"| 观测行数 / 参数 / 冗余 | {gnss_result.n_rows} / {gnss_result.n_params} / {gnss_result.redundancy} | "
        f"{joint_result.n_rows} / {joint_result.n_params} / {joint_result.redundancy} |"
    )
    lines.append(f"| 最大水平 mp (mm) | {gnss_result.max_mp * 1e3:.3f} | {joint_result.max_mp * 1e3:.3f} |")
    lines.append(f"| 最大三维 m3D (mm) | {gnss_result.max_m3D * 1e3:.3f} | {joint_result.max_m3D * 1e3:.3f} |")
    lines.append(f"| 最大垂直 σU (mm) | {gnss_result.max_sigma_U * 1e3:.3f} | {joint_result.max_sigma_U * 1e3:.3f} |")
    lines.append(f"| 最小 r_i | {gnss_result.min_r:.4f} | {joint_result.min_r:.4f} |")
    lines.append(f"| 最大 MDB (mm) | {gnss_result.max_mdb * 1e3:.3f} | {joint_result.max_mdb * 1e3:.3f} |")
    lines.append("")
    lines.append("加入地面观测后，法方程信息只增不减，`Cx` 的 Loewner 差应为半负定；")
    lines.append("本演示的联合结果在水平、三维和垂直精度上均不劣于纯 GNSS 结果。")
    lines.append("")
    lines.append("## 3. 点位精度（联合平差）")
    lines.append("")
    lines.append("| 点 | 类型 | E (m) | N (m) | U (m) | h (m) | H (m) | σE (mm) | σN (mm) | σU (mm) | mp (mm) | m3D (mm) | 95% 椭圆 a×b (mm) | 方位角 (°) |")
    lines.append("|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|---:|")
    for p in joint_result.points.values():
        kind = "固定" if p.fixed else "待定"
        H = "—" if p.H_normal is None else f"{p.H_normal:.3f}"
        lines.append(
            f"| {p.name} | {kind} | {p.E:.3f} | {p.N:.3f} | {p.U:.3f} | {p.h:.3f} | {H} | "
            f"{p.sigma_E_mm:.2f} | {p.sigma_N_mm:.2f} | {p.sigma_U_mm:.2f} | {p.mp_mm:.2f} | {p.m3D_mm:.2f} | "
            f"{p.ellipse.standard_major * K95 * 1e3:.2f}×{p.ellipse.standard_minor * K95 * 1e3:.2f} | {p.ellipse.azimuth_deg:.1f} |"
        )
    lines.append("")
    lines.append("## 4. 基线相对精度与可靠性")
    lines.append("")
    lines.append("| 基线 | 三维长 (m) | σ3D (mm) | 相对精度 3D | 水平长 (m) | σh (mm) | 相对精度水平 | r_i | MDB (mm) |")
    lines.append("|---|---:|---:|---:|---:|---:|---:|---:|---:|")
    for b in joint_result.baselines.values():
        mdb = "—" if b.mdb_mm is None else f"{b.mdb_mm:.2f}"
        r = "—" if b.r_i is None else f"{b.r_i:.3f}"
        lines.append(
            f"| {b.label} | {b.length_3d:.3f} | {b.sigma_3d_mm:.2f} | {_fmt_ratio(b.relative_3d)} | "
            f"{b.horizontal_length:.3f} | {b.sigma_horizontal_mm:.2f} | {_fmt_ratio(b.relative_horizontal)} | {r} | {mdb} |"
        )
    lines.append("")
    lines.append("`r_i` 为 3 个基线分量的多余观测分量之和（0–3）；MDB 为分量最大可探测粗差。")
    lines.append("")
    lines.append("## 5. 高程异常平面拟合")
    lines.append("")
    lines.append("| 参数 | 估值 | 中误差 |")
    lines.append("|---|---:|---:|")
    lines.append(f"| a (m) | {fit.a:.6f} | {fit.sigma_a:.6f} |")
    lines.append(f"| b (ppm) | {fit.b * 1e6:.6f} | {fit.sigma_b * 1e6:.6f} |")
    lines.append(f"| c (ppm) | {fit.c * 1e6:.6f} | {fit.sigma_c * 1e6:.6f} |")
    lines.append(f"| σ0 (mm) | {fit.sigma0 * 1e3:.3f} | — |")
    lines.append(f"| 残差 RMS (mm) | {fit.rms * 1e3:.3f} | — |")
    lines.append(f"| 最大残差 (mm) | {fit.max_abs_residual * 1e3:.3f} | — |")
    lines.append(f"| 控制点 / dof | {fit.n} / {fit.dof} | — |")
    lines.append(f"| 控制点最大间距 (km) | {fit.extent_m / 1e3:.2f} | — |")
    lines.append("")
    lines.append(f"**适用范围声明：** {fit.applicability_note}")
    if egm_compare.get("available"):
        lines.append("")
        lines.append("### 与 EGM96 格网比较")
        lines.append("")
        lines.append("| 点 | ζ(h−H) (m) | 平面 ζ̂ (m) | EGM96 ζ (m) | 平面−EGM96 (mm) |")
        lines.append("|---|---:|---:|---:|---:|")
        for i, name in enumerate(fit.point_names):
            zhat = fit.a + fit.b * fit.E[i] + fit.c * fit.N[i]
            lines.append(
                f"| {name} | {fit.zeta_values[i]:.5f} | {zhat:.5f} | {egm_compare['zeta_egm'][i]:.5f} | "
                f"{(zhat - egm_compare['zeta_egm'][i]) * 1e3:+.3f} |"
            )
        lines.append("")
        lines.append(
            f"EGM96 与平面近似的差值 RMS = {egm_compare['rms_plane_minus_egm'] * 1e3:.3f} mm；"
            "该差值主要来自局部 geoid 的非线性与格网分辨率，而不是格网误差的严格估计。"
        )
    else:
        lines.append("")
        lines.append("未找到 EGM96 裁剪样本，本次仅使用平面拟合；可用 `scripts/fetch_egm.py` 获取。")
    lines.append("")
    lines.append("## 6. 观测可靠性（联合平差）")
    lines.append("")
    lines.append("| 观测 | 类型 | σ | r_i | MDB | 外部影响 (mm) |")
    lines.append("|---|---|---:|---:|---:|---:|")
    for row in joint_result.reliability.records:
        if row.kind in ("gnss", "distance"):
            sigma_text = f"{row.sigma * 1e3:.2f} mm"
        elif row.kind in ("angle", "direction"):
            sigma_text = f"{row.sigma * 180.0 * 3600.0 / np.pi:.2f}″"
        else:
            sigma_text = f"{row.sigma * 1e3:.2f} mm"
        mdb = "—" if not np.isfinite(row.mdb) else f"{row.mdb_display:.2f}"
        lines.append(
            f"| {row.label} | {row.kind} | {sigma_text} | {row.r_i:.3f} | {mdb} | {row.external_max_mm:.2f} |"
        )
    lines.append("")
    lines.append("## 7. 输出文件")
    lines.append("")
    for key, value in paths.items():
        lines.append(f"- `{value.relative_to(ROOT)}`（{key}）")
    lines.append("")
    lines.append("## 8. 局限")
    lines.append("")
    lines.append("- 局部 ENU 是切平面近似；跨出数公里后应改用椭球面/投影归算，长边不能直接按平面处理。")
    lines.append("- 水准高差与 GNSS 大地高的统一依赖 ζ 模型；本演示用平面拟合改正，未传播 geoid 模型系统误差。")
    lines.append("- 基线协方差为模拟值；真实网解应使用上游软件的完整 VCV，并检查跨基线相关。")
    lines.append("- `r_i`/MDB 复用 `ctrlnet.reliability` 的 Baarda 公式；MDB 是统计可探测性，不是实际粗差大小。")
    lines.append("- 演示格网为 EGM96，而 DEM 元数据垂直基准为 EGM2008；未做模型间改正，ζ 数值仅用于流程演示。")
    lines.append("")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


# ---------------------------------------------------------------------------
# 5. 主流程
# ---------------------------------------------------------------------------
def main() -> int:
    d = load_demo()
    points = d["point_by_name"]
    baselines = make_baselines(points)
    distances, angles, leveling = make_ground(d["project"], points)
    fit = fit_height_anomaly(d["geoid_samples"], mode="plane")

    gnss_only = GnssNetwork(
        d["points"], baselines, origin=d["origin_name"], parameter_frame="ECEF", name="gnss-only"
    )
    joint = GnssNetwork(
        d["points"],
        baselines,
        distances=distances,
        angles=angles,
        leveling=leveling,
        origin=d["origin_name"],
        parameter_frame="ECEF",
        name="gnss-joint",
    ).with_geoid(fit)

    gnss_result = solve_gnss(gnss_only, datum="fixed")
    joint_result = solve_gnss(joint, datum="fixed")

    if d["egm"] is not None:
        zeta_egm = [
            float(d["egm"].undulation(p.lon, p.lat))
            for p in d["points"]
        ]
        zhat = np.array([fit.a + fit.b * fit.E[i] + fit.c * fit.N[i] for i in range(fit.n)])
        egm_compare = {
            "available": True,
            "zeta_egm": zeta_egm,
            "rms_plane_minus_egm": float(np.sqrt(np.mean((zhat - np.asarray(zeta_egm)) ** 2))),
        }
    else:
        egm_compare = {
            "available": False,
            "zeta_egm": [float("nan")] * len(d["points"]),
            "rms_plane_minus_egm": float("nan"),
        }

    paths = {
        "基线/椭圆/垂直精度图": plot_gnss_network(joint_result, d, baselines),
        "高程异常拟合图": plot_geoid_fit(fit, d, egm_compare),
    }
    csv_path = OUTPUTS / "gnss_results.csv"
    md_path = OUTPUTS / "gnss_results.md"
    write_csv(csv_path, gnss_result, joint_result, fit, d, egm_compare)
    paths["点/基线/ζ CSV"] = csv_path
    paths["中文报告"] = md_path
    write_markdown(md_path, gnss_result, joint_result, fit, d, egm_compare, paths)

    print("C3 GNSS 演示完成")
    print(f"  GNSS-only: rank={gnss_result.rank}, redundancy={gnss_result.redundancy}, max mp={gnss_result.max_mp*1e3:.3f} mm")
    print(f"  Joint    : rank={joint_result.rank}, redundancy={joint_result.redundancy}, max mp={joint_result.max_mp*1e3:.3f} mm, max σU={joint_result.max_sigma_U*1e3:.3f} mm")
    print(f"  zeta fit : a={fit.a:.4f} m, b={fit.b*1e6:.4f} ppm, c={fit.c*1e6:.4f} ppm, RMS={fit.rms*1e3:.3f} mm")
    if egm_compare["available"]:
        print(f"  EGM96    : 平面−格网 RMS={egm_compare['rms_plane_minus_egm']*1e3:.3f} mm")
    for key, value in paths.items():
        print(f"  {key}: {value.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
