"""网页地图的 SQLite 工程状态、方案切换、DEM 与配准演示缓存。

网页端从 ``data/sample/demo_project.sqlite`` 读取工程和方案；每个方案通过
``ctrlnet.store.get_or_compute_result`` 按 ``input_hash`` 取缓存结果。DEM、
晕渲 PNG、等高线、方案图层与报告都在进程内惰性缓存。
"""

from __future__ import annotations

import math
import os
import tempfile
import threading
from pathlib import Path
from typing import Any, Optional

from ..registration import RegistrationResult, register_affine
from ..store import get_or_compute_result, load_project
from ..terrain import DEM
from .render import (
    build_layers,
    rectify_image,
    render_hillshade_png,
)


def _repo_root() -> Path:
    # src/ctrlnet/webmap/state.py -> repo root
    return Path(__file__).resolve().parents[3]


def default_project_path() -> Path:
    """默认 SQLite 工程：环境变量 ``CTRLNET_DB`` 优先。"""
    value = os.environ.get("CTRLNET_DB") or os.environ.get("CTRLNET_PROJECT")
    if value:
        return Path(value).expanduser().resolve()
    repo = _repo_root()
    for candidate in (
        repo / "data" / "sample" / "demo_project.sqlite",
        Path.cwd() / "data" / "sample" / "demo_project.sqlite",
    ):
        if candidate.exists():
            return candidate.resolve()
    raise FileNotFoundError(
        "找不到 demo_project.sqlite；请先运行 scripts/build_demo_project.py"
    )


def _relative(path: Path, base: Path) -> str:
    try:
        return str(path.resolve().relative_to(base.resolve()))
    except ValueError:
        return str(path)


def _nice_scale(max_value: float, extent: float, target_fraction: float = 0.045) -> float:
    target = max(extent * target_fraction, 1e-9)
    if max_value <= 0.0:
        return 1.0
    raw = target / max_value
    exponent = math.floor(math.log10(raw))
    base = 10.0 ** exponent
    fraction = raw / base
    for candidate in (1.0, 2.0, 2.5, 5.0, 10.0):
        if fraction <= candidate:
            return candidate * base
    return 10.0 * base


class ProjectStore:
    """加载 ``demo_project.sqlite`` 并暴露方案化只读视图。"""

    def __init__(self, project_path: Optional[Path | str] = None) -> None:
        self.project_path = (
            Path(project_path).expanduser().resolve()
            if project_path is not None
            else default_project_path()
        )
        if not self.project_path.exists():
            raise FileNotFoundError(f"工程文件不存在：{self.project_path}")
        if self.project_path.suffix.lower() not in (".sqlite", ".sqlite3", ".db"):
            raise ValueError(
                "网页地图需要 SQLite 工程（.sqlite/.db）；"
                "请先运行 scripts/build_demo_project.py"
            )
        self.root = _repo_root()
        self.project = load_project(self.project_path)
        self._lock = threading.RLock()
        self._dem: Optional[DEM] = None
        self._layers: dict[tuple[str, bool], dict] = {}
        self._hillshade: Optional[bytes] = None
        self._registration: Optional[dict] = None
        self._registration_overlay: Optional[bytes] = None
        self._scenario_cache: dict[str, dict] = {}
        self._result_cache: dict[str, dict] = {}
        self._report_cache: dict[tuple[str, str], tuple[bytes, str, str]] = {}

    # ---- 路径 -----------------------------------------------------
    @property
    def terrain_metadata(self) -> dict:
        return dict(self.project.get("metadata", {}).get("terrain") or {})

    def resolve_data_path(self, value: str) -> Path:
        path = Path(value)
        candidates = []
        if path.is_absolute():
            candidates.append(path)
        else:
            candidates.extend(
                [
                    self.project_path.parent / path,
                    self.root / path,
                    Path.cwd() / path,
                ]
            )
        for candidate in candidates:
            if candidate.exists():
                return candidate.resolve()
        raise FileNotFoundError(f"找不到数据文件 {value!r}")

    @property
    def dem_path(self) -> Path:
        value = (self.terrain_metadata.get("dem") or {}).get("path")
        return self.resolve_data_path(str(value or "data/sample/dem_sample.tif"))

    @property
    def registration_demo_path(self) -> Path:
        return self.project_path.parent / "registration_demo.json"

    # ---- 惰性对象 -------------------------------------------------
    @property
    def dem(self) -> DEM:
        with self._lock:
            if self._dem is None:
                self._dem = DEM.from_geotiff(self.dem_path)
            return self._dem

    def hillshade_png(self) -> bytes:
        with self._lock:
            if self._hillshade is None:
                self._hillshade = render_hillshade_png(self.dem)
            return self._hillshade

    # ---- 方案 -----------------------------------------------------
    def scenario_records(self) -> list[dict]:
        records = []
        for item in self.project.get("scenarios") or []:
            records.append(
                {
                    "id": str(item["id"]),
                    "name": str(item["name"]),
                    "version": int(item.get("version", 1)),
                    "parent_id": item.get("parent_id"),
                    "description": item.get("description"),
                    "n_observations": int(
                        item.get("n_observations") or len(item.get("observations") or [])
                    ),
                    "metadata": dict(item.get("metadata") or {}),
                }
            )
        return records

    def default_scenario_id(self) -> str:
        default = str(self.project.get("metadata", {}).get("default_scenario") or "")
        records = self.scenario_records()
        for item in records:
            if item["id"] == default:
                return default
        if not records:
            raise KeyError("工程没有方案")
        return str(records[0]["id"])

    def resolve_scenario_id(self, scenario: Optional[str] = None) -> str:
        if scenario is None or str(scenario).strip() == "":
            return self.default_scenario_id()
        text = str(scenario)
        for item in self.scenario_records():
            if item["id"] == text or item["name"] == text:
                return str(item["id"])
        raise KeyError(f"工程中不存在方案 {scenario!r}")

    def scenario(self, scenario_id: Optional[str] = None) -> dict:
        sid = self.resolve_scenario_id(scenario_id)
        with self._lock:
            if sid not in self._scenario_cache:
                for item in self.project.get("scenarios") or []:
                    if str(item["id"]) == sid:
                        self._scenario_cache[sid] = item
                        break
                else:  # pragma: no cover - resolve 已保证存在
                    raise KeyError(sid)
            return self._scenario_cache[sid]

    def result(self, scenario_id: Optional[str] = None) -> dict:
        sid = self.resolve_scenario_id(scenario_id)
        with self._lock:
            if sid not in self._result_cache:
                item = self.scenario(sid)
                confidence = float(item.get("metadata", {}).get("confidence", 0.95))
                self._result_cache[sid] = get_or_compute_result(
                    self.project_path,
                    sid,
                    options={"confidence": confidence},
                )
            return self._result_cache[sid]

    def _scenario_points(self, scenario: dict) -> list[dict]:
        names = scenario.get("metadata", {}).get("points") or scenario.get(
            "metadata", {}
        ).get("point_names")
        by_name = {str(p["name"]): p for p in self.project.get("points") or []}
        if names:
            return [by_name[str(name)] for name in names if str(name) in by_name]
        return list(self.project.get("points") or [])

    def _visibility_lookup(self, scenario: dict) -> dict[tuple[str, str], dict]:
        lookup = {}
        for row in scenario.get("metadata", {}).get("visibility") or []:
            key = tuple(sorted((str(row.get("from")), str(row.get("to")))))
            lookup[key] = row
        return lookup

    def scenario_payload(self, scenario_id: Optional[str] = None) -> dict:
        sid = self.resolve_scenario_id(scenario_id)
        scenario = self.scenario(sid)
        result = self.result(sid)
        base_points = self._scenario_points(scenario)
        result_points = {row["name"]: row for row in result.get("points") or []}
        points = []
        for base in base_points:
            name = str(base["name"])
            precision = result_points.get(name, {})
            ellipse = precision.get("ellipse") or {}
            points.append(
                {
                    "name": name,
                    "E": float(precision.get("E", base.get("E", 0.0))),
                    "N": float(precision.get("N", base.get("N", 0.0))),
                    "fixed": bool(precision.get("fixed", base.get("fixed", False))),
                    "role": precision.get(
                        "role", "fixed" if base.get("fixed") else "unknown"
                    ),
                    "elevation_m": base.get("elevation_m"),
                    "lon": base.get("lon"),
                    "lat": base.get("lat"),
                    "sigma_E_mm": float(precision.get("sigma_E_mm", 0.0)),
                    "sigma_N_mm": float(precision.get("sigma_N_mm", 0.0)),
                    "mp_mm": float(precision.get("mp_mm", 0.0)),
                    "ellipse_95": {
                        "a_m": float(ellipse.get("a_m", 0.0)),
                        "b_m": float(ellipse.get("b_m", 0.0)),
                        "azimuth_deg": float(ellipse.get("azimuth_deg", 0.0)),
                        "confidence": ellipse.get("confidence", 0.95),
                    },
                }
            )

        names = {p["name"] for p in points}
        visibility = [
            row
            for row in scenario.get("metadata", {}).get("visibility") or []
            if str(row.get("from")) in names and str(row.get("to")) in names
        ]
        lookup = self._visibility_lookup(scenario)
        result_obs = {
            str(row.get("id")): row for row in result.get("observations") or []
        }
        observations = []
        for row in scenario.get("observations") or []:
            if not row.get("enabled", True):
                continue
            kind = str(row.get("kind") or "")
            item = {
                "id": str(row.get("id") or ""),
                "kind": kind,
                "enabled": True,
            }
            if kind == "distance":
                frm, to = str(row.get("from", row.get("frm"))), str(row.get("to"))
                vis = lookup.get(tuple(sorted((frm, to))))
                item.update(
                    {
                        "from": frm,
                        "to": to,
                        "value_m": row.get("value_m"),
                        "visible": None if vis is None else bool(vis.get("visible")),
                        "status": "observed" if vis is None else vis.get("status"),
                        "distance_m": (
                            float(vis["distance_m"]) if vis else row.get("value_m")
                        ),
                        "min_clearance_m": None
                        if vis is None
                        else vis.get("min_clearance_m"),
                        "min_distance_m": None
                        if vis is None
                        else vis.get("min_distance_m"),
                        "obstruction": None if vis is None else vis.get("obstruction"),
                        "samples": 0 if vis is None else vis.get("samples", 0),
                        "nodata_count": 0
                        if vis is None
                        else vis.get("nodata_count", 0),
                    }
                )
            elif kind == "angle":
                item.update(
                    {
                        "backsight": str(row.get("backsight", row.get("rear"))),
                        "station": str(row.get("station")),
                        "foresight": str(row.get("foresight", row.get("front"))),
                        "value_deg": row.get("value_deg"),
                        "visible": None,
                        "status": "observed",
                    }
                )
            else:
                item.update(
                    {key: row.get(key) for key in ("station", "target", "from", "to")}
                )
            rel = result_obs.get(item["id"]) or {}
            item.update(
                {
                    "r_i": rel.get("r_i"),
                    "mdb": rel.get("mdb"),
                    "mdb_unit": rel.get("mdb_unit"),
                    "external_max_mm": rel.get("external_max_mm"),
                    "external_point": rel.get("external_point"),
                }
            )
            observations.append(item)

        analysis = dict(self.terrain_metadata.get("analysis") or {})
        extent = max(
            max((p["E"] for p in points), default=1.0)
            - min((p["E"] for p in points), default=0.0),
            max((p["N"] for p in points), default=1.0)
            - min((p["N"] for p in points), default=0.0),
            1.0,
        )
        max_a = max(
            (
                float((p.get("ellipse_95") or {}).get("a_m", 0.0))
                for p in points
                if not p.get("fixed")
            ),
            default=0.0,
        )
        analysis["ellipse_scale"] = _nice_scale(max_a, extent)
        analysis.setdefault("confidence", 0.95)
        summary = dict(result.get("summary") or {})
        summary.update(
            {
                "name": self.project.get("name"),
                "scenario_id": sid,
                "scenario_name": scenario.get("name"),
                "scenario_version": scenario.get("version"),
                "n_pairs": len(visibility),
                "n_visible": sum(1 for row in visibility if row.get("visible")),
                "n_points": len(points),
                "n_fixed": sum(1 for p in points if p.get("fixed")),
                "n_observations": len(observations),
                "crs": self.project.get("crs"),
                "max_mp_mm": float(summary.get("max_mp_mm", 0.0)),
                "min_r": summary.get("min_r"),
                "snapshot_hash": result.get("input_hash"),
                "dem": self.terrain_metadata.get("dem") or {},
            }
        )
        return {
            "scenario": {
                "id": sid,
                "name": scenario.get("name"),
                "version": scenario.get("version"),
                "parent_id": scenario.get("parent_id"),
                "description": scenario.get("description"),
                "metadata": dict(scenario.get("metadata") or {}),
            },
            "points": points,
            "observations": observations,
            "visibility": visibility,
            "analysis": analysis,
            "network": result.get("network"),
            "datum": result.get("datum"),
            "summary": summary,
            "snapshot_hash": result.get("input_hash"),
            "dem": self.terrain_metadata.get("dem") or {},
            "crs": self.project.get("crs"),
        }

    def _render_project(self, payload: dict) -> dict:
        return {
            "dem": payload.get("dem") or {},
            "analysis": payload["analysis"],
            "points": payload["points"],
            "visibility": payload["visibility"],
            "observations": payload["observations"],
        }

    # ---- 图层 -----------------------------------------------------
    def layers(self, scenario_id: Optional[str] = None, *, include_contours: bool = True) -> dict:
        sid = self.resolve_scenario_id(scenario_id)
        with self._lock:
            key = (sid, include_contours)
            if key not in self._layers:
                payload = self.scenario_payload(sid)
                render_project = self._render_project(payload)
                layers = build_layers(render_project, self.dem, include_contours=include_contours)
                layers["scenario"] = payload["scenario"]
                layers["summary"] = payload["summary"]
                layers["analysis"] = payload["analysis"]
                self._layers[key] = layers
            return self._layers[key]

    # ---- 摘要 / 工程载荷 -----------------------------------------
    def summary(self, scenario_id: Optional[str] = None) -> dict:
        payload = self.scenario_payload(scenario_id)
        summary = dict(payload["summary"])
        summary["schema"] = "ctrlnet.project/2"
        summary["dem"] = {
            **(self.terrain_metadata.get("dem") or {}),
            "shape": list(self.dem.shape),
            "resolution_m": list(self.dem.resolution),
            "bounds_native": list(self.dem.bounds),
        }
        summary["analysis"] = payload["analysis"]
        summary["snapshot_hash"] = payload["snapshot_hash"]
        return summary

    def project_payload(self, scenario_id: Optional[str] = None) -> dict:
        sid = self.resolve_scenario_id(scenario_id)
        payload = self.scenario_payload(sid)
        return {
            "schema": "ctrlnet.project/2",
            "id": self.project.get("id"),
            "name": self.project.get("name"),
            "description": self.project.get("description"),
            "crs": self.project.get("crs"),
            "project_path": _relative(self.project_path, self.root),
            "scenarios": self.scenario_records(),
            "selected_scenario": sid,
            "points": payload["points"],
            "observations": payload["observations"],
            "visibility": payload["visibility"],
            "analysis": payload["analysis"],
            "network": payload["network"],
            "datum": payload["datum"],
            "summary": payload["summary"],
            "snapshot_hash": payload["snapshot_hash"],
            "dem": payload["dem"],
            "api": {
                "scenarios": "/api/scenarios",
                "scenario": f"/api/scenario/{sid}",
                "layers": f"/api/layers?scenario={sid}",
                "hillshade": "/api/overlay/hillshade.png",
                "profile": "/api/profile?from=P1&to=P2",
                "registration_demo": "/api/registration/demo",
                "report_html": f"/api/report?scenario={sid}&format=html",
                "report_md": f"/api/report?scenario={sid}&format=md",
                "report_docx": f"/api/report?scenario={sid}&format=docx",
            },
        }

    # ---- 报告 -----------------------------------------------------
    def report_content(
        self, scenario_id: Optional[str] = None, fmt: str = "html"
    ) -> tuple[bytes, str, str]:
        sid = self.resolve_scenario_id(scenario_id)
        fmt = str(fmt or "html").lower().lstrip(".")
        if fmt in ("htm", "html"):
            fmt = "html"
        if fmt in ("md", "markdown"):
            fmt = "md"
        if fmt not in ("html", "md", "docx"):
            raise ValueError(f"不支持的报告格式：{fmt!r}（可选 html/md/docx）")
        key = (sid, fmt)
        with self._lock:
            if key in self._report_cache:
                return self._report_cache[key]

        from ..reportgen import render_html_report, write_report

        scenario_name = next(
            (
                str(item["name"])
                for item in self.scenario_records()
                if item["id"] == sid
            ),
            sid,
        )
        title = (
            "平面控制网设计报告 · "
            f"{self.project.get('name')} · {scenario_name}"
        )
        if fmt == "html":
            text = render_html_report(self.project_path, scenario=sid, title=title)
            content = text.encode("utf-8")
            media = "text/html; charset=utf-8"
            filename = f"design_report_{sid}.html"
        else:
            with tempfile.TemporaryDirectory(prefix="ctrlnet-web-report-") as tmp:
                data = write_report(
                    self.project_path,
                    tmp,
                    scenario=sid,
                    title=title,
                    docx=(fmt == "docx"),
                )
                if fmt == "md":
                    content = Path(data["markdown_path"]).read_bytes()
                    media = "text/markdown; charset=utf-8"
                    filename = f"design_report_{sid}.md"
                else:
                    docx_path = data.get("docx_path")
                    if not docx_path:
                        raise RuntimeError(
                            f"DOCX 生成失败：{data.get('docx_error', '未知原因')}"
                        )
                    content = Path(docx_path).read_bytes()
                    media = (
                        "application/vnd.openxmlformats-officedocument."
                        "wordprocessingml.document"
                    )
                    filename = f"design_report_{sid}.docx"
        result = (content, media, filename)
        with self._lock:
            self._report_cache[key] = result
        return result

    # ---- 配准演示 -------------------------------------------------
    @property
    def registration_demo(self) -> dict:
        with self._lock:
            if self._registration is None:
                self._registration = self._build_registration_demo()
            return self._registration

    def registration_overlay_png(self) -> bytes:
        with self._lock:
            self.registration_demo  # 确保已配准
            assert self._registration_overlay is not None
            return self._registration_overlay

    def _build_registration_demo(self) -> dict:
        import json

        path = self.registration_demo_path
        if not path.exists():
            raise FileNotFoundError(f"配准演示数据不存在：{path}")
        demo = json.loads(path.read_text(encoding="utf-8"))
        image_path = self.resolve_data_path(str(demo["image"]))
        result: RegistrationResult = register_affine(
            demo.get("control_points", []),
            demo.get("check_points", []),
        )
        bounds = self._registered_bounds(result, image_path)
        overlay, overlay_bounds, overlay_size = rectify_image(
            str(image_path), result.transform
        )
        self._registration_overlay = overlay
        payload = result.as_dict()
        payload.update(
            {
                "kind": "demo-scan",
                "description": demo.get("description"),
                "image_url": "/api/registration/demo/image.png",
                "overlay_url": "/api/registration/demo/overlay.png",
                "overlay_bounds": overlay_bounds,
                "overlay_size": list(overlay_size),
                "bounds_native": bounds,
                "opacity": float(demo.get("opacity", 0.48)),
                "pixel_convention": demo.get("pixel_convention"),
                "source_affine_reference": demo.get("source_affine"),
                "crs": demo.get("crs"),
                "image_name": image_path.name,
            }
        )
        return payload

    @staticmethod
    def _registered_bounds(result: RegistrationResult, image_path: Path) -> list[float]:
        try:
            from PIL import Image

            with Image.open(image_path) as image:
                width, height = image.width, image.height
        except Exception:  # pragma: no cover - 图像尺寸未知时退回控制点包络
            width = height = 1
        corners = [
            result.transform.xy(0.0, 0.0),
            result.transform.xy(float(width), 0.0),
            result.transform.xy(float(width), float(height)),
            result.transform.xy(0.0, float(height)),
        ]
        xs = [p[0] for p in corners]
        ys = [p[1] for p in corners]
        return [min(xs), min(ys), max(xs), max(ys)]


__all__ = ["ProjectStore", "default_project_path"]
