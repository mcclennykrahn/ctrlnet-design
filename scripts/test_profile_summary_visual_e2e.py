import os
import subprocess
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

from e2e_database import isolated_environment
from test_thesis_e2e import _free_port, _wait_server

phase = sys.argv[1]
output = Path(os.environ["VISUAL_ARTIFACTS"]) / phase
output.mkdir(parents=True, exist_ok=True)
port = str(_free_port())
base = f"http://127.0.0.1:{port}"
server = subprocess.Popen(
    [sys.executable, "-m", "uvicorn", "ctrlnet.webmap.app:app", "--port", port],
    env=isolated_environment(),
)
try:
    _wait_server(base + "/api/health")
    with sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path="/opt/ungoogled-chromium/chrome")
        cases = {}
        for point in ("P2", "P3", "P4", "P5", "P6", "P7", "P8", "P9"):
            response = browser.new_page()
            result = response.request.get(f"{base}/api/profile?from=P1&to={point}")
            if result.ok:
                data = result.json()
                if data["visible"]:
                    cases.setdefault("visible", point)
                elif data.get("obstruction"):
                    cases.setdefault("blocked", point)
            response.close()
            if len(cases) == 2:
                break
        assert set(cases) == {"visible", "blocked"}, cases
        for width in (1440, 820, 390, 320):
            page = browser.new_page(viewport={"width": width, "height": 900})
            page_errors = []
            page.on("pageerror", lambda error: page_errors.append(str(error)))
            page.goto(base)
            page.wait_for_function("window.ctrlnetReady")
            chart = page.locator("#profile-chart")
            for state, point in cases.items():
                with page.expect_response(lambda r: "/api/profile?" in r.url) as profile:
                    page.evaluate("(point) => window.ctrlnetApp.showProfile('P1', point)", point)
                assert profile.value.ok
                plot = chart.locator("svg")
                assert plot.count() == 1
                assert plot.locator("path").count() == 2
                assert plot.locator("circle").count() == (state == "blocked")
                chart.locator("..").screenshot(path=output / f"{width}-{state}.png")
                if phase == "after":
                    result = profile.value.json()
                    expected = [f'{result["distance_m"] / 1000:,.3f} km', f'{result["min_clearance_m"]:,.2f} m']
                    if result.get("obstruction"):
                        expected.append(f'{result["obstruction"]["distance_m"]:,.1f} m')
                    summary = page.locator("#profile-summary")
                    assert summary.locator(".profile-route strong").inner_text() == f"P1 → {point}"
                    assert summary.locator(".profile-result").inner_text() == ("通视" if state == "visible" else "遮挡")
                    assert summary.locator(".profile-metrics dt").all_text_contents() == (["距离", "最小净空"] + (["遮挡点距起点"] if state == "blocked" else []))
                    assert summary.locator(".profile-metrics dd").all_text_contents() == expected
                    assert summary.locator(".profile-obstruction").count() == (state == "blocked")
                    assert summary.evaluate("e => e.scrollWidth <= e.clientWidth")
                    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
                    legend = chart.locator(".profile-chart-legend")
                    assert legend.inner_text().splitlines() == ["地形高程（m）", "曲率折光视线"]
                    assert legend.bounding_box()["y"] >= plot.bounding_box()["y"] + plot.bounding_box()["height"]
                    assert chart.evaluate("e => e.scrollWidth <= e.clientWidth")
                    assert plot.locator("path").nth(1).get_attribute("stroke-dasharray")
                    for tick in plot.locator("text").all():
                        assert tick.evaluate("""e => {
                            const tick = e.getBoundingClientRect();
                            const plot = e.ownerSVGElement.getBoundingClientRect();
                            return tick.left >= plot.left - 1 && tick.right <= plot.right + 1;
                        }""")
            assert not page_errors, page_errors
            page.close()
        print(f"PASS {phase}: {cases}; four widths, both line-of-sight states and obstruction marker")
finally:
    server.terminate()
    server.wait()
