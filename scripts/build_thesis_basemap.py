#!/usr/bin/env python3
"""生成论文示例区域（徐州）的离线浅色 DEM 底图。

流程（只在本机进行，运行时不访问网络）：

1. 用 ``scripts/fetch_dem.py`` 的下载函数获取 Copernicus GLO-30 ``N34 E117``
   原始瓦片，缓存到 ``data/cache/``（已 gitignore）；
2. 裁剪 ``117.10–117.30°E, 34.15–34.25°N``；
3. 渲染浅色分层设色 + 晕渲 + 10 m 等高线，输出
   ``data/sample/thesis_basemap.png``（≤3 MB）和同名 JSON 元数据。

用法::

    .venv/bin/python scripts/build_thesis_basemap.py
    .venv/bin/python scripts/build_thesis_basemap.py --force
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Tuple

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))

from fetch_dem import download  # noqa: E402  (同目录脚本)

TILE_NAME = "Copernicus_DSM_COG_10_N34_00_E117_00_DEM"
SOURCE_URL = (
    "https://copernicus-dem-30m.s3.amazonaws.com/"
    f"{TILE_NAME}/{TILE_NAME}.tif"
)
CACHE_DIR = ROOT / "data" / "cache"
SAMPLE_DIR = ROOT / "data" / "sample"
CACHE_TILE = CACHE_DIR / f"{TILE_NAME}.tif"
CROP_TIF = CACHE_DIR / "xuzhou_thesis_dem_crop.tif"
OUT_PNG = SAMPLE_DIR / "thesis_basemap.png"
OUT_JSON = SAMPLE_DIR / "thesis_basemap.json"

BOUNDS: Tuple[float, float, float, float] = (117.10, 34.15, 117.30, 34.25)
CONTOUR_INTERVAL = 10.0
INDEX_INTERVAL = 50.0
MAX_PNG_BYTES = 3 * 1024 * 1024
IMAGE_WIDTH = 1800
IMAGE_HEIGHT = 900


def _fill_nodata(z, valid):
    import numpy as np
    from scipy import ndimage

    if valid.all():
        return z
    if not valid.any():
        raise ValueError("裁剪窗口内没有有效 DEM 像元")
    if not np.isfinite(z[valid]).all():
        z = np.where(np.isfinite(z), z, np.nan)
        valid = np.isfinite(z)
    indices = ndimage.distance_transform_edt(
        ~valid, return_distances=False, return_indices=True
    )
    filled = np.asarray(z)[tuple(indices)]
    return filled


def _shade(z, lat_mean: float, dlon: float, dlat: float):
    import numpy as np

    xres = 111320.0 * math.cos(math.radians(lat_mean)) * dlon
    yres = 110574.0 * dlat
    dz_drow, dz_dcol = np.gradient(np.asarray(z, dtype=float), yres, xres)
    # 行号向南增加，故北向梯度取负；x 东、y 北、z 上。
    dz_dnorth = -dz_drow
    dz_deast = dz_dcol
    normal = np.dstack((-dz_deast, -dz_dnorth, np.ones_like(z)))
    normal /= np.linalg.norm(normal, axis=2, keepdims=True)
    azimuth = math.radians(315.0)
    altitude = math.radians(42.0)
    light = np.array(
        [
            math.cos(altitude) * math.sin(azimuth),
            math.cos(altitude) * math.cos(azimuth),
            math.sin(altitude),
        ]
    )
    shade = np.clip(normal @ light, 0.0, 1.0)
    return shade


def _pale_color(z, valid):
    import numpy as np

    stops = np.array([0.0, 0.22, 0.45, 0.68, 0.86, 1.0])
    colors = np.array(
        [
            [0.976, 0.980, 0.960],  # 近白
            [0.945, 0.960, 0.920],  # 极淡草绿
            [0.912, 0.938, 0.875],
            [0.894, 0.918, 0.842],
            [0.902, 0.898, 0.824],  # 淡米色
            [0.922, 0.910, 0.846],
        ]
    )
    low = float(np.percentile(z[valid], 2.0))
    high = float(np.percentile(z[valid], 98.0))
    t = np.clip((z - low) / max(high - low, 1e-9), 0.0, 1.0)
    rgb = np.empty(z.shape + (3,), dtype=float)
    for channel in range(3):
        rgb[..., channel] = np.interp(t, stops, colors[:, channel])
    return rgb


def render_crop(crop_path: Path = CROP_TIF, *, force: bool = False) -> Dict[str, Any]:
    import numpy as np
    import rasterio
    from rasterio.windows import Window, from_bounds

    if not CACHE_TILE.exists() or force:
        download(SOURCE_URL, CACHE_TILE, force=force)

    with rasterio.open(CACHE_TILE) as src:
        window = from_bounds(*BOUNDS, transform=src.transform)
        window = window.round_offsets().round_lengths()
        window = window.intersection(Window(0, 0, src.width, src.height))
        if window.width < 2 or window.height < 2:
            raise ValueError("裁剪窗口为空；请检查 BOUNDS 是否位于瓦片内")
        data = src.read(1, window=window)
        transform = src.window_transform(window)
        nodata = src.nodata
        crs = src.crs
        source_tags = {str(k): str(v) for k, v in src.tags().items()}

    z = np.asarray(data, dtype=float)
    valid = np.ones(z.shape, dtype=bool)
    if nodata is not None:
        valid &= z != float(nodata)
    valid &= np.isfinite(z)
    z = _fill_nodata(np.where(valid, z, np.nan), valid)
    valid = np.isfinite(z)
    if not valid.any():
        raise ValueError("裁剪窗口没有有效高程")

    left, bottom, right, top = BOUNDS
    dlon = (right - left) / z.shape[1]
    dlat = (top - bottom) / z.shape[0]
    with rasterio.open(
        crop_path,
        "w",
        driver="GTiff",
        height=z.shape[0],
        width=z.shape[1],
        count=1,
        dtype="float32",
        crs=crs,
        transform=transform,
        nodata=float(nodata) if nodata is not None else -9999.0,
        compress="DEFLATE",
        predictor=3,
    ) as dst:
        dst.write(z.astype("float32"), 1)
        dst.update_tags(**source_tags)

    return {
        "z": z,
        "valid": valid,
        "shape": list(z.shape),
        "transform": transform,
        "crs": str(crs),
        "source_tags": source_tags,
        "dlon": dlon,
        "dlat": dlat,
        "crop_path": crop_path,
    }


def render_png(crop: Dict[str, Any], *, force: bool = False) -> Path:
    import matplotlib

    matplotlib.use("Agg", force=False)
    import matplotlib.pyplot as plt
    import numpy as np

    z = crop["z"]
    valid = crop["valid"]
    shade = _shade(z, (BOUNDS[1] + BOUNDS[3]) / 2.0, crop["dlon"], crop["dlat"])
    rgb = _pale_color(z, valid)
    brightness = 0.935 + 0.105 * shade
    rgb = np.clip(rgb * brightness[..., None], 0.0, 1.0)

    left, bottom, right, top = BOUNDS
    width, height = IMAGE_WIDTH, IMAGE_HEIGHT
    dpi = 200
    fig = plt.figure(figsize=(width / dpi, height / dpi), dpi=dpi, facecolor="white")
    ax = fig.add_axes([0.0, 0.0, 1.0, 1.0])
    ax.set_facecolor("white")
    ax.imshow(
        rgb,
        extent=(left, right, bottom, top),
        origin="upper",
        interpolation="bilinear",
        zorder=0,
    )

    lons = left + (np.arange(z.shape[1]) + 0.5) * crop["dlon"]
    lats = top - (np.arange(z.shape[0]) + 0.5) * crop["dlat"]
    lon_grid, lat_grid = np.meshgrid(lons, lats)
    lo = math.floor(float(np.nanmin(z[valid])) / CONTOUR_INTERVAL) * CONTOUR_INTERVAL
    hi = float(np.nanmax(z[valid]))
    levels = np.arange(lo, hi + CONTOUR_INTERVAL * 0.5, CONTOUR_INTERVAL)
    if levels.size >= 2:
        ax.contour(
            lon_grid,
            lat_grid,
            z,
            levels=levels,
            colors="#a8b39c",
            linewidths=0.35,
            alpha=0.55,
            zorder=2,
        )
        index_levels = [
            level for level in levels if abs(level % INDEX_INTERVAL) < 1e-9
        ]
        if len(index_levels) >= 2:
            ax.contour(
                lon_grid,
                lat_grid,
                z,
                levels=index_levels,
                colors="#8d9a82",
                linewidths=0.7,
                alpha=0.62,
                zorder=3,
            )

    ax.set_xlim(left, right)
    ax.set_ylim(bottom, top)
    ax.set_axis_off()
    ax.margins(0.0)
    OUT_PNG.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(
        OUT_PNG,
        dpi=dpi,
        facecolor="white",
        edgecolor="none",
        bbox_inches=None,
        pad_inches=0.0,
    )
    plt.close(fig)
    size = OUT_PNG.stat().st_size
    if size > MAX_PNG_BYTES:
        raise RuntimeError(f"底图 PNG 超过 3 MB：{size} bytes")
    return OUT_PNG


def write_metadata(crop: Dict[str, Any]) -> Path:
    import numpy as np

    z = crop["z"]
    valid = crop["valid"]
    payload = {
        "schema": "ctrlnet.thesis.basemap/1",
        "name": "徐州论文示例区域离线底图",
        "offline": True,
        "online_tiles": False,
        "source": "Copernicus GLO-30 DEM",
        "source_tile": TILE_NAME,
        "source_url": SOURCE_URL,
        "source_crs": crop["crs"],
        "bounds": list(BOUNDS),
        "image": {
            "path": OUT_PNG.name,
            "width": IMAGE_WIDTH,
            "height": IMAGE_HEIGHT,
            "attribution": "Copernicus DEM © ESA / 本地离线渲染",
        },
        "elevation_m": {
            "min": round(float(np.nanmin(z[valid])), 3),
            "max": round(float(np.nanmax(z[valid])), 3),
            "mean": round(float(np.nanmean(z[valid])), 3),
        },
        "contour_interval_m": CONTOUR_INTERVAL,
        "index_contour_interval_m": INDEX_INTERVAL,
        "style": "浅色分层设色 + 315°/42° 晕渲 + 等高线",
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "crop_tif_cache": str(crop["crop_path"].relative_to(ROOT)),
        "note": "原始瓦片只放 data/cache/，仓库仅提交本 PNG 与 JSON；运行时不访问网络。",
    }
    OUT_JSON.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return OUT_JSON


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="生成徐州论文区域离线 DEM 底图")
    parser.add_argument("--force", action="store_true", help="强制重新下载/渲染")
    args = parser.parse_args(argv)
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    SAMPLE_DIR.mkdir(parents=True, exist_ok=True)
    crop = render_crop(force=args.force)
    png = render_png(crop, force=args.force)
    meta = write_metadata(crop)
    print(f"[basemap] {png} ({png.stat().st_size / 1024:.1f} KiB)")
    print(f"[basemap] {meta}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
