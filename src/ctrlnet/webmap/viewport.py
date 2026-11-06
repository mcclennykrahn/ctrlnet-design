"""Bounded terrain rendering in native project coordinates; no external services."""
from collections import OrderedDict
from hashlib import sha256
from math import ceil, isfinite
from threading import RLock
import json

import numpy as np

from ..terrain import DEM, AffineTransform
from .render import build_contours_geojson, render_hillshade_png


def parse_view(bbox: str, zoom: float):
    try:
        bounds = tuple(float(v) for v in bbox.split(','))
    except ValueError:
        raise ValueError('bbox must be west,south,east,north in native coordinates')
    if (len(bounds) != 4 or not all(isfinite(v) for v in bounds)
            or bounds[0] >= bounds[2] or bounds[1] >= bounds[3]):
        raise ValueError('bbox must contain four finite, ordered native coordinates')
    if not isfinite(zoom) or not -10 <= zoom <= 12:
        raise ValueError('zoom must be finite and between -10 and 12 (Leaflet CRS.Simple)')
    return bounds, zoom


class ViewportTerrain:
    """32-entry LRU of rendered responses, serialized under a Matplotlib-safe lock.

    Sampling is bounded to 256x256 cells per request, independently of DEM size.
    Source DEM is immutable for the lifetime of the application.
    """
    def __init__(self, dem):
        self.dem = dem
        self.cache = OrderedDict()
        self.lock = RLock()

    def render(self, bbox, zoom, kind='contours'):
        bounds, zoom = parse_view(bbox, zoom)
        key = (bounds, zoom, kind)
        with self.lock:
            if key in self.cache:
                self.cache.move_to_end(key)
                return (*self.cache[key], True)
            w, s, e, n = bounds
            dw, ds, de, dn = self.dem.bounds
            w, s, e, n = max(w, dw), max(s, ds), min(e, de), min(n, dn)
            features = []
            spacing = max(self.dem.transform.xres, self.dem.transform.yres, 2 ** (-zoom) * 2)
            interval = max(50., 50. * 2 ** max(0, ceil(-zoom - 2)))
            if w < e and s < n:
                spacing = max(spacing, (e-w)/255, (n-s)/255)
                cols, rows = max(2, ceil((e-w)/spacing)), max(2, ceil((n-s)/spacing))
                dx, dy = (e-w)/cols, (n-s)/rows
                x, y = np.meshgrid(w + (np.arange(cols)+.5)*dx, n - (np.arange(rows)+.5)*dy)
                values = self.dem.elevation(x, y)
                local = DEM(values, AffineTransform.from_origin(w, n, dx, dy))
                if kind == 'hillshade' and local.valid_mask.any():
                    body = render_hillshade_png(local, scale=1)
                elif kind == 'contours':
                    features = build_contours_geojson(local, interval=interval)['features']
            if kind == 'hillshade' and (w >= e or s >= n or not local.valid_mask.any()):
                # Transparent pixel for viewports outside the DEM.
                import io
                from PIL import Image
                output = io.BytesIO()
                Image.new('RGBA', (1, 1)).save(output, format='PNG')
                body = output.getvalue()
            if kind == 'contours':
                payload = {'type': 'FeatureCollection', 'features': features, 'view': {
                    'bbox': list(bounds), 'zoom': zoom, 'sample_spacing_m': spacing,
                    'interval_m': interval, 'feature_count': len(features),
                    'vertex_count': sum(len(f['geometry']['coordinates']) for f in features),
                    'max_grid_size': 256, 'detail': 'resampled DEM; 50 m minimum interval'}}
                body = json.dumps(payload, separators=(',', ':'), allow_nan=False).encode()
            etag = '"' + sha256(body).hexdigest() + '"'
            self.cache[key] = (body, etag)
            if len(self.cache) > 32:
                self.cache.popitem(last=False)
            return body, etag, False
