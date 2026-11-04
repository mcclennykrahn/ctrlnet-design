#!/usr/bin/env python3
"""下载并裁剪 PROJ-data EGM96 15′ 格网，供 GNSS 高程异常比较使用。

数据源（公开、无需登录）：

    https://cdn.proj.org/us_nga_egm96_15.tif

完整格网约 2.7 MB，放入 ``data/cache/``（已 gitignore）；仓库只提交覆盖
北京西山演示区的裁剪小样本 ``data/sample/egm96_beijing.tif``（远小于 2 MB）。

运行::

    .venv/bin/python scripts/fetch_egm.py

依赖：``rasterio``（``pip install -e ".[terrain]"`` 或 ``".[test]"``）。
"""

from __future__ import annotations

import argparse
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CACHE_PATH = ROOT / "data" / "cache" / "us_nga_egm96_15.tif"
SAMPLE_PATH = ROOT / "data" / "sample" / "egm96_beijing.tif"
URL = "https://cdn.proj.org/us_nga_egm96_15.tif"

# 北京西山 DEM 演示区外扩约 0.5°，保留双线性插值余量。
CROP_BOUNDS = (115.125, 39.125, 117.125, 41.125)


def download(path: Path = CACHE_PATH, *, force: bool = False) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and not force:
        return path
    print(f"下载 {URL}\n  -> {path}")
    with urllib.request.urlopen(URL, timeout=60) as response, path.open("wb") as out:
        while True:
            chunk = response.read(1 << 20)
            if not chunk:
                break
            out.write(chunk)
    return path


def crop_sample(source: Path = CACHE_PATH, target: Path = SAMPLE_PATH) -> Path:
    try:
        import rasterio
        from rasterio.windows import Window
    except ImportError as exc:  # pragma: no cover
        raise SystemExit("需要 rasterio：.venv/bin/pip install -e '.[terrain]'") from exc
    target.parent.mkdir(parents=True, exist_ok=True)
    with rasterio.open(source) as src:
        window = rasterio.windows.from_bounds(*CROP_BOUNDS, transform=src.transform)
        window = Window(
            round(window.col_off),
            round(window.row_off),
            round(window.width),
            round(window.height),
        )
        data = src.read(1, window=window)
        transform = src.window_transform(window)
        profile = src.profile.copy()
    profile.update(
        driver="GTiff",
        height=data.shape[0],
        width=data.shape[1],
        transform=transform,
        count=1,
        compress="deflate",
        predictor=3,
        tiled=False,
    )
    with rasterio.open(target, "w", **profile) as dst:
        dst.write(data, 1)
    print(
        f"裁剪样本 {target}：{data.shape[1]}×{data.shape[0]}，"
        f"{target.stat().st_size / 1024:.1f} KB，范围 {CROP_BOUNDS}"
    )
    return target


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--force", action="store_true", help="强制重新下载完整格网")
    args = parser.parse_args(argv)
    source = download(force=args.force)
    crop_sample(source)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
