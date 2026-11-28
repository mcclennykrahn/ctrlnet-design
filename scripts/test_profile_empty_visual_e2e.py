"""Capture empty profile guidance and verify transition to calculated results."""
import os
from pathlib import Path
import subprocess
import sys
from playwright.sync_api import sync_playwright
from e2e_database import isolated_environment
from test_thesis_e2e import _free_port, _wait_server

phase = sys.argv[1]
out = Path(os.environ['VISUAL_ARTIFACTS']) / phase
out.mkdir(parents=True, exist_ok=True)
port = str(_free_port())
base = 'http://127.0.0.1:' + port
server = subprocess.Popen([sys.executable, '-m', 'uvicorn', 'ctrlnet.webmap.app:app', '--port', port, '--log-level', 'error'], env=isolated_environment())
try:
    _wait_server(base + '/api/health')
    with sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path='/opt/ungoogled-chromium/chrome')
        for width in (1440, 820, 390, 320):
            page = browser.new_page(viewport={'width': width, 'height': 900})
            errors = []
            page.on('pageerror', lambda e: errors.append(str(e)))
            page.goto(base)
            page.wait_for_function('window.ctrlnetReady')
            section = page.locator('#profile-chart').locator('..')
            section.screenshot(path=out / f'{width}-empty.png')
            if phase == 'after':
                assert page.locator('.profile-steps li').count() == 2
                assert page.locator('.profile-empty strong').inner_text() == '等待选择剖面起终点'
                assert section.evaluate('e => e.scrollWidth <= e.clientWidth')
                assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
                assert not page.locator('#profile-summary code').count()
                # Real map clicks exercise the same path described by the guidance.
                canvas = page.locator('#map')
                canvas.scroll_into_view_if_needed()
                positions = page.evaluate("""() => {
                    const app = window.ctrlnetApp;
                    const a = app.state.project.points[0], b = app.state.project.points[1];
                    return [.35, .65].map(t => {
                        const p = app.map.latLngToContainerPoint([
                            a.N + (b.N - a.N) * t + 500, a.E + (b.E - a.E) * t + 500]);
                        return {x: p.x, y: p.y};
                    });
                }""")
                canvas.click(position=positions[0])
                with page.expect_response(lambda r: '/api/profile?' in r.url) as response:
                    canvas.click(position=positions[1])
                assert response.value.ok
                page.wait_for_selector('#profile-chart > svg')
                assert page.locator('.profile-empty').count() == 0
                assert page.locator('.profile-steps').count() == 0
                assert page.locator('.profile-metrics').count() == 1
                section.screenshot(path=out / f'{width}-result.png')
            assert not errors, errors
            page.close()
        browser.close()
    print(f'PASS {phase}: four widths; empty profile' + (' and real two-click result transition' if phase == 'after' else ' baseline'))
finally:
    server.terminate()
    server.wait(timeout=10)
