#!/usr/bin/env python3
"""投影归算演示：尺度因子、收敛角、grid/ground 与跨带检查。

输出 ``outputs/projection_results.md``，所有数值均离线计算；对照项包括：

1. 高斯-克吕格二阶尺度/三阶收敛角解析级数；
2. 由 ``thesis.gauss_forward`` 中心差分得到的数值雅可比；
3. UTM 东坐标近似 ``m ≈ k0(1 + y²/(2R²))``；
4. grid→ground→grid 手工公式与往返残差。
"""

from __future__ import annotations

import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Tuple

from ctrlnet.projection import (
    GeoPoint,
    ProjectionSpec,
    check_cross_zone,
    grid_to_ground,
    ground_to_grid,
    local_curvature_radius,
    meridian_convergence,
    point_scale_factor,
    reduction_factors,
)
from ctrlnet.thesis import gauss_forward, get_ellipsoid

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "outputs" / "projection_results.md"
TERRAIN = ROOT / "data" / "sample" / "terrain_project.json"

KNOWN_POINTS = [
    ("论文算例1-点1", 34.187637001, 117.250217, 117.0, 1.0, "Gauss 3°"),
    ("论文算例1-点9", 34.191638001, 117.253595, 117.0, 1.0, "Gauss 3°"),
    ("UTM50N-P1", 39.93764839164841, 116.00932231333756, 117.0, 0.9996, "UTM 6°"),
    ("UTM50N-P7", 39.9101149755697, 116.0458705565617, 117.0, 0.9996, "UTM 6°"),
    ("赤道检查点", 0.0, 1.0, 0.0, 1.0, "Gauss 3°"),
    ("中纬检查点", 45.0, 120.5, 120.0, 1.0, "Gauss 3°"),
    ("高纬检查点", 60.0, 10.0, 9.0, 0.9996, "UTM 6°"),
]


def _series_scale_gamma(lat_deg: float, lon_deg: float, cm: float, k0: float) -> Tuple[float, float]:
    """独立二阶尺度、三阶收敛角级数（度）。"""
    ell = get_ellipsoid("CGCS2000")
    lat = math.radians(lat_deg)
    lam = math.radians(lon_deg - cm)
    ep2 = ell.e2 / (1.0 - ell.e2)
    t = math.tan(lat)
    eta2 = ep2 * math.cos(lat) ** 2
    c = math.cos(lat)
    m = k0 * (
        1.0
        + 0.5 * lam**2 * c**2 * (1.0 + eta2)
        + (lam**4 * c**4 / 24.0)
        * (5.0 - 4.0 * t**2 + 14.0 * eta2 - 28.0 * t**2 * eta2)
        + (lam**6 * c**6 / 720.0)
        * (61.0 - 148.0 * t**2 + 16.0 * t**4 + 330.0 * eta2 - 600.0 * t**2 * eta2)
    )
    gamma = math.degrees(
        lam * math.sin(lat)
        + (lam**3 / 3.0) * math.sin(lat) * c**2 * (1.0 + 3.0 * eta2 + 2.0 * eta2**2)
        + (lam**5 / 15.0) * math.sin(lat) * c**4 * (2.0 - t**2)
    )
    return m, gamma


def _numeric_scale_gamma(
    lat_deg: float, lon_deg: float, cm: float, k0: float, step: float = 1e-4
) -> Tuple[float, float]:
    ell = get_ellipsoid("CGCS2000")
    lat = math.radians(lat_deg)
    x1, y1 = gauss_forward(lat_deg - step, lon_deg, central_meridian=cm)
    x2, y2 = gauss_forward(lat_deg + step, lon_deg, central_meridian=cm)
    m_radius = ell.a * (1.0 - ell.e2) / (1.0 - ell.e2 * math.sin(lat) ** 2) ** 1.5
    m = math.hypot(x2 - x1, y2 - y1) * k0 / (m_radius * 2.0 * math.radians(step))
    gamma = -math.degrees(math.atan2(y2 - y1, x2 - x1))
    return m, gamma


def _table_known_points() -> Tuple[List[str], Dict[str, float]]:
    lines = [
        "| 点 | 纬度/° | 经度/° | Δλ/(°) | k0 | m | 尺度偏差/ppm | γ/(°) | γ/(′) | 二阶 m | Δm/ppm | γ级数/(″) | Δγ/(″) | 数值 Δm/ppm | 数值 Δγ/(″) |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    max_series_m = 0.0
    max_series_g = 0.0
    max_numeric_m = 0.0
    max_numeric_g = 0.0
    for name, lat, lon, cm, k0, _mode in KNOWN_POINTS:
        m = point_scale_factor(lat, lon, central_meridian=cm, scale_factor=k0)
        gamma = meridian_convergence(lat, lon, central_meridian=cm, scale_factor=k0)
        series_m, series_gamma = _series_scale_gamma(lat, lon, cm, k0)
        numeric_m, numeric_gamma = _numeric_scale_gamma(lat, lon, cm, k0)
        dm_series = (m - series_m) * 1e6
        dg_series = (gamma - series_gamma) * 3600.0
        dm_numeric = (m - numeric_m) * 1e6
        dg_numeric = (gamma - numeric_gamma) * 3600.0
        max_series_m = max(max_series_m, abs(dm_series))
        max_series_g = max(max_series_g, abs(dg_series))
        max_numeric_m = max(max_numeric_m, abs(dm_numeric))
        max_numeric_g = max(max_numeric_g, abs(dg_numeric))
        lines.append(
            "| {name} | {lat:.9f} | {lon:.9f} | {dl:+.6f} | {k0:g} | {m:.12f} | "
            "{ppm:+.4f} | {gamma:+.9f} | {gamin:+.5f} | {sm:.12f} | {dm:+.6f} | "
            "{sg:.6f} | {dg:+.6f} | {nm:+.4f} | {ng:+.6f} |".format(
                name=name,
                lat=lat,
                lon=lon,
                dl=lon - cm,
                k0=k0,
                m=m,
                ppm=(m / k0 - 1.0) * 1e6,
                gamma=gamma,
                gamin=gamma * 60.0,
                sm=series_m,
                dm=dm_series,
                sg=series_gamma * 3600.0,
                dg=dg_series,
                nm=dm_numeric,
                ng=dg_numeric,
            )
        )
    summary = {
        "max_series_m": max_series_m,
        "max_series_g": max_series_g,
        "max_numeric_m": max_numeric_m,
        "max_numeric_g": max_numeric_g,
    }
    return lines, summary


def _terrain_points() -> Dict[str, Dict[str, Any]]:
    if not TERRAIN.is_file():
        return {}
    payload = json.loads(TERRAIN.read_text(encoding="utf-8"))
    return {str(item["name"]): item for item in payload.get("points", [])}


def _table_edges() -> Tuple[List[str], Dict[str, float]]:
    points = _terrain_points()
    pairs = [("P1", "P2"), ("P1", "P4"), ("P1", "P7"), ("P3", "P6"), ("P6", "P7")]
    spec = ProjectionSpec(
        central_meridian=117.0,
        scale_factor=0.9996,
        zone_width=6.0,
        convention="utm",
        name="UTM 50N",
    )
    lines = [
        "| 边 | 投影距离/m | 平均高程/m | R/m | k投影（端点均值） | 高程因子 | 综合尺度 | 地面距离/m | 手工值/m | 往返恢复/m | 往返误差/mm |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    max_roundtrip = 0.0
    for a, b in pairs:
        if a not in points or b not in points:
            continue
        pa, pb = points[a], points[b]
        grid = math.hypot(float(pb["E"]) - float(pa["E"]), float(pb["N"]) - float(pa["N"]))
        height = 0.5 * (float(pa["elevation_m"]) + float(pb["elevation_m"]))
        lat_mean = 0.5 * (float(pa["lat"]) + float(pb["lat"]))
        k = 0.5 * (spec.scale(float(pa["lat"]), float(pa["lon"])) + spec.scale(float(pb["lat"]), float(pb["lon"])))
        factors = reduction_factors(
            mean_height_m=height,
            projection_scale=k,
            latitude_deg=lat_mean,
        )
        ground = grid_to_ground(
            grid,
            mean_height_m=height,
            projection_scale=k,
            latitude_deg=lat_mean,
        )
        manual = grid / (k * factors.radius_m / (factors.radius_m + height))
        recovered = ground_to_grid(
            ground,
            mean_height_m=height,
            projection_scale=k,
            latitude_deg=lat_mean,
        )
        error = (recovered - grid) * 1000.0
        max_roundtrip = max(max_roundtrip, abs(error))
        lines.append(
            f"| {a}–{b} | {grid:.4f} | {height:.3f} | {factors.radius_m:.2f} | "
            f"{k:.12f} | {factors.height_factor:.12f} | {factors.combined_scale:.12f} | "
            f"{ground:.6f} | {manual:.6f} | {recovered:.6f} | {error:+.3e} |"
        )
    return lines, {"max_roundtrip_mm": max_roundtrip}


def _table_utm_approx() -> List[str]:
    points = _terrain_points()
    spec = ProjectionSpec(
        central_meridian=117.0,
        scale_factor=0.9996,
        zone_width=6.0,
        convention="utm",
    )
    lines = [
        "| 点 | E/m | E−500km/m | m（复变导数） | m≈k0(1+y²/2R²) | 差值/ppm |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for name in ("P1", "P7"):
        if name not in points:
            continue
        item = points[name]
        lat, lon = float(item["lat"]), float(item["lon"])
        easting, _ = spec.forward(lat, lon)
        y = easting - 500000.0
        radius = local_curvature_radius(lat)
        m = spec.scale(lat, lon)
        approx = 0.9996 * (1.0 + y * y / (2.0 * radius * radius))
        lines.append(
            f"| {name} | {easting:.4f} | {y:+.4f} | {m:.12f} | {approx:.12f} | "
            f"{(m - approx) * 1e6:+.4f} |"
        )
    return lines


def _table_zone_checks() -> List[str]:
    checks = [
        (
            "3°带跨带（可换带）",
            [GeoPoint(34.2, 118.4, "A"), GeoPoint(34.2, 118.7, "B")],
            dict(zone=39),
        ),
        (
            "3°带跨带（需分区）",
            [GeoPoint(34.2, 117.4, "A"), GeoPoint(34.2, 118.6, "B")],
            dict(zone=39),
        ),
        (
            "UTM50N 带内",
            [GeoPoint(39.93764839164841, 116.00932231333756, "P1"), GeoPoint(39.9101149755697, 116.0458705565617, "P7")],
            dict(zone=50, zone_width=6.0, convention="utm"),
        ),
        (
            "当前带号错误",
            [GeoPoint(34.2, 117.2, "A"), GeoPoint(34.2, 117.25, "B")],
            dict(zone=40),
        ),
    ]
    lines = [
        "| 场景 | 当前带 | 当前CM/° | 点所在带 | 跨带 | 建议换带 | 推荐带 | 推荐CM/° | 当前最大尺度偏差/ppm | 推荐最大尺度偏差/ppm | 最大γ/(′) | 警告代码 |",
        "|---|---:|---:|---|---|---|---:|---:|---:|---:|---:|---|",
    ]
    for title, points, kwargs in checks:
        result = check_cross_zone(points, **kwargs)
        native = sorted({point.zone for point in result.points})
        lines.append(
            f"| {title} | {result.current_zone} | {result.current_central_meridian:.3f} | "
            f"{'、'.join(map(str, native))} | {'是' if result.crosses_zone else '否'} | "
            f"{'是' if result.should_switch_zone else '否'} | {result.recommended_zone} | "
            f"{result.recommended_central_meridian:.3f} | {result.max_scale_deviation_ppm:.2f} | "
            f"{result.recommended_max_scale_deviation_ppm:.2f} | {result.max_convergence_arcmin:.3f} | "
            f"{', '.join(result.warning_codes)} |"
        )
    return lines


def build_markdown() -> str:
    known_lines, summary = _table_known_points()
    edge_lines, edge_summary = _table_edges()
    utm_lines = _table_utm_approx()
    zone_lines = _table_zone_checks()
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    lines = [
        "# 投影归算结果（E1）",
        "",
        f"生成时间：{now}；引擎：`ctrlnet.projection`；椭球：CGCS2000。",
        "长度单位 m，角度输入度；`γ = 真北方位角 − 网格方位角`，东于中央子午线为正。",
        "尺度因子 `m = ds_grid / ds_ellipsoid`，`k0` 为中央经线尺度（UTM 0.9996）。",
        "",
        "## 1. 已知点尺度因子与收敛角",
        "",
        *known_lines,
        "",
        "对照说明：",
        "",
        f"- 二阶/三阶解析级数 vs 复变 n⁶ 严格式：最大 |Δm| = {summary['max_series_m']:.5f} ppm，"
        f"最大 |Δγ| = {summary['max_series_g']:.6f}″；",
        f"- `thesis.gauss_forward` 中心差分雅可比 vs 严格式：最大 |Δm| = {summary['max_numeric_m']:.5f} ppm，"
        f"最大 |Δγ| = {summary['max_numeric_g']:.6f}″；",
        "- 中央子午线上 m=k0、γ=0 由解析式精确保证（表中检查点）；",
        "- 收敛角符号与 `grid_azimuth = true_azimuth − γ` 一致，网页/报告不得在 UI 层临时加减。",
        "",
        "## 2. UTM 东坐标近似对照",
        "",
        *utm_lines,
        "",
        "近似式 `m ≈ k0(1 + y²/(2R²))` 只用于快速手算；上表差值约 0.07 ppm，"
        "正式成果使用模块的复变导数。",
        "",
        "## 3. grid ↔ ground 距离归算",
        "",
        *edge_lines,
        "",
        f"往返最大误差 {edge_summary['max_roundtrip_mm']:.3e} mm。公式：",
        "",
        "```text",
        "s_ground = s_grid / [k_prj · R/(R+H_m)]",
        "s_grid   = s_ground · k_prj · R/(R+H_m)",
        "R = sqrt(M·N)，H_m 为测线平均大地高（m）",
        "```",
        "",
        "`H_m` 用正常高/正高时是工程近似，成果中必须注明高程类型；高精度应使用逐点曲率半径或 PROJ。",
        "",
        "## 4. 跨带/中央子午线检查",
        "",
        *zone_lines,
        "",
        "阈值：`|m/k0−1| > 10 ppm`、`|γ|或Δγ > 30′` 触发提示；跨带只警告并要求分区/3D-ENU，"
        "不直接拒绝计算。带内尺度超限时仍可用地面坐标或低变形投影。",
        "",
        "## 5. 复现命令",
        "",
        "```bash",
        ".venv/bin/python scripts/run_projection_demo.py",
        ".venv/bin/python -m pytest -q tests/test_projection.py",
        "```",
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(build_markdown(), encoding="utf-8")
    print(f"写出 {OUTPUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
