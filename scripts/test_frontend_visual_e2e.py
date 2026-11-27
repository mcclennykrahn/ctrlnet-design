"""Capture the thesis workspace at desktop, tablet and phone sizes in Chromium.

Run with VISUAL_PHASE=before or after and VISUAL_ARTIFACTS pointing at evidence.
Each run uses an isolated database; after additionally checks viewport containment.
"""
import json
import os
from pathlib import Path
import subprocess
import sys

from playwright.sync_api import sync_playwright
from e2e_database import isolated_environment
from test_thesis_e2e import _free_port, _wait_server


def main():
    phase = os.environ.get('VISUAL_PHASE', 'after')
    artifacts = Path(os.environ.get('VISUAL_ARTIFACTS', '/workspace/ctrlnet-v08/cn_frontend_visual')) / phase
    artifacts.mkdir(parents=True, exist_ok=True)
    base = f'http://127.0.0.1:{_free_port()}'
    proc = subprocess.Popen([sys.executable, '-m', 'uvicorn', 'ctrlnet.webmap.app:app',
                             '--host', '127.0.0.1', '--port', base.rsplit(':', 1)[1],
                             '--log-level', 'error'], env=isolated_environment())
    results = []
    try:
        _wait_server(base + '/api/health')
        with sync_playwright() as p:
            options = {'args': ['--no-sandbox']}
            if os.environ.get('CHROMIUM_EXECUTABLE'):
                options['executable_path'] = os.environ['CHROMIUM_EXECUTABLE']
            browser = p.chromium.launch(**options)
            for width, height in ((1440, 1000), (821, 1000), (820, 1180), (390, 844)):
                page = browser.new_page(viewport={'width': width, 'height': height})
                errors, external = [], []
                page.on('pageerror', lambda e: errors.append(str(e)))
                page.on('request', lambda r: external.append(r.url) if not r.url.startswith((base, 'data:', 'blob:')) else None)
                page.goto(base + '/thesis', wait_until='networkidle')
                page.wait_for_selector('#map img.leaflet-image-layer')
                page.click('[data-example="1"]')
                page.wait_for_function('document.querySelectorAll("#point-body tr").length === 9')
                page.locator('#project-name').scroll_into_view_if_needed()
                page.screenshot(path=str(artifacts / f'{width}-workspace.png'), full_page=width <= 820)
                page.click('#calculate')
                page.wait_for_selector('#result-box:not(.hidden)')
                assert page.locator('#result-qxx').inner_text().startswith('0.6502')
                assert page.locator('#result-qyy').inner_text().startswith('0.3039')
                assert page.locator('#denom-body tr').count() == 17
                page.locator('#result-box').scroll_into_view_if_needed()
                page.screenshot(path=str(artifacts / f'{width}-results.png'))
                metrics = page.evaluate('''() => ({
                    viewport: innerWidth, document: document.documentElement.scrollWidth,
                    sidebar: document.querySelector('.library-side').getBoundingClientRect().width,
                    map: document.querySelector('#map').getBoundingClientRect().width
                })''')
                results.append(dict(width=width, height=height, metrics=metrics,
                                    page_errors=errors, external_requests=external))
                if phase == 'after':
                    assert metrics['document'] <= width, metrics
                    # A narrow desktop sidebar must not split a decimal's digits.
                    for selector in ('#result-qxx', '#result-qyy'):
                        assert page.locator(selector).evaluate('''el => {
                            const range = document.createRange(); range.selectNodeContents(el);
                            return range.getClientRects().length === 1;
                        }'''), f'{selector} wraps at {width}px'
                    for selector in ('#project-name', '#calculate', '#result-box', '#basemap-select'):
                        rect = page.locator(selector).bounding_box()
                        assert rect and rect['x'] >= 0 and rect['x'] + rect['width'] <= width + 1, (selector, rect)
                assert not errors and not external, (errors, external)
                page.close()
            browser.close()
        (artifacts / 'evidence.json').write_text(json.dumps(results, indent=2) + '\n')
        print(f'PASS: {phase}, desktop/tablet/phone; example 1 calculation and 17 result rows; no page errors or external requests')
    finally:
        proc.terminate()
        proc.wait(timeout=10)


if __name__ == '__main__':
    main()
