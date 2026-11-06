"""Fresh-process peak RSS comparison; temporary tiled fixture, no project writes.

Run .venv/bin/python scripts/benchmark_dem_memory.py [--size 6000].
RSS is Linux /proc VmHWM, reset after imports (includes the current import
baseline and rendering). This avoids inherited parent ru_maxrss high-water marks.
"""
import argparse
from hashlib import sha256
import json
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import numpy as np
import rasterio
from rasterio.transform import from_origin
from rasterio.windows import Window


def fixture(path, size):
    with rasterio.open(path, 'w', driver='GTiff', width=size, height=size,
                       count=1, dtype='float32', crs='EPSG:32650',
                       transform=from_origin(0,size*10,10,10), tiled=True,
                       blockxsize=256, blockysize=256) as ds:
        x = np.arange(size)[None, :]
        for row in range(0,size,128):
            y = np.arange(row,min(row+128,size))[:,None]
            values = (300+180*np.sin(x/30)*np.cos(y/40)).astype('float32')
            ds.write(values,1,window=Window(0,row,size,len(y)))


def worker(path, mode):
    from ctrlnet.terrain import DEM, WindowedDEM
    from ctrlnet.webmap.viewport import ViewportTerrain
    Path("/proc/self/clear_refs").write_text("5")
    start = time.perf_counter()
    dem = DEM.from_geotiff(path) if mode == 'full' else WindowedDEM(path)
    w,s,e,n = dem.bounds
    bbox = ','.join(map(str,(w+(e-w)*.475,s+(n-s)*.475,w+(e-w)*.525,s+(n-s)*.525)))
    service = ViewportTerrain(dem)
    body,_,_ = service.render(bbox,-2)
    png,_,_ = service.render(bbox,-2,'hillshade')
    print(json.dumps(dict(mode=mode, peak_rss_mib=round(int(next(line.split()[1] for line in Path('/proc/self/status').read_text().splitlines() if line.startswith('VmHWM:')))/1024,2),
                         seconds=round(time.perf_counter()-start,3), contour_bytes=len(body), png_bytes=len(png),
                         contour_sha256=sha256(body).hexdigest(), png_sha256=sha256(png).hexdigest())))


def compare(path):
    results = []
    for mode in ('full','windowed'):
        result = subprocess.run([sys.executable,__file__,'--worker',str(path),mode],
                                check=True,capture_output=True,text=True,timeout=60)
        results.append(json.loads(result.stdout))
    return results


if __name__ == '__main__':
    if len(sys.argv)>1 and sys.argv[1]=='--worker':
        worker(*sys.argv[2:])
    else:
        parser=argparse.ArgumentParser()
        parser.add_argument('--size',type=int,default=6000)
        args=parser.parse_args()
        sample=Path(__file__).resolve().parents[1]/'data/sample/dem_sample.tif'
        print(json.dumps(dict(case='sample',results=compare(sample))))
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'large.tif'
            fixture(path,args.size)
            print(json.dumps(dict(case=f'synthetic {args.size}x{args.size}',results=compare(path))))
