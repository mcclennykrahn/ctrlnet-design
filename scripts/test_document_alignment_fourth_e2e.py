"""第四批共享工程 + 参数，真实 Chromium；进程独立 SQLite。"""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from playwright.sync_api import sync_playwright
from test_thesis_e2e import _free_port, _wait_server

ROOT = Path(__file__).resolve().parents[1]
with tempfile.TemporaryDirectory(prefix='ctrlnet-fourth-') as temp:
    db = Path(temp)/'demo.sqlite'
    shutil.copy2(ROOT/'data/sample/demo_project.sqlite', db)
    for resource in (ROOT/'data/sample').iterdir():
        if resource.suffix not in ('.sqlite', '.db'):
            (Path(temp)/resource.name).symlink_to(resource)
    env = dict(os.environ, CTRLNET_DB=str(db), CTRLNET_THESIS_DB=str(Path(temp)/'engineering.sqlite'))
    port = _free_port()
    base = f'http://127.0.0.1:{port}'
    proc = subprocess.Popen([sys.executable,'-m','uvicorn','ctrlnet.webmap.app:app','--host','127.0.0.1','--port',str(port),'--log-level','error'],cwd=ROOT,env=env)
    try:
        _wait_server(base+'/api/health')
        with sync_playwright() as p:
            browser = p.chromium.launch(args=['--no-sandbox'])
            page = browser.new_page(viewport={'width':1600,'height':1200})
            errors=[]
            page.on('pageerror',lambda e:errors.append(str(e)))
            page.on('dialog',lambda d:d.accept())
            page.goto(base+'/thesis',wait_until='networkidle')
            page.click('[data-example="1"]')
            page.wait_for_function('window.ctrlnetThesis.state.data.points.length === 9')
            page.locator('#observed-edge-list input').first.check()
            page.wait_for_function('window.ctrlnetThesis.state.data.network.observed_edges.length === 1 && !window.ctrlnetThesis.state.busy')
            original=page.request.get(base+'/api/thesis/state').json()
            page.fill('#engineering-name','第四批共享工程')
            page.click('#engineering-save')
            page.wait_for_function('document.querySelector("#engineering-result").textContent.includes("snapshot_id")')
            a=json.loads(page.text_content('#engineering-result'))
            page.locator('#observed-edge-list input').nth(1).check()
            page.wait_for_function('window.ctrlnetThesis.state.data.network.observed_edges.length === 2 && !window.ctrlnetThesis.state.busy')
            page.fill('#engineering-name','分支方案')
            page.click('#engineering-branch')
            page.wait_for_function('document.querySelector("#engineering-result").textContent.includes(\'"version": 2\')')
            b=json.loads(page.text_content('#engineering-result'))
            page.select_option('#engineering-scenario',a['scenario_id'])
            with page.expect_navigation(wait_until='networkidle'):
                page.click('#engineering-open')
            loaded=page.request.get(base+'/api/thesis/state').json()
            for key in ('points','lines','angles','network','projection'):
                assert loaded[key] == original[key], key
            page.select_option('#engineering-project',a['project_id'])
            page.select_option('#engineering-scenario',a['scenario_id'])
            page.click('#engineering-calculate')
            page.wait_for_function('document.querySelector("#engineering-result").textContent.includes("sigma_E_mm")')
            low=json.loads(page.text_content('#engineering-result'))
            page.select_option('#engineering-confidence','0.99')
            page.click('#engineering-calculate')
            page.wait_for_function('document.querySelector("#engineering-result").textContent.includes(\'"confidence": 0.99\')')
            high=json.loads(page.text_content('#engineering-result'))
            assert low['input_hash'] != high['input_hash']
            assert {o['kind'] for o in high['observations']} == {'angle','distance'}
            assert max(p['ellipse']['a_m'] for p in high['points']) > max(p['ellipse']['a_m'] for p in low['points'])
            page.screenshot(path=str(ROOT/'outputs/document_alignment_fourth_thesis.png'))
            page.goto(base+'/dashboard',wait_until='networkidle')
            page.wait_for_function('window.ctrlnetReady === true')
            page.click('#engineering-panel > summary')
            page.select_option('#engineering-project',a['project_id'])
            page.select_option('#engineering-scenario',a['scenario_id'])
            page.select_option('#engineering-candidate',b['scenario_id'])
            page.click('#engineering-compare')
            page.wait_for_function('document.querySelector("#engineering-result").textContent.includes("base_hash")')
            diff=json.loads(page.text_content('#engineering-result'))
            assert diff['base_hash'] != diff['candidate_hash']
            page.screenshot(path=str(ROOT/'outputs/document_alignment_fourth_dashboard.png'))
            assert page.request.get(base+'/api/project').json()['selected_scenario'] == 'dem-all'
            assert not errors,errors
            (ROOT/'outputs/document_alignment_fourth_evidence.json').write_text(json.dumps(dict(saved=a,branch=b,options=[low['options'],high['options']],compare=diff,pageerrors=errors),ensure_ascii=False,indent=2))
            browser.close()
        print('PASS: thesis named project/save/parent snapshot/branch/open topology; 95/99% UI/API/ellipse; dashboard scoped selection/compare; no global map overwrite; zero pageerror')
    finally:
        proc.terminate();proc.wait(timeout=10)
