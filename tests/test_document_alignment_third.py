"""第三批重投影及编辑原子性验证。"""
import io
import numpy as np
from PIL import Image
from fastapi.testclient import TestClient
from ctrlnet.webmap.app import create_app
from ctrlnet.webmap.warp import warp_png
from test_webmap import DB


def test_warp_pixel_location_and_bounds():
    # 经纬度栅格中心红十字，投影后仍位于由真实 Mercator 公式计算的像元。
    from rasterio.warp import transform
    a = np.zeros((400,400,4),dtype=np.uint8)
    a[:,:,3] = 255
    a[195:205,:,0] = 255
    a[:,195:205,0] = 255
    buf = io.BytesIO(); Image.fromarray(a).save(buf,format='PNG')
    content,b = warp_png(buf.getvalue(),(115,30,117,40),'EPSG:4326')
    im = np.asarray(Image.open(io.BytesIO(content)))
    xs,ys = transform('EPSG:4326','EPSG:3857',[115,116,117],[30,35,40])
    col = round((xs[1]-xs[0])/(xs[2]-xs[0])*im.shape[1])
    row = round((ys[2]-ys[1])/(ys[2]-ys[0])*im.shape[0])
    assert im[row,col,0] > 200
    assert np.allclose(b,[[30,115],[40,117]])


def test_xyz_cache_and_profile(tmp_path):
    app = create_app(DB,thesis_db=tmp_path/'thesis.sqlite')
    with TestClient(app) as c:
        data = c.get('/api/layers/geographic').json()
        assert len(data['warps']) == 2
        for item in data['warps']:
            r=c.get(item['url']); assert r.status_code == 200
            assert r.headers['x-warp-cache'] == 'HIT'
        points = next(l for l in data['layers'] if l['id']=='points')['geojson']['features']
        refs = [','.join(map(str,p['geometry']['coordinates'])) for p in points[:2]]
        r=c.get('/api/profile/geographic',params={'start':refs[0],'end':refs[1]})
        assert r.status_code == 200
        assert r.json()['samples'] > 2
        assert c.get('/api/profile/geographic',params={'start':'nan,34','end':refs[1]}).status_code == 400


def test_move_atomic_and_refresh(tmp_path):
    app=create_app(DB,thesis_db=tmp_path/'thesis.sqlite')
    service=app.state.thesis
    service.load_example(1)
    old=service.snapshot()
    p=old['points'][0]
    with TestClient(app) as c:
        route='/api/thesis/points/'+p['id']
        r=c.patch(route,json={'lon':p['lon']+.001,'lat':p['lat']+.001,'snap_m':10})
        assert r.status_code == 200
        new=r.json()
        assert new['points'][0]['x'] % 10 == 0
        assert new['points'][0]['y'] % 10 == 0
        assert new['lines'] != old['lines']
        assert new['network']['observed_edges'] == old['network']['observed_edges']
        assert c.patch(route,json={'lon':120,'lat':34}).status_code == 400
        assert service.snapshot()['points'] == new['points']
        fixed = next(p for p in new['points'] if p['fixed'])
        assert c.patch('/api/thesis/points/'+fixed['id'],json={'lon':fixed['lon']+.001,'lat':fixed['lat']}).status_code == 400
