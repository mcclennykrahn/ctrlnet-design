"""Responsive registration summary screenshots and reload regression."""
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
                page.locator('#reload-registration').click()
                page.wait_for_function("document.querySelector('#reg-rms').textContent !== '—'")
                page.locator('.registration').scroll_into_view_if_needed()
                page.screenshot(path=str(out / f'{width}-registration.png'))
                assert page.locator('#registration-stats strong').count() == 4
                if phase == 'after':
                    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
                    assert page.locator('#registration-stats').evaluate('(el) => el.scrollWidth <= el.clientWidth')
                    assert page.locator('#registration-stats > div').first.bounding_box()['height'] >= 70
                    assert page.locator('#reload-registration').bounding_box()['height'] >= 40
                assert not errors, errors
                page.close()
            browser.close()
        print(f'PASS {phase}: four-width Chromium registration metrics, reload, containment and card readability')
    finally:
        proc.terminate()
        proc.wait(timeout=10)


if __name__ == '__main__':
    main()
