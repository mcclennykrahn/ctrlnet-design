"""本地网页地图 API 测试（FastAPI TestClient，不启动真实端口）。"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from ctrlnet.store import snapshot
from ctrlnet.webmap.app import create_app

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "data" / "sample" / "demo_project.sqlite"
TERRAIN_PROJECT = ROOT / "data" / "sample" / "terrain_project.json"


@pytest.fixture(scope="module")
def client():
    app = create_app(DB)
    with TestClient(app) as test_client:
        yield test_client


def test_index_and_offline_leaflet_assets(client: TestClient):
    response = client.get("/")
    assert response.status_code == 200
    assert "CTRLNET" in response.text
    assert "/static/leaflet/leaflet.js" in response.text
    assert "unpkg.com" not in response.text
    assert "cdn." not in response.text
    # 新界面：方案下拉与报告下载按钮。
    assert 'id="scenario-select"' in response.text
    assert 'id="report-html"' in response.text
    assert 'id="report-docx"' in response.text

    leaflet_js = client.get("/static/leaflet/leaflet.js")
    assert leaflet_js.status_code == 200
    assert "javascript" in leaflet_js.headers["content-type"]
    assert len(leaflet_js.content) > 100_000
    assert client.get("/static/leaflet/leaflet.css").status_code == 200
    assert client.get("/static/app.js").status_code == 200


def test_project_api_default_scenario(client: TestClient):
    response = client.get("/api/project")
    assert response.status_code == 200
    payload = response.json()
    assert payload["schema"] == "ctrlnet.project/2"
    assert payload["selected_scenario"] == "dem-all"
    assert len(payload["scenarios"]) == 4
    assert {item["id"] for item in payload["scenarios"]} == {
        "s13-base",
        "s13-added",
        "dem-all",
        "dem-opt",
    }
    assert payload["summary"]["n_points"] == 7
    assert payload["summary"]["n_fixed"] == 2
    assert payload["summary"]["n_observations"] == 76
    assert payload["summary"]["n_pairs"] == 21
    assert payload["summary"]["n_visible"] == 16
    assert payload["summary"]["crs"] == "EPSG:32650"
    assert payload["summary"]["max_mp_mm"] == pytest.approx(10.048316, abs=1e-5)
    assert payload["api"]["report_html"].startswith("/api/report?scenario=dem-all")
    point = payload["points"][0]
    for key in ("name", "E", "N", "lon", "lat", "fixed", "mp_mm", "ellipse_95"):
        assert key in point


def test_scenarios_api(client: TestClient):
    response = client.get("/api/scenarios")
    assert response.status_code == 200
    payload = response.json()
    assert payload["default_scenario"] == "dem-all"
    scenarios = {item["id"]: item for item in payload["scenarios"]}
    assert scenarios["s13-base"]["version"] == 1
    assert scenarios["s13-added"]["parent_id"] == "s13-base"
    assert scenarios["s13-added"]["n_observations"] == 8
    assert scenarios["dem-opt"]["parent_id"] == "dem-all"
    assert scenarios["dem-opt"]["n_observations"] == 25


def test_scenario_switch_updates_points_observations_and_stats(client: TestClient):
    response = client.get("/api/scenario/s13-added")
    assert response.status_code == 200
    payload = response.json()
    assert payload["scenario"]["id"] == "s13-added"
    assert payload["scenario"]["parent_id"] == "s13-base"
    assert payload["summary"]["n_points"] == 4
    assert payload["summary"]["n_observations"] == 8
    assert payload["summary"]["max_mp_mm"] == pytest.approx(1.310260, abs=1e-6)
    assert len(payload["points"]) == 4
    assert {p["name"] for p in payload["points"]} == {"A", "B", "C", "D"}
    c_point = next(p for p in payload["points"] if p["name"] == "C")
    assert c_point["mp_mm"] == pytest.approx(1.310260, abs=1e-6)
    assert c_point["ellipse_95"]["a_m"] > 0.0
    assert payload["snapshot_hash"] == snapshot(DB, "s13-added", options={"confidence": 0.95})["input_hash"]

    base = client.get("/api/scenario/s13-base").json()
    assert base["summary"]["n_observations"] == 7
    assert base["summary"]["max_mp_mm"] == pytest.approx(1.716084, abs=1e-6)
    assert base["points"][2]["mp_mm"] == pytest.approx(1.716084, abs=1e-6)

    unknown = client.get("/api/scenario/missing")
    assert unknown.status_code == 404


def test_layers_api_switches_scenario(client: TestClient):
    response = client.get("/api/layers")
    assert response.status_code == 200
    payload = response.json()
    assert payload["crs"] == "EPSG:32650"
    assert payload["scenario"]["id"] == "dem-all"
    layers = {layer["id"]: layer for layer in payload["layers"]}
    assert set(layers) == {"hillshade", "contours", "observations", "ellipses", "points"}

    assert layers["hillshade"]["kind"] == "raster"
    assert layers["hillshade"]["url"] == "/api/overlay/hillshade.png"

    contours = layers["contours"]["geojson"]
    assert contours["type"] == "FeatureCollection"
    assert len(contours["features"]) > 20

    observations = layers["observations"]["geojson"]
    # 16 距离 + 60 角度 × 2 射线 + 5 条非观测遮挡线。
    assert len(observations["features"]) == 141
    kinds = {feature["properties"]["kind"] for feature in observations["features"]}
    assert {"distance", "angle", "visibility"} == kinds
    assert any(feature["properties"]["visible"] is False for feature in observations["features"])
    assert any(feature["properties"]["kind"] == "angle" for feature in observations["features"])

    points = layers["points"]["geojson"]
    assert len(points["features"]) == 7
    assert sum(1 for f in points["features"] if f["properties"]["fixed"]) == 2
    ellipses = layers["ellipses"]["geojson"]
    assert len(ellipses["features"]) == 5
    assert all(f["geometry"]["type"] == "Polygon" for f in ellipses["features"])

    s13 = client.get("/api/layers", params={"scenario": "s13-base"}).json()
    s13_layers = {layer["id"]: layer for layer in s13["layers"]}
    assert len(s13_layers["points"]["geojson"]["features"]) == 4
    assert len(s13_layers["ellipses"]["geojson"]["features"]) == 2
    assert len(s13_layers["observations"]["geojson"]["features"]) == 9
    assert s13["analysis"]["ellipse_scale"] == pytest.approx(2000.0)


def test_hillshade_png(client: TestClient):
    response = client.get("/api/overlay/hillshade.png")
    assert response.status_code == 200
    assert response.headers["content-type"] == "image/png"
    assert response.content.startswith(b"\x89PNG\r\n\x1a\n")
    assert len(response.content) > 10_000


def test_profile_visible_and_blocked(client: TestClient):
    blocked = client.get("/api/profile", params={"from": "P1", "to": "P6"})
    assert blocked.status_code == 200
    data = blocked.json()
    assert data["from"]["label"] == "P1"
    assert data["to"]["label"] == "P6"
    assert data["status"] == "blocked"
    assert data["visible"] is False
    assert data["distance_m"] == pytest.approx(4441.824, abs=0.01)
    assert data["min_clearance_m"] < 0.0
    assert data["obstruction"] is not None
    assert data["obstruction"]["elevation_m"] > 700.0
    profile = data["profile"]
    for key in ("distance_m", "elevation_m", "los_m", "chord_m", "clearance_m", "nodata"):
        assert key in profile
    assert len(profile["distance_m"]) == len(profile["elevation_m"])
    assert len(profile["distance_m"]) == len(profile["los_m"])
    assert len(profile["distance_m"]) == data["samples"]
    assert profile["distance_m"][0] == 0.0
    assert profile["distance_m"][-1] == pytest.approx(data["distance_m"], abs=1e-3)

    visible = client.get("/api/profile", params={"from": "P1", "to": "P2"})
    assert visible.status_code == 200
    assert visible.json()["status"] == "visible"
    assert visible.json()["min_clearance_m"] >= 0.0

    coordinates = client.get(
        "/api/profile",
        params={"from": "415358.4,4421306.6", "to": "418358.4,4422686.6"},
    )
    assert coordinates.status_code == 200
    assert coordinates.json()["from"]["source"] == "coordinate"
    assert coordinates.json()["from"]["label"].startswith("E=415358")
    assert coordinates.json()["distance_m"] == pytest.approx(3302.18, abs=0.05)


def test_profile_errors(client: TestClient):
    assert client.get("/api/profile", params={"from": "P1"}).status_code == 422
    assert client.get("/api/profile", params={"from": "NOPE", "to": "P1"}).status_code == 404
    assert client.get("/api/profile", params={"from": "P1", "to": "P1"}).status_code == 400
    assert client.get("/api/profile", params={"from": "bad", "to": "P1"}).status_code == 404


def test_report_html_endpoint(client: TestClient):
    response = client.get("/api/report", params={"scenario": "s13-added", "format": "html"})
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert "attachment" in response.headers["content-disposition"]
    text = response.text
    assert "<!doctype html>" in text
    assert "第 13 节增补方案" in text
    assert "data:image/png;base64," in text
    assert "1.310" in text

    md = client.get("/api/report", params={"scenario": "s13-base", "format": "md"})
    assert md.status_code == 200
    assert "markdown" in md.headers["content-type"]
    assert "# 平面控制网设计报告" in md.text
    assert "## 7. 可靠性" in md.text

    assert client.get("/api/report.md", params={"scenario": "dem-opt"}).status_code == 200


def test_report_docx_endpoint(client: TestClient):
    response = client.get("/api/report", params={"scenario": "s13-base", "format": "docx"})
    if shutil.which("pandoc"):
        assert response.status_code == 200
        assert response.content.startswith(b"PK")
        assert "wordprocessingml" in response.headers["content-type"]
    else:  # pragma: no cover
        assert response.status_code == 503


def test_report_errors(client: TestClient):
    assert client.get("/api/report", params={"scenario": "missing"}).status_code == 404
    assert client.get("/api/report", params={"scenario": "s13-base", "format": "pdf"}).status_code == 400


def test_registration_demo_api(client: TestClient):
    response = client.get("/api/registration/demo")
    assert response.status_code == 200
    data = response.json()
    assert data["model"] == "6-parameter-affine"
    assert data["n_control_points"] == 4
    assert len(data["control_points"]) == 4
    assert len(data["check_points"]) == 2
    assert data["rms_m"] > 0.0
    assert data["check_rms_m"] > 0.0
    assert data["overlay_url"] == "/api/registration/demo/overlay.png"
    assert data["image_url"] == "/api/registration/demo/image.png"
    assert data["opacity"] > 0.0
    assert len(data["overlay_bounds"]) == 2
    assert data["parameters"]["a1"] == pytest.approx(10.0, abs=0.1)
    assert data["parameters"]["b2"] == pytest.approx(-12.0, abs=0.1)
    for point in data["control_points"]:
        assert point["residual_m"] >= 0.0
        assert point["col"] >= 0.0
        assert point["row"] >= 0.0

    raw_image = client.get("/api/registration/demo/image.png")
    assert raw_image.status_code == 200
    assert raw_image.content.startswith(b"\x89PNG\r\n\x1a\n")

    overlay = client.get("/api/registration/demo/overlay.png")
    assert overlay.status_code == 200
    assert overlay.headers["content-type"] == "image/png"
    assert overlay.content.startswith(b"\x89PNG\r\n\x1a\n")
    assert len(overlay.content) > 100_000


def test_health_and_docs(client: TestClient):
    health = client.get("/api/health")
    assert health.status_code == 200
    assert health.json()["status"] == "ok"
    assert health.json()["n_scenarios"] == 4
    assert client.get("/api/openapi.json").status_code == 200
    assert client.get("/api/docs").status_code == 200


def test_demo_metadata_consistent():
    payload = json.loads((ROOT / "data" / "sample" / "registration_demo.json").read_text(encoding="utf-8"))
    assert payload["image_width"] > 0
    assert payload["image_height"] > 0
    assert len(payload["control_points"]) == 4
    assert len(payload["check_points"]) == 2
    assert (ROOT / "data" / "sample" / payload["image"]).exists()
    assert TERRAIN_PROJECT.exists()
    assert DB.stat().st_size < 5 * 1024 * 1024
