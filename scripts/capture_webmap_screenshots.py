#!/usr/bin/env python3
"""用 Playwright 无头 Chromium 截图本地网页地图。

前置条件：服务已在 ``127.0.0.1:8765`` 启动（``.venv/bin/ctrlnet-web``），
且运行本脚本的 Python 已安装 Playwright/Chromium（例如
``/workspace/venvs/lab/bin/python``）。脚本只访问本机 URL，不启动或关闭服务。

运行::

    /workspace/venvs/lab/bin/python scripts/capture_webmap_screenshots.py
    /workspace/venvs/lab/bin/python scripts/capture_webmap_screenshots.py \
        --url http://127.0.0.1:8765/ --scenario dem-opt
"""

from __future__ import annotations

import argparse
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUTPUTS = ROOT / "outputs"


def capture(url: str, scenario: str) -> tuple[Path, Path]:
    from playwright.sync_api import sync_playwright

    OUTPUTS.mkdir(parents=True, exist_ok=True)
    first = OUTPUTS / "webmap_screenshot.png"
    second = OUTPUTS / "webmap_scenario_screenshot.png"
    errors: list[str] = []

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            headless=True, args=["--no-sandbox", "--disable-dev-shm-usage"]
        )
        page = browser.new_page(viewport={"width": 1440, "height": 900})
        page.on("console", lambda msg: errors.append(f"{msg.type}: {msg.text}") if msg.type == "error" else None)
        page.on("pageerror", lambda exc: errors.append(f"pageerror: {exc}"))
        page.goto(url, wait_until="networkidle", timeout=60_000)
        page.wait_for_function("window.ctrlnetBooted === true", timeout=60_000)
        page.wait_for_function("window.ctrlnetReady === true", timeout=60_000)
        page.wait_for_selector("#reg-rms", timeout=30_000)
        page.wait_for_timeout(1200)
        page.screenshot(path=str(first))

        # 切换方案：下拉框 → 后端重新取点/观测/椭圆/统计。
        page.select_option("#scenario-select", scenario)
        page.wait_for_function(
            "(sid) => window.ctrlnetScenarioReady === sid",
            arg=scenario,
            timeout=60_000,
        )
        page.wait_for_timeout(900)
        page.screenshot(path=str(second))
        browser.close()

    if errors:
        print("浏览器控制台错误：")
        for line in errors:
            print("  " + line)
    return first, second


def main() -> None:
    parser = argparse.ArgumentParser(description="截图 CTRLNET 本地网页地图")
    parser.add_argument("--url", default="http://127.0.0.1:8765/")
    parser.add_argument("--scenario", default="dem-opt", help="第二张截图切换到的方案 id")
    args = parser.parse_args()
    first, second = capture(args.url, args.scenario)
    print(f"wrote {first.relative_to(ROOT)}")
    print(f"wrote {second.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
