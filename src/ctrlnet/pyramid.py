"""Lazy display-only tiled GeoTIFF levels built with GDAL average resampling."""
from hashlib import sha256
from math import ceil, isfinite
from pathlib import Path
import os
import tempfile

import numpy as np


def display_elevation(dem, E, N, spacing):
    if not isfinite(spacing) or spacing <= 0:
        raise ValueError('spacing must be positive and finite')
    factor = 1
    ratio = spacing / max(dem.resolution) / 2
    while factor * 2 <= ratio and min(dem.shape) / (factor * 2) >= 2:
        factor *= 2
    if factor == 1 or dem.pyramid_dir is None:
        return dem.elevation(E, N)
    from .terrain import WindowedDEM
    with dem._tile_lock:
        if factor not in dem._levels:
            path = build_level(dem, factor)
            dem._levels.clear()  # retain only one bounded level LRU
            dem._levels[factor] = WindowedDEM(path, tile_size=dem.tile_size,
                cache_size=dem.cache_size, pyramid_dir=None)
        level = dem._levels[factor]
    inv = dem.transform.inverse()
    E, N = np.broadcast_arrays(np.asarray(E, dtype=float), np.asarray(N, dtype=float))
    c = inv.a*E + inv.b*N + inv.c
    r = inv.d*E + inv.e*N + inv.f
    inside = (c >= .5) & (c <= dem.width-.5) & (r >= .5) & (r <= dem.height-.5)
    # Extend coarse edge centers only inside the native center domain.
    c = np.clip(c * level.width/dem.width, .5, level.width-.5)
    r = np.clip(r * level.height/dem.height, .5, level.height-.5)
    x = level.transform.a*c + level.transform.b*r + level.transform.c
    y = level.transform.d*c + level.transform.e*r + level.transform.f
    result = np.where(inside, level.elevation(x, y), np.nan)
    return float(result) if result.ndim == 0 else result


def build_level(dem, factor):
    """Atomic publication; concurrent builders can duplicate work, never partial files."""
    import rasterio
    from rasterio.enums import Resampling
    from rasterio.windows import Window
    from affine import Affine
    stat = Path(dem.path).stat()
    identity = repr((dem.path, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns,
                     'average-f64-v1', factor)).encode()
    directory = Path(dem.pyramid_dir)
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / (sha256(identity).hexdigest() + '.tif')
    if target.exists():
        return target
    width, height = ceil(dem.width/factor), ceil(dem.height/factor)
    fd, temporary = tempfile.mkstemp(suffix='.tif', dir=directory)
    os.close(fd)
    try:
        with rasterio.Env(GDAL_CACHEMAX=8 * 1024 * 1024):
            with rasterio.open(dem.path) as src:
                transform = src.transform * Affine.scale(dem.width/width, dem.height/height)
                with rasterio.open(temporary, 'w', driver='GTiff', width=width,
                        height=height, count=1, dtype='float64', nodata=np.nan,
                        crs=src.crs, transform=transform, tiled=True,
                        blockxsize=256, blockysize=256, compress='deflate') as dst:
                    for _, window in dst.block_windows(1):
                        source_window = Window(window.col_off*dem.width/width,
                            window.row_off*dem.height/height,
                            window.width*dem.width/width, window.height*dem.height/height)
                        values = src.read(1, window=source_window,
                            out_shape=(int(window.height), int(window.width)),
                            out_dtype='float64', masked=True,
                            resampling=Resampling.average).filled(np.nan)
                        values[~np.isfinite(values)] = np.nan
                        dst.write(values, 1, window=window)
        os.replace(temporary, target)
        dem.pyramid_builds += 1
    finally:
        Path(temporary).unlink(missing_ok=True)
    return target
