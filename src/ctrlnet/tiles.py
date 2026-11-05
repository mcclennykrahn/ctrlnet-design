"""离线 PNG MBTiles：公共 API 使用 XYZ，数据库使用 TMS 行号。"""
import io
import math
import sqlite3
from pathlib import Path
from PIL import Image
import numpy as np

WEB_MERCATOR_LIMIT = math.pi * 6378137


def xyz_to_tms(z, y):
    if not isinstance(z, int) or not isinstance(y, int) or not 0 <= z <= 30 or not 0 <= y < 2**z:
        raise ValueError('非法瓦片坐标')
    return 2**z-1-y


tms_to_xyz = xyz_to_tms


class MBTiles:
    def __init__(self, path, *, readonly=False):
        path = Path(path).resolve()
        self.readonly = readonly
        self.connection = sqlite3.connect(path.as_uri()+'?mode=ro', uri=True) if readonly else sqlite3.connect(path)
        if not readonly:
            self.connection.executescript('CREATE TABLE IF NOT EXISTS metadata (name TEXT PRIMARY KEY, value TEXT); CREATE TABLE IF NOT EXISTS tiles (zoom_level INTEGER, tile_column INTEGER, tile_row INTEGER, tile_data BLOB, PRIMARY KEY(zoom_level,tile_column,tile_row));')
            self.connection.executemany('INSERT OR IGNORE INTO metadata VALUES (?,?)',
                                        [('format', 'png'), ('type', 'baselayer'), ('version', '1.3'), ('name', path.stem)])

    def __enter__(self):
        return self

    def __exit__(self, *args):
        if args[0] is None and not self.readonly:
            self.connection.commit()
        self.connection.close()

    def set_metadata(self, values):
        self.connection.executemany('INSERT OR REPLACE INTO metadata VALUES (?,?)', [(k, str(v)) for k, v in values.items()])

    @property
    def metadata(self):
        return dict(self.connection.execute('SELECT name,value FROM metadata'))

    def put_tile(self, z, x, y, data):
        row = xyz_to_tms(z, y)
        if not 0 <= x < 2**z:
            raise ValueError('非法 x')
        with Image.open(io.BytesIO(data)) as im:
            if im.format != 'PNG' or im.size != (256, 256):
                raise ValueError('需要 256px PNG')
        self.connection.execute('INSERT OR REPLACE INTO tiles VALUES (?,?,?,?)', (z, x, row, data))

    def get_tile(self, z, x, y):
        row = xyz_to_tms(z, y)
        if not 0 <= x < 2**z:
            raise ValueError('非法 x')
        result = self.connection.execute('SELECT tile_data FROM tiles WHERE zoom_level=? AND tile_column=? AND tile_row=?', (z, x, row)).fetchone()
        return None if result is None else bytes(result[0])

    def export_xyz(self, directory):
        root = Path(directory)
        count = 0
        for z, x, row, data in self.connection.execute('SELECT * FROM tiles ORDER BY zoom_level,tile_column,tile_row'):
            path = root/str(z)/str(x)/f'{tms_to_xyz(z, row)}.png'
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
            count += 1
        return count


def image_to_mbtiles(image, bounds, zooms, path, *, max_tiles=4096):
    """北向上 EPSG:3857 影像边界 (west,south,east,north)，像素角点约定。

    DEM/扫描图须先重投影为该坐标系。范围外保持透明；按目标像素中心双线性采样。
    """
    west, south, east, north = map(float, bounds)
    limit = WEB_MERCATOR_LIMIT
    if not np.isfinite(bounds).all() or not -limit <= west < east <= limit or not -limit <= south < north <= limit:
        raise ValueError('需要有效 EPSG:3857 边界')
    source = image.convert('RGBA')
    jobs = []
    for z in sorted(set(zooms)):
        xyz_to_tms(z, 0)
        n = 2**z
        span = 2*limit/n
        x0, x1 = max(0, math.floor((west+limit)/span)), min(n-1, math.ceil((east+limit)/span)-1)
        y0, y1 = max(0, math.floor((limit-north)/span)), min(n-1, math.ceil((limit-south)/span)-1)
        if len(jobs)+(x1-x0+1)*(y1-y0+1) > max_tiles:
            raise ValueError('瓦片数量超过上限')
        jobs.extend((z,x,y) for x in range(x0,x1+1) for y in range(y0,y1+1))
    if not jobs:
        raise ValueError('至少指定一个 zoom')
    with MBTiles(path) as db:
        lon = lambda v: v/limit*180
        lat = lambda v: math.degrees(math.atan(math.sinh(v/6378137)))
        db.set_metadata({'minzoom': min(j[0] for j in jobs), 'maxzoom': max(j[0] for j in jobs), 'bounds': ','.join(map(str,(lon(west),lat(south),lon(east),lat(north))))})
        for z, x, y in jobs:
            span = 2*limit/2**z
            left, top = -limit+x*span, limit-y*span
            sx, sy = source.width/(east-west), source.height/(north-south)
            tile = source.transform((256,256), Image.Transform.AFFINE, (span/256*sx,0,(left-west)*sx,0,span/256*sy,(north-top)*sy), Image.Resampling.BILINEAR, fillcolor=(0,0,0,0))
            buf = io.BytesIO()
            tile.save(buf, format='PNG', optimize=True)
            db.put_tile(z,x,y,buf.getvalue())
    return len(jobs)


def render_native_overlay(path, bounds, crs, size=512):
    """把本地 MBTiles 重投影为工程平面预览，供现有 CRS.Simple 图层使用。"""
    import rasterio
    from rasterio.transform import from_bounds
    from rasterio.warp import reproject, Resampling
    target = np.zeros((4, size, size), dtype=np.uint8)
    with rasterio.open(path) as src:
        for i in range(min(src.count, 4)):
            reproject(rasterio.band(src, i+1), target[i], src_transform=src.transform,
                      src_crs=src.crs, dst_transform=from_bounds(*bounds, size, size),
                      dst_crs=crs, resampling=Resampling.bilinear)
        if src.count < 4:
            mask = src.dataset_mask()
            reproject(mask, target[3], src_transform=src.transform, src_crs=src.crs,
                      dst_transform=from_bounds(*bounds, size, size), dst_crs=crs)
    buf = io.BytesIO()
    Image.fromarray(np.moveaxis(target, 0, -1)).save(buf, format='PNG')
    return buf.getvalue()
