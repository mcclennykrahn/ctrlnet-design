"""Offline viewport contract and bounded large-terrain rendering."""
import json
import numpy as np
import pytest
from fastapi.testclient import TestClient
from ctrlnet.terrain import DEM, AffineTransform
from ctrlnet.webmap.viewport import ViewportTerrain
from ctrlnet.webmap.app import create_app


def synthetic(size=1200):
    y, x = np.mgrid[:size, :size]
    return DEM(300 + 180*np.sin(x/30)*np.cos(y/40),
               AffineTransform.from_origin(0, size*10, 10, 10))


def test_large_bounded_detail_and_cache():
    service = ViewportTerrain(synthetic())
    body, tag, hit = service.render('0,0,12000,12000', -5)
    low = json.loads(body)
    assert not hit
    assert service.render('0,0,12000,12000', -5) == (body, tag, True)
    high = json.loads(service.render('1000,1000,2000,2000', 2)[0])
    assert high['view']['sample_spacing_m'] < low['view']['sample_spacing_m']
    assert high['view']['interval_m'] < low['view']['interval_m']
    assert high['features']
    for f in high['features']:
        assert all(1000 <= x <= 2000 and 1000 <= y <= 2000 for x,y in f['geometry']['coordinates'])
    assert service.render('1000,1000,2000,2000', 2, 'hillshade')[0].startswith(b'\x89PNG')
    assert json.loads(service.render('20000,20000,21000,21000', 0)[0])['features'] == []
    for i in range(40):
        service.render(f'{20000+i},20000,22000,22000', 0)
    assert len(service.cache) == 32
    assert not service.render('0,0,12000,12000', -5)[2]


@pytest.mark.parametrize('bbox,zoom', [('1,2,3',0), ('nan,0,2,3',0), ('2,0,1,3',0), ('0,0,1,1',13), ('0,0,1,1','nan'), ('x,0,1,1',0)])
def test_invalid_view(bbox, zoom):
    with TestClient(create_app()) as client:
        assert client.get('/api/terrain/contours', params={'bbox':bbox,'zoom':zoom}).status_code == 422


def test_api_cache_compatibility_and_manifest():
    with TestClient(create_app()) as client:
        manifest = client.get('/api/layers?terrain=false').json()
        assert not next(l for l in manifest['layers'] if l['id']=='contours')['geojson']['features']
        assert next(l for l in manifest['layers'] if l['id']=='points')['geojson']['features']
        bbox = ','.join(map(str, manifest['bounds_native']))
        url = '/api/terrain/contours'
        params = {'bbox':bbox, 'zoom':-3}
        first = client.get(url, params=params)
        assert first.status_code == 200
        assert first.json()['features']
        assert first.headers['x-terrain-cache'] == 'miss'
        second = client.get(url, params=params)
        assert second.content == first.content
        assert second.headers['x-terrain-cache'] == 'hit'
        assert client.get(url, params=params, headers={'If-None-Match':first.headers['etag']}).status_code == 304
        assert client.get('/api/terrain/hillshade', params=params).content.startswith(b'\x89PNG')
        assert client.get('/api/terrain/nope', params=params).status_code == 404
        assert client.get(url).status_code == 422


def test_nodata_and_partial_overlap():
    dem = DEM(np.full((20,20), np.nan), AffineTransform.from_origin(0,200,10,10))
    service = ViewportTerrain(dem)
    assert service.render('-100,-100,100,100',0,'hillshade')[0].startswith(b'\x89PNG')
    assert json.loads(service.render('-100,-100,100,100',0)[0])['features'] == []
