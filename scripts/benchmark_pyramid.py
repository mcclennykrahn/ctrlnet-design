"""Wide viewport benchmark: cold build and durable reuse, no OS cache eviction.

New DEM and ViewportTerrain per measurement bypass both application LRUs.
Native read_count counts application windows, not physical device I/O.
"""
import json
from pathlib import Path
import tempfile
from time import perf_counter

import numpy as np
from ctrlnet.terrain import WindowedDEM
from ctrlnet.webmap.viewport import ViewportTerrain
from benchmark_dem_memory import fixture


def measure(path, directory):
    # Warm plotting/font/contour initialization equally before timed requests.
    from ctrlnet.terrain import DEM, AffineTransform
    warm = ViewportTerrain(DEM(np.arange(400).reshape(20,20),
                              AffineTransform.from_origin(0,20,1,1)))
    warm.render('0,0,20,20',0)
    warm.render('0,0,20,20',0,'hillshade')
    results = []
    for mode in ('native','build','reuse'):
        dem = WindowedDEM(path,pyramid_dir=None if mode == 'native' else directory)
        bbox = ','.join(map(str,dem.bounds))
        start = perf_counter()
        service = ViewportTerrain(dem)
        service.render(bbox,-6)
        service.render(bbox,-6,'hillshade')
        seconds = perf_counter()-start
        # Compare the same display sample grid, including the source boundary.
        w,s,e,n = dem.bounds
        spacing = max(max(dem.resolution),128,(e-w)/255,(n-s)/255)
        cols,rows = max(2,int(np.ceil((e-w)/spacing))),max(2,int(np.ceil((n-s)/spacing)))
        x,y = np.meshgrid(w+(np.arange(cols)+.5)*(e-w)/cols,n-(np.arange(rows)+.5)*(n-s)/rows)
        level_reads = sum(level.read_count for level in dem._levels.values())
        windows = dem.read_count
        values = dem.display_elevation(x,y,min((e-w)/cols,(n-s)/rows))
        exact = WindowedDEM(path,pyramid_dir=None).elevation(x,y)
        results.append(dict(mode=mode,seconds=round(seconds,4),native_windows=windows,
            level_windows=level_reads,builds=dem.pyramid_builds,
            max_error_m=round(float(np.nanmax(abs(values-exact))),6),
            rmse_m=round(float(np.sqrt(np.nanmean((values-exact)**2))),6)))
    return results


if __name__ == '__main__':
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        print(json.dumps(dict(case='sample',results=measure(Path('data/sample/dem_sample.tif'),root/'sample'))))
        path = root/'large.tif'
        fixture(path,6000)
        print(json.dumps(dict(case='6000x6000 tiled',results=measure(path,root/'large'))))
