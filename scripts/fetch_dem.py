#!/usr/bin/env python3
"""下载并裁剪 Copernicus GLO-30 DEM 小样本。

默认下载北京西山瓦片 ``N39_00_E116_00``（约 50 MB），从公开 AWS S3 读取，
无需登录；原始文件保存在 ``data/cache/``（已 gitignore），裁剪后重投影到
UTM 50N 的小样本写入 ``data/sample/dem_sample.tif``（仓库交付，≤2 MB）。

用法::

    .venv/bin/python scripts/fetch_dem.py
    .venv/bin/python scripts/fetch_dem.py --force
    .venv/bin/python scripts/fetch_dem.py \
        --bounds 116.00 39.90 116.10 40.00 --output data/sample/dem_sample.tif

依赖：``pip install -e ".[terrain]"``（rasterio）。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Tuple

try:
    ROOT = Path(__file__).resolve().parents[1]
except NameError:  # pragma: no cover - notebook
    ROOT = Path.cwd()

DEFAULT_URL = (
    "https://copernicus-dem-30m.s3.amazonaws.com/"
    "Copernicus_DSM_COG_10_N39_00_E116_00_DEM/"
    "Copernicus_DSM_COG_10_N39_00_E116_00_DEM.tif"
)
# 北京西山：海拔约 90–990 m，包含山脊、沟谷和城区边缘，适合通视演示。
DEFAULT_BOUNDS = (116.00, 39.90, 116.10, 40.00)
DEFAULT_CRS = "EPSG:32650"  # UTM zone 50N，覆盖 114°E–120°E / 北半球
DEFAULT_RESOLUTION = 30.0
DEFAULT_NODATA = -9999.0
MAX_SAMPLE_BYTES = 2 * 1024 * 1024


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _human_bytes(size: int) -> str:
    value = float(size)
    for unit in ("B", "KiB", "MiB", "GiB"):
        if value < 1024.0 or unit == "GiB":
            return f"{value:.2f} {unit}"
        value /= 1024.0
    return f"{value:.2f} GiB"


def download(
    url: str,
    destination: Path,
    *,
    force: bool = False,
    timeout: float = 120.0,
) -> Path:
    """流式下载 URL 到 ``destination``，已存在且非空时跳过。"""
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists() and destination.stat().st_size > 0 and not force:
        print(f"[cache] 已存在，跳过下载：{destination} ({_human_bytes(destination.stat().st_size)})")
        return destination

    print(f"[download] {url}")
    request = urllib.request.Request(
        url, headers={"User-Agent": "ctrlnet-dem-fetch/1.0 (+terrain demo)"}
    )
    tmp = destination.with_suffix(destination.suffix + ".part")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            total = int(response.headers.get("Content-Length") or 0)
            with tmp.open("wb") as fh:
                received = 0
                while True:
                    chunk = response.read(1024 * 1024)
                    if not chunk:
                        break
                    fh.write(chunk)
                    received += len(chunk)
                    if total:
                        pct = 100.0 * received / total
                        print(
                            f"\r  {_human_bytes(received)} / {_human_bytes(total)} "
                            f"({pct:5.1f}%)",
                            end="",
                            flush=True,
                        )
            print()
        if total and tmp.stat().st_size != total:
            raise IOError(
                f"下载不完整：期望 {total} 字节，实际 {tmp.stat().st_size} 字节"
            )
        os.replace(tmp, destination)
    finally:
        if tmp.exists():
            tmp.unlink()
    print(f"[download] 完成：{destination} ({_human_bytes(destination.stat().st_size)})")
    return destination


def crop_and_reproject(
    source: Path,
    output: Path,
    bounds: Tuple[float, float, float, float],
    *,
    target_crs: str = DEFAULT_CRS,
    resolution: float = DEFAULT_RESOLUTION,
    nodata: float = DEFAULT_NODATA,
    source_url: str | None = None,
) -> dict:
    """裁剪 ``bounds``（源 CRS 经纬度）并重投影为米制 UTM GeoTIFF。"""
    try:
        import numpy as np
        import rasterio
        from rasterio.crs import CRS
        from rasterio.enums import Resampling
        from rasterio.transform import array_bounds
        from rasterio.warp import calculate_default_transform, reproject, transform_bounds
        from rasterio.windows import Window, from_bounds
    except ImportError as exc:  # pragma: no cover - 依赖未安装
        raise SystemExit(
            "缺少 rasterio。请先运行：.venv/bin/pip install -e '.[terrain]'"
        ) from exc

    left, bottom, right, top = (float(v) for v in bounds)
    if not (right > left and top > bottom):
        raise ValueError("bounds 必须是 (left, bottom, right, top) 且 right>left、top>bottom")

    with rasterio.open(source) as src:
        if src.crs is None:
            raise ValueError("源 DEM 缺少 CRS")
        if src.count < 1:
            raise ValueError("源 DEM 没有波段")
        window = from_bounds(left, bottom, right, top, transform=src.transform)
        window = window.round_offsets().round_lengths()
        window = window.intersection(Window(0, 0, src.width, src.height))
        if window.width < 2 or window.height < 2:
            raise ValueError("裁剪窗口为空；请检查 --bounds 是否位于瓦片内")
        data = src.read(1, window=window)
        src_transform = src.window_transform(window)
        src_nodata = src.nodata
        source_crs = src.crs
        source_tags = {str(k): str(v) for k, v in src.tags().items()}
        src_left, src_bottom, src_right, src_top = array_bounds(
            data.shape[0], data.shape[1], src_transform
        )

    dst_crs = CRS.from_user_input(target_crs)
    dst_transform, dst_width, dst_height = calculate_default_transform(
        source_crs,
        dst_crs,
        data.shape[1],
        data.shape[0],
        src_left,
        src_bottom,
        src_right,
        src_top,
        resolution=float(resolution),
    )
    destination = np.full((dst_height, dst_width), nodata, dtype="float32")
    reproject(
        source=data,
        destination=destination,
        src_transform=src_transform,
        src_crs=source_crs,
        src_nodata=src_nodata,
        dst_transform=dst_transform,
        dst_crs=dst_crs,
        dst_nodata=nodata,
        resampling=Resampling.bilinear,
        num_threads=2,
    )
    invalid = ~np.isfinite(destination) | (destination <= -1000.0)
    destination[invalid] = nodata

    output.parent.mkdir(parents=True, exist_ok=True)
    profile = {
        "driver": "GTiff",
        "height": dst_height,
        "width": dst_width,
        "count": 1,
        "dtype": "float32",
        "crs": dst_crs,
        "transform": dst_transform,
        "nodata": nodata,
        "compress": "deflate",
        "predictor": 3,
        "tiled": True,
        "blockxsize": 256,
        "blockysize": 256,
        "BIGTIFF": "NO",
    }
    tags = {
        "AREA_OR_POINT": "Area",
        "DEM_SOURCE": "Copernicus GLO-30 DSM (AWS Open Data)",
        "VERTICAL_DATUM": "EGM2008 orthometric height",
        "SURFACE_TYPE": "DSM",
        "SOURCE_CRS": str(source_crs),
        "PROCESSING": "crop + bilinear reprojection to local UTM",
        "UNITS": "metre",
        "LICENSE": "Copernicus DEM (c) ESA; free use with attribution",
        "CREATED_UTC": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    with rasterio.open(output, "w", **profile) as dst:
        dst.write(destination, 1)
        dst.update_tags(**tags)

    valid = destination != nodata
    if not valid.any():
        raise ValueError("裁剪结果全部为 NoData")
    values = destination[valid]
    dst_bounds = array_bounds(dst_height, dst_width, dst_transform)
    lonlat_bounds = transform_bounds(dst_crs, CRS.from_epsg(4326), *dst_bounds)
    size_bytes = output.stat().st_size
    metadata = {
        "path": str(output.relative_to(ROOT)) if output.is_relative_to(ROOT) else str(output),
        "source_url": source_url or DEFAULT_URL,
        "source_cache": str(source.relative_to(ROOT)) if source.is_relative_to(ROOT) else str(source),
        "source_tile": source.stem,
        "source_crs": str(source_crs),
        "target_crs": str(dst_crs),
        "bounds_wgs84": [float(v) for v in bounds],
        "output_bounds_lonlat": [float(v) for v in lonlat_bounds],
        "output_bounds_native": [float(v) for v in dst_bounds],
        "width": int(dst_width),
        "height": int(dst_height),
        "resolution_m": [abs(float(dst_transform.a)), abs(float(dst_transform.e))],
        "nodata": float(nodata),
        "elevation_min_m": float(values.min()),
        "elevation_max_m": float(values.max()),
        "elevation_mean_m": float(values.mean()),
        "valid_pixels": int(valid.sum()),
        "total_pixels": int(destination.size),
        "nodata_fraction": float(1.0 - valid.sum() / destination.size),
        "vertical_datum": "EGM2008 orthometric height",
        "surface_type": "DSM",
        "source": "Copernicus GLO-30 DSM, AWS Open Data, (c) ESA",
        "license": "Free use with attribution to Copernicus DEM / ESA",
        "created_utc": tags["CREATED_UTC"],
        "size_bytes": int(size_bytes),
        "sha256": _sha256(output),
        "source_tags": source_tags,
    }
    sidecar = output.with_suffix(".json")
    sidecar.write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return metadata


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default=DEFAULT_URL, help="Copernicus DEM 瓦片 URL")
    parser.add_argument(
        "--cache",
        type=Path,
        default=ROOT / "data" / "cache",
        help="原始大文件缓存目录（gitignore）",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "data" / "sample" / "dem_sample.tif",
        help="裁剪后的交付 GeoTIFF（≤2 MB）",
    )
    parser.add_argument(
        "--bounds",
        nargs=4,
        type=float,
        metavar=("LEFT", "BOTTOM", "RIGHT", "TOP"),
        default=DEFAULT_BOUNDS,
        help="裁剪范围（源 CRS 经纬度，默认北京西山）",
    )
    parser.add_argument("--crs", default=DEFAULT_CRS, help="输出投影 CRS")
    parser.add_argument("--resolution", type=float, default=DEFAULT_RESOLUTION)
    parser.add_argument("--force", action="store_true", help="强制重新下载")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    source_name = Path(urllib.parse.urlparse(args.url).path).name or "copernicus_dem.tif"
    args.cache = Path(args.cache).resolve()
    args.output = Path(args.output).resolve()
    source = args.cache / source_name
    bounds = tuple(float(v) for v in args.bounds)
    print(f"[tile] {source.name}  bounds={bounds}  output_crs={args.crs}")
    download(args.url, source, force=args.force)
    metadata = crop_and_reproject(
        source,
        args.output,
        bounds,
        target_crs=args.crs,
        resolution=args.resolution,
        source_url=args.url,
    )
    print("[crop] 完成：")
    print(f"  输出        : {args.output}")
    print(
        f"  栅格        : {metadata['width']} x {metadata['height']} @ "
        f"{metadata['resolution_m'][0]:g} m"
    )
    print(f"  CRS         : {metadata['target_crs']}")
    print(
        f"  高程范围    : {metadata['elevation_min_m']:.1f} – "
        f"{metadata['elevation_max_m']:.1f} m (NoData {metadata['nodata_fraction']*100:.2f}%)"
    )
    print(f"  文件大小    : {_human_bytes(metadata['size_bytes'])}")
    print(f"  元数据      : {args.output.with_suffix('.json')}")
    if metadata["size_bytes"] > MAX_SAMPLE_BYTES:
        print(
            f"[error] 样本 {_human_bytes(metadata['size_bytes'])} 超过 2 MB 交付上限；"
            "请提高压缩率或减小裁剪范围。",
            file=sys.stderr,
        )
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
