"""Focused Chromium lifecycle workflow, with isolated databases."""
import json
import os
from pathlib import Path
import subprocess
import sys
from playwright.sync_api import sync_playwright
from e2e_database import isolated_environment
from test_thesis_e2e import _free_port, _wait_server

ROOT = Path(__file__).resolve().parents[1]
ARTIFACTS = Path(os.environ.get('LIFECYCLE_ARTIFACTS', '/workspace/ctrlnet-v08/cn_post_v08_lifecycle'))


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
            sid = root['scenario_id']
            for target in ('review','approved','archived','draft'):
                page.select_option('#engineering-target', target)
                page.fill('#engineering-note', '<workflow decision>')
                page.click('#engineering-transition')
                page.wait_for_function("target => document.querySelector('#engineering-lifecycle').textContent.startsWith(target + ' · ')", arg=target)
                assert page.locator('#engineering-rename').is_disabled() == (target != 'draft')
            assert page.locator('#engineering-lifecycle workflow').count() == 0
            proc.terminate(); proc.wait(timeout=10)
            proc = start()
            page.reload(wait_until='networkidle')
            page.wait_for_function("document.querySelector('#engineering-lifecycle').textContent.includes('archived → draft')")
            rows = page.request.get(base+'/api/engineering/projects').json()['projects']
            scenario = next(s for p in rows for s in p['scenarios'] if s['id'] == sid)
            assert len(scenario['lifecycle']['history']) == 4
            assert scenario['lifecycle']['history'][1]['evidence']['input_hash']
            assert not errors, errors
            page.screenshot(path=str(ARTIFACTS/'lifecycle.png'))
            result = dict(ok=True, checks=['UI submit, approve, archive, restore', 'mutation button guards', 'escaped history', 'restart durability', 'snapshot evidence', 'no page errors'])
            (ARTIFACTS/'e2e.json').write_text(json.dumps(result,indent=2)+'\n')
            print(json.dumps(result))
            browser.close()
    finally:
        proc.terminate(); proc.wait(timeout=10)


if __name__ == '__main__':
    main()
