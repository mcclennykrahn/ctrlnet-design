"""Batch 2 local Chromium UI checks; tiles mocked without public network requests."""
import json
import subprocess
import sys
from pathlib import Path
from playwright.sync_api import sync_playwright
from test_thesis_e2e import _free_port, _wait_server

ROOT = Path(__file__).resolve().parents[1]
port = _free_port()
base = f'http://127.0.0.1:{port}'
process = subprocess.Popen([sys.executable, '-m', 'uvicorn', 'ctrlnet.webmap.app:app', '--host', '127.0.0.1', '--port', str(port), '--log-level', 'error'], cwd=ROOT)
try:
    _wait_server(base + '/api/health')
    with sync_playwright() as p:
        browser = p.chromium.launch(args=['--no-sandbox'])
        page = browser.new_page(viewport={'width':1600, 'height':1100})
        errors = []
        page.on('pageerror', lambda err: errors.append(str(err)))
        page.on('dialog', lambda dialog: dialog.accept())
        page.goto(base + '/dashboard', wait_until='networkidle')
        page.wait_for_function('window.ctrlnetReady === true')
        assert page.locator('#dashboard-basemap option').count() >= 4
        # Return a valid local image, then test failure separately.
        page.route('https://tile.openstreetmap.org/**', lambda route: route.fulfill(path=str(ROOT/'data/sample/thesis_basemap.png'), content_type='image/png'))
        page.select_option('#dashboard-basemap', 'road')
        page.wait_for_function('document.querySelector("#dashboard-basemap-status").textContent.includes("已加载")')
        assert 'EPSG:3857' in page.inner_text('#dashboard-basemap-status')
        data = page.request.get(base + '/api/layers/geographic').json()
        points = next(layer for layer in data['layers'] if layer['id'] == 'points')['geojson']['features']
        assert all(115 < f['geometry']['coordinates'][0] < 120 and 30 < f['geometry']['coordinates'][1] < 40 for f in points)
        page.select_option('#scenario-select', 's13-added')
        page.wait_for_function('window.ctrlnetScenarioReady === "s13-added"')
        page.select_option('#dashboard-basemap', 'offline')
        page.unroute('https://tile.openstreetmap.org/**')
        page.route('https://tile.openstreetmap.org/**', lambda route: route.abort())
        page.select_option('#dashboard-basemap', 'road')
        page.wait_for_function('document.querySelector("#dashboard-basemap-status").textContent.includes("已回退")')
        assert page.input_value('#dashboard-basemap') == 'offline'
        assert 'CRS.Simple' in page.inner_text('#dashboard-basemap-status')
        stalled = []
        page.route('https://server.arcgisonline.com/**', lambda route: stalled.append(route))
        page.select_option('#dashboard-basemap', 'satellite')
        page.wait_for_function('document.querySelector("#dashboard-basemap-status").textContent.includes("12秒超时")', timeout=16000)
        assert page.input_value('#dashboard-basemap') == 'offline'
        for route in stalled:
            route.abort()
        page.select_option('#dashboard-basemap', index=3)
        page.wait_for_function('document.querySelector("#dashboard-basemap-status").textContent.includes("已加载")')
        page.screenshot(path=str(ROOT/'outputs/document_alignment_batch2_dashboard_xyz.png'))
        page.select_option('#dashboard-basemap', 'offline')
        page.evaluate("window.ctrlnetApp.showProfile('P1','P6')")
        page.wait_for_selector('#profile-chart svg')
        page.click('#compare-versions')
        page.wait_for_function('document.querySelector("#version-comparison").textContent.includes("方案对比")')
        assert page.locator('#version-list button').count() >= 2
        page.screenshot(path=str(ROOT/'outputs/document_alignment_batch2_dashboard.png'))
        page.goto(base + '/thesis', wait_until='networkidle')
        page.click('[data-example="1"]')
        page.wait_for_function('window.ctrlnetThesis.state.data.points.length === 9')
        page.fill('#projection-cm', '117.3'); page.click('#apply-projection')
        page.wait_for_function('window.ctrlnetThesis.state.data.projection.central_meridian === 117.3')
        assert '117.3°E' in page.inner_text('#projection-summary')
        page.fill('#projection-cm', '120'); page.click('#apply-projection')
        page.wait_for_function('document.querySelector("#toast").textContent.includes("跨带")')
        assert page.evaluate('window.ctrlnetThesis.state.data.projection.central_meridian') == 117.3
        payload = page.evaluate('window.ctrlnetThesis.state.data')
        payload['name'] = 'batch2-json-roundtrip'
        def upload(data):
            page.set_input_files('#topology-file', {'name':'project.json','mimeType':'application/json','buffer':json.dumps(data).encode()})
        upload(payload)
        page.wait_for_function('window.ctrlnetThesis.state.data.name === "batch2-json-roundtrip"')
        assert page.evaluate('window.ctrlnetThesis.state.data.lines.length') == len(payload['lines'])
        bad = json.loads(json.dumps(payload)); bad['lines'][0]['from'] = 'missing'
        upload(bad)
        page.wait_for_function('document.querySelector("#toast").textContent.includes("导入失败")')
        assert page.evaluate('window.ctrlnetThesis.state.data.name') == payload['name']
        page.click('#undo-mutation')
        page.wait_for_function('window.ctrlnetThesis.state.data.name !== "batch2-json-roundtrip"')
        page.screenshot(path=str(ROOT/'outputs/document_alignment_batch2_thesis.png'))
        assert not errors, errors
        browser.close()
        print('PASS: dashboard XYZ/CRS/fallback, version compare, CM edit/cross-zone, atomic JSON topology, undo')
finally:
    process.terminate(); process.wait(timeout=10)
