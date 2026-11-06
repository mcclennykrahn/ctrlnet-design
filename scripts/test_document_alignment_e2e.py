"""Document alignment UI regression plus optional live public-tile probe (no bulk download)."""
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
        page = browser.new_page(viewport={'width':1440,'height':1000})
        errors = []
        page.on('pageerror', lambda err: errors.append(str(err)))
        page.goto(base + '/thesis', wait_until='networkidle')
        page.wait_for_selector('#basemap-select option[value="satellite"]', state='attached')
        assert '117°E' in page.inner_text('#projection-summary')
        assert page.locator('#basemap-select option').count() >= 4
        page.click('[data-example="1"]')
        page.wait_for_function('window.ctrlnetThesis.state.data.points.length === 9')
        page.click('#export-coords')
        page.wait_for_selector('#export-modal:not(.hidden)')
        text = page.inner_text('#export-text')
        page.click('#close-export')
        page.on('dialog', lambda dialog: dialog.accept())
        page.set_input_files('#coordinate-file', {'name':'roundtrip.txt','mimeType':'text/plain','buffer':text.encode()})
        page.wait_for_function('window.ctrlnetThesis.state.data.name === "roundtrip.txt"')
        assert page.locator('#point-body tr').count() == 9
        assert page.locator('#line-body tr').count() == 0
        page.fill('#line-start','1'); page.fill('#line-end','2'); page.click('#add-line')
        page.wait_for_function('window.ctrlnetThesis.state.data.lines.length === 1')
        for selector,value in [('#angle-back','1'),('#angle-station','2'),('#angle-fore','3')]: page.fill(selector,value)
        page.click('#add-angle')
        page.wait_for_function('window.ctrlnetThesis.state.data.angles.length === 1')
        page.fill('#project-name','document-alignment-ui'); page.click('#save-project')
        page.wait_for_selector('#project-select option[value="document-alignment-ui"]', state='attached')
        page.click('#new-project')
        page.wait_for_function('window.ctrlnetThesis.state.data.points.length === 0')
        page.select_option('#project-select','document-alignment-ui'); page.click('#load-project')
        page.wait_for_function('window.ctrlnetThesis.state.data.points.length === 9')
        page.route('https://tile.openstreetmap.org/**', lambda route: route.abort())
        page.select_option('#basemap-select','road')
        page.wait_for_function('document.querySelector("#basemap-status").textContent.includes("瓦片未加载")')
        assert page.input_value('#basemap-select') == 'offline'
        page.unroute('https://tile.openstreetmap.org/**')
        page.wait_for_timeout(800)
        page.screenshot(path=str(ROOT/'outputs/document_alignment_editor.png'))
        live = {}
        # Browser requests through normal tile layers, with no proxy or secret.
        for mode in ['road','satellite']:
            page.select_option('#basemap-select',mode)
            page.wait_for_function('!document.querySelector("#basemap-status").textContent.includes("正在加载")', timeout=18000)
            page.wait_for_timeout(800)
            live[mode] = page.inner_text('#basemap-status')
            page.screenshot(path=str(ROOT/f'outputs/document_alignment_{mode}.png'))
            page.select_option('#basemap-select','offline')
        page.goto(base + '/', wait_until='networkidle')
        assert page.locator('a[href="/thesis"]').count() >= 1
        page.wait_for_selector('#scenario-select option', state='attached')
        assert not errors, errors
        (ROOT/'outputs/document_alignment_network.json').write_text(json.dumps(live,ensure_ascii=False,indent=2)+'\n')
        print('UI PASS: import, line/angle, save/new/load, offline/network failure, dashboard entry')
        print(json.dumps(live,ensure_ascii=False))
        browser.close()
finally:
    process.terminate(); process.wait(timeout=10)
