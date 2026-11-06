"""Focused Chromium scenario tree, rename and merge, with isolated databases."""
import json
import os
from pathlib import Path
import subprocess
import sys
from playwright.sync_api import sync_playwright
from e2e_database import isolated_environment
from test_thesis_e2e import _free_port, _wait_server

ROOT = Path(__file__).resolve().parents[1]
ARTIFACTS = Path(os.environ.get('SCENARIO_ARTIFACTS', '/workspace/ctrlnet-v08/cn_post_v08_scenario_tree'))


def main():
    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    env = isolated_environment()
    base = f'http://127.0.0.1:{_free_port()}'
    def start():
        proc = subprocess.Popen([sys.executable,'-m','uvicorn','ctrlnet.webmap.app:app','--host','127.0.0.1','--port',base.rsplit(':',1)[1],'--log-level','error'],cwd=ROOT,env=env)
        _wait_server(base+'/api/health')
        return proc
    proc = start()
    try:
        with sync_playwright() as p:
            options = {'args':['--no-sandbox']}
            if os.environ.get('CHROMIUM_EXECUTABLE'):
                options['executable_path'] = os.environ['CHROMIUM_EXECUTABLE']
            browser = p.chromium.launch(**options)
            page = browser.new_page(viewport={'width':1600,'height':1200})
            errors = []
            page.on('pageerror',lambda e:errors.append(str(e)))
            page.on('dialog',lambda d:d.accept())
            page.goto(base+'/thesis',wait_until='networkidle')
            page.click('[data-example="1"]')
            page.wait_for_function('window.ctrlnetThesis.state.data.points.length === 9 && !window.ctrlnetThesis.state.busy')
            page.fill('#engineering-name','base')
            page.click('#engineering-save')
            page.wait_for_function('document.querySelector("#engineering-result").textContent.includes("snapshot_id")')
            root = json.loads(page.text_content('#engineering-result'))
            def branch(name, sigma):
                r = page.request.post(base+'/api/engineering/save',data=dict(name=name,project_id=root['project_id'],parent_snapshot=root['snapshot_id'],gnss=[dict(**{'from':'8','to':'1'},sigma_E=sigma,sigma_N=.007,correlation=.3)]))
                assert r.ok, r.text()
                return r.json()
            a, b = branch('left',.005), branch('right',.02)
            page.click('#engineering-refresh')
            page.wait_for_function('document.querySelectorAll("#engineering-scenario option").length === 3')
            page.select_option('#engineering-scenario',a['scenario_id'])
            page.fill('#engineering-name','renamed <left>')
            page.click('#engineering-rename')
            page.wait_for_function('document.querySelector("#engineering-tree").textContent.includes("renamed <left>")')
            assert page.locator('#engineering-tree left').count() == 0
            page.select_option('#engineering-candidate',b['scenario_id'])
            page.click('#engineering-merge-preview')
            page.wait_for_selector('#engineering-conflicts select[data-unit="gnss"]')
            page.fill('#engineering-name','merged')
            page.click('#engineering-merge')
            page.wait_for_function('document.querySelector("#engineering-summary").textContent.includes("target/source")')
            assert len(page.request.get(base+'/api/engineering/projects').json()['projects'][0]['scenarios']) == 3
            page.select_option('#engineering-conflicts select[data-unit="gnss"]','source')
            page.click('#engineering-merge')
            page.wait_for_function('document.querySelector("#engineering-result").textContent.includes("merge_parents") || document.querySelector("#engineering-result").textContent.includes("snapshot_id")')
            page.wait_for_function('document.querySelectorAll("#engineering-scenario option").length === 4')
            merged = json.loads(page.text_content('#engineering-result'))
            assert merged['merge']['base'] == root['scenario_id']
            tree = page.text_content('#engineering-tree')
            assert a['scenario_id']+' + '+b['scenario_id'] in tree
            assert '  └' in tree
            page.screenshot(path=str(ARTIFACTS/'scenario_tree.png'))
            proc.terminate(); proc.wait(timeout=10)
            proc = start()
            page.reload(wait_until='networkidle')
            page.wait_for_function('document.querySelectorAll("#engineering-scenario option").length === 4')
            assert 'renamed <left>' in page.text_content('#engineering-tree')
            page.select_option('#engineering-scenario',merged['scenario_id'])
            with page.expect_navigation(wait_until='networkidle'):
                page.click('#engineering-open')
            assert page.locator('#engineering-gnss input[data-key="sigma_E"]').input_value() == '0.02'
            assert not errors, errors
            result = dict(ok=True,checks=['tree hierarchy and both merge parents','UI durable rename with escaped name','conflict requires explicit selection','UI merge creates new scenario','restart preserves tree and rename','merged GNSS reopened in editor','no page errors'])
            (ARTIFACTS/'e2e.json').write_text(json.dumps(result,indent=2)+'\n')
            print(json.dumps(result))
            browser.close()
    finally:
        proc.terminate(); proc.wait(timeout=10)


if __name__ == '__main__':
    main()
