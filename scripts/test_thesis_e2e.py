#!/usr/bin/env python
"""Playwright 无头 Chromium 端到端验证论文模式页面。

流程：启动仅绑定 127.0.0.1 的本地服务 → 打开 /thesis → 载入论文算例 1 →
点击“精度计算” → 确认结果表出现且关键数值正确 → 截图到 outputs/。

用法::

    .venv/bin/pip install -e '.[e2e]'
    .venv/bin/python scripts/test_thesis_e2e.py
"""

from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "outputs"
SCREENSHOT = OUT / "thesis_web_example1.png"


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _wait_server(url: str, timeout: float = 30.0) -> None:
    deadline = time.time() + timeout
    last_error = None
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=1.5) as response:
                if response.status == 200:
                    return
        except Exception as exc:  # pragma: no cover - 启动等待
            last_error = exc
        time.sleep(0.25)
    raise RuntimeError(f"本地服务未在 {timeout}s 内启动：{last_error}")


def main() -> int:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("缺少 playwright：请运行 .venv/bin/pip install -e '.[e2e]'", file=sys.stderr)
        return 2

    OUT.mkdir(parents=True, exist_ok=True)
    port = _free_port()
    base = f"http://127.0.0.1:{port}"
    env = os.environ.copy()
    env.setdefault("MPLCONFIGDIR", str(ROOT / ".mplconfig"))
    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "ctrlnet.webmap.app:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
            "--log-level",
            "warning",
        ],
        cwd=str(ROOT),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    errors: list[str] = []
    external: list[str] = []
    console_errors: list[str] = []
    try:
        _wait_server(base + "/api/health")
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(
                headless=True,
                args=["--no-sandbox", "--disable-dev-shm-usage"],
            )
            page = browser.new_page(viewport={"width": 1440, "height": 1000}, device_scale_factor=1)
            page.on(
                "console",
                lambda msg: console_errors.append(f"{msg.type}: {msg.text}")
                if msg.type == "error"
                else None,
            )
            page.on("pageerror", lambda exc: errors.append(f"pageerror: {exc}"))
            page.on(
                "request",
                lambda request: external.append(request.url)
                if not (
                    request.url.startswith(base)
                    or request.url.startswith("data:")
                    or request.url.startswith("blob:")
                )
                else None,
            )
            page.goto(base + "/thesis", wait_until="networkidle", timeout=30000)
            page.wait_for_selector(".leaflet-container", timeout=15000)
            page.wait_for_selector("#map img.leaflet-image-layer", timeout=15000)

            page.click('button[data-example="1"]')
            page.wait_for_function(
                "document.querySelectorAll('#point-body tr').length === 9",
                timeout=20000,
            )
            page.wait_for_function(
                "document.querySelectorAll('#line-body tr').length === 17",
                timeout=10000,
            )
            page.wait_for_function(
                "document.querySelectorAll('#angle-body tr').length === 14",
                timeout=10000,
            )

            page.click("#calculate")
            page.wait_for_selector("#result-box:not(.hidden)", timeout=20000)
            page.wait_for_function(
                "document.querySelectorAll('#denom-body tr').length === 17",
                timeout=10000,
            )
            weakest = page.text_content("#result-weakest").strip()
            qxx = page.text_content("#result-qxx").strip()
            qyy = page.text_content("#result-qyy").strip()
            m_value = page.text_content("#result-m").strip()
            badge = page.text_content("#result-badge").strip()
            denom_rows = page.locator("#denom-body tr").count()
            point_rows = page.locator("#point-body tr").count()
            line_rows = page.locator("#line-body tr").count()
            angle_rows = page.locator("#angle-body tr").count()
            page.screenshot(path=str(SCREENSHOT), full_page=False)
            browser.close()

        problems = []
        if "最弱点 1" not in weakest:
            problems.append(f"最弱点显示异常：{weakest!r}")
        if not qxx.startswith("0.6502"):
            problems.append(f"Qxx 显示异常：{qxx!r}")
        if not qyy.startswith("0.3039"):
            problems.append(f"Qyy 显示异常：{qyy!r}")
        if "满足" not in badge:
            problems.append(f"限差判定异常：{badge!r}")
        if denom_rows != 17:
            problems.append(f"分母表行数异常：{denom_rows}")
        if (point_rows, line_rows, angle_rows) != (9, 17, 14):
            problems.append(f"点/线/角行数异常：{point_rows}/{line_rows}/{angle_rows}")
        if external:
            problems.append("出现非本地请求：" + ", ".join(external[:5]))
        if errors or console_errors:
            problems.append("浏览器错误：" + "; ".join((errors + console_errors)[:5]))
        if problems:
            print("E2E FAILED", file=sys.stderr)
            for problem in problems:
                print(" -", problem, file=sys.stderr)
            return 1
        print("[e2e] /thesis 加载成功（仅本地请求）")
        print(f"[e2e] 算例 1：{point_rows} 点 / {line_rows} 线 / {angle_rows} 角")
        print(f"[e2e] 精度计算：{weakest}，Qxx={qxx}，Qyy={qyy}，M={m_value}，{badge}")
        print(f"[e2e] 分母表 {denom_rows} 行；截图 {SCREENSHOT.relative_to(ROOT)}")
        return 0
    finally:
        process.terminate()
        try:
            output, _ = process.communicate(timeout=8)
        except subprocess.TimeoutExpired:  # pragma: no cover
            process.kill()
            output, _ = process.communicate()
        if process.returncode not in (0, -15) and output:
            print(output[-3000:], file=sys.stderr)


if __name__ == "__main__":
    raise SystemExit(main())
