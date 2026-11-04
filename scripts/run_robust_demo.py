# %% [markdown]
# # 粗差探测与稳健估计演示（C1）
#
# 本脚本演示 `ctrlnet.robust`：
#
# - 用第 13 节增补网的真值坐标模拟观测，随机误差按先验 σ，固定随机种子；
# - 在 CD 距离上注入 10σ 粗差，从约 0.3 m 的近似坐标做高斯-牛顿迭代；
# - Baarda w 检验（临界值 3.29）迭代剔除超限观测；
# - Huber（c=1.345）与 IGG-III（k0=1.5、k1=3.0）稳健估计；
# - 对比 LS、剔除后 LS、Huber、IGG-III 的坐标偏差。
#
# 输出：
# - `outputs/blunder_detection.png`
# - `outputs/robust_results.md`
# - `outputs/robust_results.csv`
#
# 运行：
#
# ```bash
# .venv/bin/python scripts/run_robust_demo.py
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
import numpy as np
from matplotlib import font_manager

from ctrlnet import (
    DEFAULT_W_CRITICAL,
    analyze_reliability,
    data_snooping,
    estimate_network,
    huber_estimate,
    igg3_estimate,
    section13_added,
    simulate_observations,
    solve,
)

OUTPUTS = ROOT / "outputs"
OUTPUTS.mkdir(parents=True, exist_ok=True)

SEED = 30
BLUNDER_LABEL = "CD"
BLUNDER_K = 10.0
APPROXIMATE = {"C": (0.32, 100.28), "D": (99.74, 100.31)}

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
# 1. 模拟观测：干净数据与注入 10σ 粗差的数据共用同一随机种子。
scenario = section13_added()
network = scenario.network
clean_dataset = simulate_observations(network, seed=SEED)
contaminated_dataset = simulate_observations(
    network,
    seed=SEED,
    blunders={BLUNDER_LABEL: BLUNDER_K},
)

reliability = analyze_reliability(solve(scenario))
true_coords = {name: (p.E, p.N) for name, p in ((p.name, p) for p in network.points)}
points = [p.name for p in network.points if not p.fixed]
labels = contaminated_dataset.labels
r_by_label = {row.label: row.r_i for row in reliability.records}

# %%
# 2. 四种解算。
ls = estimate_network(contaminated_dataset, approximate=APPROXIMATE)
clean_ls = estimate_network(clean_dataset, approximate=APPROXIMATE)
snooping = data_snooping(contaminated_dataset, approximate=APPROXIMATE)
removed_ls = snooping.final_estimate
huber = huber_estimate(contaminated_dataset, approximate=APPROXIMATE)
igg = igg3_estimate(contaminated_dataset, approximate=APPROXIMATE)

methods = [
    ("LS", "LS（全部观测）", ls),
    ("Snooping-LS", "剔除后 LS", removed_ls),
    ("Huber", "Huber", huber),
    ("IGG-III", "IGG-III", igg),
]


def method_outliers(key: str, result: object) -> list[str]:
    if key == "LS":
        return []
    if key == "Snooping-LS":
        return list(snooping.removed_labels)
    return list(getattr(result, "outlier_labels", []))

print(f"种子={SEED}，注入 {BLUNDER_LABEL} = {BLUNDER_K:g}σ")
print(f"LS 迭代：{ls.iterations} 次，收敛={ls.converged}，max|dx|={ls.max_update:.2e}")
print(f"w 检验剔除：{snooping.removed_labels or '无'}")
print(f"Huber 异常：{huber.outlier_labels or '无'}")
print(f"IGG-III 异常：{igg.outlier_labels or '无'}")
for key, title, result in methods:
    dev = {name: result.point_deviation_mm(name) for name in points}
    print(
        f"  {title:12s} max|Δ|={result.max_deviation_mm():6.3f} mm，"
        f"RMS={result.rms_deviation_mm():6.3f} mm，偏差={dev}"
    )

# %%
# 3. 图件：初始 |w|、剔除后 |w|、IGG-III 权因子、坐标偏差对比。
critical = DEFAULT_W_CRITICAL
initial_w = np.asarray(
    [ls.w_by_label.get(label, 0.0) for label in labels], dtype=float
)
final_w = np.asarray(
    [removed_ls.w_by_label.get(label, 0.0) for label in labels], dtype=float
)
removed_mask = np.isin(labels, snooping.removed_labels)
igg_weights = np.asarray(igg.observation_weight_factors, dtype=float)

fig, axes = plt.subplots(2, 2, figsize=(14.5, 9.2))
x = np.arange(len(labels))
colors = ["#c0392b" if m else "#4c78a8" for m in removed_mask]

ax = axes[0, 0]
ax.bar(x, initial_w, color=colors)
ax.axhline(critical, color="#d97706", ls="--", lw=1.6, label=f"临界值 {critical:.2f}")
ax.set_title(T("迭代前：全部观测的 |w|", "Before: |w| for all observations"))
ax.set_ylabel("|w|")
ax.set_xticks(x, labels, rotation=20, ha="right")
ax.grid(axis="y", alpha=0.25)
ax.legend(loc="upper right", fontsize=9)
for xi, value in zip(x, initial_w):
    ax.text(xi, value + 0.08, f"{value:.2f}", ha="center", va="bottom", fontsize=8)

ax = axes[0, 1]
final_w_plot = np.where(removed_mask, 0.0, final_w)
ax.bar(x, final_w_plot, color=np.where(removed_mask, "#bdbdbd", "#4c78a8"))
ax.axhline(critical, color="#d97706", ls="--", lw=1.6, label=f"临界值 {critical:.2f}")
ax.set_title(T("迭代后：保留观测的 |w|", "After: |w| for retained observations"))
ax.set_ylabel("|w|")
ax.set_xticks(x, labels, rotation=20, ha="right")
ax.grid(axis="y", alpha=0.25)
ax.legend(loc="upper right", fontsize=9)
for xi, value, removed in zip(x, final_w, removed_mask):
    if removed:
        ax.text(xi, 0.08, "剔除", ha="center", va="bottom", fontsize=8, color="#7f1d1d")
    else:
        ax.text(xi, value + 0.08, f"{value:.2f}", ha="center", va="bottom", fontsize=8)

ax = axes[1, 0]
weights_plot = np.asarray(
    [igg.observation_weight(label) for label in labels], dtype=float
)
ax.bar(x, weights_plot, color=["#c0392b" if w < 0.5 else "#2a9d8f" for w in weights_plot])
ax.axhline(1.0, color="#334155", ls=":", lw=1.2, label="原权 1.0")
ax.set_ylim(0.0, 1.12)
ax.set_title(T("IGG-III 权因子（k0=1.5, k1=3.0）", "IGG-III weight factors"))
ax.set_ylabel(T("权因子", "weight factor"))
ax.set_xticks(x, labels, rotation=20, ha="right")
ax.grid(axis="y", alpha=0.25)
ax.legend(loc="lower right", fontsize=9)
for xi, value in zip(x, weights_plot):
    ax.text(xi, value + 0.025, f"{value:.2f}", ha="center", va="bottom", fontsize=8)

ax = axes[1, 1]
width = 0.18
xpts = np.arange(len(points))
method_colors = ["#4c78a8", "#f58518", "#54a24b", "#b279a2"]
for j, ((_key, title, result), color) in enumerate(zip(methods, method_colors)):
    values = [result.point_deviation_mm(name) for name in points]
    ax.bar(xpts + (j - 1.5) * width, values, width, label=title, color=color)
    for xi, value in zip(xpts + (j - 1.5) * width, values):
        ax.text(xi, value + 0.035, f"{value:.2f}", ha="center", va="bottom", fontsize=7.5)
ax.set_xticks(xpts, points)
ax.set_ylabel(T("点位坐标偏差 / mm", "coordinate deviation / mm"))
ax.set_title(T("与真值比较：坐标偏差", "Coordinate deviation from truth"))
ax.grid(axis="y", alpha=0.25)
ax.legend(fontsize=8, ncol=2)

fig.suptitle(
    T(
        f"粗差探测与稳健估计：{scenario.name}，种子 {SEED}，{BLUNDER_LABEL} 注入 {BLUNDER_K:g}σ",
        f"Blunder detection and robust estimation: seed {SEED}, {BLUNDER_LABEL} + {BLUNDER_K:g}σ",
    ),
    fontsize=13,
)
fig.tight_layout(rect=(0, 0, 1, 0.96))
plot_path = OUTPUTS / "blunder_detection.png"
fig.savefig(plot_path, dpi=150, bbox_inches="tight")
plt.close(fig)
print(f"已生成 {plot_path.relative_to(ROOT)}")

# %%
# 4. CSV：每个方法、每个待定点的坐标与偏差。
csv_path = OUTPUTS / "robust_results.csv"
with csv_path.open("w", newline="", encoding="utf-8-sig") as fh:
    writer = csv.writer(fh)
    writer.writerow(
        [
            "method",
            "point",
            "true_E",
            "true_N",
            "est_E",
            "est_N",
            "dE_mm",
            "dN_mm",
            "deviation_mm",
            "max_coordinate_deviation_mm",
            "rms_deviation_mm",
            "detected_outliers",
            "blunder_weight",
        ]
    )
    for key, _title, result in methods:
        for name in points:
            est = result.coordinate(name)
            true = true_coords[name]
            dev = np.asarray(est) - np.asarray(true)
            writer.writerow(
                [
                    key,
                    name,
                    f"{true[0]:.6f}",
                    f"{true[1]:.6f}",
                    f"{est[0]:.6f}",
                    f"{est[1]:.6f}",
                    f"{dev[0] * 1000.0:.6f}",
                    f"{dev[1] * 1000.0:.6f}",
                    f"{result.point_deviation_mm(name):.6f}",
                    f"{result.max_deviation_mm():.6f}",
                    f"{result.rms_deviation_mm():.6f}",
                    ";".join(method_outliers(key, result)),
                    f"{result.observation_weight(BLUNDER_LABEL):.6f}",
                ]
            )
print(f"已生成 {csv_path.relative_to(ROOT)}")

# %%
# 5. Markdown 汇总。
md_lines = [
    "# 粗差探测与稳健估计结果（C1）",
    "",
    f"- 方案：{scenario.name}",
    f"- 随机种子：`{SEED}`；随机误差按各观测先验 σ 生成。",
    f"- 注入粗差：`{BLUNDER_LABEL}` = {BLUNDER_K:g}σ"
    f"（{BLUNDER_K * contaminated_dataset.record(BLUNDER_LABEL).sigma[0] * 1000.0:.3f} mm）。",
    f"- 近似坐标起点：C≈(0.32, 100.28) m，D≈(99.74, 100.31) m；"
    f"LS 高斯-牛顿迭代 {ls.iterations} 次收敛。",
    f"- w 检验临界值：{critical:.2f}（α0=0.001 双侧，σ0 已知）。",
    "- 单位：坐标/偏差为 m/mm，角度为角秒。",
    "",
    "## 1. 方法对比",
    "",
    "| 方法 | max 点位偏差/mm | RMS 点位偏差/mm | 识别粗差 | 剔除/降权观测 |",
    "|---|---:|---:|---|---|",
]
for key, title, result in methods:
    outlier_list = method_outliers(key, result)
    outliers = "、".join(outlier_list) if outlier_list else "—"
    md_lines.append(
        f"| {title} | {result.max_deviation_mm():.3f} | "
        f"{result.rms_deviation_mm():.3f} | {outliers} | "
        f"{outliers} |"
    )
md_lines.extend(
    [
        "",
        "无粗差参考解（同一随机种子）的 max 点位偏差为 "
        f"{clean_ls.max_deviation_mm():.3f} mm、RMS 为 "
        f"{clean_ls.rms_deviation_mm():.3f} mm；"
        f"IGG-III 解与无粗差参考解的最大坐标差为 "
        f"{max(float(np.linalg.norm(igg.deviation(name) - clean_ls.deviation(name)) * 1000.0) for name in points):.3f} mm。",
        "",
        "## 2. 数据探测迭代",
        "",
        "| 轮次 | 活动观测数 | max abs(w) | 临界值 | 剔除 | σ̂0 | χ² | p(χ²) |",
        "|---:|---:|---:|---:|---|---:|---:|---:|",
    ]
)
for rnd in snooping.rounds:
    md_lines.append(
        f"| {rnd.iteration} | {rnd.n_active} | {rnd.max_abs_statistic:.3f} | "
        f"{rnd.critical_value:.3f} | {rnd.removed_label or '—'} | "
        f"{rnd.sigma0_hat:.3f} | {rnd.chi_square:.3f} | {rnd.chi_square_p_value:.4f} |"
    )
md_lines.extend(
    [
        "",
        "## 3. 各观测 w 统计量与 IGG-III 权因子",
        "",
        "| 观测 | 类型 | r_i | 初始 abs(w) | 最终 abs(w) | IGG-III 权因子 | 判定 |",
        "|---|---|---:|---:|---:|---:|---|",
    ]
)
for label in labels:
    kind = contaminated_dataset.record(label).kind
    init_w = ls.w_by_label.get(label, 0.0)
    fin_w = removed_ls.w_by_label.get(label, 0.0)
    weight = igg.observation_weight(label)
    if label in snooping.removed_labels:
        verdict = "w 剔除 / IGG 降权"
    elif label in igg.outlier_labels:
        verdict = "IGG 降权"
    else:
        verdict = "保留"
    md_lines.append(
        f"| {label} | {kind} | {r_by_label.get(label, float('nan')):.4f} | "
        f"{init_w:.3f} | {fin_w:.3f} | {weight:.4f} | {verdict} |"
    )
md_lines.extend(
    [
        "",
        "## 4. 可控性与 r_i",
        "",
        f"- `{BLUNDER_LABEL}` 的 r_i={r_by_label[BLUNDER_LABEL]:.4f}，"
        f"MDB/σ={reliability[BLUNDER_LABEL].mdb_sigma_ratio:.2f}，10σ 粗差在 w 检验中显著。",
        "- 角度观测的 r_i 很小："
        + "、".join(
            f"`{label}` r_i={r_by_label[label]:.4f}"
            for label in ("∠C-A-B", "∠A-B-D", "∠D-C-A")
        )
        + "。按 `w_i≈(∇_i/σ_i)·sqrt(r_i)`，同样 10σ 的角度粗差 |w| 仅约 "
        f"{10.0 * np.sqrt(r_by_label['∠C-A-B']):.2f}～"
        f"{10.0 * np.sqrt(r_by_label['∠D-C-A']):.2f}，低于 3.29，难以发现；"
        "这正是“精度好不等于可靠性好”的体现。",
        "- 稳健估计不能替代设计阶段的 MDB/外部可靠性；两者应结合使用。",
        "",
        "## 5. 说明",
        "",
        "- LS 对 10σ 粗差敏感；剔除后 LS 与 IGG-III 将其权因子降为 0，结果接近无粗差解。",
        "- Huber 对粗差降权但不淘汰，因此仍保留少量粗差影响；其权因子见 CSV/上图。",
        "- 单粗差、小样本下仍可能出现遮蔽/淹没；实际工程应结合 w 检验、稳健估计与人工核查。",
        "",
    ]
)
md_path = OUTPUTS / "robust_results.md"
md_path.write_text("\n".join(md_lines), encoding="utf-8")
print(f"已生成 {md_path.relative_to(ROOT)}")

# %%
print("\n方法汇总：")
for key, title, result in methods:
    print(
        f"  {title:12s} max={result.max_deviation_mm():.3f} mm, "
        f"RMS={result.rms_deviation_mm():.3f} mm, outliers={method_outliers(key, result) or '—'}"
    )
print(f"pytest 摘要见 README；图件 {plot_path.name}，结果 {md_path.name}/{csv_path.name}")
