"""Focused HTTP + Chromium selected measured line addition and restart check."""
import json
import os
from pathlib import Path
import subprocess
import sys
from playwright.sync_api import sync_playwright
from e2e_database import isolated_environment
from test_thesis_e2e import _free_port, _wait_server

ROOT = Path(__file__).resolve().parents[1]
ARTIFACTS = Path(os.environ.get('SCENARIO_ARTIFACTS', '/workspace/ctrlnet-v08/cn_post_v08_selected_line_addition'))


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
            initial['network']['observed_edges'] = []
            initial['network']['added_edges'] = []
            for line in initial['lines']:
                for field in ('from_name', 'to_name', 'status'):
                    line.pop(field, None)
            # Import intentionally drops the example's measured line overrides.
            initial = request('post', '/api/thesis/import/json', initial)
            removed = initial['lines'][0]
            initial = request('delete', '/api/thesis/lines/'+removed['id'])
            root = request('post', '/api/engineering/save', {'name': 'base'})
            from ctrlnet import store
            pt = next(pt for pt in initial['points'] if pt['id'] == removed['from'])
            added = request('post', '/api/thesis/lines', {'from': removed['from'], 'to': removed['to']})
            added_line = added['lines'][-1]
            # The editor has no measurement editing endpoint; seed the authored
            # measurement through the store, then exercise the real merge UI.
            from ctrlnet.webmap.project_bridge import editor_records
            import copy
            state = copy.deepcopy(store.get_scenario(env['CTRLNET_THESIS_DB'], root['scenario_id'])['metadata']['thesis_state'])
            state['lines'].append(copy.deepcopy(added_line))
            state['seq']['line'] = added['seq']['line']
            # Public display-only fields are absent from persisted snapshots.
            for line in state['lines']:
                for field in ('from_name', 'to_name', 'status'):
                    line.pop(field, None)
            state['lines'][-1].update(length=123.25, _keep_length=True)
            state['network']['observed_edges'].append(added_line['id'])
            records, observations = editor_records(state)
            left = store.save_editor_version(env['CTRLNET_THESIS_DB'],
                dict(id=root['project_id'], name='measured addition', points=records),
                dict(name='measured addition', observations=observations, metadata={'thesis_state': state}),
                parent_snapshot=root['snapshot_id'])
            request('post', '/api/engineering/open/'+root['scenario_id'], {})
            moved = request('patch', '/api/thesis/points/'+pt['id'],
                            dict(lon=pt['lon']+.00001, lat=pt['lat']+.00001))
            expected_point = next(x for x in moved['points'] if x['id'] == pt['id'])
            right = request('post', '/api/engineering/save', dict(name='coordinates', project_id=root['project_id'], parent_snapshot=root['snapshot_id']))
            branches = [left, right]
            page.reload(wait_until='networkidle')
            page.wait_for_function('document.querySelectorAll("#engineering-scenario option").length === 3')
            page.select_option('#engineering-scenario', branches[0]['scenario_id'])
            page.select_option('#engineering-candidate', branches[1]['scenario_id'])
            with page.expect_response(lambda r: '/merge/preview?' in r.url) as response:
                page.click('#engineering-merge-preview')
            assert response.value.json()['conflicts'] == []
            page.fill('#engineering-name', 'line addition and coordinates')
            with page.expect_response(lambda r: r.url.endswith('/api/engineering/merge')) as response:
                page.click('#engineering-merge')
            assert response.value.ok, response.value.text()
            merged = response.value.json()
            page.wait_for_function('document.querySelectorAll("#engineering-scenario option").length === 4')
            page.screenshot(path=str(ARTIFACTS/'line_addition_merge.png'))
            proc.terminate(); proc.wait(timeout=10)
            proc = start()
            page.reload(wait_until='networkidle')
            page.wait_for_function('document.querySelectorAll("#engineering-scenario option").length === 4')
            page.select_option('#engineering-scenario', merged['scenario_id'])
            with page.expect_navigation(wait_until='networkidle'):
                page.click('#engineering-open', no_wait_after=True)
            actual = request('get', '/api/thesis/state')
            assert next(x for x in actual['points'] if x['id'] == pt['id']) == expected_point
            assert [x['id'] for x in actual['lines']] == [x['id'] for x in added['lines']]
            assert added_line['id'] in {x['id'] for x in actual['lines']}
            assert actual['seq']['line'] == added['seq']['line']
            assert actual['lines'][-1]['length'] == 123.25
            assert actual['lines'][-1]['azimuth'] != added_line['azimuth']
            saved = store.get_scenario(env['CTRLNET_THESIS_DB'], merged['scenario_id'])
            assert saved['metadata']['thesis_state']['lines'][-1]['_keep_length'] is True
            assert actual['network']['observed_edges'] == [added_line['id']]
            assert saved['metadata']['merge_parents'] == [left['scenario_id'], right['scenario_id']]
            request('delete', '/api/thesis/lines/'+added_line['id'])
            next_state = request('post', '/api/thesis/lines', {'from': removed['from'], 'to': removed['to']})
            assert next_state['lines'][-1]['id'] not in {x['id'] for x in added['lines']}
            assert not errors, errors
            result = dict(ok=True, checks=['HTTP line addition and coordinates', 'Chromium conflict-free preview and merge', 'restart/reopen retains addition, preserved measurement, recomputed azimuth, coordinates, target order and dual parents', 'fresh line allocation', 'no page errors'])
            (ARTIFACTS/'e2e.json').write_text(json.dumps(result, indent=2)+'\n')
            print(json.dumps(result))
            browser.close()
    finally:
        proc.terminate(); proc.wait(timeout=10)


if __name__ == '__main__':
    main()
