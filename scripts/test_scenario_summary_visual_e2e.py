"""Capture scenario measurements and verify values after scenario switching."""
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
            section = page.locator('#scenario-meta')
            section.screenshot(path=out / f'{width}-summary.png')
            if phase == 'after':
                assert section.locator('.scenario-measures > div').count() == 7
                assert section.evaluate('e => e.scrollWidth <= e.clientWidth')
                assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
                assert section.locator('dt').all_inner_texts() == ['观测', '点数', '固定', 'max mp', 'min r_i', '通视', '冗余']
                assert section.locator('dd').count() == 7
                def check_values():
                    summary = page.evaluate('window.ctrlnetApp.state.project.summary')
                    expected = [str(summary[k]) for k in ('n_observations', 'n_points', 'n_fixed')]
                    expected += [f"{summary['max_mp_mm']:.2f} mm", f"{summary['min_r']:.3f}" if summary['min_r'] is not None else '—', f"{summary['n_visible']} / {summary['n_pairs']}", str(summary['redundancy'])]
                    assert section.locator('dd').all_inner_texts() == expected
                check_values()
                page.select_option('#scenario-select', 'dem-opt')
                page.wait_for_function("window.ctrlnetApp.state.selectedScenario === 'dem-opt' && !document.querySelector('#scenario-meta').textContent.includes('正在')")
                check_values()
                section.screenshot(path=out / f'{width}-switched.png')
            assert not errors, errors
            page.close()
        browser.close()
    print(f'PASS {phase}: four-width Chromium scenario summary and containment')
finally:
    server.terminate()
    server.wait(timeout=10)
