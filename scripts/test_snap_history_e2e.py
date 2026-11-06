"""Focused Chromium check: segment snap, drag point snap, durable undo/redo on restart.
Uses temporary databases and installed Chromium when CHROMIUM_EXECUTABLE is set.
"""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from playwright.sync_api import sync_playwright
from e2e_database import isolated_environment
from test_thesis_e2e import _free_port, _wait_server
from ctrlnet.webmap.thesis_web import _empty_state, _inverse_xy

ROOT = Path(__file__).resolve().parents[1]


def main():
    env = isolated_environment()
    port = _free_port()
    base = f'http://127.0.0.1:{port}'
    def start():
        proc = subprocess.Popen([sys.executable, '-m', 'uvicorn', 'ctrlnet.webmap.app:app', '--host', '127.0.0.1', '--port', str(port), '--log-level', 'error'], cwd=ROOT, env=env)
        _wait_server(base+'/api/health')
        return proc
    proc = start()
    try:
        with sync_playwright() as p:
            options = {'args': ['--no-sandbox']}
            if os.environ.get('CHROMIUM_EXECUTABLE'):
                options['executable_path'] = os.environ['CHROMIUM_EXECUTABLE']
            browser = p.chromium.launch(**options)
            page = browser.new_page(viewport={'width':1600, 'height':1100})
            errors = []
            page.on('pageerror', lambda e: errors.append(str(e)))
            def post(path, body):
                r = page.request.post(base+path, data=body)
                assert r.ok, r.text()
                return r.json()
            post('/api/thesis/import/coordinates', {'text':'1；3800000，500000\n2；3800100，500000\n3；3800050，500050', 'name':'snap-e2e'})
            post('/api/thesis/lines', {'from':'p1', 'to':'p2'})
            page.goto(base+'/thesis', wait_until='networkidle')
            page.wait_for_function('window.ctrlnetThesis && window.ctrlnetThesis.state.data.points.length === 3')
            page.fill('#snap-geometry-m', '3')
            lat, lon = _inverse_xy(_empty_state(), 3800050, 500002)
            # Leaflet's normal map click listener reads the UI snap distance.
            page.evaluate('([lat,lng]) => window.ctrlnetThesis.map.fire("click", {latlng:L.latLng(lat,lng)})', [lat,lon])
            page.wait_for_function('window.ctrlnetThesis.state.data.points.length === 4 && !window.ctrlnetThesis.state.busy')
            snapped = page.request.get(base+'/api/thesis/state').json()
            assert snapped['points'][-1]['y'] == 500000
            # Normal draggable marker listener excludes the point itself.
            target = snapped['points'][1]
            page.evaluate('([lat,lng]) => { const marker = window.ctrlnetThesis.state.layers.points.getLayers()[2]; marker.setLatLng([lat,lng]); marker.fire("dragend"); }', [target['lat'], target['lon']])
            page.wait_for_function('!window.ctrlnetThesis.state.busy && window.ctrlnetThesis.state.data.points[2].y === 500000')
            moved = page.request.get(base+'/api/thesis/state').json()
            assert moved['points'][2]['x'] == target['x']
            proc.terminate(); proc.wait(timeout=10)
            proc = start()
            page.reload(wait_until='networkidle')
            page.wait_for_function('window.ctrlnetThesis')
            assert page.request.get(base+'/api/thesis/state').json() == moved
            page.click('#undo-mutation')
            page.wait_for_function('!window.ctrlnetThesis.state.busy && window.ctrlnetThesis.state.data.points[2].y === 500050')
            assert page.request.get(base+'/api/thesis/state').json() == snapped
            page.reload(wait_until='networkidle')
            page.wait_for_function('window.ctrlnetThesis')
            page.click('#redo-mutation')
            page.wait_for_function('!window.ctrlnetThesis.state.busy && window.ctrlnetThesis.state.data.points[2].y === 500000')
            assert page.request.get(base+'/api/thesis/state').json() == moved
            assert not errors, errors
            print(json.dumps({'ok':True,'checks':['UI segment snap','UI drag point snap','server restart draft recovery','undo after restart','redo after reload','no page errors']}))
            browser.close()
    finally:
        proc.terminate(); proc.wait(timeout=10)


if __name__ == '__main__':
    main()
