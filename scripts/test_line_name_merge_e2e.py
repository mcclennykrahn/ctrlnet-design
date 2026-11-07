"""Focused HTTP + Chromium ID-based reordered topology merge and restart check."""
import json
import os
from pathlib import Path
import subprocess
import sys
from playwright.sync_api import sync_playwright
from e2e_database import isolated_environment
from test_thesis_e2e import _free_port, _wait_server

ROOT = Path(__file__).resolve().parents[1]
ARTIFACTS = Path(os.environ.get('SCENARIO_ARTIFACTS', '/workspace/ctrlnet-v08/cn_post_v08_line_name_merge'))


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
            from ctrlnet.webmap.project_bridge import editor_records
            import copy
            pt = next(pt for pt in initial['points'] if not pt['fixed'])
            moved = request('patch', '/api/thesis/points/'+pt['id'],
                            dict(lon=pt['lon']+.00001, lat=pt['lat']+.00001))
            expected_point = next(x for x in moved['points'] if x['id'] == pt['id'])
            aid = moved['lines'][0]['id']
            target_state = copy.deepcopy(store.get_scenario(env['CTRLNET_THESIS_DB'], root['scenario_id'])['metadata']['thesis_state'])
            target_state['points'] = moved['points']
            target_state['lines'][0]['name'] = 801
            records, observations = editor_records(target_state)
            left = store.save_editor_version(env['CTRLNET_THESIS_DB'],
                dict(id=root['project_id'], name='target line', points=records),
                dict(name='target line', observations=observations, metadata={'thesis_state': target_state}),
                parent_snapshot=root['snapshot_id'])
            # Seed a saved measured branch through the store: the editor has no
            # line-override editing endpoint. UI preview/merge uses real HTTP.
            state = copy.deepcopy(store.get_scenario(env['CTRLNET_THESIS_DB'], root['scenario_id'])['metadata']['thesis_state'])
            state['lines'][0]['name'] = 802
            line_id = state['lines'][0]['id']
            state['lines'][0].update(length=123.25, _keep_length=True)
            state['points'].reverse()
            state['lines'].reverse()
            assert len(state['angles']) > 1
            state['angles'].reverse()
            records, observations = editor_records(state)
            right = store.save_editor_version(env['CTRLNET_THESIS_DB'],
                dict(id=root['project_id'], name='measured branch', points=records),
                dict(name='measured branch', observations=observations, metadata={'thesis_state': state}),
                parent_snapshot=root['snapshot_id'])
            branches = [left, right]
            page.reload(wait_until='networkidle')
            page.wait_for_function('document.querySelectorAll("#engineering-scenario option").length === 3')
            page.select_option('#engineering-scenario', branches[0]['scenario_id'])
            page.select_option('#engineering-candidate', branches[1]['scenario_id'])
            with page.expect_response(lambda r: '/merge/preview?' in r.url) as response:
                page.click('#engineering-merge-preview')
            assert response.value.json()['conflicts'] == ['line:'+aid]
            page.select_option('select[data-unit="line:'+aid+'"]', 'source')
            page.fill('#engineering-name', 'reordered source and coordinates')
            with page.expect_response(lambda r: r.url.endswith('/api/engineering/merge')) as response:
                page.click('#engineering-merge')
            assert response.value.ok, response.value.text()
            merged = response.value.json()
            page.wait_for_function('document.querySelectorAll("#engineering-scenario option").length === 4')
            page.screenshot(path=str(ARTIFACTS/'line_name_merge.png'))
            proc.terminate(); proc.wait(timeout=10)
            proc = start()
            page.reload(wait_until='networkidle')
            page.wait_for_function('document.querySelectorAll("#engineering-scenario option").length === 4')
            page.select_option('#engineering-scenario', merged['scenario_id'])
            with page.expect_navigation(wait_until='networkidle'):
                page.click('#engineering-open')
            actual = request('get', '/api/thesis/state')
            assert next(x for x in actual['points'] if x['id'] == pt['id']) == expected_point
            assert [x['id'] for x in actual['points']] == [x['id'] for x in moved['points']]
            assert [x['id'] for x in actual['lines']] == [x['id'] for x in moved['lines']]
            assert [x['id'] for x in actual['angles']] == [x['id'] for x in moved['angles']]
            assert next(x for x in actual['lines'] if x['id'] == line_id)['length'] == 123.25
            assert next(a for a in actual['lines'] if a['id'] == aid)['name'] == 802
            saved = store.get_scenario(env['CTRLNET_THESIS_DB'], merged['scenario_id'])
            assert saved['metadata']['thesis_state']['lines'][0]['_keep_length'] is True
            assert not errors, errors
            result = dict(ok=True, checks=['HTTP coordinates and store-seeded competing numeric line names', 'Chromium whole-line source choice', 'restart and UI reopen preserve coordinate, measured override and target order', 'no page errors'])
            (ARTIFACTS/'e2e.json').write_text(json.dumps(result, indent=2)+'\n')
            print(json.dumps(result))
            browser.close()
    finally:
        proc.terminate(); proc.wait(timeout=10)


if __name__ == '__main__':
    main()
