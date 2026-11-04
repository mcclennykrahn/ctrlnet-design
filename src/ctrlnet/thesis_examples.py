"""论文第 5 章两个算例的数据与复现入口。

算例 1 的 9 点高斯坐标、角度拓扑与线库数字均来自 ``docs/target/target_spec.md``
第 3 节（论文图 5-3/5-5/5-6 的转录）。算例 2 未公布点位坐标，本模块用线库
的边长/方位角按最小二乘重建相对坐标（已知点 8 为原点），仅用于近似复现。
"""

from __future__ import annotations

import itertools
from dataclasses import dataclass
from math import cos, hypot, radians, sin
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

import numpy as np

from .thesis import (
    ThesisNetworkResult,
    build_angle_network,
    build_network,
    export_angle_topology,
    parse_angle_topology,
)

# ---------------------------------------------------------------------------
# 算例 1：9 点测角网（图 5-1/5-3/5-5/5-6）
# ---------------------------------------------------------------------------

EXAMPLE1_POINTS: Dict[str, Tuple[float, float]] = {
    "1": (3784503.204274250, 523065.320310928),
    "2": (3784451.530284550, 523608.679028850),
    "3": (3784572.292422130, 524204.605323638),
    "4": (3785121.754256420, 524047.504863555),
    "5": (3785385.695877990, 523672.512982637),
    "6": (3785337.959870050, 523122.908177453),
    "7": (3785075.765488550, 522911.547582046),
    "8": (3784947.789360060, 523375.605537780),
    "9": (3784826.405775060, 523849.522776987),
}
EXAMPLE1_UNKNOWN = [str(i) for i in range(1, 8)]
EXAMPLE1_KNOWN = ["8", "9"]

EXAMPLE1_TOPOLOGY = (
    "[-1,1,2;-2,-1,2;-1,-2,2;-2,2,3;4,-2,3;3,4,-2;4,5,-2;"
    "5,-2,4;5,-1,-2;-1,5,6;5,6,-1;6,-1,7;-1,7,1;7,1,-1]"
)

# 编号, 起点, 终点, 距离 m, 方位 °（图 5-3）
EXAMPLE1_LINES: List[Tuple[int, str, str, float, float]] = [
    (1, "1", "2", 544.8431, 95.5981),
    (2, "2", "3", 606.8201, 78.6371),
    (3, "3", "4", 572.8671, 344.2601),
    (4, "4", "5", 458.2711, 305.4111),
    (5, "5", "6", 550.4881, 265.1581),
    (6, "6", "7", 338.9791, 218.6851),
    (7, "7", "1", 594.1051, 155.1721),
    (8, "1", "8", 542.6451, 34.8291),
    (9, "2", "8", 549.1431, 335.0871),
    (10, "2", "9", 446.0501, 32.7431),
    (11, "3", "9", 436.3761, 305.8621),
    (12, "4", "9", 355.9161, 213.8601),
    (13, "5", "9", 587.8101, 162.6571),
    (14, "5", "8", 529.5781, 214.1601),
    (15, "6", "8", 465.3521, 147.3311),
    (16, "7", "8", 480.4901, 105.6261),
    (17, "8", "9", 488.2891, 104.5731),
]

EXAMPLE1_PUBLISHED: Dict[str, Any] = {
    "weakest_point": "1",
    "qxx": 0.6502,
    "qyy": 0.3039,
    "mp_text_mm": 9.77,
    "mp_text_cm": 0.97,
    "optimized_angles": 27,
    "optimized_qxx": 0.4636,
    "optimized_qyy": 0.1861,
    "optimized_mp_text_cm": 0.81,
    "q_unit": "论文截图数值（实际对应 cm²/(″)²）",
    "edge_denominators": [
        54464.3,
        60682.1,
        57266.7,
        45827.1,
        55048.8,
        33697.9,
        59410.5,
        54264.5,
        54914.3,
        44605.0,
        43637.6,
        35591.6,
        58781.0,
        52957.9,
        46535.2,
        48049.0,
        48828.9,
    ],
}


def example1_angles(order: str = "station_first") -> List[Tuple[str, str, str]]:
    """按指定原文顺序解析图 5-6 的 14 个角，返回规范 ``(后视,测站,前视)``。"""
    return parse_angle_topology(
        EXAMPLE1_TOPOLOGY,
        known_names=EXAMPLE1_KNOWN,
        order=order,
    )


def example1_result(
    angles: Optional[Iterable[Sequence[str]]] = None,
    *,
    order: str = "station_first",
    coordinate_unit_mm: float = 1.0,
) -> ThesisNetworkResult:
    """构建算例 1 测角网（``P=I``，``Mw=10″``）。"""
    angle_list = (
        list(angles) if angles is not None else example1_angles(order=order)
    )
    return build_angle_network(
        EXAMPLE1_POINTS,
        angle_list,
        unknown=EXAMPLE1_UNKNOWN,
        known=EXAMPLE1_KNOWN,
        mw_arcsec=10.0,
        coordinate_unit_mm=coordinate_unit_mm,
    )


def example1_order_probe() -> List[Dict[str, Any]]:
    """尝试六种三元组角色排列，返回 Q 与论文值的对比。

    论文的数值结果对应 ``(测站, 后视, 前视)`` 顺序，即三元组第一个点是
    测站（与论文 4.5 节 JS 代码 ``j=JKH(i,1)`` 一致，而正文“顶点放中间”
    的表述与代码/结果不符）。
    """
    triples = [
        [int(v) for v in chunk.split(",")]
        for chunk in EXAMPLE1_TOPOLOGY.strip("[]").split(";")
    ]
    id_map = {-1: "8", -2: "9"}
    rows: List[Dict[str, Any]] = []
    for perm in itertools.permutations(range(3)):
        canonical = []
        for triple in triples:
            names = [id_map.get(v, str(v)) for v in triple]
            canonical.append(tuple(names[i] for i in perm))
        try:
            result = example1_result(canonical)
        except Exception as exc:  # 秩亏等
            rows.append(
                {
                    "permutation": perm,
                    "role_order": _permutation_name(perm),
                    "ok": False,
                    "error": str(exc),
                }
            )
            continue
        qxx, qyy, _ = result.q_mm2[0, 0], result.q_mm2[1, 1], 0.0
        rows.append(
            {
                "permutation": perm,
                "role_order": _permutation_name(perm),
                "ok": True,
                "qxx_mm2": qxx,
                "qyy_mm2": qyy,
                "paper_qxx": qxx / 100.0,
                "paper_qyy": qyy / 100.0,
                "matches_paper": abs(qxx / 100.0 - 0.6502) < 5e-5
                and abs(qyy / 100.0 - 0.3039) < 5e-5,
            }
        )
    return rows


def _permutation_name(perm: Sequence[int]) -> str:
    labels = ("后视", "测站", "前视")
    return "(" + ",".join(labels[i] for i in perm) + ")"


def example1_triangle_angles() -> List[Tuple[str, str, str]]:
    """由 17 条边得到的全部三角形内角（9 个三角形共 27 个角）。"""
    adjacency: Dict[str, set] = {str(i): set() for i in range(1, 10)}
    for _, a, b, _, _ in EXAMPLE1_LINES:
        adjacency[a].add(b)
        adjacency[b].add(a)
    angles: List[Tuple[str, str, str]] = []
    for station in sorted(adjacency, key=int):
        neighbours = sorted(adjacency[station], key=int)
        for backsight, foresight in itertools.combinations(neighbours, 2):
            if foresight in adjacency[backsight]:
                angles.append((backsight, station, foresight))
    return angles


def example1_missing_triangle_angles() -> List[Tuple[str, str, str]]:
    """14 个已给角之外、补齐 9 个三角形所需的 13 个角。"""
    used = {
        (min(b, f), s, max(b, f))
        for b, s, f in example1_angles(order="station_first")
    }
    return [
        angle
        for angle in example1_triangle_angles()
        if (min(angle[0], angle[2]), angle[1], max(angle[0], angle[2])) not in used
    ]


# 27 角优化的新增观测未公布；这是本仓库在 38 个候选角中做 13 元子集局部
# 搜索得到的最接近组合。正确 P=I 最小二乘下它的 Q 仍与论文公布值不符，
# 详见 docs/target/reproduction.md。
EXAMPLE1_OPTIMIZED_ATTEMPT: List[Tuple[str, str, str]] = [
    ("3", "2", "8"),
    ("3", "2", "9"),
    ("8", "2", "9"),
    ("2", "3", "9"),
    ("4", "5", "6"),
    ("4", "5", "8"),
    ("6", "5", "9"),
    ("5", "6", "7"),
    ("5", "6", "8"),
    ("1", "8", "9"),
    ("2", "8", "7"),
    ("7", "8", "9"),
    ("3", "9", "8"),
]
EXAMPLE1_OPTIMIZED_ATTEMPT_Q = (41.29197126, 19.41680032)


def example1_edges_from_coordinates() -> Dict[str, float]:
    """由高斯坐标反算的 17 条边长（用于和线库数值对比）。"""
    lengths: Dict[str, float] = {}
    for _, a, b, _, _ in EXAMPLE1_LINES:
        xa, ya = EXAMPLE1_POINTS[a]
        xb, yb = EXAMPLE1_POINTS[b]
        lengths[f"{a}{b}"] = hypot(xb - xa, yb - ya)
    return lengths


# ---------------------------------------------------------------------------
# 算例 2：边角网（图 5-9/5-10），点位未公布，按线库重建
# ---------------------------------------------------------------------------

EXAMPLE2_LINES: List[Tuple[int, str, str, float, float]] = [
    (1, "1", "2", 462.0851, 113.7241),
    (2, "2", "3", 481.0551, 124.4761),
    (3, "3", "4", 464.8421, 180.8161),
    (4, "4", "5", 839.9711, 236.9411),
    (5, "5", "6", 619.7001, 318.6101),
    (6, "6", "7", 611.8351, 320.4071),
    (7, "7", "1", 821.4671, 57.2071),
    (8, "1", "8", 444.9021, 180.4151),
    (9, "2", "8", 498.7651, 238.7211),
    (10, "2", "9", 732.5551, 186.9951),
    (11, "3", "9", 665.4451, 226.8891),
    (12, "4", "9", 479.2781, 271.1981),
    (13, "5", "9", 519.4021, 25.6431),
    (14, "6", "9", 634.5221, 89.6971),
    (15, "6", "8", 557.4451, 32.2451),
    (16, "7", "8", 687.3631, 90.0001),
    (17, "8", "9", 576.8541, 144.2441),
]

# 由 17 条边的距离/方位角按最小二乘重建的局部坐标（x 北、y 东，m）。
# 已知点 8 固定为原点；9 由边 17 直接起算。整体平移/旋转不改变 Q。
EXAMPLE2_POINTS: Dict[str, Tuple[float, float]] = {
    "1": (444.8923, 3.2213),
    "2": (258.9693, 426.2792),
    "3": (-13.3492, 822.8643),
    "4": (-478.1518, 816.2562),
    "5": (-936.3717, 112.2895),
    "6": (-471.4718, -297.4291),
    "7": (-0.0038, -687.3550),
    "8": (0.0, 0.0),
    "9": (-468.1250713250028, 337.0750217440785),
}
EXAMPLE2_UNKNOWN = [str(i) for i in range(1, 8)]
EXAMPLE2_KNOWN = ["8", "9"]

# 观测选择未知；以下为在 3 分钟上限内搜索到的一组组合，其论文口径
# Qxx≈0.17153、Qyy≈0.15748，与公布值 0.1715/0.1575 在 4 位小数内一致，
# 且点 7 为最弱点（M7≈5.74 mm 论文口径，公布 0.57 cm）。
EXAMPLE2_SELECTED_EDGES: List[Tuple[str, str]] = [
    ("2", "3"),
    ("4", "9"),
    ("6", "8"),
    ("3", "4"),
    ("6", "9"),
    ("2", "8"),
    ("4", "5"),
    ("2", "9"),
    ("6", "7"),
    ("3", "9"),
]
EXAMPLE2_SELECTED_ANGLES: List[Tuple[str, str, str]] = [
    ("6", "9", "8"),
    ("2", "3", "9"),
    ("3", "4", "9"),
    ("1", "8", "2"),
    ("2", "9", "8"),
    ("6", "7", "8"),
    ("2", "1", "8"),
    ("1", "8", "7"),
    ("1", "7", "8"),
    ("4", "9", "5"),
    ("5", "9", "6"),
]
EXAMPLE2_PUBLISHED: Dict[str, Any] = {
    "weakest_point": "7",
    "qxx": 0.1715,
    "qyy": 0.1575,
    "mp_text_cm": 0.57,
    "optimized_qxx": 0.1411,
    "optimized_qyy": 0.1298,
    "optimized_mp_text_cm": 0.52,
    "grade": "二级",
    "q_unit": "论文截图数值（实际对应 cm²/(″)²）",
    "edge_denominators": [
        46208.5,
        48105.5,
        46484.2,
        83997.1,
        61970.0,
        61183.5,
        82146.7,
        44490.2,
        49876.5,
        73255.5,
        66544.5,
        47927.8,
        51940.2,
        63452.2,
        55744.5,
        68736.3,
        57685.4,
    ],
}


def example2_result(
    edges: Optional[Iterable[Sequence[str]]] = None,
    angles: Optional[Iterable[Sequence[str]]] = None,
) -> ThesisNetworkResult:
    """按二级参数构建近似边角网（10 边 + 11 角）。"""
    edge_list = list(edges) if edges is not None else EXAMPLE2_SELECTED_EDGES
    angle_list = list(angles) if angles is not None else EXAMPLE2_SELECTED_ANGLES
    return build_network(
        EXAMPLE2_POINTS,
        unknown=EXAMPLE2_UNKNOWN,
        known=EXAMPLE2_KNOWN,
        angles=angle_list,
        distances=edge_list,
        mw_arcsec=10.0,
        distance_a_mm=15.0,
        distance_b_ppm=20.0,
        distance_sigma_model="linear",
        distance_weights=True,
        sigma0=10.0,
    )


def example2_edge_sigmas() -> List[Dict[str, float]]:
    """按二级参数给出线库各边的先验中误差（线性 σS=a+bS）。"""
    from .thesis import distance_sigma_mm

    rows: List[Dict[str, float]] = []
    for number, a, b, length, azimuth in EXAMPLE2_LINES:
        rows.append(
            {
                "number": number,
                "from": a,
                "to": b,
                "length": length,
                "azimuth": azimuth,
                "sigma_mm": distance_sigma_mm(
                    length, a_mm=15.0, b_ppm=20.0, model="linear"
                ),
            }
        )
    return rows


__all__ = [
    "EXAMPLE1_POINTS",
    "EXAMPLE1_UNKNOWN",
    "EXAMPLE1_KNOWN",
    "EXAMPLE1_TOPOLOGY",
    "EXAMPLE1_LINES",
    "EXAMPLE1_PUBLISHED",
    "example1_angles",
    "example1_result",
    "example1_order_probe",
    "example1_triangle_angles",
    "example1_missing_triangle_angles",
    "example1_edges_from_coordinates",
    "EXAMPLE1_OPTIMIZED_ATTEMPT",
    "EXAMPLE1_OPTIMIZED_ATTEMPT_Q",
    "EXAMPLE2_POINTS",
    "EXAMPLE2_UNKNOWN",
    "EXAMPLE2_KNOWN",
    "EXAMPLE2_LINES",
    "EXAMPLE2_SELECTED_EDGES",
    "EXAMPLE2_SELECTED_ANGLES",
    "EXAMPLE2_PUBLISHED",
    "example2_result",
    "example2_edge_sigmas",
]
