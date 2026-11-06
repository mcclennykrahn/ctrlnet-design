"""论文模式（D2）网页后端的工程状态、计算与 SQLite 持久化。

本模块只使用 D1 的 :mod:`ctrlnet.thesis` 计算核，不引入任何在线地图或网络
请求。前端把点/线/角/网拓扑保存在页面状态中；每次增删改都会同步到本模块
的内存工程。计算时按论文第 3 章的误差方程组装 B 矩阵，返回网页需要的
最弱点、Qxx/Qyy、M、限差、边长相对中误差分母与误差椭圆。

旧存档通过 ``thesis_projects`` JSON 表兼容读取。共享工程桥接使用
:mod:`ctrlnet.store` 的原生 projects/scenarios/snapshots 保存可追踪版本，
完整论文拓扑随方案元数据保留；不修改 D1 计算核和黄金算例。
"""

from __future__ import annotations

import json
import os
import copy
import math
import threading
from datetime import datetime, timezone
from math import atan2, degrees, hypot, isfinite
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

import numpy as np
from fastapi import APIRouter, Body, HTTPException
from fastapi.responses import FileResponse, JSONResponse

from ..store import connect
from ..thesis import (
    GRADES,
    build_network,
    check_tolerance,
    error_ellipse,
    export_angle_topology,
    export_coordinate_text,
    parse_coordinate_text,
    gauss_forward,
    gauss_inverse,
    get_grade,
    suggest_grade,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
SAMPLE_DIR = REPO_ROOT / "data" / "sample"
STATIC_DIR = Path(__file__).resolve().parent / "static"
DEFAULT_DB = Path(os.environ.get("CTRLNET_THESIS_DB", str(SAMPLE_DIR / "thesis_web.sqlite")))
DEFAULT_CENTRAL_MERIDIAN = 117.0
ORIGIN_LAT = 34.200
ORIGIN_LON = 117.200
SCHEMA = "ctrlnet.thesis.web/1"


class ThesisError(Exception):
    """带 HTTP 状态码的业务错误。"""

    def __init__(self, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.status_code = int(status_code)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _finite(value: Any, field: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise ThesisError(f"{field} 必须是数值") from None
    if not isfinite(number):
        raise ThesisError(f"{field} 必须是有限数值")
    return number


def _round(value: float, digits: int) -> float:
    return float(f"{float(value):.{int(digits)}f}")


def _plane_length_azimuth(
    x1: float, y1: float, x2: float, y2: float
) -> Tuple[float, float]:
    dx = float(x2) - float(x1)
    dy = float(y2) - float(y1)
    return hypot(dx, dy), degrees(atan2(dy, dx)) % 360.0


def _angle_at(
    backsight: Mapping[str, Any],
    station: Mapping[str, Any],
    foresight: Mapping[str, Any],
) -> float:
    _, az_back = _plane_length_azimuth(
        float(station["x"]), float(station["y"]), float(backsight["x"]), float(backsight["y"])
    )
    _, az_fore = _plane_length_azimuth(
        float(station["x"]), float(station["y"]), float(foresight["x"]), float(foresight["y"])
    )
    return (az_fore - az_back) % 360.0


def _lonlat_from_local(x: float, y: float) -> Tuple[float, float]:
    """把算例 2 的局部平面坐标放到徐州附近。

    局部坐标以已知点 8 为原点；这里用高斯反算把它锚定到
    ``ORIGIN_LAT/ORIGIN_LON`` 对应的平面位置，保证“反算经纬度 → 地图点击
    → 正算平面坐标”能还原同一组局部坐标（往返误差 < 1e-6 m），而不是用
    固定 110574 m/° 的近似换算引入米级缩放。
    """
    origin_x, origin_y = gauss_forward(
        ORIGIN_LAT, ORIGIN_LON, central_meridian=DEFAULT_CENTRAL_MERIDIAN
    )
    lat, lon = gauss_inverse(
        origin_x + float(x),
        origin_y + float(y),
        central_meridian=DEFAULT_CENTRAL_MERIDIAN,
    )
    return lon, lat


def _local_from_lonlat(lon: float, lat: float) -> Tuple[float, float]:
    origin_x, origin_y = gauss_forward(
        ORIGIN_LAT, ORIGIN_LON, central_meridian=DEFAULT_CENTRAL_MERIDIAN
    )
    x, y = gauss_forward(
        float(lat), float(lon), central_meridian=DEFAULT_CENTRAL_MERIDIAN
    )
    return x - origin_x, y - origin_y


def _projection(state):
    raw = state.get("projection", {})
    cm = _finite(raw.get("central_meridian", 117), "中央子午线")
    width = _finite(raw.get("zone_width", 3), "带宽")
    convention = raw.get("convention", "gauss")
    fe = _finite(raw.get("false_easting_m", 500000), "假东")
    if not -180 <= cm <= 180 or width not in (3, 6) or convention not in ("gauss", "utm") or abs(fe) > 10000000:
        raise ThesisError("投影参数无效：中央子午线 -180～180，带宽 3/6，约定 gauss/utm")
    return dict(central_meridian=cm, zone_width=width, convention=convention,
                false_easting_m=fe, zone_number=round(cm / width) if convention == "gauss" else round((cm + 183) / 6),
                ellipsoid="CGCS2000" if convention == "gauss" else "WGS84",
                axis="x 北 / y 东（m）", map_crs="WGS84 / EPSG:3857")


def _project_xy(state, lat, lon):
    p = _projection(state)
    if abs(lon - p["central_meridian"]) > p["zone_width"] / 2 or not -85 < lat < 85:
        raise ThesisError(f"跨带/带外坐标：超出中央子午线 {p['central_meridian']}° 的 {p['zone_width']}° 带")
    x, y = gauss_forward(lat, lon, central_meridian=p["central_meridian"],
                         zone_width=p["zone_width"], false_easting=0, ellipsoid=p["ellipsoid"])
    k = .9996 if p["convention"] == "utm" else 1
    return x * k, y * k + p["false_easting_m"]


def _inverse_xy(state, x, y):
    p = _projection(state)
    k = .9996 if p["convention"] == "utm" else 1
    return gauss_inverse(x / k, (y - p["false_easting_m"]) / k,
                         central_meridian=p["central_meridian"], zone_width=p["zone_width"],
                         false_easting=0, ellipsoid=p["ellipsoid"])


def _empty_state(name: str = "未命名论文工程") -> Dict[str, Any]:
    return {
        "schema": SCHEMA,
        "name": name,
        "created_at": _now(),
        "updated_at": _now(),
        "points": [],
        "lines": [],
        "angles": [],
        "network": {
            "grade": "二级",
            "observed_edges": [],
            "observed_angles": [],
            "added_edges": [],
            "added_angles": [],
            "tolerance_mm": 20.0,
            "ellipse_scale": 2000.0,
            "show_ellipses": True,
        },
        "seq": {"point": 0, "line": 0, "angle": 0},
    }


def _point_by_ref(state: Mapping[str, Any], ref: Any) -> Dict[str, Any]:
    text = str(ref).strip()
    if not text:
        raise ThesisError("点号不能为空")
    for point in state.get("points", []):
        if str(point.get("id")) == text:
            return point
    for point in state.get("points", []):
        if str(point.get("name")) == text:
            return point
    raise ThesisError(f"不存在点 {text!r}", status_code=404)


def _line_by_id(state: Mapping[str, Any], line_id: str) -> Dict[str, Any]:
    for line in state.get("lines", []):
        if str(line.get("id")) == str(line_id):
            return line
    raise ThesisError(f"不存在线 {line_id!r}", status_code=404)


def _angle_by_id(state: Mapping[str, Any], angle_id: str) -> Dict[str, Any]:
    for angle in state.get("angles", []):
        if str(angle.get("id")) == str(angle_id):
            return angle
    raise ThesisError(f"不存在角 {angle_id!r}", status_code=404)


def _ids(values: Any, allowed: set[str], label: str) -> List[str]:
    if values is None:
        return []
    if not isinstance(values, (list, tuple, set)):
        raise ThesisError(f"{label} 必须是数组")
    result: List[str] = []
    for value in values:
        text = str(value)
        if text and text not in allowed:
            raise ThesisError(f"{label} 中存在无效编号 {text!r}")
        if text and text not in result:
            result.append(text)
    return result


def _reindex_names(state: Dict[str, Any]) -> None:
    """按当前顺序重排点名/线号/角号；引用使用稳定 id，不受影响。"""
    for index, point in enumerate(state.get("points", []), start=1):
        point["name"] = str(index)
    for index, line in enumerate(state.get("lines", []), start=1):
        line["name"] = index
    for index, angle in enumerate(state.get("angles", []), start=1):
        angle["name"] = index


def _next_name(state: Mapping[str, Any], key: str) -> int:
    existing = [
        int(item.get("name"))
        for item in state.get(key, [])
        if str(item.get("name", "")).isdigit()
    ]
    return max([*existing, 0]) + 1


def _touch(state: Dict[str, Any]) -> None:
    state["updated_at"] = _now()


def _ensure_geometry(state: Dict[str, Any]) -> None:
    """按工程投影补齐坐标；旧工程沿用徐州默认值。"""
    for point in state.get("points", []):
        lon = point.get("lon")
        lat = point.get("lat")
        x = point.get("x")
        y = point.get("y")
        if (x is None or y is None) and lon is not None and lat is not None:
            x, y = _project_xy(state, float(lat), float(lon))
            point["x"], point["y"] = x, y
        if (lon is None or lat is None) and x is not None and y is not None:
            ox, oy = _project_xy(state, ORIGIN_LAT, ORIGIN_LON) if abs(float(x)) < 100000 else (0, 0)
            lat, lon = _inverse_xy(state, float(x) + ox, float(y) + oy)
            point["lon"], point["lat"] = lon, lat
        if x is None or y is None or lon is None or lat is None:
            raise ThesisError(f"点 {point.get('name')!r} 缺少坐标")
        point["x"] = float(x)
        point["y"] = float(y)
        point["lon"] = float(lon)
        point["lat"] = float(lat)
        point["fixed"] = bool(point.get("fixed", False))


def _line_geometry(state: Mapping[str, Any], line: Mapping[str, Any]) -> Tuple[float, float]:
    a = _point_by_ref(state, line.get("from"))
    b = _point_by_ref(state, line.get("to"))
    return _plane_length_azimuth(a["x"], a["y"], b["x"], b["y"])


def _angle_value(state: Mapping[str, Any], angle: Mapping[str, Any]) -> float:
    b = _point_by_ref(state, angle.get("backsight"))
    s = _point_by_ref(state, angle.get("station"))
    f = _point_by_ref(state, angle.get("foresight"))
    return _angle_at(b, s, f)


def _refresh_derived(state: Dict[str, Any]) -> None:
    for line in state.get("lines", []):
        length, azimuth = _line_geometry(state, line)
        if line.get("_keep_length"):
            line["length"] = float(line.get("length", length))
        else:
            line["length"] = length
        if line.get("_keep_azimuth"):
            line["azimuth"] = float(line.get("azimuth", azimuth))
        else:
            line["azimuth"] = azimuth
    for angle in state.get("angles", []):
        angle["value"] = _angle_value(state, angle)


def _public_state(state: Dict[str, Any]) -> Dict[str, Any]:
    _ensure_geometry(state)
    _refresh_derived(state)
    network = state.get("network", {})
    point_by_id = {str(p["id"]): p for p in state.get("points", [])}
    lines = []
    for line in state.get("lines", []):
        a = point_by_id[str(line["from"])]
        b = point_by_id[str(line["to"])]
        lines.append(
            {
                "id": line["id"],
                "name": int(line.get("name", 0)),
                "from": line["from"],
                "to": line["to"],
                "from_name": a["name"],
                "to_name": b["name"],
                "length": _round(line["length"], 4),
                "azimuth": _round(line["azimuth"], 4),
                "status": (
                    "added"
                    if line["id"] in network.get("added_edges", [])
                    else "observed"
                    if line["id"] in network.get("observed_edges", [])
                    else "graph"
                ),
            }
        )
    angles = []
    for angle in state.get("angles", []):
        b = point_by_id[str(angle["backsight"])]
        s = point_by_id[str(angle["station"])]
        f = point_by_id[str(angle["foresight"])]
        angles.append(
            {
                "id": angle["id"],
                "name": int(angle.get("name", 0)),
                "backsight": angle["backsight"],
                "station": angle["station"],
                "foresight": angle["foresight"],
                "backsight_name": b["name"],
                "station_name": s["name"],
                "foresight_name": f["name"],
                "value": _round(angle["value"], 4),
                "status": (
                    "added"
                    if angle["id"] in network.get("added_angles", [])
                    else "observed"
                    if angle["id"] in network.get("observed_angles", [])
                    else "graph"
                ),
            }
        )
    points = []
    for point in state.get("points", []):
        points.append(
            {
                "id": point["id"],
                "name": point["name"],
                "lon": float(point["lon"]),
                "lat": float(point["lat"]),
                "x": float(point["x"]),
                "y": float(point["y"]),
                "fixed": bool(point.get("fixed", False)),
            }
        )
    lengths = [line["length"] for line in lines]
    mean_side = float(np.mean(lengths)) if lengths else 0.0
    try:
        suggested = suggest_grade(mean_side).name if mean_side > 0 else str(network.get("grade", "二级"))
    except ValueError:
        suggested = str(network.get("grade", "二级"))
    payload = {
        "projection": dict(_projection(state),
            local=any(abs(p["x"]) < 100000 for p in points),
            note="局部平面锚定徐州原点" if any(abs(p["x"]) < 100000 for p in points) else "工程投影；WGS84 显示未应用基准七参数"),
        "schema": state.get("schema", SCHEMA),
        "name": state.get("name", "未命名论文工程"),
        "created_at": state.get("created_at"),
        "updated_at": state.get("updated_at"),
        "points": points,
        "lines": lines,
        "angles": angles,
        "network": {
            "grade": str(network.get("grade", "二级")),
            "observed_edges": list(network.get("observed_edges", [])),
            "observed_angles": list(network.get("observed_angles", [])),
            "added_edges": list(network.get("added_edges", [])),
            "added_angles": list(network.get("added_angles", [])),
            "tolerance_mm": float(network.get("tolerance_mm", 20.0)),
            "ellipse_scale": float(network.get("ellipse_scale", 200.0)),
            "show_ellipses": bool(network.get("show_ellipses", True)),
        },
        "seq": dict(state.get("seq", {})),
        "summary": {
            "n_points": len(points),
            "n_known": sum(1 for point in points if point["fixed"]),
            "n_unknown": sum(1 for point in points if not point["fixed"]),
            "n_lines": len(lines),
            "n_angles": len(angles),
            "avg_side_m": _round(mean_side, 4),
            "suggested_grade": suggested,
        },
        "grade_table": [
            {
                "name": grade.name,
                "mean_side_km": grade.mean_side_km,
                "angle_sigma_arcsec": grade.angle_sigma_arcsec,
                "a_mm": grade.a_mm,
                "b_ppm": grade.b_ppm,
                "max_relative_denominator": grade.max_relative_denominator,
            }
            for grade in GRADES
        ],
        "basemap": _basemap_payload(),
        "offline": True,
        "server_bind": "127.0.0.1",
    }
    return payload


def _basemap_payload() -> Dict[str, Any]:
    meta_path = SAMPLE_DIR / "thesis_basemap.json"
    png_path = SAMPLE_DIR / "thesis_basemap.png"
    if meta_path.exists():
        try:
            payload = json.loads(meta_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            payload = {}
    else:
        payload = {}
    payload.setdefault("bounds", [117.10, 34.15, 117.30, 34.25])
    payload["png_url"] = "/api/thesis/basemap.png"
    payload["png_exists"] = png_path.exists()
    payload["png_bytes"] = png_path.stat().st_size if png_path.exists() else 0
    return payload


def _grade_payload(name: str) -> Dict[str, Any]:
    try:
        grade = get_grade(name)
    except ValueError as exc:
        raise ThesisError(str(exc)) from exc
    return {
        "name": grade.name,
        "mean_side_km": grade.mean_side_km,
        "angle_sigma_arcsec": grade.angle_sigma_arcsec,
        "a_mm": grade.a_mm,
        "b_ppm": grade.b_ppm,
        "max_relative_denominator": grade.max_relative_denominator,
    }


def _calculate_impl(
    state: Mapping[str, Any],
    *,
    observed_edges: Sequence[str],
    observed_angles: Sequence[str],
    added_edges: Sequence[str],
    added_angles: Sequence[str],
    grade_name: str,
    tolerance_mm: float,
) -> Dict[str, Any]:
    grade = _grade_payload(grade_name)
    points = {str(p["name"]): (float(p["x"]), float(p["y"])) for p in state.get("points", [])}
    if not points:
        raise ThesisError("点库为空，无法计算")
    unknown = [str(p["name"]) for p in state.get("points", []) if not p.get("fixed")]
    known = [str(p["name"]) for p in state.get("points", []) if p.get("fixed")]
    if not unknown:
        raise ThesisError("没有未知点：请至少保留一个未知点")

    line_by_id = {str(line["id"]): line for line in state.get("lines", [])}
    angle_by_id = {str(angle["id"]): angle for angle in state.get("angles", [])}
    angle_ids = list(dict.fromkeys([*observed_angles, *added_angles]))
    edge_ids = list(dict.fromkeys([*observed_edges, *added_edges]))
    angles: List[Tuple[str, str, str]] = []
    for angle_id in angle_ids:
        angle = angle_by_id[angle_id]
        angles.append(
            (
                str(_point_by_ref(state, angle["backsight"])["name"]),
                str(_point_by_ref(state, angle["station"])["name"]),
                str(_point_by_ref(state, angle["foresight"])["name"]),
            )
        )
    distances: List[Tuple[str, str]] = []
    for edge_id in edge_ids:
        line = line_by_id[edge_id]
        distances.append(
            (
                str(_point_by_ref(state, line["from"])["name"]),
                str(_point_by_ref(state, line["to"])["name"]),
            )
        )
    if not angles and not distances:
        raise ThesisError("请至少勾选一个观测角或观测边")

    try:
        result = build_network(
            points,
            unknown=unknown,
            known=known,
            angles=angles,
            distances=distances,
            mw_arcsec=float(grade["angle_sigma_arcsec"]),
            coordinate_unit_mm=1.0,
            distance_a_mm=float(grade["a_mm"]),
            distance_b_ppm=float(grade["b_ppm"]),
            distance_sigma_model="linear",
            distance_weights=bool(distances),
            sigma0=float(grade["angle_sigma_arcsec"]),
        )
    except np.linalg.LinAlgError as exc:
        raise ThesisError(f"法方程秩亏，网形或已知点不足：{exc}", status_code=422) from exc
    except (ValueError, KeyError) as exc:
        raise ThesisError(f"计算失败：{exc}", status_code=422) from exc

    weakest = result.weakest_point()
    qxx, qyy, qxy = result.paper_q(weakest)
    strict_qxx, strict_qyy, strict_qxy = result.point_q(weakest)
    mw = float(grade["angle_sigma_arcsec"])
    ellipse_paper = error_ellipse(qxx, qyy, qxy, mw=mw)
    paper_mp_mm = float(result.paper_mp_mm(weakest))
    strict_mp_mm = float(result.mp_mm(weakest))
    ok, tolerance_text = check_tolerance(paper_mp_mm, tolerance_mm=float(tolerance_mm))
    mp_cm = paper_mp_mm / 10.0
    message = (
        f"最弱点 {weakest}：M={paper_mp_mm:.2f} mm（{mp_cm:.2f} cm），"
        + ("满足精度要求" if ok else "不满足精度要求")
        + f"（限差 {float(tolerance_mm):.1f} mm）"
    )

    ellipses = []
    for name in result.unknown:
        qx, qy, qz = result.paper_q(name)
        e = error_ellipse(qx, qy, qz, mw=mw)
        ellipses.append(
            {
                "name": name,
                "Qxx": _round(qx, 6),
                "Qyy": _round(qy, 6),
                "Qxy": _round(qz, 6),
                "E_mm": _round(e.E, 6),
                "F_mm": _round(e.F, 6),
                "phi_E_deg": _round(e.phi_E_deg, 6),
                "M_mm": _round(float(result.paper_mp_mm(name)), 6),
            }
        )

    observed_edge_set = set(edge_ids)
    edge_rows = []
    point_by_name = {str(p["name"]): p for p in state.get("points", [])}
    for line in state.get("lines", []):
        a = point_by_name[str(_point_by_ref(state, line["from"])["name"])]
        b = point_by_name[str(_point_by_ref(state, line["to"])["name"])]
        calc_length, calc_azimuth = _plane_length_azimuth(a["x"], a["y"], b["x"], b["y"])
        length = float(line.get("length") or calc_length)
        azimuth = float(line.get("azimuth") or calc_azimuth)
        denominator = length / 0.01 if length > 0 else float("inf")
        edge_rows.append(
            {
                "id": line["id"],
                "number": int(line.get("name", 0)),
                "from": a["name"],
                "to": b["name"],
                "length": _round(length, 4),
                "azimuth": _round(azimuth, 4),
                "denominator": _round(denominator, 1) if math.isfinite(denominator) else None,
                "limit": float(grade["max_relative_denominator"]),
                "passes": bool(denominator >= float(grade["max_relative_denominator"])),
                "observed": line["id"] in observed_edge_set,
                "status": (
                    "added"
                    if line["id"] in set(added_edges)
                    else "observed"
                    if line["id"] in set(observed_edges)
                    else "graph"
                ),
            }
        )
    finite_edges = [row for row in edge_rows if row["denominator"] is not None]
    weakest_edge = min(finite_edges, key=lambda row: row["denominator"]) if finite_edges else None

    comparison = None
    if added_edges or added_angles:
        base = _calculate_impl(
            state,
            observed_edges=observed_edges,
            observed_angles=observed_angles,
            added_edges=[],
            added_angles=[],
            grade_name=grade_name,
            tolerance_mm=tolerance_mm,
        )
        comparison = {
            "base_weakest_point": base["weakest_point"],
            "base_mp_mm": base["mp_paper_mm"],
            "base_mp_cm": base["mp_cm"],
            "optimized_mp_mm": paper_mp_mm,
            "optimized_mp_cm": mp_cm,
            "improved": bool(paper_mp_mm < base["mp_paper_mm"] - 1e-12),
            "base_n_observations": base["n_observations"],
            "optimized_n_observations": int(result.metadata.get("n_rows", 0)),
        }

    lengths = []
    for row in edge_rows:
        lengths.append(row["length"])
    mean_side = float(np.mean(lengths)) if lengths else 0.0
    try:
        suggested = suggest_grade(mean_side).name if mean_side > 0 else grade["name"]
    except ValueError:
        suggested = grade["name"]

    return {
        "ok": True,
        "grade": grade["name"],
        "grade_params": grade,
        "n_points": len(points),
        "n_unknown": len(unknown),
        "n_known": len(known),
        "n_observations": int(result.metadata.get("n_rows", 0)),
        "n_angles": len(angles),
        "n_observed_edges": len(distances),
        "n_added_observations": len(added_angles) + len(added_edges),
        "B_shape": [int(result.B.shape[0]), int(result.B.shape[1])],
        "rank": int(result.metadata.get("rank", 0)),
        "redundancy": int(result.metadata.get("redundancy", 0)),
        "weakest_point": weakest,
        "qxx": _round(qxx, 6),
        "qyy": _round(qyy, 6),
        "qxy": _round(qxy, 6),
        "q_unit": "论文数值口径（cm²/″²；严格 mm² 值同时给出）",
        "qxx_mm2": _round(strict_qxx, 6),
        "qyy_mm2": _round(strict_qyy, 6),
        "qxy_mm2": _round(strict_qxy, 6),
        "mp_paper_mm": _round(paper_mp_mm, 6),
        "mp_mm": _round(strict_mp_mm, 6),
        "mp_cm": _round(mp_cm, 6),
        "mw_arcsec": mw,
        "tolerance_mm": float(tolerance_mm),
        "satisfied": bool(ok),
        "tolerance_text": tolerance_text,
        "message": message,
        "ellipse": {
            "E_mm": _round(ellipse_paper.E, 6),
            "F_mm": _round(ellipse_paper.F, 6),
            "phi_E_deg": _round(ellipse_paper.phi_E_deg, 6),
        },
        "ellipses": ellipses,
        "edge_denominators": edge_rows,
        "weakest_edge": weakest_edge,
        "mean_side_m": _round(mean_side, 4),
        "suggested_grade": suggested,
        "comparison": comparison,
        "note": (
            "Qxx/Qyy/M 显示论文截图数值口径；严格 mm² 口径见 qxx_mm2/qyy_mm2/mp_mm。"
            "边长相对中误差分母按论文图 5-7/5-12 反推为 S/0.01 m。"
        ),
    }


def calculate_state(state: Mapping[str, Any]) -> Dict[str, Any]:
    network = state.get("network", {}) if isinstance(state, Mapping) else {}
    points = state.get("points", [])
    if not points:
        raise ThesisError("点库为空，无法计算")
    observed_edges = [str(v) for v in network.get("observed_edges", [])]
    observed_angles = [str(v) for v in network.get("observed_angles", [])]
    added_edges = [str(v) for v in network.get("added_edges", [])]
    added_angles = [str(v) for v in network.get("added_angles", [])]
    return _calculate_impl(
        state,
        observed_edges=observed_edges,
        observed_angles=observed_angles,
        added_edges=added_edges,
        added_angles=added_angles,
        grade_name=str(network.get("grade", "二级")),
        tolerance_mm=float(network.get("tolerance_mm", 20.0)),
    )


class ThesisRepository:
    """论文工程 JSON 的 SQLite 存储；与 ctrlnet.store 使用同一个连接入口。"""

    def __init__(self, path: Optional[Path | str] = None) -> None:
        self.path = Path(path).expanduser().resolve() if path else DEFAULT_DB
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def _init_schema(self) -> None:
        conn = connect(self.path)
        try:
            with conn:
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS thesis_projects (
                        name TEXT PRIMARY KEY,
                        state_json TEXT NOT NULL,
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL
                    )
                    """
                )
        finally:
            conn.close()

    def save(self, name: str, state: Mapping[str, Any]) -> Dict[str, Any]:
        text = str(name or "").strip()
        if not text:
            raise ThesisError("工程名不能为空")
        now = _now()
        conn = connect(self.path)
        try:
            with conn:
                existing = conn.execute(
                    "SELECT created_at FROM thesis_projects WHERE name=?", (text,)
                ).fetchone()
                created = str(existing["created_at"]) if existing else now
                conn.execute(
                    "INSERT INTO thesis_projects(name, state_json, created_at, updated_at) "
                    "VALUES (?,?,?,?) ON CONFLICT(name) DO UPDATE SET "
                    "state_json=excluded.state_json, updated_at=excluded.updated_at",
                    (
                        text,
                        json.dumps(state, ensure_ascii=False, separators=(",", ":")),
                        created,
                        now,
                    ),
                )
        finally:
            conn.close()
        return self.get(text)

    def get(self, name: str) -> Dict[str, Any]:
        conn = connect(self.path)
        try:
            row = conn.execute(
                "SELECT * FROM thesis_projects WHERE name=?", (str(name),)
            ).fetchone()
        finally:
            conn.close()
        if row is None:
            raise ThesisError(f"不存在论文工程 {name!r}", status_code=404)
        payload = json.loads(row["state_json"])
        payload.setdefault("schema", SCHEMA)
        payload["saved_name"] = str(row["name"])
        payload["saved_created_at"] = str(row["created_at"])
        payload["saved_updated_at"] = str(row["updated_at"])
        return payload

    def list(self) -> List[Dict[str, Any]]:
        conn = connect(self.path)
        try:
            rows = conn.execute(
                "SELECT name, created_at, updated_at, state_json FROM thesis_projects "
                "ORDER BY updated_at DESC, name"
            ).fetchall()
        finally:
            conn.close()
        records = []
        for row in rows:
            try:
                state = json.loads(row["state_json"])
            except ValueError:
                state = {}
            records.append(
                {
                    "name": str(row["name"]),
                    "created_at": str(row["created_at"]),
                    "updated_at": str(row["updated_at"]),
                    "n_points": len(state.get("points", [])),
                    "n_lines": len(state.get("lines", [])),
                    "n_angles": len(state.get("angles", [])),
                    "grade": (state.get("network") or {}).get("grade", "二级"),
                }
            )
        return records


class ThesisService:
    """当前浏览器工程的进程内状态；页面单用户使用。"""

    def __init__(
        self,
        db_path: Optional[Path | str] = None,
        *,
        sample_dir: Optional[Path | str] = None,
    ) -> None:
        self.sample_dir = Path(sample_dir).resolve() if sample_dir else SAMPLE_DIR
        self.repository = ThesisRepository(db_path)
        self._lock = threading.RLock()
        self.state = _empty_state()

    def reset(self, name: str = "未命名论文工程") -> Dict[str, Any]:
        with self._lock:
            self.state = _empty_state(name)
            return _public_state(self.state)

    def snapshot(self) -> Dict[str, Any]:
        with self._lock:
            return _public_state(self.state)

    def add_point(self, lon: float, lat: float, fixed: bool = False, snap_m: float = 0) -> Dict[str, Any]:
        lon = _finite(lon, "经度")
        lat = _finite(lat, "纬度")
        if not (-180.0 <= lon <= 180.0 and -90.0 < lat < 90.0):
            raise ThesisError("经纬度超出合理范围")
        _project_xy(self.state, lat, lon)
        with self._lock:
            _ensure_geometry(self.state)
            seq = int(self.state["seq"].get("point", 0)) + 1
            name = _next_name(self.state, "points")
            x, y = _project_xy(self.state, lat, lon)
            if any(abs(p["x"]) < 100000 for p in self.state["points"]):
                ox, oy = _project_xy(self.state, ORIGIN_LAT, ORIGIN_LON)
                x, y = x - ox, y - oy
            step = _finite(snap_m, "吸附间距")
            if not 0 <= step <= 1000:
                raise ThesisError("吸附间距须为0–1000米")
            if step:
                x, y = round(x / step) * step, round(y / step) * step
                ox, oy = _project_xy(self.state, ORIGIN_LAT, ORIGIN_LON) if any(abs(p["x"]) < 100000 for p in self.state["points"]) else (0, 0)
                lat, lon = _inverse_xy(self.state, x + ox, y + oy)
                _project_xy(self.state, lat, lon)
            point = {
                "id": f"p{seq}",
                "name": str(name),
                "lon": lon,
                "lat": lat,
                "x": x,
                "y": y,
                "fixed": bool(fixed),
            }
            self.state["points"].append(point)
            self.state["seq"]["point"] = seq
            _touch(self.state)
            return _public_state(self.state)

    def import_coordinates(self, text: str, name: str) -> Dict[str, Any]:
        """原子替换：论文高斯坐标文本，不把局部坐标猜成绝对坐标。"""
        if len(text.encode("utf-8")) > 1_000_000:
            raise ThesisError("坐标文本不得超过 1 MB")
        try:
            coords = parse_coordinate_text(text)
        except ValueError as exc:
            raise ThesisError(str(exc)) from exc
        if len(coords) > 2000:
            raise ThesisError("本入口最多导入 2000 点")
        candidate = _empty_state(name.strip() or "导入论文坐标")
        candidate["projection"] = _projection(self.state)
        for index, (label, (x, y)) in enumerate(coords.items(), 1):
            if not label.isdigit() or int(label) < 1 or str(int(label)) != label:
                raise ThesisError("点号必须为无前导零的正整数，以便构线构角")
            if not isfinite(x) or not isfinite(y) or not 0 < x < 10000000 or not abs(y - candidate["projection"]["false_easting_m"]) < 900000:
                raise ThesisError(f"点 {label} 需要绝对高斯坐标 x北/y东（m），不接受局部坐标或非有限数")
            lat, lon = _inverse_xy(candidate, x, y)
            _project_xy(candidate, lat, lon)
            candidate["points"].append(dict(id=f"p{index}", name=label, x=x, y=y,
                                            lon=lon, lat=lat, fixed=False))
        candidate["seq"]["point"] = len(coords)
        with self._lock:
            self.state = candidate
            return _public_state(self.state)

    def set_projection(self, settings):
        with self._lock:
            candidate = copy.deepcopy(self.state)
            candidate["projection"] = _projection({"projection": settings})
            local = any(abs(p["x"]) < 100000 for p in candidate["points"])
            origin = _project_xy(candidate, ORIGIN_LAT, ORIGIN_LON) if local else (0, 0)
            for point in candidate["points"]:
                x, y = _project_xy(candidate, point["lat"], point["lon"])
                point["x"], point["y"] = x - origin[0], y - origin[1]
            payload = _public_state(candidate)
            self.state = candidate
            return payload

    def import_state(self, raw):
        """先完整校验副本，再提交；引用使用稳定 id。"""
        try:
            if not isinstance(raw, dict) or raw.get("schema") != SCHEMA:
                raise ThesisError(f"JSON schema 必须为 {SCHEMA}")
            if len(json.dumps(raw)) > 4000000:
                raise ThesisError("JSON 不得超过 4 MB")
            candidate = _empty_state(str(raw.get("name") or "导入工程"))
            candidate["projection"] = _projection(raw)
            for key in ("points", "lines", "angles"):
                rows = raw.get(key)
                if not isinstance(rows, list) or len(rows) > 2000:
                    raise ThesisError(f"{key} 必须为数组且不超过 2000 项")
                candidate[key] = copy.deepcopy(rows)
                ids = [str(row["id"]) for row in rows]
                if len(set(ids)) != len(ids) or any(not v for v in ids):
                    raise ThesisError(f"{key} 编号重复或为空")
                candidate["seq"][key[:-1] if key != "points" else "point"] = max(
                    [len(rows)] + [int(v[1:]) for v in ids if v[1:].isdigit()])
            names = [str(p["name"]) for p in candidate["points"]]
            if len(set(names)) != len(names) or any(not v.isdigit() or int(v) < 1 for v in names):
                raise ThesisError("点名必须为唯一正整数")
            for point in candidate["points"]:
                for key in ("x", "y", "lon", "lat"):
                    point[key] = _finite(point[key], key)
                _project_xy(candidate, point["lat"], point["lon"])
            local = any(abs(p["x"]) < 100000 for p in candidate["points"])
            origin = _project_xy(candidate, ORIGIN_LAT, ORIGIN_LON) if local else (0, 0)
            for point in candidate["points"]:
                x, y = _project_xy(candidate, point["lat"], point["lon"])
                if max(abs(point["x"] - (x - origin[0])), abs(point["y"] - (y - origin[1]))) > .05:
                    raise ThesisError("JSON 双坐标与所选投影不一致（允许 0.05 m 舍入误差）")
            for line in candidate["lines"]:
                line.pop("_keep_length", None)
                line.pop("_keep_azimuth", None)
                if line["from"] == line["to"]:
                    raise ThesisError("线的两端不能相同")
            for angle in candidate["angles"]:
                if len({angle[k] for k in ("backsight", "station", "foresight")}) != 3:
                    raise ThesisError("角需要三个不同点")
            candidate["network"].update(raw.get("network", {}))
            network = candidate["network"]
            _grade_payload(network["grade"])
            for key in ("tolerance_mm", "ellipse_scale"):
                if _finite(network[key], key) <= 0:
                    raise ThesisError(f"{key} 必须为正数")
            for key in ("observed_edges", "added_edges", "observed_angles", "added_angles"):
                allowed = {r["id"] for r in candidate["lines" if "edges" in key else "angles"]}
                network[key] = _ids(network.get(key), allowed, key)
            payload = _public_state(candidate)
        except (KeyError, TypeError, ValueError, OverflowError) as exc:
            raise ThesisError(f"JSON 拓扑无效：{exc}") from exc
        with self._lock:
            self.state = candidate
        return payload

    def move_point(self, point_id, lon, lat, snap_m=0):
        with self._lock:
            if _point_by_ref(self.state, point_id).get("fixed"):
                raise ThesisError("已知点默认锁定；请先在点库明确改为未知点后移动")
            lon, lat = _finite(lon, "经度"), _finite(lat, "纬度")
            step = _finite(snap_m, "吸附间距")
            if not 0 <= step <= 1000:
                raise ThesisError("吸附间距须为0–1000米")
            x, y = _project_xy(self.state, lat, lon)
            local = any(abs(p["x"]) < 100000 for p in self.state["points"])
            ox, oy = _project_xy(self.state, ORIGIN_LAT, ORIGIN_LON) if local else (0, 0)
            x, y = x - ox, y - oy
            if step:
                x, y = round(x / step) * step, round(y / step) * step
            lat, lon = _inverse_xy(self.state, x + ox, y + oy)
            _project_xy(self.state, lat, lon)
            point = _point_by_ref(self.state, point_id)
            point.update(x=x, y=y, lon=lon, lat=lat)
            for line in self.state["lines"]:
                if point_id in (line["from"], line["to"]):
                    line.pop("_keep_length", None)
                    line.pop("_keep_azimuth", None)
            _touch(self.state)
            return _public_state(self.state)

    def set_point_fixed(self, point_id: str, fixed: bool) -> Dict[str, Any]:
        with self._lock:
            point = _point_by_ref(self.state, point_id)
            point["fixed"] = bool(fixed)
            _touch(self.state)
            return _public_state(self.state)

    def delete_point(self, point_id: str) -> Dict[str, Any]:
        with self._lock:
            point = _point_by_ref(self.state, point_id)
            pid = str(point["id"])
            self.state["points"] = [
                item for item in self.state["points"] if str(item["id"]) != pid
            ]
            removed_lines = {
                str(line["id"])
                for line in self.state["lines"]
                if pid in (str(line["from"]), str(line["to"]))
            }
            self.state["lines"] = [
                line for line in self.state["lines"] if str(line["id"]) not in removed_lines
            ]
            removed_angles = {
                str(angle["id"])
                for angle in self.state["angles"]
                if pid
                in (
                    str(angle["backsight"]),
                    str(angle["station"]),
                    str(angle["foresight"]),
                )
            }
            self.state["angles"] = [
                angle
                for angle in self.state["angles"]
                if str(angle["id"]) not in removed_angles
            ]
            network = self.state["network"]
            for key in ("observed_edges", "added_edges"):
                network[key] = [
                    item for item in network.get(key, []) if item not in removed_lines
                ]
            for key in ("observed_angles", "added_angles"):
                network[key] = [
                    item for item in network.get(key, []) if item not in removed_angles
                ]
            _reindex_names(self.state)
            _touch(self.state)
            return _public_state(self.state)

    def add_line(self, from_ref: str, to_ref: str) -> Dict[str, Any]:
        with self._lock:
            _ensure_geometry(self.state)
            a = _point_by_ref(self.state, from_ref)
            b = _point_by_ref(self.state, to_ref)
            if a["id"] == b["id"]:
                raise ThesisError("起点与终点不能相同")
            for line in self.state["lines"]:
                if {str(line["from"]), str(line["to"])} == {str(a["id"]), str(b["id"])}:
                    raise ThesisError("该边已存在", status_code=409)
            seq = int(self.state["seq"].get("line", 0)) + 1
            line = {
                "id": f"l{seq}",
                "name": _next_name(self.state, "lines"),
                "from": a["id"],
                "to": b["id"],
            }
            length, azimuth = _line_geometry(self.state, line)
            line["length"] = length
            line["azimuth"] = azimuth
            self.state["lines"].append(line)
            self.state["seq"]["line"] = seq
            _touch(self.state)
            return _public_state(self.state)

    def delete_line(self, line_id: str) -> Dict[str, Any]:
        with self._lock:
            line = _line_by_id(self.state, line_id)
            lid = str(line["id"])
            self.state["lines"] = [
                item for item in self.state["lines"] if str(item["id"]) != lid
            ]
            network = self.state["network"]
            network["observed_edges"] = [
                item for item in network.get("observed_edges", []) if item != lid
            ]
            network["added_edges"] = [
                item for item in network.get("added_edges", []) if item != lid
            ]
            _reindex_names(self.state)
            _touch(self.state)
            return _public_state(self.state)

    def add_angle(
        self, backsight_ref: str, station_ref: str, foresight_ref: str
    ) -> Dict[str, Any]:
        with self._lock:
            _ensure_geometry(self.state)
            b = _point_by_ref(self.state, backsight_ref)
            s = _point_by_ref(self.state, station_ref)
            f = _point_by_ref(self.state, foresight_ref)
            if len({str(b["id"]), str(s["id"]), str(f["id"])}) < 3:
                raise ThesisError("后视、测站、前视必须是三个不同的点")
            for angle in self.state["angles"]:
                if (
                    str(angle["backsight"]) == str(b["id"])
                    and str(angle["station"]) == str(s["id"])
                    and str(angle["foresight"]) == str(f["id"])
                ):
                    raise ThesisError("该角已存在", status_code=409)
            seq = int(self.state["seq"].get("angle", 0)) + 1
            angle = {
                "id": f"a{seq}",
                "name": _next_name(self.state, "angles"),
                "backsight": b["id"],
                "station": s["id"],
                "foresight": f["id"],
            }
            angle["value"] = _angle_value(self.state, angle)
            self.state["angles"].append(angle)
            self.state["seq"]["angle"] = seq
            _touch(self.state)
            return _public_state(self.state)

    def delete_angle(self, angle_id: str) -> Dict[str, Any]:
        with self._lock:
            angle = _angle_by_id(self.state, angle_id)
            aid = str(angle["id"])
            self.state["angles"] = [
                item for item in self.state["angles"] if str(item["id"]) != aid
            ]
            network = self.state["network"]
            network["observed_angles"] = [
                item for item in network.get("observed_angles", []) if item != aid
            ]
            network["added_angles"] = [
                item for item in network.get("added_angles", []) if item != aid
            ]
            _reindex_names(self.state)
            _touch(self.state)
            return _public_state(self.state)

    def configure_network(self, payload: Mapping[str, Any]) -> Dict[str, Any]:
        network = self.state["network"]
        known_edges = {str(line["id"]) for line in self.state["lines"]}
        known_angles = {str(angle["id"]) for angle in self.state["angles"]}
        if "grade" in payload and payload["grade"] is not None:
            _grade_payload(str(payload["grade"]))
            network["grade"] = str(payload["grade"])
        if "observed_edges" in payload:
            network["observed_edges"] = _ids(
                payload.get("observed_edges"), known_edges, "观测边"
            )
        if "observed_angles" in payload:
            network["observed_angles"] = _ids(
                payload.get("observed_angles"), known_angles, "观测角"
            )
        if "added_edges" in payload:
            network["added_edges"] = _ids(
                payload.get("added_edges"), known_edges, "新增观测边"
            )
        if "added_angles" in payload:
            network["added_angles"] = _ids(
                payload.get("added_angles"), known_angles, "新增观测角"
            )
        if "tolerance_mm" in payload and payload["tolerance_mm"] is not None:
            tolerance = _finite(payload["tolerance_mm"], "限差")
            if tolerance <= 0:
                raise ThesisError("限差必须为正")
            network["tolerance_mm"] = tolerance
        if "ellipse_scale" in payload and payload["ellipse_scale"] is not None:
            scale = _finite(payload["ellipse_scale"], "误差椭圆放大倍数")
            if scale <= 0:
                raise ThesisError("误差椭圆放大倍数必须为正")
            network["ellipse_scale"] = scale
        if "show_ellipses" in payload:
            network["show_ellipses"] = bool(payload["show_ellipses"])
        # “新增观测”必须相对基准观测集是新增的，避免同一观测被重复计数。
        network["added_edges"] = [
            item
            for item in network.get("added_edges", [])
            if item not in network.get("observed_edges", [])
        ]
        network["added_angles"] = [
            item
            for item in network.get("added_angles", [])
            if item not in network.get("observed_angles", [])
        ]
        _touch(self.state)
        return _public_state(self.state)

    def calculate(self) -> Dict[str, Any]:
        with self._lock:
            _ensure_geometry(self.state)
            result = calculate_state(self.state)
            result["projection"] = _projection(self.state)
            return result

    def export_coordinates(self) -> Dict[str, Any]:
        with self._lock:
            _ensure_geometry(self.state)
            coords = {
                str(point["name"]): (float(point["x"]), float(point["y"]))
                for point in self.state["points"]
            }
            if not coords:
                raise ThesisError("点库为空，无法导出")
            names = [str(point["name"]) for point in self.state["points"]]
            text = export_coordinate_text(coords, names, precision=9)
            return {
                "format": "论文坐标转换文本",
                "text": text,
                "n_points": len(names),
                "separator": "点号；x，y",
            }

    def export_angles(self) -> Dict[str, Any]:
        with self._lock:
            _ensure_geometry(self.state)
            if not self.state["angles"]:
                raise ThesisError("角库为空，无法导出")
            fixed = [
                str(point["name"])
                for point in self.state["points"]
                if point.get("fixed")
            ]
            unknown = [
                str(point["name"])
                for point in self.state["points"]
                if not point.get("fixed")
            ]
            unknown_ids = {name: index + 1 for index, name in enumerate(unknown)}
            triples = []
            for angle in self.state["angles"]:
                triples.append(
                    (
                        str(_point_by_ref(self.state, angle["backsight"])["name"]),
                        str(_point_by_ref(self.state, angle["station"])["name"]),
                        str(_point_by_ref(self.state, angle["foresight"])["name"]),
                    )
                )
            text = export_angle_topology(
                triples,
                known_names=fixed,
                order="station_first",
                unknown_ids=unknown_ids,
            )
            return {
                "format": "论文角度拓扑文本（(测站,后视,前视)；已知点记 -1,-2…）",
                "text": text,
                "n_angles": len(triples),
                "known_names": fixed,
                "unknown_ids": unknown_ids,
            }

    def load_example(self, key: str) -> Dict[str, Any]:
        name = str(key).strip().lower().replace("example", "").strip("_- ")
        if name not in ("1", "2"):
            raise ThesisError("算例只支持 1 或 2", status_code=404)
        path = self.sample_dir / f"thesis_example{name}.json"
        if not path.exists():
            raise ThesisError(f"找不到算例文件 {path.name}", status_code=404)
        data = json.loads(path.read_text(encoding="utf-8"))
        state = self._state_from_example(data, key=name)
        with self._lock:
            self.state = state
            return _public_state(self.state)

    def _state_from_example(self, data: Mapping[str, Any], *, key: str) -> Dict[str, Any]:
        state = _empty_state(str(data.get("name") or f"论文算例 {key}"))
        state["description"] = str(data.get("description") or "")
        state["source"] = str(data.get("source") or "")
        points = list(data.get("points") or [])
        name_to_id: Dict[str, str] = {}
        for index, raw in enumerate(points, start=1):
            pid = f"p{index}"
            name = str(raw["name"])
            name_to_id[name] = pid
            lon = raw.get("lon")
            lat = raw.get("lat")
            x = raw.get("x")
            y = raw.get("y")
            if lon is None or lat is None:
                if x is None or y is None:
                    raise ThesisError(f"算例点 {name} 缺少坐标")
                lon, lat = _lonlat_from_local(float(x), float(y))
            if x is None or y is None:
                x, y = gauss_forward(
                    float(lat), float(lon), central_meridian=DEFAULT_CENTRAL_MERIDIAN
                )
            state["points"].append(
                {
                    "id": pid,
                    "name": name,
                    "lon": float(lon),
                    "lat": float(lat),
                    "x": float(x),
                    "y": float(y),
                    "fixed": bool(raw.get("fixed", name in data.get("known", []))),
                }
            )
        state["seq"]["point"] = len(points)

        for index, raw in enumerate(data.get("lines") or [], start=1):
            lid = f"l{index}"
            frm = name_to_id.get(str(raw["from"]))
            to = name_to_id.get(str(raw["to"]))
            if frm is None or to is None:
                raise ThesisError("算例线库引用了不存在的点")
            line = {
                "id": lid,
                "name": int(raw.get("number", index)),
                "from": frm,
                "to": to,
                "length": float(raw.get("length", 0.0)),
                "azimuth": float(raw.get("azimuth", 0.0)),
                "_keep_length": True,
                "_keep_azimuth": True,
            }
            if not line["length"]:
                length, azimuth = _line_geometry(state, line)
                line["length"], line["azimuth"] = length, azimuth
                line.pop("_keep_length", None)
                line.pop("_keep_azimuth", None)
            state["lines"].append(line)
        state["seq"]["line"] = len(state["lines"])

        for index, raw in enumerate(data.get("angles") or [], start=1):
            if len(raw) != 3:
                continue
            bids = [name_to_id.get(str(value)) for value in raw]
            if any(item is None for item in bids):
                raise ThesisError("算例角库引用了不存在的点")
            state["angles"].append(
                {
                    "id": f"a{index}",
                    "name": index,
                    "backsight": bids[0],
                    "station": bids[1],
                    "foresight": bids[2],
                }
            )
        state["seq"]["angle"] = len(state["angles"])

        network = state["network"]
        network["grade"] = str(data.get("grade") or "二级")
        network["observed_angles"] = [angle["id"] for angle in state["angles"]]
        selected = data.get("selected_edges")
        if selected:
            pair_to_id = {}
            for line in state["lines"]:
                key_pair = frozenset(
                    (
                        _point_by_ref(state, line["from"])["name"],
                        _point_by_ref(state, line["to"])["name"],
                    )
                )
                pair_to_id[key_pair] = line["id"]
            network["observed_edges"] = [
                pair_to_id[frozenset((str(pair[0]), str(pair[1])))]
                for pair in selected
                if frozenset((str(pair[0]), str(pair[1]))) in pair_to_id
            ]
        state["network"]["tolerance_mm"] = 20.0
        _ensure_geometry(state)
        _refresh_derived(state)
        return state


def create_thesis_router(service: ThesisService) -> APIRouter:
    router = APIRouter()

    @router.get("/thesis", include_in_schema=False)
    def thesis_page() -> FileResponse:
        path = STATIC_DIR / "thesis.html"
        if not path.exists():
            raise HTTPException(status_code=500, detail="thesis.html 不存在")
        return FileResponse(path, media_type="text/html; charset=utf-8")

    @router.get("/api/thesis/state")
    def state() -> JSONResponse:
        return JSONResponse(service.snapshot())

    @router.get("/api/thesis/basemap")
    def basemap_meta() -> JSONResponse:
        return JSONResponse(_basemap_payload())

    @router.get("/api/thesis/basemap.png")
    def basemap_png() -> FileResponse:
        path = service.sample_dir / "thesis_basemap.png"
        if not path.exists():
            raise HTTPException(status_code=404, detail="离线底图未生成")
        return FileResponse(
            path,
            media_type="image/png",
            headers={"Cache-Control": "public, max-age=3600"},
        )

    @router.get("/api/thesis/examples")
    def examples() -> JSONResponse:
        items = []
        for key in ("1", "2"):
            path = service.sample_dir / f"thesis_example{key}.json"
            if not path.exists():
                continue
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except ValueError:
                continue
            items.append(
                {
                    "key": key,
                    "name": data.get("name"),
                    "description": data.get("description"),
                    "n_points": len(data.get("points") or []),
                    "n_lines": len(data.get("lines") or []),
                    "n_angles": len(data.get("angles") or []),
                }
            )
        return JSONResponse({"examples": items})

    @router.post("/api/thesis/examples/{key}")
    def load_example(key: str) -> JSONResponse:
        try:
            return JSONResponse(service.load_example(key))
        except ThesisError as exc:
            raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc

    @router.post("/api/thesis/import/coordinates")
    def import_coordinates(payload: Dict[str, Any] = Body(...)) -> JSONResponse:
        try:
            return JSONResponse(service.import_coordinates(str(payload.get("text") or ""), str(payload.get("name") or "导入论文坐标")))
        except (ThesisError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/api/thesis/projection")
    def projection(payload: Dict[str, Any] = Body(...)):
        try:
            return service.set_projection(payload)
        except (ThesisError, ValueError) as exc:
            raise HTTPException(400, str(exc)) from exc

    @router.post("/api/thesis/import/json")
    def import_json(payload: Dict[str, Any] = Body(...)):
        try:
            return service.import_state(payload)
        except ThesisError as exc:
            raise HTTPException(400, str(exc)) from exc

    @router.post("/api/thesis/new")
    def new_project(payload: Optional[Dict[str, Any]] = Body(default=None)) -> JSONResponse:
        name = str((payload or {}).get("name") or "未命名论文工程")
        return JSONResponse(service.reset(name))

    @router.post("/api/thesis/points")
    def add_point(payload: Dict[str, Any] = Body(...)) -> JSONResponse:
        try:
            return JSONResponse(
                service.add_point(
                    payload.get("lon"), payload.get("lat"), bool(payload.get("fixed", False)), payload.get("snap_m", 0)
                )
            )
        except ThesisError as exc:
            raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc

    @router.patch("/api/thesis/points/{point_id}")
    def patch_point(point_id: str, payload: Dict[str, Any] = Body(...)) -> JSONResponse:
        try:
            if "lon" in payload or "lat" in payload:
                return JSONResponse(service.move_point(point_id, payload.get("lon"), payload.get("lat"), payload.get("snap_m", 0)))
            return JSONResponse(
                service.set_point_fixed(point_id, bool(payload.get("fixed", False)))
            )
        except ThesisError as exc:
            raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc

    @router.delete("/api/thesis/points/{point_id}")
    def delete_point(point_id: str) -> JSONResponse:
        try:
            return JSONResponse(service.delete_point(point_id))
        except ThesisError as exc:
            raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc

    @router.post("/api/thesis/lines")
    def add_line(payload: Dict[str, Any] = Body(...)) -> JSONResponse:
        try:
            return JSONResponse(
                service.add_line(str(payload.get("from", "")), str(payload.get("to", "")))
            )
        except ThesisError as exc:
            raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc

    @router.delete("/api/thesis/lines/{line_id}")
    def delete_line(line_id: str) -> JSONResponse:
        try:
            return JSONResponse(service.delete_line(line_id))
        except ThesisError as exc:
            raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc

    @router.post("/api/thesis/angles")
    def add_angle(payload: Dict[str, Any] = Body(...)) -> JSONResponse:
        try:
            return JSONResponse(
                service.add_angle(
                    str(payload.get("backsight", payload.get("start", ""))),
                    str(payload.get("station", "")),
                    str(payload.get("foresight", payload.get("end", ""))),
                )
            )
        except ThesisError as exc:
            raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc

    @router.delete("/api/thesis/angles/{angle_id}")
    def delete_angle(angle_id: str) -> JSONResponse:
        try:
            return JSONResponse(service.delete_angle(angle_id))
        except ThesisError as exc:
            raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc

    @router.post("/api/thesis/network")
    def configure_network(payload: Dict[str, Any] = Body(...)) -> JSONResponse:
        try:
            return JSONResponse(service.configure_network(payload))
        except ThesisError as exc:
            raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc

    @router.post("/api/thesis/calculate")
    def calculate() -> JSONResponse:
        try:
            return JSONResponse(service.calculate())
        except ThesisError as exc:
            raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc

    @router.get("/api/thesis/export/coordinates")
    def export_coordinates() -> JSONResponse:
        try:
            return JSONResponse(service.export_coordinates())
        except ThesisError as exc:
            raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc

    @router.get("/api/thesis/export/angles")
    def export_angles() -> JSONResponse:
        try:
            return JSONResponse(service.export_angles())
        except ThesisError as exc:
            raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc

    @router.get("/api/thesis/projects")
    def projects() -> JSONResponse:
        return JSONResponse({"projects": service.repository.list()})

    @router.post("/api/thesis/projects/save")
    def save_project(payload: Dict[str, Any] = Body(...)) -> JSONResponse:
        name = str(payload.get("name") or "")
        try:
            with service._lock:
                service.state["name"] = name.strip() or service.state["name"]
                saved = service.repository.save(name, service.state)
            return JSONResponse(
                {
                    "ok": True,
                    "name": saved["saved_name"],
                    "projects": service.repository.list(),
                    "state": _public_state(service.state),
                }
            )
        except ThesisError as exc:
            raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc

    @router.post("/api/thesis/projects/load")
    def load_project(payload: Dict[str, Any] = Body(...)) -> JSONResponse:
        name = str(payload.get("name") or "")
        try:
            state = service.repository.get(name)
            with service._lock:
                state.setdefault("seq", {"point": 0, "line": 0, "angle": 0})
                service.state = state
                return JSONResponse(_public_state(service.state))
        except ThesisError as exc:
            raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc

    return router


__all__ = [
    "DEFAULT_DB",
    "ThesisError",
    "ThesisRepository",
    "ThesisService",
    "calculate_state",
    "create_thesis_router",
]
