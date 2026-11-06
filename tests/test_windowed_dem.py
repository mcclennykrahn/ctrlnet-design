"""Native file-backed sampling and independent-process memory regression."""
import importlib.util
from pathlib import Path

import numpy as np
import pytest

from ctrlnet.terrain import DEM, WindowedDEM
from ctrlnet.webmap.viewport import ViewportTerrain


@pytest.fixture
def raster(tmp_path):
    import rasterio
    from rasterio.transform import from_origin
    path = tmp_path/'terrain.tif'
    values = np.arange(600*700,dtype='float32').reshape(600,700) / 100
    values[255,255] = -9999
    with rasterio.open(path,'w',driver='GTiff',height=600,width=700,count=1,
                       dtype='float32',transform=from_origin(0,6000,10,10),
                       nodata=-9999,tiled=True,blockxsize=256,blockysize=256) as ds:
        ds.write(values,1)
    return path


def test_windows_sampling_and_bounded_cache(raster):
    lazy = WindowedDEM(raster,cache_size=2)
    full = DEM.from_geotiff(raster)
    assert lazy.shape == full.shape and lazy.bounds == full.bounds
    np.testing.assert_equal(lazy.read_window(250,250,12,12),
                            np.where(full.valid_mask[250:262,250:262],full.array[250:262,250:262],np.nan))
    # Includes tile seams, exact pixel centers, NoData, outside and NaN.
    E = np.array([5,2555,2560,6995,-1,np.nan,5100])
    N = np.array([5995,3445,3440,5,100,100,2000])
    np.testing.assert_allclose(lazy.elevation(E,N),full.elevation(E,N),equal_nan=True)
    assert lazy.elevation(5,5995) == full.elevation(5,5995)
    reads=lazy.read_count
    lazy.elevation(5,5995)
    assert lazy.read_count == reads
    lazy.elevation(6995,5)
    lazy.elevation(3005,2995)
    reads=lazy.read_count
    lazy.elevation(5,5995)
    assert lazy.read_count > reads  # evicted first tile is read again
    assert len(lazy._tiles) <= 2
    assert sum(a.nbytes for a in lazy._tiles.values()) <= 2*256*256*8
    assert lazy.overview(64).width <= 64
    np.testing.assert_allclose(lazy.profile((10,100),(100,200)).elevation,
                               full.profile((10,100),(100,200)).elevation)
    service=ViewportTerrain(lazy)
    first=service.render('2000,2000,3000,3000',0)
    reads=lazy.read_count
    assert service.render('2000,2000,3000,3000',0) == (*first[:2],True)
    assert lazy.read_count == reads


@pytest.mark.parametrize('window', [(-1,0,2,2),(0,-1,2,2),(0,0,0,2),
    (599,699,2,2),(0,0,257,1),(0.5,0,2,2),(0,0,2,-1)])
def test_invalid_windows(raster,window):
    with pytest.raises(ValueError):
        WindowedDEM(raster).read_window(*window)


def test_large_raster_peak_rss(tmp_path):
    spec=importlib.util.spec_from_file_location('memory_bench',Path(__file__).resolve().parents[1]/'scripts/benchmark_dem_memory.py')
    bench=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(bench)
    path=tmp_path/'large.tif'
    bench.fixture(path,5000)
    full,windowed=bench.compare(path)
    assert windowed['peak_rss_mib'] < full['peak_rss_mib']*.65, (full,windowed)
    assert windowed['contour_bytes'] == full['contour_bytes']
    assert windowed['png_bytes'] == full['png_bytes']
    assert windowed['contour_sha256'] == full['contour_sha256']
    assert windowed['png_sha256'] == full['png_sha256']


def test_file_backed_api(raster, monkeypatch):
    from fastapi.testclient import TestClient
    from ctrlnet.webmap.app import create_app
    from ctrlnet.webmap.state import ProjectStore
    monkeypatch.setattr(ProjectStore, 'dem_path', property(lambda self: raster))
    app=create_app()
    with TestClient(app) as client:
        assert isinstance(app.state.store.dem,WindowedDEM)
        assert client.get('/api/layers?terrain=false').status_code == 200
        params={'bbox':'2000,2000,3000,3000','zoom':0}
        first=client.get('/api/terrain/contours',params=params)
        assert first.status_code == 200 and first.json()['features']
        reads=app.state.store.dem.read_count
        second=client.get('/api/terrain/contours',params=params)
        assert second.headers['x-terrain-cache'] == 'hit'
        assert second.content == first.content
        assert app.state.store.dem.read_count == reads
        assert client.get('/api/terrain/contours',params=params,
                          headers={'If-None-Match':first.headers['etag']}).status_code == 304
        assert client.get('/api/terrain/hillshade',params=params).content.startswith(b'\x89PNG')
        assert client.get('/api/layers').status_code == 200
        assert client.get('/api/terrain/contours',params={'bbox':'-1,0,0,1','zoom':0}).json()['features'] == []
