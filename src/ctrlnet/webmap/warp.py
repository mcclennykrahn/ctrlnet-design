"""有界的地理配准影像 → WebMercator 重采样；缓存归属于工程服务实例。"""
import io
import numpy as np
from PIL import Image
from rasterio.transform import from_bounds
from rasterio.warp import calculate_default_transform, reproject, Resampling, transform_bounds


def warp_png(content, bounds, crs, limit=1536):
    image = Image.open(io.BytesIO(content)).convert('RGBA')
    image.thumbnail((limit, limit), Image.Resampling.BILINEAR)
    src = np.asarray(image)
    h, w = src.shape[:2]
    affine, width, height = calculate_default_transform(crs, 'EPSG:3857', w, h, *bounds)
    ratio = min(1, limit / max(width, height))
    width, height = max(1, round(width * ratio)), max(1, round(height * ratio))
    west, south, east, north = transform_bounds(crs, 'EPSG:3857', *bounds, densify_pts=41)
    target = from_bounds(west, south, east, north, width, height)
    dst = np.zeros((height, width, 4), dtype=np.uint8)
    for band in range(4):
        reproject(src[:,:,band], dst[:,:,band], src_transform=from_bounds(*bounds, w, h),
                  src_crs=crs, dst_transform=target, dst_crs='EPSG:3857',
                  resampling=Resampling.bilinear)
    output = io.BytesIO()
    Image.fromarray(dst).save(output, format='PNG')
    b = transform_bounds('EPSG:3857', 'EPSG:4326', west, south, east, north)
    return output.getvalue(), [[b[1], b[0]], [b[3], b[2]]]
