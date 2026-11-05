import io
import sqlite3
from pathlib import Path
import pytest
from PIL import Image
from fastapi.testclient import TestClient
from ctrlnet.tiles import MBTiles, xyz_to_tms, tms_to_xyz, image_to_mbtiles, WEB_MERCATOR_LIMIT
from ctrlnet.webmap.app import create_app

ROOT = Path(__file__).resolve().parents[1]


def png():
    b=io.BytesIO(); Image.new('RGBA',(256,256),(30,80,150,255)).save(b,format='PNG')
    return b.getvalue()


def test_mbtiles_roundtrip(tmp_path):
    path=tmp_path/'sample.mbtiles'
    data=png()
    with MBTiles(path) as db:
        db.set_metadata({'description':'测试'})
        db.put_tile(3,2,1,data)
    with sqlite3.connect(path) as conn:
        assert conn.execute('SELECT tile_row FROM tiles').fetchone()[0] == 6
    with MBTiles(path,readonly=True) as db:
        assert db.get_tile(3,2,1) == data
        assert db.get_tile(3,2,0) is None
        assert db.metadata['description'] == '测试'
        assert db.export_xyz(tmp_path/'xyz') == 1
        with pytest.raises(sqlite3.OperationalError):
            db.put_tile(3,2,1,data)
    assert (tmp_path/'xyz/3/2/1.png').read_bytes() == data
    for z in range(7):
        for y in range(2**z):
            assert tms_to_xyz(z,xyz_to_tms(z,y)) == y
    with pytest.raises(ValueError):
        xyz_to_tms(2,4)


def test_cut_and_route(tmp_path):
    limit=WEB_MERCATOR_LIMIT
    count=image_to_mbtiles(Image.new('RGBA',(32,32),'red'), (-limit,-limit,limit,limit),[0,1],tmp_path/'world.mbtiles')
    assert count == 5
    with MBTiles(tmp_path/'world.mbtiles',readonly=True) as db:
        im=Image.open(io.BytesIO(db.get_tile(1,0,0)))
        assert im.size == (256,256)
        assert im.getpixel((128,128)) == (255,0,0,255)
    client=TestClient(create_app(ROOT/'data/sample/demo_project.sqlite',tiles_dir=tmp_path))
    response=client.get('/tiles/world/1/0/0.png')
    assert response.status_code == 200
    assert response.headers['content-type'] == 'image/png'
    assert response.content.startswith(b'\x89PNG')
    assert client.get('/tiles/world/1/3/0.png').status_code == 404
    assert client.get('/tiles/missing/1/0/0.png').status_code == 404
    assert client.get('/tiles/world/2/0/0.png').status_code == 404
    assert client.get('/api/tiles').json()['resources'][0]['name'] == 'world'
    overlay=client.get('/api/tiles/world/overlay.png')
    assert overlay.status_code == 200
    assert Image.open(io.BytesIO(overlay.content)).size == (512,512)


def test_partial_coverage(tmp_path):
    limit=WEB_MERCATOR_LIMIT
    image_to_mbtiles(Image.new('RGBA',(32,32),'blue'),(-limit/2,-limit/2,limit/2,limit/2),[0],tmp_path/'part.mbtiles')
    with MBTiles(tmp_path/'part.mbtiles',readonly=True) as db:
        im=Image.open(io.BytesIO(db.get_tile(0,0,0)))
        assert im.getpixel((0,0))[3] == 0
        assert im.getpixel((128,128)) == (0,0,255,255)
