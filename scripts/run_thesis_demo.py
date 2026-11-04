#!/usr/bin/env python
"""运行论文算例演示并写 outputs（完全离线）。

输出：
    outputs/thesis_results.md
    outputs/thesis_example1_edges.csv
    outputs/thesis_example1_network.png
"""

from __future__ import annotations

import csv
import itertools
import math
import os
from pathlib import Path

os.environ.setdefault("MPLCONFIGDIR", str(Path(__file__).resolve().parents[1] / ".mplconfig"))

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from ctrlnet.thesis import (
    central_meridian,
    compare_geodesic_and_plane,
    gauss_forward,
    gauss_inverse,
    thesis_edge_denominator,
)
from ctrlnet.thesis_examples import (
    EXAMPLE1_LINES,
    EXAMPLE1_OPTIMIZED_ATTEMPT,
    EXAMPLE1_OPTIMIZED_ATTEMPT_Q,
    EXAMPLE1_POINTS,
    EXAMPLE1_PUBLISHED,
    EXAMPLE1_TOPOLOGY,
    EXAMPLE2_PUBLISHED,
    EXAMPLE2_SELECTED_ANGLES,
    EXAMPLE2_SELECTED_EDGES,
    example1_angles,
    example1_missing_triangle_angles,
    example1_order_probe,
    example1_result,
    example2_result,
)

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "outputs"


def _best_five_extra():
    base = example1_result()
    target = np.array([base.q_mm2[0, 0], base.q_mm2[1, 1]])
    best = None
    for combo in itertools.combinations(example1_missing_triangle_angles(), 5):
        result = example1_result(list(example1_angles()) + list(combo))
        q = np.array([result.q_mm2[0, 0], result.q_mm2[1, 1]])
        score = float(np.linalg.norm((q / 100.0 - np.array([0.6502, 0.3039])) / np.array([0.6502, 0.3039])))
        if best is None or score < best[0]:
            best = (score, combo, q)
    return best


def _write_csv() -> Path:
    path = OUT / "thesis_example1_edges.csv"
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            [
                "number",
                "from",
                "to",
                "library_length_m",
                "library_azimuth_deg",
                "coordinate_length_m",
                "paper_denominator",
                "published_denominator",
            ]
        )
        for (number, a, b, length, azimuth), published in zip(
            EXAMPLE1_LINES, EXAMPLE1_PUBLISHED["edge_denominators"]
        ):
            xa, ya = EXAMPLE1_POINTS[a]
            xb, yb = EXAMPLE1_POINTS[b]
            coordinate_length = math.hypot(xb - xa, yb - ya)
            writer.writerow(
                [
                    number,
                    a,
                    b,
                    f"{length:.4f}",
                    f"{azimuth:.4f}",
                    f"{coordinate_length:.4f}",
                    f"{thesis_edge_denominator(length):.1f}",
                    f"{published:.1f}",
                ]
            )
    return path


def _plot() -> Path:
    result = example1_result()
    path = OUT / "thesis_example1_network.png"
    x0 = EXAMPLE1_POINTS["1"][0]
    y0 = EXAMPLE1_POINTS["1"][1]
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(12, 5.4), dpi=150)

    # 左：网形
    for _, a, b, _, _ in EXAMPLE1_LINES:
        xa, ya = EXAMPLE1_POINTS[a]
        xb, yb = EXAMPLE1_POINTS[b]
        ax1.plot([ya - y0, yb - y0], [xa - x0, xb - x0], color="#59a14f", lw=1.2, ls="--")
    for name, (x, y) in EXAMPLE1_POINTS.items():
        fixed = name in ("8", "9")
        ax1.plot(y - y0, x - x0, "s" if fixed else "o", ms=7,
                 color="#d62728" if fixed else "#1f77b4")
        ax1.annotate(name, (y - y0, x - x0), xytext=(4, 4), textcoords="offset points", fontsize=8)
    ax1.set_aspect("equal")
    ax1.set_xlabel("Δy / m")
    ax1.set_ylabel("Δx / m")
    ax1.set_title("Example 1: 14-angle network")
    ax1.grid(alpha=0.25)

    # 右：误差椭圆（放大 1000 倍显示）
    scale = 1000.0
    for _, a, b, _, _ in EXAMPLE1_LINES:
        xa, ya = EXAMPLE1_POINTS[a]
        xb, yb = EXAMPLE1_POINTS[b]
        ax2.plot([ya - y0, yb - y0], [xa - x0, xb - x0], color="#bbbbbb", lw=0.8)
    for name in result.unknown:
        x, y = EXAMPLE1_POINTS[name]
        ellipse = result.ellipse(name)
        theta = np.linspace(0.0, 2.0 * math.pi, 180)
        phi = math.radians(ellipse.phi_E_deg)
        # 长轴从北顺时针；局部 x=北、y=东。
        a_major = ellipse.E * scale
        b_minor = ellipse.F * scale
        dx = a_major * np.cos(theta) * math.cos(phi) - b_minor * np.sin(theta) * math.sin(phi)
        dy = a_major * np.cos(theta) * math.sin(phi) + b_minor * np.sin(theta) * math.cos(phi)
        ax2.plot(y - y0 + dy, x - x0 + dx, color="#9467bd", lw=1.0)
        ax2.plot(y - y0, x - x0, "o", ms=3, color="#1f77b4")
        ax2.annotate(name, (y - y0, x - x0), xytext=(3, 3), textcoords="offset points", fontsize=7)
    ax2.set_aspect("equal")
    ax2.set_xlabel("Δy / m")
    ax2.set_ylabel("Δx / m")
    ax2.set_title(f"Error ellipses ×{scale:.0f} (E/F in mm)")
    ax2.grid(alpha=0.25)

    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)
    return path


def _markdown(best_five) -> str:
    result = example1_result()
    qxx, qyy, qxy = result.q_mm2[0, 0], result.q_mm2[1, 1], result.q_mm2[0, 1]
    paper = result.paper_q("1")
    ellipse = result.ellipse("1")
    opt = example1_result(list(example1_angles()) + list(EXAMPLE1_OPTIMIZED_ATTEMPT))
    e2 = example2_result()

    lines = []
    lines.append("# 论文算例复现结果（D1）\n")
    lines.append("本文件由 `scripts/run_thesis_demo.py` 离线生成。\n")

    lines.append("## 1. 高斯投影核对\n")
    for name, (x, y) in EXAMPLE1_POINTS.items():
        lat, lon = gauss_inverse(x, y, central_meridian=117.0)
        lines.append(f"- 点{name}: x={x:.6f}, y={y:.6f} -> {lat:.9f}°, {lon:.9f}°")
    x, y = gauss_forward(34.2, 117.2)
    lat2, lon2 = gauss_inverse(x, y, central_meridian=117.0)
    lines.append(
        f"\n正反算往返示例：34.2°,117.2° -> {x:.6f},{y:.6f} -> "
        f"{lat2:.12f}°,{lon2:.12f}°\n"
    )
    comp = compare_geodesic_and_plane(34.2, 117.2, 34.21, 117.21)
    lines.append(
        f"椭球面 vs 平面（约 1.4 km）：距离差 {comp.distance_difference * 1000:.3f} mm，"
        f"方位角差 {comp.azimuth_difference * 3600:.3f}″\n"
    )

    lines.append("## 2. 算例 1：三元组顺序\n")
    lines.append("| 排列（后视,测站,前视 的角色） | Qxx mm² | Qyy mm² | 论文口径 Qxx | 论文口径 Qyy |")
    lines.append("|---|---:|---:|---:|---:|")
    for row in example1_order_probe():
        if row.get("ok"):
            lines.append(
                f"| {row['role_order']} | {row['qxx_mm2']:.4f} | {row['qyy_mm2']:.4f} | "
                f"{row['paper_qxx']:.4f} | {row['paper_qyy']:.4f} |"
            )
        else:
            lines.append(f"| {row['permutation']} | 秩亏 | 秩亏 | — | — |")
    lines.append("")

    lines.append("## 3. 算例 1：14 个已给角\n")
    lines.append(
        f"- Qxx(1) = **{qxx:.6f}** mm²/(″)²，Qyy(1) = **{qyy:.6f}** mm²/(″)²，"
        f"Qxy = {qxy:.6f}"
    )
    lines.append(
        f"- 论文口径：Qxx = **{paper[0]:.6f}**，Qyy = **{paper[1]:.6f}**"
    )
    lines.append(f"- 最弱点：点 {result.weakest_point()}")
    lines.append(f"- M1（严格）= {result.mp_mm('1'):.4f} mm")
    lines.append(f"- M1（论文数值口径）= {result.paper_mp_mm('1'):.4f}")
    lines.append(
        f"- 误差椭圆：E={ellipse.E:.4f} mm，F={ellipse.F:.4f} mm，"
        f"φE={ellipse.phi_E_deg:.4f}°"
    )
    lines.append("")

    lines.append("## 4. 算例 1：19 个角的尝试\n")
    lines.append(
        "14 个已给角已精确给出论文 Q（/100 口径）；从 13 个三角形剩余角中"
        "穷举 C(13,5)=1287 种补 5 角组合，最接近论文值的一组为："
    )
    lines.append(
        f"- 补充角：{', '.join('-'.join(a) for a in best_five[1])}"
    )
    lines.append(
        f"- Qxx={best_five[2][0]:.4f} mm²，Qyy={best_five[2][1]:.4f} mm²"
        f"（论文口径 {best_five[2][0]/100:.4f}/{best_five[2][1]/100:.4f}）"
    )
    lines.append("- 结论：无法复现 0.6502/0.3039；新增真实观测只会改善精度。\n")

    lines.append("## 5. 算例 1：27 角优化尝试\n")
    lines.append(
        f"- 搜索得到的 13 个新增角：{', '.join('-'.join(a) for a in EXAMPLE1_OPTIMIZED_ATTEMPT)}"
    )
    lines.append(
        f"- Qxx={opt.q_mm2[0,0]:.4f} mm²，Qyy={opt.q_mm2[1,1]:.4f} mm²"
        f"（论文口径 {opt.paper_q('1')[0]:.4f}/{opt.paper_q('1')[1]:.4f}）"
    )
    lines.append(
        f"- 论文公布 0.4636/0.1861（严格口径 46.36/18.61 mm²）；"
        "新增观测未公布，不能唯一反推。\n"
    )

    lines.append("## 6. 图 5-7 边长相对中误差分母\n")
    lines.append("反推公式：`分母 = S / 0.01 m = 100·S`。\n")
    lines.append("| 线 | 线库 S/m | 100·S | 论文表值 | 差 |")
    lines.append("|---:|---:|---:|---:|---:|")
    for (number, a, b, length, _), published in zip(
        EXAMPLE1_LINES, EXAMPLE1_PUBLISHED["edge_denominators"]
    ):
        model = thesis_edge_denominator(length)
        lines.append(
            f"| {number} | {length:.4f} | {model:.1f} | {published:.1f} | {model-published:+.1f} |"
        )
    lines.append("")

    lines.append("## 7. 算例 2：近似边角网\n")
    lines.append(
        "点位由线库 17 条边的距离/方位角重建；观测选择未知，采用搜索得到的"
        "10 边 + 11 角，二级参数 `a=15 mm, b=20 ppm, σS=a+bS`，"
        "`P=σ0²/σS²`，取 `σ0=10`。\n"
    )
    lines.append(f"- 观测边：{', '.join('-'.join(e) for e in EXAMPLE2_SELECTED_EDGES)}")
    lines.append(f"- 观测角：{', '.join('-'.join(a) for a in EXAMPLE2_SELECTED_ANGLES)}")
    lines.append(
        f"- 点 7：Qxx={e2.q_mm2[12,12]:.6f} mm²，Qyy={e2.q_mm2[13,13]:.6f} mm²"
    )
    lines.append(
        f"- 论文口径：Qxx={e2.paper_q('7')[0]:.6f}，Qyy={e2.paper_q('7')[1]:.6f}"
        f"（公布 {EXAMPLE2_PUBLISHED['qxx']}/{EXAMPLE2_PUBLISHED['qyy']}）"
    )
    lines.append(
        f"- 最弱点：点 {e2.weakest_point()}；M7（论文数值口径）={e2.paper_mp_mm('7'):.4f}"
        f"（公布 0.57 cm = 5.7 mm）"
    )
    lines.append(
        f"- 观测数/秩/多余观测：{e2.metadata['n_rows']}/{e2.metadata['rank']}/"
        f"{e2.metadata['redundancy']}\n"
    )

    lines.append("## 8. 文件\n")
    lines.append("- `data/sample/thesis_example1.json`")
    lines.append("- `data/sample/thesis_example2.json`")
    lines.append("- `outputs/thesis_example1_edges.csv`")
    lines.append("- `outputs/thesis_example1_network.png`")
    lines.append("- `docs/target/reproduction.md`")
    return "\n".join(lines) + "\n"


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    print("投影核对：", gauss_forward(34.2, 117.2), central_meridian(117.2))
    best_five = _best_five_extra()
    csv_path = _write_csv()
    png_path = _plot()
    md_path = OUT / "thesis_results.md"
    md_path.write_text(_markdown(best_five), encoding="utf-8")
    print(f"wrote {csv_path.relative_to(ROOT)}")
    print(f"wrote {png_path.relative_to(ROOT)}")
    print(f"wrote {md_path.relative_to(ROOT)}")
    print(
        "example1 paper Q:",
        tuple(round(v, 4) for v in example1_result().paper_q("1")[:2]),
    )
    print(
        "example2 paper Q7:",
        tuple(round(v, 4) for v in example2_result().paper_q("7")[:2]),
        "weakest=",
        example2_result().weakest_point(),
    )


if __name__ == "__main__":
    main()
