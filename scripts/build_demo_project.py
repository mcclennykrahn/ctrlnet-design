#!/usr/bin/env python3
"""生成可提交的小体积 SQLite 演示工程 ``data/sample/demo_project.sqlite``。

工程包含四个方案：

1. ``s13-base``：第 13 节基准方案（A/B 固定，C/D 待定，5 距离 + 2 角度）；
2. ``s13-added``：第 13 节增补方案（父方案为基准，增加角 D-C-A）；
3. ``dem-all``：DEM 通视网全部通视边（16 距离 + 60 角度，共 76 观测）；
4. ``dem-opt``：DEM 优化方案（全部 16 条通视距离 + 贪心/1 换 1 选出的 9 个
   通视角度，预算 12）。

第 13 节只做整体平移，几何形状、距离和角度保持与 ``examples.py`` 完全一致，
因此黄金期望值不受影响；平移后的点位落在 DEM 覆盖范围内，便于网页地图展示。
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any, Dict, List, Sequence

from ctrlnet import Angle, Distance, Network, Point, section13_added, section13_base
from ctrlnet.optimize import Candidate, CostModel, local_search_optimize
from ctrlnet.store import save_project

ROOT = Path(__file__).resolve().parents[1]
SAMPLE = ROOT / "data" / "sample"
TERRAIN_PATH = SAMPLE / "terrain_project.json"
DB_PATH = SAMPLE / "demo_project.sqlite"

# 第 13 节网整体平移到 DEM 覆盖范围内（只平移，不缩放/旋转）。
S13_OFFSET_E = 415_900.0
S13_OFFSET_N = 4_420_800.0


def _angle_deg(points: Dict[str, Point], rear: str, station: str, front: str) -> float:
    a = points[station]
    b = points[rear]
    c = points[front]
    az_b = math.atan2(b.E - a.E, b.N - a.N)
    az_f = math.atan2(c.E - a.E, c.N - a.N)
    value = (az_f - az_b + math.pi) % (2.0 * math.pi) - math.pi
    return math.degrees(value)


def _distance_m(points: Dict[str, Point], frm: str, to: str) -> float:
    return math.hypot(points[to].E - points[frm].E, points[to].N - points[frm].N)


def _section13_scenario(added: bool) -> Dict[str, Any]:
    scenario = section13_added() if added else section13_base()
    points = {
        p.name: Point(
            p.name,
            p.E + S13_OFFSET_E,
            p.N + S13_OFFSET_N,
            fixed=p.fixed,
        )
        for p in scenario.points
    }
    observations: List[Dict[str, Any]] = []
    for index, obs in enumerate(scenario.observations, start=1):
        if isinstance(obs, Distance):
            observations.append(
                {
                    "id": f"{'s13-added' if added else 's13-base'}-d{index}",
                    "kind": "distance",
                    "from": obs.frm,
                    "to": obs.to,
                    "a_m": obs.a,
                    "b_ppm": obs.b_ppm,
                    "value_m": _distance_m(points, obs.frm, obs.to),
                }
            )
        elif isinstance(obs, Angle):
            observations.append(
                {
                    "id": f"{'s13-added' if added else 's13-base'}-a{index}",
                    "kind": "angle",
                    "backsight": obs.backsight,
                    "station": obs.station,
                    "foresight": obs.foresight,
                    "sigma_arcsec": obs.sigma_arcsec,
                    "value_deg": _angle_deg(
                        points, obs.backsight, obs.station, obs.foresight
                    ),
                }
            )
    return {
        "id": "s13-added" if added else "s13-base",
        "name": "第 13 节增补方案" if added else "第 13 节基准方案",
        "version": 2 if added else 1,
        "parent_id": "s13-base" if added else None,
        "description": (
            "在基准方案上增加角 D-C-A；点坐标整体平移到 DEM 范围，几何与第 13 节一致。"
            if added
            else "A/B 固定、C/D 待定，5 距离 + 2 角度；点坐标整体平移到 DEM 范围。"
        ),
        "metadata": {
            "datum": "fixed",
            "points": ["A", "B", "C", "D"],
            "source": "ctrlnet.examples.section13",
            "confidence": 0.95,
        },
        "observations": observations,
    }


def _dem_points(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    return [
        {
            "name": str(item["name"]),
            "E": float(item["E"]),
            "N": float(item["N"]),
            "fixed": bool(item["fixed"]),
            "elevation_m": float(item.get("elevation_m", 0.0)),
            "lon": float(item.get("lon", 0.0)),
            "lat": float(item.get("lat", 0.0)),
            "metadata": {"crs": item.get("crs", "EPSG:32650")},
        }
        for item in payload["points"]
    ]


def _dem_visibility(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    rows = []
    for item in payload.get("visibility", []):
        rows.append(
            {
                "from": str(item["from"]),
                "to": str(item["to"]),
                "distance_m": float(item["distance_m"]),
                "status": str(item["status"]),
                "visible": bool(item["visible"]),
                "min_clearance_m": float(item["min_clearance_m"]),
                "min_distance_m": float(item["min_distance_m"]),
                "obstruction": item.get("obstruction"),
                "k": float(item.get("k", 0.13)),
                "R_m": float(item.get("R_m", 6_371_000.0)),
                "clearance_threshold_m": float(item.get("clearance_threshold_m", 0.0)),
                "samples": int(item.get("samples", 0)),
                "nodata_count": int(item.get("nodata_count", 0)),
            }
        )
    return rows


def _dem_observations(
    payload: Dict[str, Any], points: Dict[str, Point], *, suffix: str
) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for index, item in enumerate(payload["observations"]["distances"], start=1):
        rows.append(
            {
                "id": f"{suffix}-d{index}",
                "kind": "distance",
                "from": str(item["from"]),
                "to": str(item["to"]),
                "a_m": float(item.get("sigma_a_m", 0.002)),
                "b_ppm": float(item.get("sigma_b_ppm", 2.0)),
                "value_m": _distance_m(points, item["from"], item["to"]),
            }
        )
    for index, item in enumerate(payload["observations"]["angles"], start=1):
        rows.append(
            {
                "id": f"{suffix}-a{index}",
                "kind": "angle",
                "backsight": str(item["backsight"]),
                "station": str(item["station"]),
                "foresight": str(item["foresight"]),
                "sigma_arcsec": float(item.get("sigma_arcsec", 1.0)),
                "value_deg": _angle_deg(
                    points,
                    str(item["backsight"]),
                    str(item["station"]),
                    str(item["foresight"]),
                ),
            }
        )
    return rows


def _optimized_subset(payload: Dict[str, Any], points: Dict[str, Point]) -> List[str]:
    """用 C2 局部搜索选出预算 12 下的通视角度子集（结果自动记录）。"""
    base_rows = payload["observations"]["distances"]
    angle_rows = payload["observations"]["angles"]
    base_obs = [Distance(row["from"], row["to"]) for row in base_rows]
    base = Network(
        [
            Point(p.name, p.E, p.N, fixed=p.fixed)
            for p in points.values()
        ],
        base_obs,
        name="DEM 通视边角网（全部通视距离）",
    )
    candidates = [
        Candidate(
            Angle(row["backsight"], row["station"], row["foresight"]),
            1.0,
        )
        for row in angle_rows
    ]
    outcome = local_search_optimize(
        base,
        candidates,
        criterion="max_mp",
        budget=12.0,
        cost_model=CostModel(default_station_cost=3.0),
    )
    return list(outcome.selected_labels)


def main() -> int:
    terrain = json.loads(TERRAIN_PATH.read_text(encoding="utf-8"))
    dem_points = _dem_points(terrain)
    point_map = {row["name"]: Point(row["name"], row["E"], row["N"], fixed=row["fixed"]) for row in dem_points}
    visibility = _dem_visibility(terrain)
    all_observations = _dem_observations(terrain, point_map, suffix="dem-all")

    selected_labels = _optimized_subset(terrain, point_map)
    selected_set = set(selected_labels)
    optimized = [
        dict(item)
        for item in all_observations
        if item["kind"] == "distance"
        or (
            item["kind"] == "angle"
            and f"∠{item['backsight']}-{item['station']}-{item['foresight']}"
            in selected_set
        )
    ]
    # 重新编号，保证方案内观测 id 稳定。
    for index, item in enumerate(optimized, start=1):
        item["id"] = f"dem-opt-o{index:03d}"

    # 优化子集的指标由 store 在生成报告/网页时复算，脚本只记录选择信息。
    analysis = dict(terrain.get("analysis") or {})
    analysis.setdefault("confidence", 0.95)
    terrain_meta = {
        "dem": {
            "path": str((SAMPLE / "dem_sample.tif").relative_to(ROOT)),
            "crs": terrain.get("dem", {}).get("crs", "EPSG:32650"),
            "shape": terrain.get("dem", {}).get("shape"),
            "resolution_m": terrain.get("dem", {}).get("resolution_m"),
            "bounds_native": terrain.get("dem", {}).get("bounds_native"),
            "source": terrain.get("dem", {}).get("source"),
            "vertical_datum": terrain.get("dem", {}).get("vertical_datum"),
            "surface_type": terrain.get("dem", {}).get("surface_type"),
        },
        "analysis": analysis,
        "terrain_project": str(TERRAIN_PATH.relative_to(ROOT)),
    }

    scenario_common = {
        "datum": "fixed",
        "points": [row["name"] for row in dem_points],
        "visibility": visibility,
        "confidence": 0.95,
    }
    dem_all_scenario = {
        "id": "dem-all",
        "name": "DEM 全部通视边",
        "version": 1,
        "parent_id": None,
        "description": "7 个高地控制点，16 条通视距离 + 60 个通视水平角（全部通视边）。",
        "metadata": {
            **scenario_common,
            "source": "data/sample/terrain_project.json",
            "n_visible_pairs": sum(1 for row in visibility if row["visible"]),
        },
        "observations": all_observations,
    }
    dem_opt_scenario = {
        "id": "dem-opt",
        "name": "DEM 优化方案（预算 12）",
        "version": 2,
        "parent_id": "dem-all",
        "description": "16 条通视距离 + 贪心/1 换 1 选出的 9 个通视角度；观测成本 1.0、设站成本 3.0。",
        "metadata": {
            **scenario_common,
            "source": "ctrlnet.optimize.local_search_optimize",
            "optimization": {
                "algorithm": "greedy_local_search",
                "criterion": "max_mp",
                "budget": 12.0,
                "observation_cost": 1.0,
                "station_cost": 3.0,
                "selected_labels": selected_labels,
                "note": "先以全部 16 条通视距离为基准网，再在 60 个通视角度中选 9 个。",
            },
        },
        "observations": optimized,
    }

    points = [
        {
            "name": "A",
            "E": S13_OFFSET_E + 0.0,
            "N": S13_OFFSET_N + 0.0,
            "fixed": True,
            "metadata": {"source": "section13"},
        },
        {
            "name": "B",
            "E": S13_OFFSET_E + 100.0,
            "N": S13_OFFSET_N + 0.0,
            "fixed": True,
            "metadata": {"source": "section13"},
        },
        {
            "name": "C",
            "E": S13_OFFSET_E + 0.0,
            "N": S13_OFFSET_N + 100.0,
            "fixed": False,
            "metadata": {"source": "section13"},
        },
        {
            "name": "D",
            "E": S13_OFFSET_E + 100.0,
            "N": S13_OFFSET_N + 100.0,
            "fixed": False,
            "metadata": {"source": "section13"},
        },
    ] + dem_points

    project = {
        "id": "demo-project",
        "name": "CTRLNET 演示工程",
        "description": "第 13 节基准/增补方案 + DEM 通视全部边/优化方案",
        "schema_version": "2.0",
        "crs": "EPSG:32650",
        "metadata": {
            "default_scenario": "dem-all",
            "terrain": terrain_meta,
            "datum": "fixed",
            "generated_by": "scripts/build_demo_project.py",
        },
        "points": points,
        "scenarios": [
            _section13_scenario(False),
            _section13_scenario(True),
            dem_all_scenario,
            dem_opt_scenario,
        ],
    }
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    if DB_PATH.exists():
        DB_PATH.unlink()
    loaded = save_project(DB_PATH, project, overwrite=True)
    print(f"[ok] {DB_PATH.relative_to(ROOT)}  {DB_PATH.stat().st_size/1024:.1f} KiB")
    for scenario in loaded["scenarios"]:
        print(
            f"  {scenario['id']:<10s} v{scenario['version']}  "
            f"{scenario['n_observations']:>2d} obs  {scenario['name']}"
        )
    print(f"  优化选中：{'；'.join(selected_labels)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
