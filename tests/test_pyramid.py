"""Durable display levels, exact native paths and API cache contracts."""
import json

import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin

from ctrlnet.terrain import WindowedDEM
from ctrlnet.webmap.viewport import ViewportTerrain


@pytest.fixture
def plane(tmp_path):
    path = tmp_path/'plane.tif'
    y, x = np.mgrid[:1024, :1024]
    with rasterio.open(path, 'w', driver='GTiff', width=1024, height=1024,
                       count=1, dtype='float32', transform=from_origin(0,1024,1,1),
                       tiled=True, blockxsize=256, blockysize=256, nodata=-9999) as dst:
        dst.write((100+x*.1+y*.2).astype('float32'), 1)
    return path, tmp_path/'cache'


def test_durable_level_and_accuracy(plane):
    path, cache = plane
    dem = WindowedDEM(path, pyramid_dir=cache)
    x, y = np.meshgrid(np.linspace(10,1014,100), np.linspace(10,1014,100))
    native = dem.elevation(x,y)
    coarse = dem.display_elevation(x,y,16)
    # A linear surface is preserved away from edge extension (float32 source).
    np.testing.assert_allclose(coarse, native, atol=4e-5, rtol=0)
    assert dem.pyramid_builds == 1
    level = dem._levels[8]
    with rasterio.open(level.path) as ds:
        assert ds.is_tiled and ds.width == 128 and ds.nodata != ds.nodata
    reads = level.read_count
    np.testing.assert_equal(dem.display_elevation(x,y,16), coarse)
    assert level.read_count == reads
    restarted = WindowedDEM(path, pyramid_dir=cache)
    np.testing.assert_equal(restarted.display_elevation(x,y,16), coarse)
    assert restarted.pyramid_builds == 0
    assert np.isnan(dem.display_elevation(-1,10,16))
    assert len(list(cache.glob('*.tif'))) == 1
    # Source replacement invalidates durable levels in a new immutable reader.
    with rasterio.open(path, 'r+') as ds:
        ds.write(np.full((1024,1024),42,dtype='float32'),1)
    changed = WindowedDEM(path,pyramid_dir=cache)
    assert changed.display_elevation(100,100,16) == 42
    assert changed.pyramid_builds == 1


@pytest.mark.parametrize('spacing', [0,-1,float('nan'),float('inf')])
def test_invalid_spacing(plane, spacing):
    with pytest.raises(ValueError):
        WindowedDEM(plane[0],pyramid_dir=plane[1]).display_elevation(10,10,spacing)
    assert not plane[1].exists()


def test_exact_paths_and_viewport(plane):
    path, cache = plane
    dem = WindowedDEM(path,pyramid_dir=cache)
    native = WindowedDEM(path,pyramid_dir=None)
    x = np.array([.5,255.8,512.2,1023.5,np.nan])
    np.testing.assert_equal(dem.display_elevation(x,500,3.99),native.elevation(x,500))
    a,b = ViewportTerrain(dem),ViewportTerrain(native)
    for kind in ('contours','hillshade'):
        assert a.render('0,0,1024,1024',2,kind)[:2] == b.render('0,0,1024,1024',2,kind)[:2]
    np.testing.assert_equal(dem.profile((10,10),(900,900)).elevation,
                            native.profile((10,10),(900,900)).elevation)
    first = a.render('0,0,1024,1024',-3)
    assert dem.pyramid_builds == 1
    assert a.render('0,0,1024,1024',-3) == (*first[:2],True)
    assert json.loads(first[0])['features']
    np.testing.assert_equal(dem.elevation(x,500),native.elevation(x,500))


def test_nodata_and_failed_build(plane, monkeypatch):
    path, cache = plane
    with rasterio.open(path,'r+') as ds:
        ds.write(np.full((1024,1024),-9999,dtype='float32'),1)
    dem = WindowedDEM(path,pyramid_dir=cache)
    assert np.isnan(dem.display_elevation(500,500,16))
    other = WindowedDEM(path,pyramid_dir=cache/'failed')
    def fail(*args):
        raise OSError('publish failure')
    monkeypatch.setattr('ctrlnet.pyramid.os.replace',fail)
    with pytest.raises(OSError,match='publish failure'):
        other.display_elevation(500,500,16)
    assert not list((cache/'failed').iterdir())


def test_low_zoom_api_disk_reuse(plane, monkeypatch):
    from fastapi.testclient import TestClient
    from ctrlnet.webmap.app import create_app
    from ctrlnet.webmap.state import ProjectStore
    path, cache = plane
    monkeypatch.setattr(ProjectStore,'dem_path',property(lambda self:path))
    for run in range(2):
        app = create_app()
        app.state.store._dem = WindowedDEM(path,pyramid_dir=cache)
        with TestClient(app) as client:
            params = dict(bbox='0,0,1024,1024',zoom=-3)
            first = client.get('/api/terrain/contours',params=params)
            assert first.status_code == 200 and first.json()['features']
            assert app.state.store.dem.pyramid_builds == (1 if run == 0 else 0)
            assert client.get('/api/terrain/hillshade',params=params).content.startswith(b'\x89PNG')
            second = client.get('/api/terrain/contours',params=params)
            assert second.content == first.content and second.headers['x-terrain-cache'] == 'hit'
            assert client.get('/api/terrain/contours',params=params,
                headers={'If-None-Match':first.headers['etag']}).status_code == 304
            assert client.get('/api/terrain/contours',params=dict(bbox='nan,0,1,1',zoom=-3)).status_code == 422
