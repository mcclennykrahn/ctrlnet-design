"""Responsive object inspector screenshots using real map selections."""
import os
from pathlib import Path
import subprocess
import sys
from playwright.sync_api import sync_playwright
from e2e_database import isolated_environment
from test_thesis_e2e import _free_port, _wait_server


def main():
    phase = os.environ.get('VISUAL_PHASE', 'after')
    out = Path(os.environ['VISUAL_ARTIFACTS']) / phase
    out.mkdir(parents=True, exist_ok=True)
    base = f'http://127.0.0.1:{_free_port()}'
    proc = subprocess.Popen([sys.executable, '-m', 'uvicorn', 'ctrlnet.webmap.app:app', '--host', '127.0.0.1', '--port', base.rsplit(':', 1)[1], '--log-level', 'error'], env=isolated_environment())
    try:
        _wait_server(base + '/api/health')
        with sync_playwright() as p:
            browser = p.chromium.launch(executable_path='/opt/ungoogled-chromium/chrome', args=['--no-sandbox'])
            for width in (1440, 1024, 390, 320):
                page = browser.new_page(viewport={'width': width, 'height': 1000})
                errors = []
                page.on('pageerror', lambda e: errors.append(str(e)))
                page.goto(base, wait_until='networkidle')
                page.wait_for_function('window.ctrlnetReady === true')
                page.locator('.point-marker').first.click(force=True)
                page.locator('#inspector .kv').wait_for()
                page.locator('#inspector').scroll_into_view_if_needed()
                page.screenshot(path=str(out / f'{width}-inspector.png'))
                assert page.locator('#inspector dt').count() > 3
                assert page.locator('#inspector dd').count() == page.locator('#inspector dt').count()
                if phase == 'after':
                    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
                    assert page.locator('#inspector').evaluate('(el) => el.scrollWidth <= el.clientWidth')
                    assert page.locator('#inspector dt').first.bounding_box()['height'] >= 30
                assert not errors, errors
                page.close()
            browser.close()
        print(f'PASS {phase}: four-width Chromium real map object inspector, populated label/value pairs, containment and row readability')
    finally:
        proc.terminate()
        proc.wait(timeout=10)


if __name__ == '__main__':
    main()
