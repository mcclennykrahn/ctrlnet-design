"""Dashboard screenshot evidence and responsive interaction checks, isolated DBs."""
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
    out = Path(os.environ['VISUAL_ARTIFACTS']) / phase
    out.mkdir(parents=True, exist_ok=True)
    base = f'http://127.0.0.1:{_free_port()}'
    proc = subprocess.Popen([sys.executable, '-m', 'uvicorn', 'ctrlnet.webmap.app:app', '--host', '127.0.0.1', '--port', base.rsplit(':', 1)[1], '--log-level', 'error'], env=isolated_environment())
    evidence = []
    try:
        _wait_server(base + '/api/health')
        with sync_playwright() as p:
            browser = p.chromium.launch(executable_path='/opt/ungoogled-chromium/chrome', args=['--no-sandbox'])
            for width in (1440, 1024, 820, 390, 320):
                page = browser.new_page(viewport={'width': width, 'height': 1000})
                errors = []
                page.on('pageerror', lambda e: errors.append(str(e)))
                page.goto(base, wait_until='networkidle')
                page.wait_for_function('window.ctrlnetReady === true')
                page.screenshot(path=str(out / f'{width}-dashboard.png'), full_page=True)
                if phase == 'after':
                    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
                    rects = {s: page.locator(s).bounding_box() for s in ('#map', '#left-panel', '#right-panel', '#topbar', '#statusbar')}
                    for s, r in rects.items():
                        assert r and r['x'] >= 0 and r['x'] + r['width'] <= width + 1, (s, r)
                    if width <= 1024:
                        assert rects['#map']['y'] >= rects['#topbar']['height']
                        assert rects['#left-panel']['y'] >= rects['#map']['y'] + rects['#map']['height']
                        assert rects['#right-panel']['y'] >= rects['#left-panel']['y'] + rects['#left-panel']['height']
                    else:
                        assert rects['#map']['width'] >= 400
                    # All control points must fit inside the dedicated canvas.
                    assert page.evaluate("""() => {
                        const box = document.querySelector('#map').getBoundingClientRect();
                        const markers = [...document.querySelectorAll('#map .point-marker')];
                        return markers.length > 0 && markers.every(el => {
                            const r = el.getBoundingClientRect();
                            return r.x >= box.x && r.right <= box.right && r.y >= box.y && r.bottom <= box.bottom;
                        });
                    }""")
                    page.locator('#lyr-contours').uncheck()
                    assert not page.locator('#lyr-contours').is_checked()
                    page.locator('#lyr-contours').check()
                    page.select_option('#scenario-select', 'dem-opt')
                    page.wait_for_function('window.ctrlnetScenarioReady === "dem-opt"')
                    page.evaluate("window.ctrlnetApp.showProfile('P1','P6')")
                    page.wait_for_selector('#profile-chart > svg')
                    page.locator('#right-panel').scroll_into_view_if_needed()
                    page.screenshot(path=str(out / f'{width}-profile.png'))
                assert not errors, errors
                evidence.append({'width': width, 'page_errors': errors, 'document_width': page.evaluate('document.documentElement.scrollWidth')})
                page.close()
            browser.close()
        (out / 'evidence.json').write_text(json.dumps(evidence, indent=2) + '\n')
        print(f'PASS: {phase}: five Chromium widths; ' + ('containment, map/panel separation, layer toggle, scenario switch and profile' if phase == 'after' else 'baseline screenshots'))
    finally:
        proc.terminate()
        proc.wait(timeout=10)


if __name__ == '__main__':
    main()
