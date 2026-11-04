# %% [markdown]
# # 高程/水准网演示（B1）
#
# 本脚本演示 `ctrlnet.leveling`：
#
# - 6 点水准网（1 个固定基准、5 个待定点，含两个闭合环）；
# - 水准路线按 `σ_km·sqrt(L)`，其中一条按测站数 `σ_station·sqrt(n)`；
# - 两条三角高程观测（斜距形式 + 平距形式，含球气差/折光改正）；
# - 高程平差、`Cx`、点高程中误差、相对高差中误差、`r_i`、MDB、外部可靠性；
# - 生成 `outputs/leveling_points.csv`、`outputs/leveling_results.md`、
#   `outputs/leveling_network.png`。
#
# 运行：
#
# ```bash
# .venv/bin/python scripts/run_leveling_demo.py
# ```

# %%
from __future__ import annotations

import csv
import os
from pathlib import Path

try:
    ROOT = Path(__file__).resolve().parents[1]
except NameError:  # notebook 中没有 __file__
    ROOT = Path.cwd()
    if ROOT.name == "notebooks":
        ROOT = ROOT.parent

os.environ.setdefault(
    "MPLCONFIGDIR", str(Path(os.environ.get("TMPDIR", "/tmp")) / "ctrlnet-mplconfig")
)
Path(os.environ["MPLCONFIGDIR"]).mkdir(parents=True, exist_ok=True)

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import font_manager

from ctrlnet import (
    HeightDifference,
    LevelingNetwork,
    LevelingPoint,
    TrigHeight,
    plot_leveling_network,
    solve_leveling,
)

OUTPUTS = ROOT / "outputs"
OUTPUTS.mkdir(parents=True, exist_ok=True)

# 有中文字体时用中文图题，否则退回英文，避免方框乱码。
_available_fonts = {f.name for f in font_manager.fontManager.ttflist}
_CJK_CANDIDATES = [
    "Noto Sans CJK SC",
    "Noto Sans CJK JP",
    "WenQuanYi Zen Hei",
    "Droid Sans Fallback",
]
_CJK_FONT = next((name for name in _CJK_CANDIDATES if name in _available_fonts), None)
if _CJK_FONT:
    plt.rcParams["font.family"] = "sans-serif"
    plt.rcParams["font.sans-serif"] = [_CJK_FONT, "DejaVu Sans"]
plt.rcParams["axes.unicode_minus"] = False


def T(zh: str, en: str) -> str:
    return zh if _CJK_FONT else en


# %%
# 1. 6 点水准网 + 两条三角高程观测。
#    真实高程仅用于检查算例；观测值含 3 mm 闭合差，便于展示平差分配。
points = [
    LevelingPoint("A", 100.000, fixed=True, height_type="normal"),
    LevelingPoint("B", 101.500, height_type="normal"),
    LevelingPoint("C", 102.300, height_type="normal"),
    LevelingPoint("D", 101.100, height_type="normal"),
    LevelingPoint("E", 102.900, height_type="normal"),
    LevelingPoint("F", 101.800, height_type="normal"),
]

leveling = [
    HeightDifference("A", "B", +1.500, length_km=1.2, sigma_per_km_mm=2.0),
    HeightDifference("B", "C", +0.800, length_km=1.5, sigma_per_km_mm=2.0),
    HeightDifference("C", "D", -1.200, length_km=1.0, sigma_per_km_mm=2.0),
    # 3 mm 闭合差：1.500+0.800-1.200-1.097 = +0.003 m。
    HeightDifference("D", "A", -1.097, length_km=0.8, sigma_per_km_mm=2.0),
    HeightDifference("C", "E", +0.600, length_km=0.9, sigma_per_km_mm=2.0),
    # 该测段按测站数定权，展示 station 模式。
    HeightDifference(
        "E",
        "F",
        -1.100,
        length_km=0.7,
        n_stations=12,
        sigma_per_station_mm=0.6,
    ),
    HeightDifference("F", "D", -0.700, length_km=0.6, sigma_per_km_mm=2.0),
]

trig = [
    # 斜距形式：A→E，S=949.9 m，天顶距 89.83°。
    TrigHeight(
        "A",
        "E",
        slope_distance=949.9,
        zenith_deg=89.83,
        instrument_height=1.52,
        target_height=1.50,
        k=0.13,
        R=6371000.0,
        sigma_zenith_arcsec=1.0,
        sigma_slope_mm=2.0,
        sigma_instrument_mm=1.0,
        sigma_target_mm=1.0,
        label="A-E(trig)",
    ),
    # 平距形式：C→F，D=800 m，天顶距 90.04°。
    TrigHeight(
        "C",
        "F",
        horizontal_distance=800.0,
        zenith_deg=90.04,
        instrument_height=1.55,
        target_height=1.53,
        k=0.13,
        R=6371000.0,
        sigma_zenith_arcsec=1.0,
        sigma_horizontal_mm=2.0,
        sigma_instrument_mm=1.0,
        sigma_target_mm=1.0,
        label="C-F(trig)",
    ),
]

network = LevelingNetwork(points, leveling + trig, name="6-point leveling + trig")
result = solve_leveling(network)
assert result.reliability is not None

print(
    f"观测数={result.n_observations}（水准 {len(leveling)} + 三角高程 {len(trig)}），"
    f"参数数={result.n_params}，秩={result.rank}，冗余数={result.redundancy}，"
    f"条件数={result.condition_number:.3f}"
)
print(f"基准：{result.datum_summary}；λ0={result.reliability.lambda0_value:.3f}")
print("\n点高程与中误差：")
for name in result.point_order:
    p = result.point_precision(name)
    print(f"  {name}: H={p.H:.4f} m, σ_H={p.sigma_mm:.3f} mm, role={p.role}")

# %%
# 2. 闭合环与三角高程检核。
def observation_between(frm: str, to: str) -> tuple[float, float, str]:
    """返回 (frm→to 的高差, σ, 观测标签)；支持反向使用。"""
    for obs in network.observations:
        if obs.frm == frm and obs.to == to:
            return obs.delta_h, obs.sigma, obs.label
        if obs.frm == to and obs.to == frm:
            return -obs.delta_h, obs.sigma, obs.label + "(反向)"
    raise KeyError(f"没有连接 {frm}-{to} 的观测")


def loop_closure(loop: list[str]) -> tuple[float, float]:
    total = 0.0
    var = 0.0
    for frm, to in zip(loop, loop[1:] + loop[:1]):
        dh, sigma, _label = observation_between(frm, to)
        total += dh
        var += sigma * sigma
    return total, var**0.5


loops = {
    "A-B-C-D-A": ["A", "B", "C", "D"],
    "C-E-F-D-C": ["C", "E", "F", "D"],
}
closures = {name: loop_closure(loop) for name, loop in loops.items()}
for name, (w, sigma_w) in closures.items():
    print(f"环 {name}: 闭合差={w * 1000:+.3f} mm，环高差中误差={sigma_w * 1000:.3f} mm")

# %%
# 3. 输出 CSV（点高程、中误差、基准角色）。
csv_path = OUTPUTS / "leveling_points.csv"
with csv_path.open("w", newline="", encoding="utf-8") as fh:
    writer = csv.writer(fh)
    writer.writerow(
        [
            "point",
            "H_m",
            "sigma_H_mm",
            "role",
            "height_type",
            "fixed",
            "weighted_constraint",
        ]
    )
    for name in result.point_order:
        p = result.point_precision(name)
        writer.writerow(
            [
                name,
                f"{p.H:.6f}",
                f"{p.sigma_mm:.6f}",
                p.role,
                p.height_type,
                int(p.fixed),
                int(p.constrained),
            ]
        )

# %%
# 4. 生成 Markdown 结果表。
rel_by_label = {row.label: row for row in result.reliability.observation_records}


def obs_kind_cn(kind: str) -> str:
    return {
        "leveling": "水准",
        "trig_height": "三角高程",
        "constraint": "高程约束",
    }.get(kind, kind)


md: list[str] = []
md.append("# 高程/水准网演示结果（B1）")
md.append("")
md.append("由 `scripts/run_leveling_demo.py` 生成；数值为设计态/先验精度。")
md.append("")
md.append(
    f"- 观测量 {result.n_observations}（水准 {len(leveling)} 条 + 三角高程 {len(trig)} 条），"
    f"未知高程 {result.n_params} 个，秩 {result.rank}，冗余数 {result.redundancy}。"
)
md.append(f"- 基准：{result.datum_summary}。")
md.append(
    f"- 可靠性：λ0 = {result.reliability.lambda0_value:.3f}"
    f"（α={result.reliability.alpha:g}，power={result.reliability.power:g}）；"
    f"Σr_i = {result.reliability.sum_r:.9f}。"
)
md.append("- 高程类型仅作为属性记录；本演示为正常高，MVP 不做 geoid/高程异常转换。")
md.append("")
md.append("## 1. 点高程与精度")
md.append("")
md.append("| 点 | H / m | σ_H / mm | 角色 | 高程类型 |")
md.append("|---|---:|---:|---|---|")
role_cn = {"fixed": "固定", "constrained": "加权约束", "unknown": "待定"}
for name in result.point_order:
    p = result.point_precision(name)
    md.append(
        f"| {name} | {p.H:.4f} | {p.sigma_mm:.3f} | "
        f"{role_cn.get(p.role, p.role)} | {p.height_type} |"
    )
md.append("")
md.append("## 2. 观测精度与可靠性")
md.append("")
md.append("| 观测 | 类型 | Δh 或约束 / m | σ / mm | r_i | MDB / mm | 外部最大影响 / mm | 影响点 |")
md.append("|---|---|---:|---:|---:|---:|---:|---|")
for obs in network.observations:
    row = rel_by_label[obs.label]
    md.append(
        f"| {obs.label} | {obs_kind_cn(obs.kind)} | {obs.delta_h:+.4f} | "
        f"{obs.sigma * 1000:.3f} | {row.r_i:.4f} | {row.mdb_mm:.3f} | "
        f"{row.external_max_mm:.3f} | {row.external_point or '—'} |"
    )
md.append("")
md.append(
    "外部最大影响定义为单条粗差未检出时，对任一点高程的最大绝对影响；"
    "固定点协方差为 0，因此不会成为影响点。"
)
md.append("")
md.append("## 3. 相对高差精度")
md.append("")
md.append("| 起点 | 终点 | ΔH / m | σ_ΔH / mm |")
md.append("|---|---|---:|---:|")
for frm, to in (("A", "F"), ("B", "D"), ("C", "F"), ("A", "E"), ("D", "E")):
    rel = result.relative_height(frm, to)
    md.append(f"| {frm} | {to} | {rel.delta_h:+.4f} | {rel.sigma_mm:.3f} |")
md.append("")
md.append("## 4. 闭合环")
md.append("")
md.append("| 环 | 闭合差 / mm | 环高差中误差 / mm | 闭合差 / σ |")
md.append("|---|---:|---:|---:|")
for name, (w, sigma_w) in closures.items():
    ratio = abs(w) / sigma_w if sigma_w > 0.0 else float("inf")
    md.append(f"| {name} | {w * 1000:+.3f} | {sigma_w * 1000:.3f} | {ratio:.2f} |")
md.append("")
md.append("## 5. 三角高程")
md.append("")
md.append("| 观测 | 距离形式 | 距离 / m | 天顶距 / ° | i / m | v / m | 球气差 / m | Δh / m | σ / mm |")
md.append("|---|---|---:|---:|---:|---:|---:|---:|---:|")
for obs in trig:
    if obs.distance_mode == "slope":
        distance_label, distance_text = "斜距", f"{obs.slope_distance_value:.2f}"
    else:
        distance_label, distance_text = "平距", f"{obs.horizontal_distance_value:.2f}"
    md.append(
        f"| {obs.label} | {distance_label} | {distance_text} | "
        f"{obs.zenith_angle_deg:.3f} | {obs.instrument_height:.2f} | "
        f"{obs.target_height:.2f} | {obs.curvature_correction:.5f} | "
        f"{obs.delta_h:+.4f} | {obs.sigma * 1000:.3f} |"
    )
md.append("")
md.append(
    "三角高差公式：`Δh = S·cos(z) + (1-k)·S²·sin²(z)/(2R) + i - v`；"
    "平距形式用 `D·cot(z) + (1-k)·D²/(2R) + i - v`。"
    "本演示 k=0.13、R=6371000 m；S=1000 m 时球气差约 0.0683 m。"
)
md.append("")
md.append("## 6. 文件")
md.append("")
md.append("- `leveling_points.csv`：点高程、`σ_H`、角色与高程类型。")
md.append("- `leveling_network.png`：路线图，点标注 `H` 与 `σ_H`，线宽按观测权重。")
md.append("")
(OUTPUTS / "leveling_results.md").write_text("\n".join(md) + "\n", encoding="utf-8")

# %%
# 5. 绘制路线图：点高程中误差标注、线宽按 1/σ²。
positions = {
    "A": (0.0, 0.0),
    "B": (2.6, 0.0),
    "C": (4.4, 0.6),
    "D": (3.4, 2.6),
    "E": (1.6, 2.4),
    "F": (2.0, 4.2),
}
label_offsets = {
    "A": (-58, -12),
    "B": (-12, -34),
    "C": (10, -30),
    "D": (14, 6),
    "E": (-66, 8),
    "F": (10, 10),
}
fig, _ax = plt.subplots(figsize=(9.4, 6.6))
plot_leveling_network(
    result,
    positions=positions,
    ax=_ax,
    figsize=(9.4, 6.6),
    title=(
        f"{T('6 点水准网 + 三角高程', '6-point leveling + trig height')} — "
        f"{T('线宽按观测权重 1/σ²，点标注 σ_H', 'line width ∝ weight 1/σ²; labels show σ_H')}"
    ),
    label_offsets=label_offsets,
)
png_path = OUTPUTS / "leveling_network.png"
fig.savefig(png_path, dpi=180, bbox_inches="tight")
plt.close(fig)

print("\n输出文件：")
for path in (csv_path, OUTPUTS / "leveling_results.md", png_path):
    print(" -", path)
