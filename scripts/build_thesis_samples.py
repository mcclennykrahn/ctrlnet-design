#!/usr/bin/env python
"""生成网页可用的论文算例 JSON（不访问网络）。

输出：
    data/sample/thesis_example1.json
    data/sample/thesis_example2.json
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

from ctrlnet.thesis import gauss_inverse
from ctrlnet.thesis_examples import (
    EXAMPLE1_KNOWN,
    EXAMPLE1_LINES,
    EXAMPLE1_OPTIMIZED_ATTEMPT,
    EXAMPLE1_OPTIMIZED_ATTEMPT_Q,
    EXAMPLE1_POINTS,
    EXAMPLE1_PUBLISHED,
    EXAMPLE1_TOPOLOGY,
    EXAMPLE1_UNKNOWN,
    EXAMPLE2_KNOWN,
    EXAMPLE2_LINES,
    EXAMPLE2_POINTS,
    EXAMPLE2_PUBLISHED,
    EXAMPLE2_SELECTED_ANGLES,
    EXAMPLE2_SELECTED_EDGES,
    EXAMPLE2_UNKNOWN,
    example1_angles,
    example1_result,
    example2_result,
    export_angle_topology,
)

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "sample"


def _point_payload(
    points: Dict[str, tuple],
    unknown: List[str],
    known: List[str],
    *,
    central_meridian: float | None = None,
) -> List[Dict[str, Any]]:
    payload = []
    for name, (x, y) in points.items():
        item: Dict[str, Any] = {
            "name": name,
            "x": round(float(x), 9),
            "y": round(float(y), 9),
            "fixed": name in known,
        }
        if central_meridian is not None:
            lat, lon = gauss_inverse(
                x, y, central_meridian=central_meridian
            )
            item["lat"] = round(lat, 9)
            item["lon"] = round(lon, 9)
        payload.append(item)
    return payload


def _line_payload(lines: List[tuple]) -> List[Dict[str, Any]]:
    return [
        {
            "number": number,
            "from": a,
            "to": b,
            "length": length,
            "azimuth": azimuth,
        }
        for number, a, b, length, azimuth in lines
    ]


def _paper_denominators(lines: List[tuple], table: List[float]) -> List[Dict[str, Any]]:
    rows = []
    for (number, a, b, length, _), published in zip(lines, table):
        model = length / 0.01
        rows.append(
            {
                "number": number,
                "from": a,
                "to": b,
                "length": length,
                "paper_denominator": round(model, 1),
                "published": published,
                "difference": round(model - published, 1),
            }
        )
    return rows


def build_example1() -> Dict[str, Any]:
    result = example1_result()
    qxx, qyy, qxy = result.q_mm2[0, 0], result.q_mm2[1, 1], result.q_mm2[0, 1]
    paper_qxx, paper_qyy, paper_qxy = result.paper_q("1")
    ellipses = []
    for name in result.unknown:
        e = result.ellipse(name)
        ellipses.append(
            {
                "name": name,
                "E_mm": round(e.E, 6),
                "F_mm": round(e.F, 6),
                "phi_E_deg": round(e.phi_E_deg, 6),
                "Qxx_mm2": round(result.q_mm2[2 * (int(name) - 1), 2 * (int(name) - 1)], 9),
                "Qyy_mm2": round(result.q_mm2[2 * (int(name) - 1) + 1, 2 * (int(name) - 1) + 1], 9),
            }
        )
    optimized = example1_result(
        list(example1_angles()) + list(EXAMPLE1_OPTIMIZED_ATTEMPT)
    )
    return {
        "schema": "ctrlnet.thesis.example/1",
        "name": "论文算例 1：9 点测角网",
        "description": (
            "9 点、7 个未知点（1–7）、已知点 8/9；14 个已给角的 P=I 测角网。"
            "论文正文称 19 个角，但公布 Q 精确等于这 14 个角的解。"
        ),
        "source": "docs/target/target_spec.md §3，论文图 5-1/5-3/5-5/5-6",
        "offline": True,
        "ellipsoid": "CGCS2000",
        "central_meridian": 117.0,
        "topology_order": "station_first",
        "topology": EXAMPLE1_TOPOLOGY,
        "points": _point_payload(
            EXAMPLE1_POINTS,
            EXAMPLE1_UNKNOWN,
            EXAMPLE1_KNOWN,
            central_meridian=117.0,
        ),
        "known": EXAMPLE1_KNOWN,
        "unknown": EXAMPLE1_UNKNOWN,
        "angles": [list(a) for a in example1_angles()],
        "lines": _line_payload(EXAMPLE1_LINES),
        "published": EXAMPLE1_PUBLISHED,
        "computed": {
            "q_unit_mm2": "mm²/(″)²（B 以 ρ″=206265、坐标改正以 mm 计）",
            "qxx_mm2": round(qxx, 6),
            "qyy_mm2": round(qyy, 6),
            "qxy_mm2": round(qxy, 6),
            "qxx_paper": round(paper_qxx, 6),
            "qyy_paper": round(paper_qyy, 6),
            "qxy_paper": round(paper_qxy, 6),
            "weakest_point": result.weakest_point(),
            "mp_mm": round(result.mp_mm(result.weakest_point()), 6),
            "paper_mp_mm": round(result.paper_mp_mm(result.weakest_point()), 6),
            "ellipses": ellipses,
            "edge_denominators": _paper_denominators(
                EXAMPLE1_LINES, EXAMPLE1_PUBLISHED["edge_denominators"]
            ),
            "optimized_attempt_27": {
                "extra_angles": [list(a) for a in EXAMPLE1_OPTIMIZED_ATTEMPT],
                "qxx_mm2": round(EXAMPLE1_OPTIMIZED_ATTEMPT_Q[0], 6),
                "qyy_mm2": round(EXAMPLE1_OPTIMIZED_ATTEMPT_Q[1], 6),
                "qxx_paper": round(EXAMPLE1_OPTIMIZED_ATTEMPT_Q[0] / 100.0, 6),
                "qyy_paper": round(EXAMPLE1_OPTIMIZED_ATTEMPT_Q[1] / 100.0, 6),
                "published_qxx": 0.4636,
                "published_qyy": 0.1861,
                "note": "新增 13 个角未公布；此为本仓库搜索结果，不能精确复现公布值。",
            },
        },
        "notes": [
            "论文三元组顺序为 (测站, 后视, 前视)，与论文 4.5 节 JS 代码一致；"
            "正文“顶点放中间”的表述与代码/数值结果不一致。",
            "论文截图 Q 数值 = 严格 mm² 数值 / 100（cm² 口径）；"
            "M 的 cm/mm 标注也存在 10 倍口径差。",
        ],
    }


def build_example2() -> Dict[str, Any]:
    result = example2_result()
    qxx, qyy, qxy = result.q_mm2[12, 12], result.q_mm2[13, 13], result.q_mm2[12, 13]
    paper_qxx, paper_qyy, paper_qxy = result.paper_q("7")
    ellipses = []
    for name in result.unknown:
        i = int(name) - 1
        e = result.ellipse(name)
        ellipses.append(
            {
                "name": name,
                "E_mm": round(e.E, 6),
                "F_mm": round(e.F, 6),
                "phi_E_deg": round(e.phi_E_deg, 6),
                "Qxx_mm2": round(result.q_mm2[2 * i, 2 * i], 9),
                "Qyy_mm2": round(result.q_mm2[2 * i + 1, 2 * i + 1], 9),
            }
        )
    return {
        "schema": "ctrlnet.thesis.example/2",
        "name": "论文算例 2：9 点边角网（近似复现）",
        "description": (
            "点位未公布；由 17 条线库边长/方位角重建局部坐标。观测选择未知，"
            "本仓库在 3 分钟上限内搜索到 10 边 + 11 角，使点 7 的论文口径 "
            "Qxx/Qyy 与公布值在 4 位小数内一致。"
        ),
        "source": "docs/target/target_spec.md §3，论文图 5-9/5-10/5-11/5-12",
        "offline": True,
        "frame": "local_xy（x 北、y 东，m；已知点 8 为原点）",
        "grade": "二级",
        "points": _point_payload(EXAMPLE2_POINTS, EXAMPLE2_UNKNOWN, EXAMPLE2_KNOWN),
        "known": EXAMPLE2_KNOWN,
        "unknown": EXAMPLE2_UNKNOWN,
        "selected_edges": [list(e) for e in EXAMPLE2_SELECTED_EDGES],
        "selected_angles": [list(a) for a in EXAMPLE2_SELECTED_ANGLES],
        "angle_topology": export_angle_topology(
            EXAMPLE2_SELECTED_ANGLES,
            known_names=EXAMPLE2_KNOWN,
            order="station_first",
        ),
        "angles": [list(a) for a in EXAMPLE2_SELECTED_ANGLES],
        "lines": _line_payload(EXAMPLE2_LINES),
        "published": EXAMPLE2_PUBLISHED,
        "computed": {
            "q_unit_mm2": "mm²/(″)²；边权 P=σ0²/σS²，σ0=10，σS 以 mm 计",
            "qxx_mm2": round(qxx, 6),
            "qyy_mm2": round(qyy, 6),
            "qxy_mm2": round(qxy, 6),
            "qxx_paper": round(paper_qxx, 6),
            "qyy_paper": round(paper_qyy, 6),
            "qxy_paper": round(paper_qxy, 6),
            "weakest_point": result.weakest_point(),
            "mp_mm": round(result.mp_mm(result.weakest_point()), 6),
            "paper_mp_mm": round(result.paper_mp_mm(result.weakest_point()), 6),
            "ellipses": ellipses,
            "edge_denominators": _paper_denominators(
                EXAMPLE2_LINES, EXAMPLE2_PUBLISHED["edge_denominators"]
            ),
            "n_observations": result.metadata["n_rows"],
            "rank": result.metadata["rank"],
        },
        "notes": [
            "观测边/角的选择不可从论文截图唯一读出，因此这是近似复现而非唯一解。",
            "线库距离/方位为截图转录，重建坐标的残差约 2 cm。",
        ],
    }


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for filename, payload in (
        ("thesis_example1.json", build_example1()),
        ("thesis_example2.json", build_example2()),
    ):
        path = OUT / filename
        path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        print(f"wrote {path.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
