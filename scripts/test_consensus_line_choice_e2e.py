"""Focused HTTP + Chromium whole-line choices with differing-content criss-cross bases and restart check."""
import json
import os
from pathlib import Path
import subprocess
import sys
from playwright.sync_api import sync_playwright
from e2e_database import isolated_environment
from test_thesis_e2e import _free_port, _wait_server

ROOT = Path(__file__).resolve().parents[1]
ARTIFACTS = Path(os.environ.get('SCENARIO_ARTIFACTS', '/workspace/ctrlnet-v08/cn_post_v08_consensus_line_choice'))


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
            # Normalize the import format before branching and preserve measurement flags.
            initial = request('post', '/api/thesis/import/json', initial)
            root = request('post', '/api/engineering/save', {'name': 'root'})
            def save(name, parent):
                return request('post', '/api/engineering/save', dict(name=name, project_id=root['project_id'], parent_snapshot=parent['snapshot_id']))
            def merge(name, target, source):
                plan = request('get', '/api/engineering/merge/preview?target='+target['scenario_id']+'&source='+source['scenario_id'])
                assert plan['conflicts'] == []
                return request('post', '/api/engineering/merge', dict(plan, name=name, resolutions={}))
            a = save('a', root)
            pt = initial['points'][0]
            # Different authored ancestors must independently agree on geometry.
            request('patch', '/api/thesis/points/'+pt['id'], dict(lon=pt['lon']+.00002, lat=pt['lat']+.00001))
            b = save('b', root)
            left = merge('left', a, b)
            right = merge('right', b, a)
            bases = sorted([a['scenario_id'], b['scenario_id']])
            expected_points = {}
            children = []
            for i, parent in enumerate((left, right)):
                request('post', '/api/engineering/open/'+parent['scenario_id'], {})
                pt = initial['points'][i+1]
                state = request('patch', '/api/thesis/points/'+pt['id'], dict(lon=pt['lon']+.00003, lat=pt['lat']+.00001))
                expected_points[i+1] = state['points'][i+1]
                state['lines'][0]['name'] = 801+i
                request('post', '/api/thesis/import/json', state)
                children.append(save('edit '+str(i), parent))
            left, right = children
            page.reload(wait_until='networkidle')
            page.wait_for_function('document.querySelectorAll("#engineering-scenario option").length === 7')
            page.select_option('#engineering-scenario', left['scenario_id'])
            page.select_option('#engineering-candidate', right['scenario_id'])
            with page.expect_response(lambda r: '/merge/preview?' in r.url) as response:
                page.click('#engineering-merge-preview')
            plan = response.value.json()
            key = 'line:'+initial['lines'][0]['id']
            assert plan['conflicts'] == [key] and plan['bases'] == bases
            assert plan['differing_base_units'] == ['topology']
            page.locator('#engineering-conflicts select').select_option('source')
            page.fill('#engineering-name', 'differing bases')
            with page.expect_response(lambda r: r.url.endswith('/api/engineering/merge')) as response:
                page.click('#engineering-merge')
            assert response.value.ok, response.value.text()
            merged = response.value.json()
            page.wait_for_function('document.querySelectorAll("#engineering-scenario option").length === 8')
            page.screenshot(path=str(ARTIFACTS/'differing_bases_merge.png'))
            proc.terminate(); proc.wait(timeout=10)
            proc = start()
            page.reload(wait_until='networkidle')
            page.wait_for_function('document.querySelectorAll("#engineering-scenario option").length === 8')
            page.select_option('#engineering-scenario', merged['scenario_id'])
            with page.expect_navigation(wait_until='networkidle'):
                page.click('#engineering-open', no_wait_after=True)
            actual = request('get', '/api/thesis/state')
            for i, point in expected_points.items():
                assert actual['points'][i] == point
            from ctrlnet import store
            saved = store.get_scenario(env['CTRLNET_THESIS_DB'], merged['scenario_id'])
            assert saved['metadata']['merge_bases'] == bases
            assert saved['metadata']['merge_resolutions'] == {key: 'source'}
            assert saved['metadata']['merge_parents'] == [left['scenario_id'], right['scenario_id']]
            assert actual['lines'][0]['name'] == 802
            assert actual['name'] == initial['name']
            assert saved['name'] == 'differing bases'
            assert actual['seq'] == initial['seq']
            assert [p['id'] for p in actual['points']] == [p['id'] for p in initial['points']]
            assert ' + '.join(bases) in page.locator('#engineering-tree').inner_text()
            assert not errors, errors
            result = dict(ok=True, checks=['whole-line choice preserves independent coordinates on both tips', 'Chromium whole-line resolution with differing-content bases', 'restart/reopen retains both independent edits, order, allocators and provenance', 'tree displays both bases', 'no page errors'])
            (ARTIFACTS/'e2e.json').write_text(json.dumps(result, indent=2)+'\n')
            print(json.dumps(result))
            browser.close()
    finally:
        proc.terminate(); proc.wait(timeout=10)


if __name__ == '__main__':
    main()
