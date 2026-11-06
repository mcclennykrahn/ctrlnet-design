"""第三批：真实离线 DEM / warp 及拖动、吸附、重做浏览器闭环。"""
import json
import subprocess
import sys
from pathlib import Path
from playwright.sync_api import sync_playwright
from e2e_database import isolated_environment
from test_thesis_e2e import _free_port, _wait_server

ROOT = Path(__file__).resolve().parents[1]
port = _free_port()
base = f'http://127.0.0.1:{port}'
process = subprocess.Popen([sys.executable, '-m', 'uvicorn', 'ctrlnet.webmap.app:app', '--host', '127.0.0.1', '--port', str(port), '--log-level', 'error'], cwd=ROOT, env=isolated_environment())
try:
    _wait_server(base + '/api/health')
    with sync_playwright() as p:
        browser = p.chromium.launch(args=['--no-sandbox'])
        page = browser.new_page(viewport={'width':1600,'height':1100})
        errors = []
        page.on('pageerror', lambda err: errors.append(str(err)))
        page.on('dialog', lambda dialog: dialog.accept())
        page.goto(base + '/dashboard', wait_until='networkidle')
        page.wait_for_function('window.ctrlnetReady === true')
        page.select_option('#dashboard-basemap', 'warped-dem')
        page.wait_for_function('window.ctrlnetXYZ && document.querySelector("#dashboard-basemap-status").textContent.includes("已加载")', timeout=60000)
        assert 'warp' in page.inner_text('#dashboard-basemap-status')
        for key in ('hillshade','contours','scan'):
            page.check('#lyr-' + key)
        page.wait_for_function('Object.values(window.ctrlnetXYZ.layers).filter(x => x._url).every(x => x._image.complete && x._image.naturalWidth > 0)')
        evidence = page.evaluate('''() => {
          const x = window.ctrlnetXYZ, point = x.data.layers.find(l => l.id === 'points').geojson.features[0];
          const ll = L.latLng(point.geometry.coordinates[1],point.geometry.coordinates[0]);
          const image = x.layers.hillshade, bounds = image.getBounds();
          const pos = x.map.latLngToContainerPoint(ll);
          return {point:point.properties,lonlat:[ll.lng,ll.lat],inside:bounds.contains(ll),pixel:[pos.x,pos.y],bounds:bounds,warps:x.data.warps};
        }''')
        assert evidence['inside']
        # 对已知点的真实 Leaflet 屏幕位置加十字标记，保留栅格与点的视觉对应。
        page.evaluate('''() => {const x=window.ctrlnetXYZ; const p=x.layers.points.getLayers()[0]; p.bindTooltip('坐标核验点 '+p.feature.properties.name,{permanent:true}).openTooltip();}''')
        page.screenshot(path=str(ROOT/'outputs/document_alignment_third_xyz.png'))
        assert page.request.get(base+'/api/warp/hillshade.png').headers['x-warp-cache'] == 'HIT'
        # 使用浏览器实际地图点击，经纬度经 API 反投影回同一 DEM。
        coords = page.evaluate('''() => {const x=window.ctrlnetXYZ; return x.layers.points.getLayers().slice(0,2).map(p=>{const q=x.map.latLngToContainerPoint(p.getLatLng());return [q.x-30,q.y+20];});}''')
        box = page.locator('#xyz-map').bounding_box()
        for x,y in coords:
            page.mouse.click(box['x']+x,box['y']+y)
        page.wait_for_function('document.querySelector("#profile-mode").textContent.includes("XYZ 剖面已绘制")')
        assert page.locator('#profile-chart svg').count() == 1
        page.screenshot(path=str(ROOT/'outputs/document_alignment_third_profile.png'))
        (ROOT/'outputs/document_alignment_third_coordinates.json').write_text(json.dumps(evidence,ensure_ascii=False,indent=2))
        page.goto(base+'/thesis',wait_until='networkidle')
        page.click('[data-example="1"]')
        page.wait_for_function('window.ctrlnetThesis.state.data.points.length === 9')
        page.wait_for_function('!window.ctrlnetThesis.state.busy && !window.ctrlnetThesis.map._animatingZoom')
        page.wait_for_timeout(600)
        page.fill('#snap-m','10')
        old = page.evaluate('window.ctrlnetThesis.state.data.points[0]')
        marker = page.locator('.leaflet-marker-icon[title="点 1"]')
        b = marker.bounding_box()
        page.mouse.move(b['x']+b['width']/2,b['y']+b['height']/2)
        page.mouse.down(); page.mouse.move(b['x']+b['width']/2+35,b['y']+b['height']/2+25,steps=12); page.mouse.up()
        page.wait_for_function('(old) => window.ctrlnetThesis.state.data.points[0].x !== old',arg=old['x'])
        moved = page.evaluate('window.ctrlnetThesis.state.data.points[0]')
        assert abs(moved['x']/10-round(moved['x']/10)) < 1e-8
        assert abs(moved['y']/10-round(moved['y']/10)) < 1e-8
        page.click('#undo-mutation')
        page.wait_for_function('(v) => Math.abs(window.ctrlnetThesis.state.data.points[0].x-v)<.001',arg=old['x'])
        page.click('#redo-mutation')
        page.wait_for_function('(v) => Math.abs(window.ctrlnetThesis.state.data.points[0].x-v)<.001',arg=moved['x'])
        page.locator('#map').click(position={'x':130,'y':130})
        page.wait_for_function('window.ctrlnetThesis.state.data.points.length === 10')
        added = page.evaluate('window.ctrlnetThesis.state.data.points[9]')
        assert added['x'] % 10 == 0 and added['y'] % 10 == 0
        page.click('#redo-mutation')
        page.wait_for_function('document.querySelector("#toast").textContent.includes("没有可重做")')
        page.click('#undo-mutation')
        page.wait_for_function('window.ctrlnetThesis.state.data.points.length === 9')
        page.screenshot(path=str(ROOT/'outputs/document_alignment_third_editor.png'))
        assert not errors, errors
        browser.close()
    print('PASS: XYZ warp/contour/scan/cache/known-point screenshot/profile; drag/snap/undo/redo; no pageerror')
finally:
    process.terminate(); process.wait(timeout=10)
