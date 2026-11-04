"""CTRLNET 本地离线网页地图（FastAPI）。

只读工程 + 离线 Leaflet 静态页。默认只由 :mod:`ctrlnet.webmap.__main__`
绑定 ``127.0.0.1:8765``；本模块本身不做公网暴露，也没有账号体系。
"""

from __future__ import annotations

from math import isfinite
from pathlib import Path
from typing import Any, Optional

import numpy as np
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from ..terrain import line_of_sight_height
from .state import ProjectStore, default_project_path

STATIC_DIR = Path(__file__).resolve().parent / "static"


def _clean(value: Any, digits: int = 3) -> Optional[float]:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not isfinite(number):
        return None
    return round(number, digits)


def _clean_array(values: Any, digits: int = 3) -> list[Optional[float]]:
    return [_clean(v, digits) for v in np.asarray(values, dtype=float).ravel().tolist()]


def _point_lookup(store: ProjectStore, reference: str) -> Optional[dict]:
    ref = reference.strip()
    points = store.project.get("points", [])
    for point in points:
        if str(point.get("name")) == ref:
            return point
    upper = ref.upper()
    for point in points:
        if str(point.get("name")).upper() == upper:
            return point
    return None


def parse_endpoint(store: ProjectStore, reference: str) -> dict:
    """解析 ``P1`` 或 ``E,N`` 形式的端点。"""
    if not reference or not reference.strip():
        raise HTTPException(status_code=400, detail="端点不能为空")
    point = _point_lookup(store, reference)
    if point is not None:
        return {
            "label": str(point["name"]),
            "E": float(point["E"]),
            "N": float(point["N"]),
            "elevation_m": _clean(point.get("elevation_m")),
            "fixed": bool(point.get("fixed", False)),
            "source": "point",
        }

    text = reference.replace(";", ",").replace(" ", ",")
    parts = [part for part in text.split(",") if part != ""]
    if len(parts) == 2:
        try:
            E, N = float(parts[0]), float(parts[1])
        except ValueError:
            E = N = float("nan")
        if isfinite(E) and isfinite(N):
            return {
                "label": f"E={E:.0f},N={N:.0f}",
                "E": E,
                "N": N,
                "elevation_m": _clean(store.dem.elevation(E, N)),
                "fixed": False,
                "source": "coordinate",
            }
    if point is None and len(parts) != 2:
        raise HTTPException(
            status_code=404,
            detail=f"未知控制点 {reference!r}；可用点名或 'E,N' 坐标",
        )
    raise HTTPException(
        status_code=400,
        detail="端点格式应为点名（如 P1）或 'E,N'（如 415358.4,4421306.6）",
    )


def build_profile(store: ProjectStore, from_ref: str, to_ref: str) -> dict:
    start = parse_endpoint(store, from_ref)
    end = parse_endpoint(store, to_ref)
    if start["E"] == end["E"] and start["N"] == end["N"]:
        raise HTTPException(status_code=400, detail="剖面起点与终点重合")

    dem = store.dem
    analysis = store.project.get("analysis", {})
    inst_h = float(analysis.get("instrument_height_m", 1.5))
    target_h = float(analysis.get("target_height_m", 1.5))
    k = float(analysis.get("k", 0.13))
    radius = float(analysis.get("R_m", 6_371_000.0))
    clearance = float(analysis.get("clearance_threshold_m", 0.0))

    try:
        result = dem.intervisibility(
            (start["E"], start["N"]),
            (end["E"], end["N"]),
            inst_h=inst_h,
            target_h=target_h,
            k=k,
            R=radius,
            clearance=clearance,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    distance = result.profile.distance
    terrain = result.profile.elevation
    chord = result.h1 + (result.h2 - result.h1) * distance / result.distance
    obstruction = None
    if result.obstruction_position is not None:
        obstruction = {
            "E": _clean(result.obstruction_position[0]),
            "N": _clean(result.obstruction_position[1]),
            "elevation_m": _clean(result.min_terrain_elevation),
            "distance_m": _clean(result.min_distance),
        }

    return {
        "from": start,
        "to": end,
        "crs": store.project.get("dem", {}).get("crs", "EPSG:32650"),
        "distance_m": _clean(result.distance, 3),
        "status": result.status,
        "visible": bool(result.visible),
        "min_clearance_m": _clean(result.min_clearance, 3),
        "min_distance_m": _clean(result.min_distance, 3),
        "obstruction": obstruction,
        "nodata_count": int(result.nodata_count),
        "samples": int(result.profile.sample_count),
        "analysis": {
            "instrument_height_m": inst_h,
            "target_height_m": target_h,
            "k": k,
            "R_m": radius,
            "clearance_threshold_m": clearance,
        },
        "profile": {
            "distance_m": _clean_array(distance),
            "elevation_m": _clean_array(terrain),
            "los_m": _clean_array(result.line_height),
            "chord_m": _clean_array(chord),
            "clearance_m": _clean_array(result.clearance),
            "nodata": [bool(v) for v in result.profile.nodata.tolist()],
        },
    }


def create_app(project_path: Optional[Path | str] = None) -> FastAPI:
    store = ProjectStore(project_path)
    app = FastAPI(
        title="CTRLNET 本地网页地图",
        description="离线 DEM 晕渲/等高线/控制点/观测线/误差椭圆与影像配准演示",
        version="0.1.0",
        docs_url="/api/docs",
        redoc_url=None,
        openapi_url="/api/openapi.json",
    )
    app.state.store = store

    if STATIC_DIR.exists():
        app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    @app.get("/", include_in_schema=False)
    def index() -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html", media_type="text/html; charset=utf-8")

    @app.get("/favicon.ico", include_in_schema=False)
    def favicon() -> Response:
        return Response(status_code=204)

    @app.get("/api/health", summary="健康检查")
    def health() -> dict:
        return {"status": "ok", "project": store.project_path.name}

    @app.get("/api/project", summary="工程详情")
    def project() -> JSONResponse:
        return JSONResponse(store.project_payload())

    @app.get("/api/layers", summary="图层清单与 GeoJSON")
    def layers() -> JSONResponse:
        payload = store.layers()
        payload["summary"] = store.summary()
        return JSONResponse(payload)

    @app.get(
        "/api/overlay/hillshade.png",
        summary="DEM 晕渲 + 分层设色 PNG",
        response_class=Response,
    )
    def hillshade_png() -> Response:
        return Response(
            content=store.hillshade_png(),
            media_type="image/png",
            headers={"Cache-Control": "public, max-age=3600"},
        )

    @app.get("/api/profile", summary="DEM 剖面与通视")
    def profile(
        from_: str = Query(..., alias="from", description="起点点名或 E,N"),
        to_: str = Query(..., alias="to", description="终点点名或 E,N"),
    ) -> JSONResponse:
        return JSONResponse(build_profile(store, from_, to_))

    @app.get("/api/registration/demo", summary="示例扫描图配准结果")
    def registration_demo() -> JSONResponse:
        return JSONResponse(store.registration_demo)

    @app.get(
        "/api/registration/demo/image.png",
        summary="示例扫描图原始影像",
        response_class=FileResponse,
    )
    def registration_image() -> FileResponse:
        demo = store.registration_demo
        image_path = store.resolve_data_path(str(demo["image_name"]))
        return FileResponse(image_path, media_type="image/png")

    @app.get(
        "/api/registration/demo/overlay.png",
        summary="按 4 个控制点配准后的半透明叠加影像",
        response_class=Response,
    )
    def registration_overlay() -> Response:
        return Response(
            content=store.registration_overlay_png(),
            media_type="image/png",
            headers={"Cache-Control": "public, max-age=3600"},
        )

    return app


app = create_app()

__all__ = ["app", "build_profile", "create_app", "parse_endpoint"]
