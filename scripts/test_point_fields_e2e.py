"""Focused real HTTP + Chromium point field merge and restart check."""
import json
import os
from pathlib import Path
import subprocess
import sys
from playwright.sync_api import sync_playwright
from e2e_database import isolated_environment
from test_thesis_e2e import _free_port, _wait_server

ROOT = Path(__file__).resolve().parents[1]
ARTIFACTS = Path(os.environ.get('SCENARIO_ARTIFACTS', '/workspace/ctrlnet-v08/cn_post_v08_point_fields'))


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
            points = [pt for pt in initial['points'] if not pt['fixed']][:2]
            assert len(points) == 2
            expected = {}
            branches = []
            for i, pt in enumerate([points[0], points[0]]):
                request('post', '/api/engineering/open/'+root['scenario_id'], {})
                moved = request('patch', '/api/thesis/points/'+pt['id'], (dict(lon=pt['lon']+.00001, lat=pt['lat']+.00001) if i == 0 else dict(fixed=True)))
                if i == 0:
                    expected[pt['id']] = next(x for x in moved['points'] if x['id'] == pt['id'])
                else:
                    expected[pt['id']]['fixed'] = True
                branches.append(request('post', '/api/engineering/save', dict(name=f'branch {i}', project_id=root['project_id'], parent_snapshot=root['snapshot_id'])))
            page.reload(wait_until='networkidle')
            page.wait_for_function('document.querySelectorAll("#engineering-scenario option").length === 3')
            page.select_option('#engineering-scenario', branches[0]['scenario_id'])
            page.select_option('#engineering-candidate', branches[1]['scenario_id'])
            with page.expect_response(lambda r: '/merge/preview?' in r.url) as response:
                page.click('#engineering-merge-preview')
            assert response.value.json()['conflicts'] == []
            page.fill('#engineering-name', 'coordinates and fixed flag')
            with page.expect_response(lambda r: r.url.endswith('/api/engineering/merge')) as response:
                page.click('#engineering-merge')
            assert response.value.ok, response.value.text()
            merged = response.value.json()
            page.wait_for_function('document.querySelectorAll("#engineering-scenario option").length === 4')
            page.screenshot(path=str(ARTIFACTS/'point_fields.png'))
            proc.terminate(); proc.wait(timeout=10)
            proc = start()
            page.reload(wait_until='networkidle')
            page.wait_for_function('document.querySelectorAll("#engineering-scenario option").length === 4')
            page.select_option('#engineering-scenario', merged['scenario_id'])
            with page.expect_navigation(wait_until='networkidle'):
                page.click('#engineering-open')
            actual = request('get', '/api/thesis/state')
            for pid, point in expected.items():
                assert next(x for x in actual['points'] if x['id'] == pid) == point
            assert not errors, errors
            result = dict(ok=True, checks=['real coordinate and fixed APIs on the same point across branches', 'Chromium conflict-free preview and merge', 'restart and UI reopen preserve both field edits', 'no page errors'])
            (ARTIFACTS/'e2e.json').write_text(json.dumps(result, indent=2)+'\n')
            print(json.dumps(result))
            browser.close()
    finally:
        proc.terminate(); proc.wait(timeout=10)


if __name__ == '__main__':
    main()
