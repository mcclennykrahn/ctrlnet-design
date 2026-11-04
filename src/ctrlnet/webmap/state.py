"""网页地图的工程状态、DEM 与配准演示数据加载（进程内缓存）。"""

from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import Any, Optional

from ..registration import RegistrationResult, register_affine
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
    value = os.environ.get("CTRLNET_PROJECT")
    if value:
        return Path(value).expanduser().resolve()
    repo = _repo_root()
    candidate = repo / "data" / "sample" / "terrain_project.json"
    if candidate.exists():
        return candidate
    return (Path.cwd() / "data" / "sample" / "terrain_project.json").resolve()


def _relative(path: Path, base: Path) -> str:
    try:
        return str(path.resolve().relative_to(base.resolve()))
    except ValueError:
        return str(path)


class ProjectStore:
    """加载一个 ``terrain_project.json`` 并提供惰性缓存。"""

    def __init__(self, project_path: Optional[Path | str] = None) -> None:
        self.project_path = (
            Path(project_path).expanduser().resolve()
            if project_path is not None
            else default_project_path()
        )
        if not self.project_path.exists():
            raise FileNotFoundError(f"工程文件不存在：{self.project_path}")
        self.root = self.project_path.parents[2] if len(self.project_path.parents) >= 3 else Path.cwd()
        self.project = json.loads(self.project_path.read_text(encoding="utf-8"))
        self._lock = threading.RLock()
        self._dem: Optional[DEM] = None
        self._layers: Optional[dict] = None
        self._hillshade: Optional[bytes] = None
        self._registration: Optional[dict] = None
        self._registration_overlay: Optional[bytes] = None

    # ---- 路径 -----------------------------------------------------
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
        return self.resolve_data_path(str(self.project.get("dem", {}).get("path", "data/sample/dem_sample.tif")))

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

    def layers(self) -> dict:
        with self._lock:
            if self._layers is None:
                self._layers = build_layers(self.project, self.dem)
            return self._layers

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

    # ---- 摘要 -----------------------------------------------------
    def summary(self) -> dict:
        project = self.project
        dem = self.dem
        points = project.get("points", [])
        visibility = project.get("visibility", [])
        network = project.get("network", {})
        return {
            "name": project.get("description", project.get("schema", "ctrlnet project")),
            "schema": project.get("schema"),
            "generated_utc": project.get("generated_utc"),
            "crs": project.get("dem", {}).get("crs", "EPSG:32650"),
            "n_points": len(points),
            "n_fixed": sum(1 for p in points if p.get("fixed")),
            "n_pairs": len(visibility),
            "n_visible": sum(1 for v in visibility if v.get("visible")),
            "n_observations": int(network.get("n_observations", 0)),
            "max_mp_mm": max((float(p.get("mp_mm", 0.0)) for p in points), default=0.0),
            "dem": {
                "path": _relative(self.dem_path, self.root),
                "shape": list(dem.shape),
                "resolution_m": list(dem.resolution),
                "bounds_native": list(dem.bounds),
                "source": project.get("dem", {}).get("source"),
                "vertical_datum": project.get("dem", {}).get("vertical_datum"),
            },
            "analysis": project.get("analysis", {}),
        }

    def project_payload(self) -> dict:
        payload = dict(self.project)
        payload["project_path"] = _relative(self.project_path, self.root)
        payload["summary"] = self.summary()
        payload["api"] = {
            "layers": "/api/layers",
            "hillshade": "/api/overlay/hillshade.png",
            "profile": "/api/profile?from=P1&to=P2",
            "registration_demo": "/api/registration/demo",
        }
        return payload

    # ---- 配准演示 -------------------------------------------------
    def _build_registration_demo(self) -> dict:
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
