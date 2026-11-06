"""论文模式网页 API 测试（FastAPI TestClient，不监听端口、不访问网络）。"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from ctrlnet.webmap.app import create_app
from ctrlnet.thesis import gauss_forward
from ctrlnet.webmap.thesis_web import (
    DEFAULT_CENTRAL_MERIDIAN,
    ORIGIN_LAT,
    ORIGIN_LON,
    _lonlat_from_local,
)

ROOT = Path(__file__).resolve().parents[1]
DEMO_DB = ROOT / "data" / "sample" / "demo_project.sqlite"


@pytest.fixture()
def client(tmp_path: Path):
    app = create_app(DEMO_DB, thesis_db=tmp_path / "thesis_web.sqlite")
    with TestClient(app) as test_client:
        yield test_client


def test_thesis_page_is_offline_and_has_libraries(client: TestClient):
    response = client.get("/thesis")
    assert response.status_code == 200
    html = response.text
    assert 'id="map"' in html
    assert "/static/leaflet/leaflet.js" in html
    assert "/static/thesis.css" in html
    assert "/static/thesis.js" in html
    for forbidden in (
        "unpkg.com",
        "cdn.",
        "api.map.baidu.com",
        "openstreetmap.org",
        "tile.openstreetmap",
        "webrd",
        "tianditu",
        "amap.com",
        "googleapis.com",
    ):
        assert forbidden not in html
    assert "点库" in html and "线库" in html and "角库" in html and "网库" in html
    assert "构线" in html and "构角" in html and "精度计算" in html
    assert "#1 角度测量原理" in html
    assert "#2 坐标转换原理" in html
    assert "#3 精度估算原理" in html
    # 旧仪表盘仍可访问。
    assert client.get("/dashboard").status_code == 200
    js = client.get("/static/thesis.js")
    assert js.status_code == 200
    assert "http://" not in js.text and "https://" not in js.text


def test_basemap_is_local_and_small(client: TestClient):
    meta = client.get("/api/thesis/basemap")
    assert meta.status_code == 200
    data = meta.json()
    assert data["offline"] is True
    assert data["online_tiles"] is False
    assert data["bounds"] == [117.10, 34.15, 117.30, 34.25]
    assert data["png_url"] == "/api/thesis/basemap.png"
    assert data["png_exists"] is True
    assert data["png_bytes"] <= 3 * 1024 * 1024
    png = client.get("/api/thesis/basemap.png")
    assert png.status_code == 200
    assert png.headers["content-type"] == "image/png"
    assert png.content.startswith(b"\x89PNG\r\n\x1a\n")
    assert len(png.content) == data["png_bytes"]


def test_build_points_lines_angles_and_cascade_delete(client: TestClient):
    client.post("/api/thesis/new", json={"name": "交互建网测试"})
    coords = [
        (117.250217, 34.187637),
        (117.256110, 34.187159),
        (117.262000, 34.188000),
    ]
    for lon, lat in coords:
        response = client.post("/api/thesis/points", json={"lon": lon, "lat": lat})
        assert response.status_code == 200
        payload = response.json()
    assert [p["name"] for p in payload["points"]] == ["1", "2", "3"]
    assert payload["points"][0]["lon"] == pytest.approx(coords[0][0], abs=1e-9)
    assert payload["points"][0]["x"] > 3_700_000
    assert payload["points"][0]["y"] > 500_000

    known = client.patch("/api/thesis/points/p1", json={"fixed": True}).json()
    assert known["points"][0]["fixed"] is True
    assert known["summary"]["n_known"] == 1
    assert known["summary"]["n_unknown"] == 2

    line = client.post(
        "/api/thesis/lines", json={"from": "1", "to": "2"}
    ).json()
    assert len(line["lines"]) == 1
    edge = line["lines"][0]
    assert edge["from_name"] == "1" and edge["to_name"] == "2"
    assert edge["length"] == pytest.approx(550.0, abs=30.0)
    assert 80.0 < edge["azimuth"] < 120.0

    angle = client.post(
        "/api/thesis/angles",
        json={"backsight": "1", "station": "2", "foresight": "3"},
    ).json()
    assert len(angle["angles"]) == 1
    assert 0.0 <= angle["angles"][0]["value"] < 360.0
    assert angle["summary"]["n_angles"] == 1

    # 删除点 2：线 1-2 与角 1-2-3 都被级联删除，剩余点重排为 1、2。
    cascaded = client.delete("/api/thesis/points/p2").json()
    assert cascaded["summary"]["n_points"] == 2
    assert cascaded["summary"]["n_lines"] == 0
    assert cascaded["summary"]["n_angles"] == 0
    assert [p["name"] for p in cascaded["points"]] == ["1", "2"]


def test_duplicate_and_invalid_topology(client: TestClient):
    client.post("/api/thesis/new", json={"name": "错误测试"})
    for lon, lat in ((117.20, 34.20), (117.21, 34.20)):
        assert client.post("/api/thesis/points", json={"lon": lon, "lat": lat}).status_code == 200
    assert client.post("/api/thesis/lines", json={"from": "1", "to": "1"}).status_code == 400
    assert client.post("/api/thesis/lines", json={"from": "1", "to": "9"}).status_code == 404
    assert client.post("/api/thesis/lines", json={"from": "1", "to": "2"}).status_code == 200
    assert client.post("/api/thesis/lines", json={"from": "2", "to": "1"}).status_code == 409
    assert (
        client.post(
            "/api/thesis/angles",
            json={"backsight": "1", "station": "1", "foresight": "2"},
        ).status_code
        == 400
    )
    # 未勾选任何观测值。
    response = client.post("/api/thesis/calculate")
    assert response.status_code == 400
    assert "至少勾选" in response.json()["detail"]


def _load_example(client: TestClient, key: str) -> dict:
    response = client.post(f"/api/thesis/examples/{key}")
    assert response.status_code == 200, response.text
    return response.json()


def test_example1_calculation_matches_paper_and_exports(client: TestClient):
    state = _load_example(client, "1")
    assert state["summary"]["n_points"] == 9
    assert state["summary"]["n_lines"] == 17
    assert state["summary"]["n_angles"] == 14
    assert state["summary"]["n_known"] == 2
    assert state["network"]["observed_edges"] == []
    assert len(state["network"]["observed_angles"]) == 14

    results = client.post("/api/thesis/calculate")
    assert results.status_code == 200, results.text
    result = results.json()
    assert result["weakest_point"] == "1"
    assert result["qxx"] == pytest.approx(0.6502, abs=5e-5)
    assert result["qyy"] == pytest.approx(0.3039, abs=5e-5)
    assert result["mp_paper_mm"] == pytest.approx(9.768, abs=0.01)
    assert result["mp_cm"] == pytest.approx(0.9768, abs=0.001)
    assert result["satisfied"] is True
    assert result["B_shape"] == [14, 14]
    assert result["rank"] == 14
    assert len(result["edge_denominators"]) == 17
    assert result["edge_denominators"][0]["number"] == 1
    assert result["edge_denominators"][0]["denominator"] == pytest.approx(54484.3, abs=0.5)
    assert result["weakest_edge"] is not None
    assert len(result["ellipses"]) == 7
    assert all(item["E_mm"] >= item["F_mm"] for item in result["ellipses"])

    coords = client.get("/api/thesis/export/coordinates")
    assert coords.status_code == 200
    text = coords.json()["text"]
    lines = text.splitlines()
    assert len(lines) == 9
    assert lines[0] == "点1；3784503.204274250，523065.320310928"
    assert lines[-1].startswith("点9；")

    angles = client.get("/api/thesis/export/angles")
    assert angles.status_code == 200
    assert angles.json()["text"].startswith("[-1,1,2;-2,-1,2;-1,-2,2;")
    assert angles.json()["text"].endswith("7,1,-1]")
    assert angles.json()["n_angles"] == 14


def test_example2_mixed_network_and_optimization_comparison(client: TestClient):
    state = _load_example(client, "2")
    assert state["summary"]["n_points"] == 9
    assert len(state["network"]["observed_edges"]) == 10
    assert len(state["network"]["observed_angles"]) == 11
    result = client.post("/api/thesis/calculate").json()
    assert result["weakest_point"] == "7"
    assert result["qxx"] == pytest.approx(0.1715, abs=5e-5)
    assert result["qyy"] == pytest.approx(0.1575, abs=5e-5)
    assert result["mp_paper_mm"] == pytest.approx(5.736, abs=0.01)
    assert result["n_observations"] == 21
    assert result["B_shape"] == [21, 14]

    # 增加一个未观测角作为优化新增观测，结果应给出优化前后对比。
    added = client.post(
        "/api/thesis/angles",
        json={"backsight": "4", "station": "8", "foresight": "9"},
    ).json()
    new_angle = added["angles"][-1]
    configured = client.post(
        "/api/thesis/network",
        json={"added_angles": [new_angle["id"]]},
    )
    assert configured.status_code == 200
    optimized = client.post("/api/thesis/calculate").json()
    assert optimized["n_added_observations"] == 1
    assert optimized["comparison"] is not None
    assert optimized["comparison"]["base_n_observations"] == 21
    assert optimized["comparison"]["optimized_n_observations"] == 22


def test_save_and_load_sqlite_project(client: TestClient):
    state = _load_example(client, "1")
    assert state["summary"]["n_points"] == 9
    saved = client.post(
        "/api/thesis/projects/save", json={"name": "e2e-算例1"}
    )
    assert saved.status_code == 200, saved.text
    assert saved.json()["name"] == "e2e-算例1"
    projects = client.get("/api/thesis/projects").json()["projects"]
    assert any(item["name"] == "e2e-算例1" for item in projects)

    # 修改当前工程后再读取，点/线/角应恢复。
    client.delete("/api/thesis/points/p9")
    assert client.get("/api/thesis/state").json()["summary"]["n_points"] == 8
    loaded = client.post(
        "/api/thesis/projects/load", json={"name": "e2e-算例1"}
    )
    assert loaded.status_code == 200, loaded.text
    restored = loaded.json()
    assert restored["summary"]["n_points"] == 9
    assert restored["summary"]["n_lines"] == 17
    assert restored["summary"]["n_angles"] == 14
    assert client.post("/api/thesis/projects/load", json={"name": "不存在"}).status_code == 404


def test_examples_list_and_errors(client: TestClient):
    examples = client.get("/api/thesis/examples").json()["examples"]
    assert {item["key"] for item in examples} == {"1", "2"}
    assert client.post("/api/thesis/examples/3").status_code == 404
    # 未知线/角删除返回 404。
    client.post("/api/thesis/new", json={"name": "空"})
    assert client.delete("/api/thesis/lines/l99").status_code == 404
    assert client.delete("/api/thesis/angles/a99").status_code == 404
    assert client.get("/api/thesis/export/coordinates").status_code == 400


def test_example2_local_lonlat_roundtrip():
    """算例 2 的局部坐标放到地图后，点击反算必须还原同一平面坐标。"""
    origin_x, origin_y = gauss_forward(
        ORIGIN_LAT, ORIGIN_LON, central_meridian=DEFAULT_CENTRAL_MERIDIAN
    )
    for x, y in ((0.0, 0.0), (444.8923, 3.2213), (-468.1251, 337.0750)):
        lon, lat = _lonlat_from_local(x, y)
        gx, gy = gauss_forward(lat, lon, central_meridian=DEFAULT_CENTRAL_MERIDIAN)
        assert gx - origin_x == pytest.approx(x, abs=1e-6)
        assert gy - origin_y == pytest.approx(y, abs=1e-6)


def test_thesis_page_has_paper_stage_views(client: TestClient):
    html = client.get("/thesis").text
    assert 'id="stage-select"' in html
    assert 'data-stage="full"' in html
    for value in ("map", "points", "lines", "angles"):
        assert f'<option value="{value}">' in html
    # 顶栏已移除，页面从地图/面板开始，更接近论文截图。
    assert "thesis-topbar" not in html


def test_public_basemaps_and_projection(client):
    config = client.get('/api/basemaps').json()
    assert config['default'] == 'offline'
    assert config['coordinate_system'] == 'WGS84'
    assert [s['id'] for s in config['sources']] == ['road', 'satellite']
    assert all(s['url'].startswith('https://') and 'token' not in s['url'] for s in config['sources'])
    state = client.get('/api/thesis/state').json()
    assert state['projection']['zone_number'] == 39
    assert state['projection']['central_meridian'] == 117
    assert client.post('/api/thesis/points', json={'lon':120, 'lat':34}).status_code == 400
    assert not client.get('/api/thesis/state').json()['points']


def test_coordinate_import_roundtrip_and_atomic_errors(client):
    state = client.post('/api/thesis/examples/1').json()
    exported = client.get('/api/thesis/export/coordinates').json()['text']
    imported = client.post('/api/thesis/import/coordinates', json={'text':exported, 'name':'输入方案'}).json()
    assert imported['name'] == '输入方案'
    assert len(imported['points']) == 9
    assert imported['lines'] == imported['angles'] == []
    for before, after in zip(state['points'], imported['points']):
        assert after['x'] == pytest.approx(before['x'], abs=1e-7)
        x, y = gauss_forward(after['lat'], after['lon'], central_meridian=117)
        assert x == pytest.approx(after['x'], abs=1e-6)
        assert y == pytest.approx(after['y'], abs=1e-6)
    for text in ['点1；nan，500000', '点1；3780000，500000\n点1；3780000，500000', '点1；0，0', 'broken', '点1；3780000，899999']:
        assert client.post('/api/thesis/import/coordinates', json={'text':text}).status_code == 400
        assert client.get('/api/thesis/state').json()['points'] == imported['points']
    line = client.post('/api/thesis/lines', json={'from':'1','to':'2'})
    assert line.status_code == 200
    assert client.post('/api/thesis/angles', json={'backsight':'1','station':'2','foresight':'3'}).status_code == 200
    assert client.post('/api/thesis/projects/save', json={'name':'输入方案'}).status_code == 200
    client.post('/api/thesis/new')
    loaded = client.post('/api/thesis/projects/load', json={'name':'输入方案'}).json()
    assert len(loaded['lines']) == len(loaded['angles']) == 1


def test_example2_click_uses_local_plane(client):
    state = client.post('/api/thesis/examples/2').json()
    point = state['points'][0]
    added = client.post('/api/thesis/points', json={'lon':point['lon'], 'lat':point['lat']}).json()['points'][-1]
    assert added['x'] == pytest.approx(point['x'], abs=1e-6)
    assert added['y'] == pytest.approx(point['y'], abs=1e-6)
