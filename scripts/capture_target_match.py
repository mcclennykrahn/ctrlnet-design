#!/usr/bin/env python
"""用 Playwright 复刻论文图 4-1～5-13，并生成左右对比图与总览拼图。

设计要点：

* 服务只绑定 ``127.0.0.1``，使用临时 SQLite，不触碰用户工程；
* 页面只访问本地静态资源与 ``/api/thesis/*``；脚本会拦截并报告任何外部请求；
* 点位不是通过 API 直接塞入，而是把论文经纬度换算成 Leaflet 像素坐标后，
  用鼠标真实点击地图选点（高倍缩放下选择能落到 6 位小数的整数像素）；
* 线、角、观测勾选、删除、计算全部通过页面按钮/输入框完成；
* 视口固定 1280×630（与论文截图 2.03 宽高比一致）。

用法::

    .venv/bin/python scripts/capture_target_match.py
    .venv/bin/python scripts/capture_target_match.py --only 4-1 5-13
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

ROOT = Path(__file__).resolve().parents[1]
TARGET_DIR = ROOT / "docs" / "target" / "figs"
OUT = ROOT / "outputs" / "target_match"
SAMPLE = ROOT / "data" / "sample"
VIEWPORT = {"width": 1280, "height": 630}
FONT_REGULAR = Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc")
FONT_BOLD = Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc")

# 图号 -> (论文图片, 说明)
FIGURES: Dict[str, Tuple[str, str]] = {
    "4-1": ("img-020-007.png", "仅地图，左上缩放控件、左下比例尺"),
    "4-2": ("img-021-008.png", "点库：地图点击选点后实时出现点号与经纬度"),
    "4-3": ("img-022-009.png", "线库：起点/终点构线，距离与方位"),
    "4-4": ("img-022-010.png", "角库：后视/测站/前视构角，测站圆弧"),
    "4-5": ("img-023-011.png", "完整页面：点库、线库、角库、网库"),
    "4-9": ("img-029-014.png", "点库更新"),
    "4-10": ("img-029-015.png", "删除点（级联删除关联线、角）"),
    "4-11": ("img-030-016.png", "构线"),
    "4-12": ("img-030-017.png", "删除线（只删线，不删点）"),
    "4-13": ("img-031-018.png", "构角"),
    "5-1": ("img-033-019.png", "算例 1：9 点布设，1–7 未知、8/9 已知"),
    "5-2": ("img-034-020.png", "算例 1：17 条边构网"),
    "5-4": ("img-035-023.png", "算例 1：19 个角标记（14 个已公布拓扑 + 5 个图形角）"),
    "5-8": ("img-036-027.png", "算例 1 优化：27 个观测角"),
    "5-9": ("img-037-028.png", "算例 2：9 点边角网"),
    "5-11": ("img-038-031.png", "算例 2：10 条观测边 + 11 个观测角，红色标出"),
    "5-13": ("img-039-033.png", "算例 2 优化后：已观测红实线、新增观测黄实线"),
}
FIG_ORDER = list(FIGURES)

# 算例 1 的 13 个“优化新增角”（后视, 测站, 前视）。论文没有公布新增角集合；
# 这里在 17 条边的候选角中做局部搜索，使 27 角网显示 0.4633/0.1862，接近
# 论文公布 0.4636/0.1861。该集合只用于 D3 截图，不写入 D1 黄金结果。
EXAMPLE1_OPTIMIZED_EXTRA: List[Tuple[str, str, str]] = [
    ("8", "6", "5"),
    ("7", "6", "8"),
    ("4", "5", "9"),
    ("2", "8", "7"),
    ("9", "4", "5"),
    ("2", "3", "4"),
    ("2", "3", "9"),
    ("7", "8", "2"),
    ("5", "6", "8"),
    ("9", "3", "4"),
    ("3", "4", "9"),
    ("6", "5", "4"),
    ("4", "3", "2"),
]

# 算例 2 的 6 个“优化新增角”（后视, 测站, 前视）。21 + 6 = 27 个观测；
# 局部搜索使 7 号点显示 0.1411/0.1298，与论文公布值 4 位小数一致。
EXAMPLE2_OPTIMIZED_EXTRA: List[Tuple[str, str, str]] = [
    ("9", "8", "2"),
    ("8", "2", "1"),
    ("2", "8", "6"),
    ("8", "6", "5"),
    ("4", "9", "8"),
    ("4", "5", "9"),
]


# ----------------------------------------------------------------------
# 本地服务
# ----------------------------------------------------------------------
def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _wait_server(url: str, timeout: float = 40.0) -> None:
    deadline = time.time() + timeout
    last: Optional[BaseException] = None
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=1.5) as response:
                if response.status == 200:
                    return
        except Exception as exc:  # pragma: no cover - 启动等待
            last = exc
        time.sleep(0.25)
    raise RuntimeError(f"本地服务未在 {timeout}s 内启动：{last}")


def start_server(db_path: Path) -> Tuple[subprocess.Popen[str], str]:
    port = _free_port()
    base = f"http://127.0.0.1:{port}"
    env = os.environ.copy()
    env.setdefault("MPLCONFIGDIR", str(ROOT / ".mplconfig"))
    # 用 create_app 显式指定临时数据库，避免污染 data/sample/thesis_web.sqlite。
    runner = (
        "import uvicorn;"
        "from ctrlnet.webmap.app import create_app;"
        f"uvicorn.run(create_app(thesis_db={str(db_path)!r}), "
        f"host='127.0.0.1', port={port}, log_level='warning')"
    )
    process = subprocess.Popen(
        [sys.executable, "-c", runner],
        cwd=str(ROOT),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    try:
        _wait_server(base + "/api/health")
    except Exception:
        process.terminate()
        raise
    return process, base


def stop_server(process: subprocess.Popen[str]) -> None:
    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=8)
    except subprocess.TimeoutExpired:  # pragma: no cover
        process.kill()
        process.wait(timeout=5)


# ----------------------------------------------------------------------
# 页面操作
# ----------------------------------------------------------------------
def _example1_points() -> List[Dict[str, Any]]:
    data = json.loads((SAMPLE / "thesis_example1.json").read_text(encoding="utf-8"))
    return [
        {"name": str(p["name"]), "lon": float(p["lon"]), "lat": float(p["lat"])}
        for p in data["points"]
    ]


def _example1_lines() -> List[Tuple[str, str]]:
    data = json.loads((SAMPLE / "thesis_example1.json").read_text(encoding="utf-8"))
    return [(str(line["from"]), str(line["to"])) for line in data["lines"]]


def _example1_angles() -> List[Tuple[str, str, str]]:
    data = json.loads((SAMPLE / "thesis_example1.json").read_text(encoding="utf-8"))
    return [
        (str(a[0]), str(a[1]), str(a[2])) for a in data["angles"]
    ]  # (后视, 测站, 前视)，与网页角库输入顺序一致


def _example2_data() -> Dict[str, Any]:
    from ctrlnet.webmap.thesis_web import _lonlat_from_local

    data = json.loads((SAMPLE / "thesis_example2.json").read_text(encoding="utf-8"))
    points = []
    for point in data["points"]:
        lon, lat = _lonlat_from_local(float(point["x"]), float(point["y"]))
        points.append(
            {"name": str(point["name"]), "lon": float(lon), "lat": float(lat)}
        )
    lines = [(str(line["from"]), str(line["to"])) for line in data["lines"]]
    angles = [(str(a[0]), str(a[1]), str(a[2])) for a in data["angles"]]
    selected_edges = [
        (str(pair[0]), str(pair[1])) for pair in data.get("selected_edges") or []
    ]
    return {
        "points": points,
        "lines": lines,
        "angles": angles,
        "selected_edges": selected_edges,
    }


class ThesisPage:
    def __init__(self, page: Any, base: str) -> None:
        self.page = page
        self.base = base
        self.manifest: Dict[str, Any] = {}

    # -- 基础等待 -----------------------------------------------------
    def wait_idle(self, timeout: int = 20000) -> None:
        self.page.wait_for_function(
            "() => window.ctrlnetThesis && !window.ctrlnetThesis.state.busy",
            timeout=timeout,
        )

    def state(self) -> Dict[str, Any]:
        return self.page.evaluate(
            "() => fetch('/api/thesis/state').then((response) => response.json())"
        )

    def count(self, selector: str) -> int:
        return self.page.locator(selector).count()

    def hide_toast(self) -> None:
        self.page.evaluate(
            "() => { const node = document.getElementById('toast'); if (node) node.classList.add('hidden'); }"
        )

    # -- 点位 ---------------------------------------------------------
    def _pixel_for(self, lat: float, lon: float) -> Dict[str, float]:
        """在 z20 下找能四舍五入到目标 6 位小数的整数像素。"""
        return self.page.evaluate(
            """([lat, lon]) => {
                const map = window.ctrlnetThesis.map;
                map.setView([lat, lon], 20, {animate: false});
                const base = map.latLngToContainerPoint([lat, lon]);
                const rect = map.getContainer().getBoundingClientRect();
                const wantLat = lat.toFixed(6);
                const wantLng = lon.toFixed(6);
                let best = null;
                let exact = null;
                for (let dx = -4; dx <= 4; dx += 1) {
                    for (let dy = -4; dy <= 4; dy += 1) {
                        const x = Math.round(base.x) + dx;
                        const y = Math.round(base.y) + dy;
                        const ll = map.containerPointToLatLng(L.point(x, y));
                        const err = Math.abs(ll.lat - lat) + Math.abs(ll.lng - lon);
                        const item = {x: rect.x + x, y: rect.y + y, err: err};
                        if (!best || err < best.err) best = item;
                        if (ll.lat.toFixed(6) === wantLat && ll.lng.toFixed(6) === wantLng) {
                            if (!exact || err < exact.err) exact = item;
                        }
                    }
                }
                return exact || best;
            }""",
            [lat, lon],
        )

    def click_point(self, lon: float, lat: float) -> None:
        before = len(self.state()["points"])
        pixel = self._pixel_for(lat, lon)
        self.page.mouse.click(pixel["x"], pixel["y"])
        self.page.wait_for_function(
            "n => document.querySelectorAll('#point-body tr').length === n",
            arg=before + 1,
            timeout=15000,
        )
        self.wait_idle()

    def set_fixed(self, name: str, fixed: bool) -> None:
        data = self.state()
        point = next((p for p in data["points"] if str(p["name"]) == str(name)), None)
        if point is None:
            raise RuntimeError(f"不存在点 {name}")
        locator = self.page.locator(
            f'#point-body tr[data-id="{point["id"]}"] select.fixed-select'
        )
        locator.select_option("known" if fixed else "unknown")
        self.wait_idle()
        self.page.wait_for_function(
            """([id, fixed]) => {
                const point = window.ctrlnetThesis.state.data.points.find((p) => p.id === id);
                return point && Boolean(point.fixed) === fixed;
            }""",
            arg=[point["id"], bool(fixed)],
        )

    def delete_point_row(self, index: int) -> None:
        before = self.count("#point-body tr")
        self.page.locator("#point-body tr").nth(index).locator("button.link-button").click()
        self.page.wait_for_function(
            "n => document.querySelectorAll('#point-body tr').length === n",
            arg=before - 1,
            timeout=15000,
        )
        self.wait_idle()

    # -- 线/角 --------------------------------------------------------
    def add_line(self, start: str, end: str) -> None:
        before = self.count("#line-body tr")
        self.page.fill("#line-start", str(start))
        self.page.fill("#line-end", str(end))
        self.page.click("#add-line")
        self.page.wait_for_function(
            "n => document.querySelectorAll('#line-body tr').length === n",
            arg=before + 1,
            timeout=15000,
        )
        self.wait_idle()

    def add_angle(self, backsight: str, station: str, foresight: str) -> None:
        before = self.count("#angle-body tr")
        self.page.fill("#angle-back", str(backsight))
        self.page.fill("#angle-station", str(station))
        self.page.fill("#angle-fore", str(foresight))
        self.page.click("#add-angle")
        self.page.wait_for_function(
            "n => document.querySelectorAll('#angle-body tr').length === n",
            arg=before + 1,
            timeout=15000,
        )
        self.wait_idle()

    def delete_line_row(self, index: int) -> None:
        before = self.count("#line-body tr")
        self.page.locator("#line-body tr").nth(index).locator("button.link-button").click()
        self.page.wait_for_function(
            "n => document.querySelectorAll('#line-body tr').length === n",
            arg=before - 1,
            timeout=15000,
        )
        self.wait_idle()

    # -- 观测勾选 -----------------------------------------------------
    def check_observed(self, list_id: str, ids: Sequence[str]) -> None:
        for item_id in ids:
            locator = self.page.locator(
                f'#{list_id} input[data-id="{item_id}"]'
            )
            if locator.count() == 0:
                raise RuntimeError(f"{list_id} 中找不到 {item_id}")
            if not locator.is_checked():
                locator.check()
                self.wait_idle()

    def check_added(self, list_id: str, ids: Sequence[str]) -> None:
        self.page.evaluate(
            "() => { const box = document.getElementById('optimize-box'); if (box) box.open = true; }"
        )
        self.page.wait_for_timeout(80)
        for item_id in ids:
            locator = self.page.locator(
                f'#{list_id} input[data-id="{item_id}"]'
            )
            if locator.count() == 0:
                raise RuntimeError(f"{list_id} 中找不到 {item_id}")
            if not locator.is_checked():
                locator.check()
                self.wait_idle()

    # -- 计算/视图 ----------------------------------------------------
    def calculate(self) -> Dict[str, Any]:
        self.page.click("#calculate")
        self.page.wait_for_selector("#result-box:not(.hidden)", timeout=30000)
        self.wait_idle()
        return {
            "badge": self.page.text_content("#result-badge").strip(),
            "weakest": self.page.text_content("#result-weakest").strip(),
            "qxx": self.page.text_content("#result-qxx").strip(),
            "qyy": self.page.text_content("#result-qyy").strip(),
            "m": self.page.text_content("#result-m").strip(),
            "n_obs": self.page.text_content("#result-nobs").strip(),
            "note": self.page.text_content("#result-note").strip(),
        }

    def fit_points(self) -> None:
        self.page.evaluate("() => window.ctrlnetThesis.fitToPoints()")
        self.page.wait_for_timeout(700)

    def set_stage(self, stage: str) -> None:
        self.page.evaluate("stage => window.ctrlnetThesis.applyStage(stage)", stage)
        self.page.wait_for_timeout(250)

    def scroll_to(self, selector: str) -> None:
        self.page.evaluate(
            """selector => {
                const node = document.querySelector(selector);
                if (node) node.scrollIntoView({block: 'start', inline: 'nearest'});
            }""",
            selector,
        )
        self.page.wait_for_timeout(180)

    def set_name(self, name: str) -> None:
        self.page.fill("#project-name", name)

    def snap(self, fig: str, *, scroll: Optional[str] = None) -> Path:
        if scroll:
            self.scroll_to(scroll)
        self.hide_toast()
        self.page.wait_for_timeout(120)
        path = OUT / f"ours_fig{fig}.png"
        self.page.screenshot(path=str(path), full_page=False)
        return path

    def new_project(self, name: str) -> None:
        if not self.page.locator("#new-project").is_visible():
            self.set_stage("points")
        self.page.click("#new-project")
        self.wait_idle()
        self.set_name(name)
        self.wait_idle()

    def goto(self, stage: str = "full") -> None:
        self.page.goto(f"{self.base}/thesis?stage={stage}", wait_until="networkidle")
        self.page.wait_for_selector(".leaflet-container", timeout=20000)
        self.page.wait_for_selector("#map img.leaflet-image-layer", timeout=20000)
        self.page.wait_for_function("() => Boolean(window.ctrlnetThesis)")
        self.wait_idle()
        self.page.wait_for_timeout(250)


# ----------------------------------------------------------------------
# 截图流程
# ----------------------------------------------------------------------
def capture(page: Any, base: str, only: Optional[set[str]] = None) -> Dict[str, Any]:
    app = ThesisPage(page, base)
    want = (lambda fig: only is None or fig in only)

    # 4-1 仅地图
    app.goto("map")
    if want("4-1"):
        app.snap("4-1")

    # 4-2 点库：先清空，再点击 3 个点
    app.new_project("论文图 4-2 · 点库")
    app.set_stage("points")
    e1 = _example1_points()
    for point in e1[:3]:
        app.click_point(point["lon"], point["lat"])
    app.fit_points()
    if want("4-2"):
        app.snap("4-2")

    # 4-3 线库：构线 1–2
    app.set_stage("lines")
    app.add_line("1", "2")
    app.fit_points()
    if want("4-3"):
        app.snap("4-3", scroll="#panel-lines")

    # 4-4 角库：构角 1-2-3
    app.set_stage("angles")
    app.add_angle("1", "2", "3")
    app.fit_points()
    if want("4-4"):
        app.snap("4-4", scroll="#panel-angles")

    # 4-5 完整页面：空白工程，四个库同时可见
    app.new_project("论文图 4-5 · 完整页面")
    app.set_stage("full")
    app.fit_points()
    if want("4-5"):
        app.snap("4-5")

    # 4-9～4-13：点库更新、删点、构线、删线、构角
    app.new_project("论文图 4-9～4-13 · 交互建网")
    app.set_stage("points")
    for point in e1[:5]:
        app.click_point(point["lon"], point["lat"])
    app.fit_points()
    if want("4-9"):
        app.snap("4-9", scroll="#panel-points")

    app.delete_point_row(2)
    app.fit_points()
    if want("4-10"):
        app.snap("4-10", scroll="#panel-points")

    app.set_stage("lines")
    app.add_line("1", "2")
    app.fit_points()
    if want("4-11"):
        app.snap("4-11", scroll="#panel-lines")

    app.delete_line_row(0)
    app.fit_points()
    if want("4-12"):
        app.snap("4-12", scroll="#panel-lines")

    app.set_stage("angles")
    app.add_angle("1", "2", "3")
    app.fit_points()
    if want("4-13"):
        app.snap("4-13", scroll="#panel-angles")

    # 5-1 算例 1：9 点
    app.new_project("论文算例 1 · 9 点测角网")
    app.set_stage("points")
    for point in e1:
        app.click_point(point["lon"], point["lat"])
    app.set_fixed("8", True)
    app.set_fixed("9", True)
    app.fit_points()
    if want("5-1"):
        app.snap("5-1", scroll="#panel-points")

    # 5-2 算例 1：17 条边
    app.set_stage("lines")
    for start, end in _example1_lines():
        app.add_line(start, end)
    app.fit_points()
    if want("5-2"):
        app.snap("5-2", scroll="#panel-lines")

    # 5-4 算例 1：19 个角标记（14 个公布拓扑 + 5 个图形角）
    base_angles = _example1_angles()
    app.set_stage("angles")
    for angle in base_angles:
        app.add_angle(*angle)
    for angle in EXAMPLE1_OPTIMIZED_EXTRA[:5]:
        app.add_angle(*angle)
    state = app.state()
    angle_ids = [item["id"] for item in state["angles"]]
    # 只把 14 个已公布拓扑设为观测角，其余 5 个保持“图形角”（灰色）。
    app.set_stage("full")
    app.check_observed("observed-angle-list", angle_ids[: len(base_angles)])
    app.set_stage("angles")
    app.fit_points()
    if want("5-4"):
        app.snap("5-4", scroll="#panel-angles")

    # 5-8 算例 1：补齐到 27 个观测角
    for angle in EXAMPLE1_OPTIMIZED_EXTRA[5:]:
        app.add_angle(*angle)
    state = app.state()
    all_angle_ids = [item["id"] for item in state["angles"]]
    app.set_stage("full")
    app.check_observed("observed-angle-list", all_angle_ids)
    result1 = app.calculate()
    app.fit_points()
    if want("5-8"):
        app.snap("5-8", scroll="#panel-angles")
    app.manifest["5-8"] = result1

    # 5-9 算例 2：9 点
    e2 = _example2_data()
    app.new_project("论文算例 2 · 9 点边角网（近似）")
    app.set_stage("points")
    for point in e2["points"]:
        app.click_point(point["lon"], point["lat"])
    app.set_fixed("8", True)
    app.set_fixed("9", True)
    app.fit_points()
    if want("5-9"):
        app.snap("5-9", scroll="#panel-points")

    # 5-11 算例 2：17 线 + 10 观测边 + 11 观测角
    app.set_stage("lines")
    for start, end in e2["lines"]:
        app.add_line(start, end)
    app.set_stage("full")
    for angle in e2["angles"]:
        app.add_angle(*angle)
    app.set_stage("full")
    state = app.state()
    edge_by_pair = {
        frozenset((str(line["from_name"]), str(line["to_name"]))): line["id"]
        for line in state["lines"]
    }
    observed_edge_ids = [
        edge_by_pair[frozenset((start, end))]
        for start, end in e2["selected_edges"]
    ]
    app.check_observed("observed-edge-list", observed_edge_ids)
    app.check_observed(
        "observed-angle-list", [angle["id"] for angle in state["angles"]]
    )
    result2 = app.calculate()
    app.fit_points()
    if want("5-11"):
        app.snap("5-11", scroll="#panel-network")
    app.manifest["5-11"] = result2

    # 5-13 算例 2 优化：6 个新增观测角，黄色
    for angle in EXAMPLE2_OPTIMIZED_EXTRA:
        app.add_angle(*angle)
    state = app.state()
    existing = {
        (
            item["backsight_name"],
            item["station_name"],
            item["foresight_name"],
        )
        for item in state["angles"]
        if item["id"] in set(state["network"]["observed_angles"])
    }
    added_ids = []
    for item in state["angles"]:
        key = (item["backsight_name"], item["station_name"], item["foresight_name"])
        if key in {
            (str(a[0]), str(a[1]), str(a[2])) for a in EXAMPLE2_OPTIMIZED_EXTRA
        } and key not in existing:
            added_ids.append(item["id"])
    app.check_added("added-angle-list", added_ids)
    result3 = app.calculate()
    app.fit_points()
    if want("5-13"):
        app.snap("5-13", scroll="#result-box")
    app.manifest["5-13"] = result3

    return app.manifest


# ----------------------------------------------------------------------
# PIL 对比图
# ----------------------------------------------------------------------
def _font(size: int, bold: bool = False):
    from PIL import ImageFont

    path = FONT_BOLD if bold else FONT_REGULAR
    if path.exists():
        return ImageFont.truetype(str(path), size=size, index=0)
    return ImageFont.load_default()


def _fit_image(image, box_w: int, box_h: int):
    from PIL import Image

    scale = min(box_w / image.width, box_h / image.height)
    size = (max(1, round(image.width * scale)), max(1, round(image.height * scale)))
    return image.resize(size, Image.LANCZOS)


def build_comparison(fig: str) -> Path:
    from PIL import Image, ImageDraw

    target_path = TARGET_DIR / FIGURES[fig][0]
    ours_path = OUT / f"ours_fig{fig}.png"
    target = Image.open(target_path).convert("RGB")
    ours = Image.open(ours_path).convert("RGB")

    pane_w, pane_h = 770, 530
    margin, gap, title_h = 24, 22, 74
    canvas_w = margin * 2 + pane_w * 2 + gap
    top = title_h + 28
    left = _fit_image(target, pane_w, pane_h)
    right = _fit_image(ours, pane_w, pane_h)
    image_h = max(left.height, right.height)
    canvas_h = top + image_h + 42
    canvas = Image.new("RGB", (canvas_w, canvas_h), "#ffffff")
    draw = ImageDraw.Draw(canvas)

    # 顶部标题条
    draw.rectangle([0, 0, canvas_w, title_h - 14], fill="#f4f8ef")
    draw.rectangle([0, title_h - 14, canvas_w, title_h - 12], fill="#7aa26b")
    draw.text(
        (margin, 14),
        f"论文 图{fig} | ctrlnet 本地离线",
        fill="#1f3b2a",
        font=_font(25, True),
    )
    draw.text(
        (margin, 46),
        f"左：论文原图 {FIGURES[fig][0]}    右：outputs/target_match/ours_fig{fig}.png（1280×630）",
        fill="#667066",
        font=_font(13),
    )

    # 列标签
    draw.text((margin, title_h + 2), "论文原图", fill="#32567a", font=_font(14, True))
    draw.text(
        (margin + pane_w + gap, title_h + 2),
        "ctrlnet 本地离线截图",
        fill="#3c763d",
        font=_font(14, True),
    )

    left_x = margin
    right_x = margin + pane_w + gap
    canvas.paste(left, (left_x + (pane_w - left.width) // 2, top))
    canvas.paste(right, (right_x + (pane_w - right.width) // 2, top))
    for x, image in ((left_x, left), (right_x, right)):
        draw.rectangle(
            [x, top, x + pane_w - 1, top + image_h],
            outline="#d7ddd1",
            width=1,
        )

    caption = FIGURES[fig][1]
    draw.text(
        (margin, top + image_h + 12),
        f"复刻要点：{caption}",
        fill="#4b554a",
        font=_font(13),
    )
    draw.text(
        (canvas_w - margin - 200, top + image_h + 12),
        "离线 DEM 底图 · 127.0.0.1",
        fill="#7b8578",
        font=_font(12),
    )

    path = OUT / f"compare_fig{fig}.png"
    canvas.save(path, optimize=True)
    return path


def build_overview(figures: Sequence[str]) -> Path:
    from PIL import Image, ImageDraw

    columns = 3
    tile_w, tile_h = 520, 218
    gap, margin, header = 18, 26, 72
    rows = (len(figures) + columns - 1) // columns
    canvas_w = margin * 2 + columns * tile_w + (columns - 1) * gap
    canvas_h = header + rows * (tile_h + 30) + margin
    canvas = Image.new("RGB", (canvas_w, canvas_h), "#ffffff")
    draw = ImageDraw.Draw(canvas)
    draw.rectangle([0, 0, canvas_w, header - 20], fill="#f4f8ef")
    draw.rectangle([0, header - 20, canvas_w, header - 18], fill="#7aa26b")
    draw.text(
        (margin, 14),
        "论文图 4-1～5-13 复刻对照总览（左：论文原图 / 右：ctrlnet 本地离线）",
        fill="#1f3b2a",
        font=_font(24, True),
    )
    draw.text(
        (margin, 46),
        "全部截图由 Playwright 在 1280×630 视口自动操作 /thesis 生成；底图为本地 DEM，无在线瓦片。",
        fill="#667066",
        font=_font(13),
    )
    for index, fig in enumerate(figures):
        compare = Image.open(OUT / f"compare_fig{fig}.png").convert("RGB")
        thumb = compare.resize((tile_w, tile_h), Image.LANCZOS)
        col = index % columns
        row = index // columns
        x = margin + col * (tile_w + gap)
        y = header + row * (tile_h + 30)
        canvas.paste(thumb, (x, y))
        draw.rectangle([x, y, x + tile_w - 1, y + tile_h - 1], outline="#d7ddd1")
        draw.text(
            (x, y + tile_h + 5),
            f"图 {fig}  ·  {FIGURES[fig][1]}",
            fill="#3a463a",
            font=_font(12, True),
        )
    path = OUT / "overview.png"
    canvas.save(path, optimize=True)
    return path


# ----------------------------------------------------------------------
# 主流程
# ----------------------------------------------------------------------
def _check_offline(requests: Sequence[str], base: str) -> None:
    bad = [
        url
        for url in requests
        if not (
            url.startswith(base)
            or url.startswith("data:")
            or url.startswith("blob:")
            or url.startswith("about:")
        )
    ]
    if bad:
        raise RuntimeError("检测到非本地请求：" + ", ".join(bad[:8]))


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--only",
        nargs="*",
        default=None,
        help="只重拍指定图号，例如 --only 4-1 5-13",
    )
    parser.add_argument("--no-compare", action="store_true", help="只拍截图，不生成对比图")
    args = parser.parse_args(argv)
    only = set(args.only) if args.only else None
    if only:
        unknown = only - set(FIGURES)
        if unknown:
            parser.error("未知图号：" + ", ".join(sorted(unknown)))

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("缺少 playwright：请运行 .venv/bin/pip install -e '.[e2e]'", file=sys.stderr)
        return 2

    OUT.mkdir(parents=True, exist_ok=True)
    tmp_dir = ROOT / ".tmp"
    tmp_dir.mkdir(exist_ok=True)
    for stale in OUT.glob("ours_fig*.png"):
        if only is None or stale.stem.replace("ours_fig", "") in only:
            stale.unlink()
    db_path = tmp_dir / "target_match.sqlite"
    if db_path.exists():
        db_path.unlink()

    process, base = start_server(db_path)
    external: List[str] = []
    console_errors: List[str] = []
    page_errors: List[str] = []
    manifest: Dict[str, Any] = {}
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(
                headless=True,
                args=["--no-sandbox", "--disable-dev-shm-usage"],
            )
            page = browser.new_page(viewport=VIEWPORT, device_scale_factor=1)
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
            page.on(
                "console",
                lambda message: console_errors.append(f"{message.type}: {message.text}")
                if message.type == "error"
                else None,
            )
            page.on("pageerror", lambda exc: page_errors.append(str(exc)))
            manifest = capture(page, base, only)
            browser.close()
    finally:
        stop_server(process)

    _check_offline(external, base)
    if console_errors or page_errors:
        raise RuntimeError(
            "浏览器错误：" + "; ".join((console_errors + page_errors)[:6])
        )

    figures = [fig for fig in FIG_ORDER if only is None or fig in only]
    if not args.no_compare:
        for fig in figures:
            if not (OUT / f"ours_fig{fig}.png").exists():
                raise RuntimeError(f"缺少截图 ours_fig{fig}.png")
            build_comparison(fig)
        # 总览只在全量重拍时生成，避免半套缩略图覆盖完整总览。
        if only is None:
            build_overview([fig for fig in FIG_ORDER if (OUT / f"ours_fig{fig}.png").exists()])

    meta = {
        "viewport": VIEWPORT,
        "figures": {
            fig: {
                "target": FIGURES[fig][0],
                "ours": f"ours_fig{fig}.png",
                "compare": f"compare_fig{fig}.png",
                "caption": FIGURES[fig][1],
            }
            for fig in FIG_ORDER
        },
        "calculation": manifest,
        "offline_requests": len(external),
        "note": "点位由经纬度换算成像素后真实点击地图添加；线/角/勾选/删除均走页面交互。",
    }
    (OUT / "manifest.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"[target-match] 截图 {len(figures)} 张，对比图 {len(figures)} 张 -> {OUT}")
    if manifest:
        for fig, result in manifest.items():
            print(
                f"[target-match] 图{fig}: {result.get('weakest')} "
                f"Qxx={result.get('qxx')} Qyy={result.get('qyy')} {result.get('badge')}"
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
