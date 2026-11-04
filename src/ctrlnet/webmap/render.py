"""网页地图的离线渲染：晕渲 PNG、等高线 GeoJSON、配准影像重采样。"""

from __future__ import annotations

import io
import os
from math import ceil, floor
from pathlib import Path
from typing import Any, Iterable, Optional, Sequence

import numpy as np
from PIL import Image

from ..terrain import DEM, AffineTransform, contours, hillshade

os.environ.setdefault(
    "MPLCONFIGDIR", str(Path(os.environ.get("TMPDIR", "/tmp")) / "ctrlnet-mplconfig")
)
Path(os.environ["MPLCONFIGDIR"]).mkdir(parents=True, exist_ok=True)


def _rgb_palette() -> tuple[np.ndarray, np.ndarray]:
    stops = np.array([0.0, 0.16, 0.34, 0.54, 0.74, 0.90, 1.0])
    colors = np.array(
        [
            [0.30, 0.56, 0.35],  # 低地深绿
            [0.48, 0.68, 0.38],
            [0.70, 0.76, 0.44],
            [0.86, 0.80, 0.55],  # 黄褐
            [0.74, 0.60, 0.42],
            [0.62, 0.50, 0.38],
            [0.90, 0.90, 0.88],  # 高山灰白
        ]
    )
    return stops, colors


def hillshade_rgb(dem: DEM) -> np.ndarray:
    """返回 ``(H,W,3)`` 的 [0,1] 分层设色 + 晕渲 RGB 数组。"""
    z = np.asarray(dem.array, dtype=float)
    valid = dem.valid_mask
    if not valid.any():
        raise ValueError("DEM 没有有效像元，无法渲染")
    shade = hillshade(dem, azimuth=315.0, altitude=45.0)
    low = float(np.percentile(z[valid], 1.0))
    high = float(np.percentile(z[valid], 99.0))
    t = np.clip((z - low) / max(high - low, 1e-9), 0.0, 1.0)
    stops, colors = _rgb_palette()
    rgb = np.empty(z.shape + (3,), dtype=float)
    for channel in range(3):
        rgb[..., channel] = np.interp(t, stops, colors[:, channel])
    # 分层设色保留颜色，晕渲提供地形立体感。
    brightness = 0.52 + 0.62 * shade
    rgb = rgb * brightness[..., None]
    rgb[~valid] = 0.0
    return np.clip(rgb, 0.0, 1.0)


def render_hillshade_png(dem: DEM, *, scale: int = 2) -> bytes:
    """把 DEM 渲染为带透明 NoData 的 PNG 字节串（用于 Leaflet imageOverlay）。"""
    rgb = hillshade_rgb(dem)
    alpha = np.where(dem.valid_mask, 255, 0).astype(np.uint8)
    rgba = np.dstack([(rgb * 255.0 + 0.5).astype(np.uint8), alpha])
    image = Image.fromarray(rgba, mode="RGBA")
    if scale > 1:
        image = image.resize(
            (dem.width * scale, dem.height * scale), Image.Resampling.BILINEAR
        )
    buffer = io.BytesIO()
    image.save(buffer, format="PNG", optimize=True)
    return buffer.getvalue()


def _contour_levels(dem: DEM, interval: float = 50.0) -> np.ndarray:
    valid = dem.array[dem.valid_mask]
    if not valid.size:
        return np.array([], dtype=float)
    low = floor(float(valid.min()) / interval) * interval
    high = float(valid.max())
    return np.arange(low, high + interval * 0.5, interval)


def build_contours_geojson(dem: DEM, *, interval: float = 50.0) -> dict:
    """用 Matplotlib 提取等高线并转换为 GeoJSON（坐标 E/N，EPSG:32650）。"""
    import matplotlib

    matplotlib.use("Agg", force=False)
    import matplotlib.pyplot as plt

    levels = _contour_levels(dem, interval)
    features: list[dict] = []
    if levels.size >= 2:
        fig, ax = plt.subplots(figsize=(4, 4))
        try:
            cs = contours(dem, ax=ax, levels=levels, linewidths=0.35)
            allsegs = getattr(cs, "allsegs", [])
        finally:
            plt.close(fig)
        for level_index, segments in enumerate(allsegs):
            elevation = float(levels[level_index])
            for segment in segments:
                coords = np.asarray(segment, dtype=float)
                if coords.ndim != 2 or coords.shape[0] < 2:
                    continue
                coordinates = [
                    [round(float(x), 3), round(float(y), 3)] for x, y in coords
                ]
                features.append(
                    {
                        "type": "Feature",
                        "geometry": {"type": "LineString", "coordinates": coordinates},
                        "properties": {
                            "layer": "contours",
                            "elevation_m": elevation,
                            "index": bool(level_index % 5 == 0),
                            "interval_m": float(interval),
                        },
                    }
                )
    xs = [feature["geometry"]["coordinates"][0][0] for feature in features if feature["geometry"]["coordinates"]]
    ys = [feature["geometry"]["coordinates"][0][1] for feature in features if feature["geometry"]["coordinates"]]
    if xs and ys:
        bbox = [min(xs), min(ys), max(xs), max(ys)]
    else:
        left, bottom, right, top = dem.bounds
        bbox = [left, bottom, right, top]
    return {
        "type": "FeatureCollection",
        "name": "contours",
        "crs": {"type": "name", "properties": {"name": "EPSG:32650"}},
        "bbox": bbox,
        "features": features,
    }


def _ellipse_polygon(
    E: float, N: float, a: float, b: float, azimuth_deg: float, *, scale: float, steps: int = 72
) -> list[list[float]]:
    angles = np.linspace(0.0, 2.0 * np.pi, steps, endpoint=False)
    theta = np.deg2rad(float(azimuth_deg))
    # 长轴方位角自北顺时针；短轴与长轴垂直。
    de = float(a) * np.cos(angles) * np.sin(theta) + float(b) * np.sin(angles) * np.cos(theta)
    dn = float(a) * np.cos(angles) * np.cos(theta) - float(b) * np.sin(angles) * np.sin(theta)
    return [
        [round(float(E + scale * x), 3), round(float(N + scale * y), 3)]
        for x, y in zip(de, dn)
    ]


def build_point_geojson(project: dict) -> dict:
    features = []
    for point in project.get("points", []):
        ellipse = point.get("ellipse_95") or {}
        features.append(
            {
                "type": "Feature",
                "geometry": {
                    "type": "Point",
                    "coordinates": [float(point["E"]), float(point["N"])],
                },
                "properties": {
                    "layer": "points",
                    "name": point["name"],
                    "fixed": bool(point.get("fixed", False)),
                    "role": "fixed" if point.get("fixed") else "unknown",
                    "elevation_m": float(point.get("elevation_m", float("nan"))),
                    "lon": float(point.get("lon", float("nan"))),
                    "lat": float(point.get("lat", float("nan"))),
                    "E": float(point["E"]),
                    "N": float(point["N"]),
                    "sigma_E_mm": float(point.get("sigma_E_mm", 0.0)),
                    "sigma_N_mm": float(point.get("sigma_N_mm", 0.0)),
                    "mp_mm": float(point.get("mp_mm", 0.0)),
                    "ellipse_a_mm": float(ellipse.get("a_m", 0.0) * 1000.0),
                    "ellipse_b_mm": float(ellipse.get("b_m", 0.0) * 1000.0),
                    "ellipse_azimuth_deg": float(ellipse.get("azimuth_deg", 0.0)),
                },
            }
        )
    return {
        "type": "FeatureCollection",
        "name": "points",
        "crs": {"type": "name", "properties": {"name": project.get("dem", {}).get("crs", "EPSG:32650")}},
        "features": features,
    }


def build_observation_geojson(project: dict) -> dict:
    points = {p["name"]: p for p in project.get("points", [])}
    features = []
    for item in project.get("visibility", []):
        a = points.get(item.get("from"))
        b = points.get(item.get("to"))
        if a is None or b is None:
            continue
        features.append(
            {
                "type": "Feature",
                "geometry": {
                    "type": "LineString",
                    "coordinates": [
                        [float(a["E"]), float(a["N"])],
                        [float(b["E"]), float(b["N"])],
                    ],
                },
                "properties": {
                    "layer": "observations",
                    "from": item.get("from"),
                    "to": item.get("to"),
                    "status": item.get("status"),
                    "visible": bool(item.get("visible", False)),
                    "distance_m": float(item.get("distance_m", 0.0)),
                    "min_clearance_m": (
                        None
                        if item.get("min_clearance_m") is None
                        else float(item.get("min_clearance_m"))
                    ),
                    "min_distance_m": (
                        None
                        if item.get("min_distance_m") is None
                        else float(item.get("min_distance_m"))
                    ),
                    "obstruction": item.get("obstruction"),
                    "samples": int(item.get("samples", 0)),
                    "nodata_count": int(item.get("nodata_count", 0)),
                    "color": "#1a9850" if item.get("visible") else "#d73027",
                },
            }
        )
    return {
        "type": "FeatureCollection",
        "name": "observations",
        "crs": {"type": "name", "properties": {"name": project.get("dem", {}).get("crs", "EPSG:32650")}},
        "features": features,
    }


def build_ellipse_geojson(project: dict) -> dict:
    analysis = project.get("analysis", {})
    scale = float(analysis.get("ellipse_scale", 50000.0))
    confidence = float(analysis.get("confidence", 0.95))
    features = []
    for point in project.get("points", []):
        ellipse = point.get("ellipse_95") or {}
        a = float(ellipse.get("a_m", 0.0))
        b = float(ellipse.get("b_m", 0.0))
        if a <= 0.0 or b <= 0.0:
            continue
        polygon = _ellipse_polygon(
            float(point["E"]),
            float(point["N"]),
            a,
            b,
            float(ellipse.get("azimuth_deg", 0.0)),
            scale=scale,
        )
        features.append(
            {
                "type": "Feature",
                "geometry": {"type": "Polygon", "coordinates": [polygon + [polygon[0]]]},
                "properties": {
                    "layer": "ellipses",
                    "name": point["name"],
                    "a_m": a,
                    "b_m": b,
                    "a_mm": round(a * 1000.0, 3),
                    "b_mm": round(b * 1000.0, 3),
                    "azimuth_deg": float(ellipse.get("azimuth_deg", 0.0)),
                    "confidence": confidence,
                    "scale": scale,
                },
            }
        )
    return {
        "type": "FeatureCollection",
        "name": "ellipses",
        "crs": {"type": "name", "properties": {"name": project.get("dem", {}).get("crs", "EPSG:32650")}},
        "features": features,
    }


def build_layers(project: dict, dem: DEM, *, contour_interval: float = 50.0) -> dict:
    left, bottom, right, top = dem.bounds
    return {
        "crs": project.get("dem", {}).get("crs", "EPSG:32650"),
        "bounds_native": [left, bottom, right, top],
        "layers": [
            {
                "id": "hillshade",
                "title": "DEM 晕渲 + 分层设色",
                "kind": "raster",
                "url": "/api/overlay/hillshade.png",
                "bounds": [[bottom, left], [top, right]],
                "opacity": 0.92,
                "count": 1,
                "attribution": project.get("dem", {}).get("source", ""),
            },
            {
                "id": "contours",
                "title": f"等高线（{contour_interval:g} m）",
                "kind": "geojson",
                "geojson": build_contours_geojson(dem, interval=contour_interval),
            },
            {
                "id": "observations",
                "title": "观测线（通视 / 遮挡）",
                "kind": "geojson",
                "geojson": build_observation_geojson(project),
            },
            {
                "id": "ellipses",
                "title": "95% 误差椭圆（放大）",
                "kind": "geojson",
                "geojson": build_ellipse_geojson(project),
            },
            {
                "id": "points",
                "title": "控制点（固定 / 待定）",
                "kind": "geojson",
                "geojson": build_point_geojson(project),
            },
        ],
    }


def rectify_image(
    image_path: str,
    transform: AffineTransform,
    *,
    max_dimension: int = 1000,
) -> tuple[bytes, list[list[float]], tuple[int, int]]:
    """按配准参数把扫描影像重采样到 E/N 正北向的 RGBA PNG。

    返回 ``(png_bytes, [[bottom,left],[top,right]], (width,height))``。
    """
    with Image.open(image_path) as opened:
        source = opened.convert("RGBA")
        src = np.asarray(source, dtype=np.float32) / 255.0
    height, width = src.shape[:2]

    corners = [
        transform.xy(0.0, 0.0),
        transform.xy(float(width), 0.0),
        transform.xy(float(width), float(height)),
        transform.xy(0.0, float(height)),
    ]
    es = [p[0] for p in corners]
    ns = [p[1] for p in corners]
    left, right = min(es), max(es)
    bottom, top = min(ns), max(ns)

    span_e = max(right - left, 1e-9)
    span_n = max(top - bottom, 1e-9)
    if span_e >= span_n:
        out_w = max_dimension
        out_h = max(2, int(round(max_dimension * span_n / span_e)))
    else:
        out_h = max_dimension
        out_w = max(2, int(round(max_dimension * span_e / span_n)))

    oc = np.arange(out_w, dtype=float) + 0.5
    orow = np.arange(out_h, dtype=float) + 0.5
    E = left + oc * span_e / out_w
    N = top - orow * span_n / out_h
    EE, NN = np.meshgrid(E, N)

    inv = transform.inverse()
    col = inv.a * EE + inv.b * NN + inv.c
    row = inv.d * EE + inv.e * NN + inv.f
    u = col - 0.5
    v = row - 0.5
    valid = (u >= 0.0) & (u <= width - 1) & (v >= 0.0) & (v <= height - 1)

    u_safe = np.clip(u, 0.0, width - 1)
    v_safe = np.clip(v, 0.0, height - 1)
    c0 = np.floor(u_safe).astype(int)
    r0 = np.floor(v_safe).astype(int)
    c1 = np.minimum(c0 + 1, width - 1)
    r1 = np.minimum(r0 + 1, height - 1)
    fx = (u_safe - c0)[..., None]
    fy = (v_safe - r0)[..., None]

    out = (
        src[r0, c0] * (1.0 - fx) * (1.0 - fy)
        + src[r0, c1] * fx * (1.0 - fy)
        + src[r1, c0] * (1.0 - fx) * fy
        + src[r1, c1] * fx * fy
    )
    out[..., 3] *= valid.astype(np.float32)
    rgba = np.clip(out * 255.0 + 0.5, 0, 255).astype(np.uint8)
    image = Image.fromarray(rgba, mode="RGBA")
    buffer = io.BytesIO()
    image.save(buffer, format="PNG", optimize=True)
    return buffer.getvalue(), [[bottom, left], [top, right]], (out_w, out_h)


__all__ = [
    "build_contours_geojson",
    "build_ellipse_geojson",
    "build_layers",
    "build_observation_geojson",
    "build_point_geojson",
    "hillshade_rgb",
    "rectify_image",
    "render_hillshade_png",
]
