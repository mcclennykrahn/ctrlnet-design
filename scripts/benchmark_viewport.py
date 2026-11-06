"""Offline contour payload comparison. Run with .venv/bin/python scripts/benchmark_viewport.py."""
import json
import time
import numpy as np
from ctrlnet.terrain import DEM, AffineTransform
from ctrlnet.webmap.state import ProjectStore
from ctrlnet.webmap.render import build_contours_geojson
from ctrlnet.webmap.viewport import ViewportTerrain


def measure(name, dem):
    w,s,e,n = dem.bounds
    # Central quarter of the extent (1/16 area), zoom -2 in CRS.Simple.
    bbox = ','.join(map(str, (w+(e-w)*.375,s+(n-s)*.375,w+(e-w)*.625,s+(n-s)*.625)))
    start = time.perf_counter()
    legacy = build_contours_geojson(dem)
    old_ms = (time.perf_counter()-start)*1000
    old = json.dumps(legacy,separators=(',',':')).encode()
    service = ViewportTerrain(dem)
    start = time.perf_counter()
    body,_,_ = service.render(bbox,-2)
    cold_ms = (time.perf_counter()-start)*1000
    start = time.perf_counter()
    service.render(bbox,-2)
    warm_ms = (time.perf_counter()-start)*1000
    new = json.loads(body)
    print(json.dumps(dict(case=name, bbox=bbox, zoom=-2,
        before_bytes=len(old), after_bytes=len(body),
        before_features=len(legacy['features']), after_features=len(new['features']),
        before_vertices=sum(len(f['geometry']['coordinates']) for f in legacy['features']),
        after_vertices=new['view']['vertex_count'],
        before_ms=round(old_ms,2), cold_ms=round(cold_ms,2), warm_ms=round(warm_ms,3))))


if __name__ == '__main__':
    measure('sample DEM', DEM.from_geotiff(ProjectStore().dem_path))
    y,x = np.mgrid[:1200,:1200]
    measure('synthetic 1200x1200', DEM(300+180*np.sin(x/30)*np.cos(y/40),
        AffineTransform.from_origin(0,12000,10,10)))
