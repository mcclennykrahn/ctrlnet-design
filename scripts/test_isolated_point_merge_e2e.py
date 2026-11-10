"""Focused HTTP + Chromium isolated point addition merge and restart check."""
import json
import os
from pathlib import Path
import subprocess
import sys
from playwright.sync_api import sync_playwright
from e2e_database import isolated_environment
from test_thesis_e2e import _free_port, _wait_server

ROOT = Path(__file__).resolve().parents[1]
ARTIFACTS = Path(os.environ.get('SCENARIO_ARTIFACTS', '/workspace/ctrlnet-v08/cn_post_v08_isolated_point_merge'))


def main():
    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    env = isolated_environment()
    base = f'http://127.0.0.1:{_free_port()}'

    def start():
        proc = subprocess.Popen([sys.executable, '-m', 'uvicorn', 'ctrlnet.webmap.app:app', '--host', '127.0.0.1', '--port', base.rsplit(':', 1)[1], '--log-level', 'error'], cwd=ROOT, env=env)
        _wait_server(base+'/api/health')
        return proc

    proc = start()
    try:
        with sync_playwright() as p:
            options = {'args': ['--no-sandbox']}
            if os.environ.get('CHROMIUM_EXECUTABLE'):
                options['executable_path'] = os.environ['CHROMIUM_EXECUTABLE']
            browser = p.chromium.launch(**options)
            page = browser.new_page(viewport={'width': 1600, 'height': 1200})
            errors = []
            page.on('pageerror', lambda e: errors.append(str(e)))
            page.on('dialog', lambda d: d.accept())
            page.goto(base+'/thesis', wait_until='networkidle')

            def request(method, path, data=None):
                r = getattr(page.request, method)(base+path, **({'data': data} if data is not None else {}))
                assert r.ok, r.text()
                return r.json()

            initial = request('post', '/api/thesis/examples/1', {})
            # Import intentionally drops the example's measured line overrides.
            initial = request('post', '/api/thesis/import/json', initial)
            root = request('post', '/api/engineering/save', {'name': 'base'})
            from ctrlnet import store
            pt = next(pt for pt in initial['points'] if not pt['fixed'])
            moved = request('patch', '/api/thesis/points/'+pt['id'],
                            dict(lon=pt['lon']+.00001, lat=pt['lat']+.00001))
            expected_point = next(x for x in moved['points'] if x['id'] == pt['id'])
            left = request('post', '/api/engineering/save', dict(name='coordinate branch', project_id=root['project_id'], parent_snapshot=root['snapshot_id']))
            request('post', '/api/engineering/open/'+root['scenario_id'], {})
            added = request('post', '/api/thesis/points', dict(lon=pt['lon']+.001, lat=pt['lat']+.001))
            extra = added['points'][-1]
            right = request('post', '/api/engineering/save', dict(name='isolated addition', project_id=root['project_id'], parent_snapshot=root['snapshot_id']))
            branches = [left, right]
            page.reload(wait_until='networkidle')
            page.wait_for_function('document.querySelectorAll("#engineering-scenario option").length === 3')
            page.select_option('#engineering-scenario', branches[0]['scenario_id'])
            page.select_option('#engineering-candidate', branches[1]['scenario_id'])
            with page.expect_response(lambda r: '/merge/preview?' in r.url) as response:
                page.click('#engineering-merge-preview')
            assert response.value.json()['conflicts'] == []
            page.fill('#engineering-name', 'isolated addition and coordinates')
            with page.expect_response(lambda r: r.url.endswith('/api/engineering/merge')) as response:
                page.click('#engineering-merge')
            assert response.value.ok, response.value.text()
            merged = response.value.json()
            page.wait_for_function('document.querySelectorAll("#engineering-scenario option").length === 4')
            page.screenshot(path=str(ARTIFACTS/'isolated_point_merge.png'))
            proc.terminate(); proc.wait(timeout=10)
            proc = start()
            page.reload(wait_until='networkidle')
            page.wait_for_function('document.querySelectorAll("#engineering-scenario option").length === 4')
            page.select_option('#engineering-scenario', merged['scenario_id'])
            with page.expect_navigation(wait_until='networkidle'):
                page.click('#engineering-open')
            actual = request('get', '/api/thesis/state')
            assert next(x for x in actual['points'] if x['id'] == pt['id']) == expected_point
            assert [x['id'] for x in actual['points']] == [x['id'] for x in moved['points']] + [extra['id']]
            assert actual['points'][-1] == extra
            saved = store.get_scenario(env['CTRLNET_THESIS_DB'], merged['scenario_id'])
            assert saved['metadata']['merge_parents'] == [left['scenario_id'], right['scenario_id']]
            # A subsequent editor addition must allocate a fresh ID.
            next_state = request('post', '/api/thesis/points', dict(lon=pt['lon']+.002, lat=pt['lat']+.002))
            assert len({p['id'] for p in next_state['points']}) == len(next_state['points'])
            assert not errors, errors
            result = dict(ok=True, checks=['HTTP coordinate and isolated addition branches', 'Chromium conflict-free preview and merge', 'restart and UI reopen retain coordinates, addition, target order and dual parents', 'subsequent editor addition uses fresh ID', 'no page errors'])
            (ARTIFACTS/'e2e.json').write_text(json.dumps(result, indent=2)+'\n')
            print(json.dumps(result))
            browser.close()
    finally:
        proc.terminate(); proc.wait(timeout=10)


if __name__ == '__main__':
    main()
