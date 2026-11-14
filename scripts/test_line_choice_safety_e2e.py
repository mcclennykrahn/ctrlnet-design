"""Focused Chromium whole-topology fallback for alternate line-choice collisions."""
import json
import os
from pathlib import Path
import subprocess
import sys
from playwright.sync_api import sync_playwright
from e2e_database import isolated_environment
from test_thesis_e2e import _free_port, _wait_server

ROOT = Path(__file__).resolve().parents[1]
ARTIFACTS = Path(os.environ.get('SCENARIO_ARTIFACTS', '/workspace/ctrlnet-v08/cn_post_v08_line_choice_safety'))


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
            original = store.get_scenario(env['CTRLNET_THESIS_DB'], root['scenario_id'])['metadata']['thesis_state']
            target_state = copy.deepcopy(original)
            # Choose a free endpoint pair so each branch is valid on its own.
            from itertools import combinations
            occupied = {frozenset((line['from'], line['to'])) for line in original['lines']}
            pair = next(pair for pair in combinations([pt['id'] for pt in original['points']], 2)
                        if frozenset(pair) not in occupied)
            addition = dict(id='l900', name='900', **{'from': pair[0], 'to': pair[1]},
                            length=123.25, _keep_length=True)
            target_state['lines'].append(addition)
            target_state['seq']['line'] = 901
            target_state['lines'][0]['name'] = 801
            target_state['network']['observed_edges'].append('l900')
            source_state = copy.deepcopy(original)
            source_state['lines'][0].update({'name': 802, 'from': pair[1], 'to': pair[0]})
            def seed(state, name):
                records, observations = editor_records(state)
                return store.save_editor_version(env['CTRLNET_THESIS_DB'],
                    dict(id=root['project_id'], name=name, points=records),
                    dict(name=name, observations=observations, metadata={'thesis_state': state}),
                    parent_snapshot=root['snapshot_id'])
            left = seed(target_state, 'selected measured addition')
            right = seed(source_state, 'competing endpoint edit')
            branches = [left, right]
            page.reload(wait_until='networkidle')
            page.wait_for_function('document.querySelectorAll("#engineering-scenario option").length === 3')
            page.select_option('#engineering-scenario', branches[0]['scenario_id'])
            page.select_option('#engineering-candidate', branches[1]['scenario_id'])
            with page.expect_response(lambda r: '/merge/preview?' in r.url) as response:
                page.click('#engineering-merge-preview')
            assert response.value.json()['conflicts'] == ['topology']
            page.select_option('select[data-unit="topology"]', 'target')
            page.fill('#engineering-name', 'safe whole topology')
            with page.expect_response(lambda r: r.url.endswith('/api/engineering/merge')) as response:
                page.click('#engineering-merge')
            assert response.value.ok, response.value.text()
            merged = response.value.json()
            page.wait_for_function('document.querySelectorAll("#engineering-scenario option").length === 4')
            page.screenshot(path=str(ARTIFACTS/'line_choice_safety.png'))
            proc.terminate(); proc.wait(timeout=10)
            proc = start()
            page.reload(wait_until='networkidle')
            page.wait_for_function('document.querySelectorAll("#engineering-scenario option").length === 4')
            page.select_option('#engineering-scenario', merged['scenario_id'])
            with page.expect_navigation(wait_until='networkidle'):
                page.click('#engineering-open')
            actual = request('get', '/api/thesis/state')
            saved = store.get_scenario(env['CTRLNET_THESIS_DB'], merged['scenario_id'])
            assert saved['metadata']['thesis_state'] == target_state
            assert saved['metadata']['merge_parents'] == [left['scenario_id'], right['scenario_id']]
            assert actual['lines'][-1]['length'] == 123.25
            assert 'l900' in actual['network']['observed_edges']
            assert actual['seq']['line'] == 901
            pairs = [frozenset((line['from'], line['to'])) for line in actual['lines']]
            assert len(pairs) == len(set(pairs))
            assert not errors, errors
            result = dict(ok=True, checks=['valid branches with alternate endpoint collision', 'Chromium whole-topology preview and target choice', 'restart/reopen preserves selected measured addition, target order, allocator and dual parents', 'no duplicate endpoint pairs or page errors'])
            (ARTIFACTS/'e2e.json').write_text(json.dumps(result, indent=2)+'\n')
            print(json.dumps(result))
            browser.close()
    finally:
        proc.terminate(); proc.wait(timeout=10)


if __name__ == '__main__':
    main()
