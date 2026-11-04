"""设计报告生成：Markdown / 自包含 HTML / 可选 DOCX。

报告内容对应重设计方案 §8.2“报告预览”与 §7.2 的报告资源：

- 工程概况与数据版本（快照哈希、引擎版本）；
- 点与观测清单、先验精度模型、基准；
- 点位精度/误差椭圆表、边相对精度表；
- 可靠性（``r_i`` / MDB / 外部可靠性）；
- 多方案对比与优化建议；
- DEM 通视结果（若方案带 ``visibility`` 元数据）；
- 网图、可靠性图、方案对比图和通视净空图。

HTML 中的 PNG 以 base64 内嵌，单文件即可离线打开；Markdown 使用
``assets/`` 相对路径，便于 pandoc 生成 DOCX。
"""

from __future__ import annotations

import base64
import html
import json
import math
import os
import re
import shutil
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

os.environ.setdefault(
    "MPLCONFIGDIR", str(Path(os.environ.get("TMPDIR", "/tmp")) / "ctrlnet-mplconfig")
)
Path(os.environ["MPLCONFIGDIR"]).mkdir(parents=True, exist_ok=True)

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from matplotlib import font_manager

from . import __version__
from .model import Network, Point
from .store import (
    ENGINE_VERSION,
    get_or_compute_result,
    load_project,
    observation_to_model,
    snapshot,
)

_CJK_CANDIDATES = (
    "Noto Sans CJK SC",
    "Noto Sans CJK JP",
    "WenQuanYi Zen Hei",
    "Droid Sans Fallback",
    "Source Han Sans SC",
)
_AVAILABLE_FONTS = {f.name for f in font_manager.fontManager.ttflist}
_CJK_FONT = next((name for name in _CJK_CANDIDATES if name in _AVAILABLE_FONTS), None)
if _CJK_FONT:
    plt.rcParams["font.family"] = "sans-serif"
    plt.rcParams["font.sans-serif"] = [_CJK_FONT, "DejaVu Sans"]
plt.rcParams["axes.unicode_minus"] = False

COLOR_VISIBLE = "#1a9850"
COLOR_BLOCKED = "#d73027"
COLOR_ACCENT = "#2563eb"

KIND_LABELS = {
    "distance": "距离",
    "angle": "水平角",
    "direction": "方向",
    "gnss": "GNSS 基线",
}

ROLE_LABELS = {
    "fixed": "固定",
    "constrained": "加权",
    "unknown": "待定",
}


# ---------------------------------------------------------------------------
# 数据整理
# ---------------------------------------------------------------------------
def _fmt(value: Any, digits: int = 3, dash: str = "—") -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return dash
    if not math.isfinite(number):
        return dash
    return f"{number:.{digits}f}"


def _ratio_text(value: Any) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "—"
    if not math.isfinite(number) or number <= 0.0:
        return "1:∞"
    return f"1:{int(round(1.0 / number))}"


def _role(point: Mapping[str, Any]) -> str:
    if point.get("fixed"):
        return "fixed"
    if point.get("sigma_E") is not None or point.get("sigma_N") is not None:
        return "constrained"
    return "unknown"


def _select_scenario(
    project: Mapping[str, Any], scenario: Optional[str] = None
) -> Dict[str, Any]:
    scenarios = list(project.get("scenarios") or [])
    if not scenarios:
        raise ValueError("工程没有方案")
    if scenario is None:
        default = str(project.get("metadata", {}).get("default_scenario") or "")
        for item in scenarios:
            if item["id"] == default:
                return item
        return scenarios[0]
    text = str(scenario)
    for item in scenarios:
        if item["id"] == text or item["name"] == text:
            return item
    raise KeyError(f"工程中不存在方案 {scenario!r}")


def _scenario_points(
    project: Mapping[str, Any], scenario: Mapping[str, Any]
) -> List[Dict[str, Any]]:
    by_name = {str(item["name"]): item for item in project.get("points") or []}
    names = scenario.get("metadata", {}).get("points") or scenario.get(
        "metadata", {}
    ).get("point_names")
    if names:
        return [by_name[str(name)] for name in names if str(name) in by_name]
    return list(project.get("points") or [])


def _kind(row: Mapping[str, Any]) -> str:
    return str(row.get("kind") or row.get("type") or "")


def _observation_text(row: Mapping[str, Any]) -> str:
    kind = _kind(row)
    if kind == "distance":
        return f"{row.get('from', row.get('frm'))} – {row.get('to')}"
    if kind == "angle":
        rear = row.get("backsight", row.get("rear"))
        front = row.get("foresight", row.get("front"))
        return f"∠{rear}-{row.get('station')}-{front}"
    if kind == "direction":
        return f"{row.get('station')} → {row.get('target')}"
    if kind == "gnss":
        return f"{row.get('from', row.get('frm'))} – {row.get('to')}"
    return str(row.get("id") or kind)


def _observation_prior(row: Mapping[str, Any]) -> str:
    kind = _kind(row)
    if kind == "distance":
        a_m = float(row.get("a_m", row.get("a", 0.002)) or 0.002)
        return f"a={_fmt(a_m * 1000.0, 3)} mm, b={_fmt(row.get('b_ppm'), 2)} ppm"
    if kind in ("angle", "direction"):
        return f"σ={_fmt(row.get('sigma_arcsec', row.get('sigma')), 2)}″"
    if kind == "gnss":
        return f"σE={_fmt(row.get('sigma_E'), 3)} m, σN={_fmt(row.get('sigma_N'), 3)} m"
    return "—"


def _observation_value(row: Mapping[str, Any]) -> str:
    if row.get("value_m") is not None:
        return f"{_fmt(row.get('value_m'), 4)} m"
    if row.get("value_deg") is not None:
        return f"{_fmt(row.get('value_deg'), 6)}°"
    if row.get("value_rad") is not None:
        return f"{_fmt(float(row.get('value_rad')) * 180.0 / math.pi, 6)}°"
    return "—"


def _reliability_by_id(result: Mapping[str, Any]) -> Dict[str, Mapping[str, Any]]:
    return {
        str(row.get("id")): row for row in result.get("observations") or [] if row.get("id")
    }


def _snapshot_network(project_path: Path | str, scenario_id: str, options: Mapping[str, Any]):
    snap = snapshot(project_path, scenario_id, options=options)
    payload = snap["payload"]
    points = [
        Point(
            item["id"],
            float(item["e"]),
            float(item["n"]),
            fixed=item.get("role") == "fixed",
            sigma_E=item.get("sigma_e"),
            sigma_N=item.get("sigma_n"),
        )
        for item in payload["points"]
    ]
    observations = []
    for row in payload["observations"]:
        if not row.get("enabled", True):
            continue
        observations.append(observation_to_model(row))
    network = Network(points, observations, name=str(payload["network"].get("name") or scenario_id))
    return snap, network


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


# ---------------------------------------------------------------------------
# 图件
# ---------------------------------------------------------------------------
def _figure_network(
    project_path: Path | str,
    scenario_id: str,
    result: Mapping[str, Any],
    options: Mapping[str, Any],
    path: Path,
) -> None:
    from .plot import plot_network

    snap, network = _snapshot_network(project_path, scenario_id, options)
    extent = max(
        max((p.E for p in network.points), default=1.0)
        - min((p.E for p in network.points), default=0.0),
        max((p.N for p in network.points), default=1.0)
        - min((p.N for p in network.points), default=0.0),
        1.0,
    )
    max_major = max(
        (
            row["ellipse"]["a_m"]
            for row in result.get("points") or []
            if not row.get("fixed")
        ),
        default=0.0,
    )
    scale = _nice_scale(max_major, extent)
    fig, ax = plt.subplots(figsize=(8.2, 6.8))
    try:
        plot_network(
            network,
            ax=ax,
            scale=scale,
            confidence=result.get("options", {}).get("confidence", 0.95),
            title=(
                f"{result.get('summary', {}).get('scenario_name', scenario_id)}"
                f" — ellipses ×{scale:g}"
            ),
            legend_outside=True,
        )
        fig.tight_layout()
        fig.savefig(path, dpi=170, bbox_inches="tight", facecolor="white")
    finally:
        plt.close(fig)


def _figure_reliability(result: Mapping[str, Any], path: Path) -> None:
    rows = list(result.get("observations") or [])
    if not rows:
        return
    values = [float(row.get("r_i", 0.0)) for row in rows]
    order = np.argsort(values)
    sorted_values = [values[i] for i in order]
    labels = [str(rows[i].get("label", i + 1)) for i in order]
    fig, ax = plt.subplots(figsize=(8.4, 4.6))
    try:
        x = np.arange(len(sorted_values))
        ax.bar(x, sorted_values, color=COLOR_ACCENT, alpha=0.82, width=0.78)
        ax.axhline(0.1, color="#d97706", lw=1.0, ls="--", label="r=0.1")
        ax.axhline(0.3, color="#16a34a", lw=1.0, ls=":", label="r=0.3")
        ax.set_ylim(0.0, max(1.0, max(sorted_values) * 1.08))
        ax.set_ylabel("redundancy number r_i")
        ax.set_xlabel("observations (sorted by r_i)")
        ax.set_title(f"Reliability: r_i (n={len(rows)}, min={min(values):.4f})")
        if len(rows) <= 12:
            ax.set_xticks(x)
            ax.set_xticklabels(labels, rotation=35, ha="right", fontsize=8)
        else:
            ax.set_xticks([])
        ax.grid(axis="y", alpha=0.18, lw=0.5)
        ax.legend(fontsize=8)
        fig.tight_layout()
        fig.savefig(path, dpi=170, bbox_inches="tight", facecolor="white")
    finally:
        plt.close(fig)


def _figure_comparison(summaries: Sequence[Mapping[str, Any]], path: Path) -> None:
    labels = [str(item.get("scenario_id")) for item in summaries]
    values = [float(item.get("max_mp_mm") or 0.0) for item in summaries]
    fig, ax = plt.subplots(figsize=(7.6, 3.9))
    try:
        colors = [COLOR_ACCENT if i == 0 else "#64748b" for i in range(len(values))]
        bars = ax.bar(labels, values, color=colors, alpha=0.86, width=0.62)
        for bar, value in zip(bars, values):
            ax.text(
                bar.get_x() + bar.get_width() / 2.0,
                bar.get_height() + max(values) * 0.02,
                f"{value:.3f}",
                ha="center",
                va="bottom",
                fontsize=8,
            )
        ax.set_ylabel("max mp / mm")
        ax.set_title("Scenario comparison: maximum point error")
        ax.grid(axis="y", alpha=0.18, lw=0.5)
        fig.tight_layout()
        fig.savefig(path, dpi=170, bbox_inches="tight", facecolor="white")
    finally:
        plt.close(fig)


def _figure_visibility(visibility: Sequence[Mapping[str, Any]], path: Path) -> None:
    rows = list(visibility)
    if not rows:
        return
    labels = [f"{row.get('from')}-{row.get('to')}" for row in rows]
    clearance = [float(row.get("min_clearance_m", 0.0)) for row in rows]
    colors = [COLOR_VISIBLE if row.get("visible") else COLOR_BLOCKED for row in rows]
    fig, ax = plt.subplots(figsize=(8.6, 4.4))
    try:
        x = np.arange(len(rows))
        ax.bar(x, clearance, color=colors, alpha=0.86, width=0.7)
        ax.axhline(0.0, color="#334155", lw=0.8)
        ax.set_xticks(x)
        ax.set_xticklabels(labels, rotation=70, ha="right", fontsize=6.5)
        ax.set_ylabel("min clearance / m")
        ax.set_title("DEM intervisibility: minimum clearance")
        ax.grid(axis="y", alpha=0.18, lw=0.5)
        fig.tight_layout()
        fig.savefig(path, dpi=170, bbox_inches="tight", facecolor="white")
    finally:
        plt.close(fig)


# ---------------------------------------------------------------------------
# Markdown 组装
# ---------------------------------------------------------------------------
def _md_table(headers: Sequence[str], rows: Iterable[Sequence[Any]], align: Optional[Sequence[str]] = None) -> str:
    align = list(align or ["---"] * len(headers))
    lines = ["| " + " | ".join(str(h) for h in headers) + " |"]
    lines.append("|" + "|".join(align) + "|")
    for row in rows:
        cells = [str(value).replace("|", "\\|") for value in row]
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines)


def _comparison_line(base: Mapping[str, Any], candidate: Mapping[str, Any]) -> str:
    parts = []
    base_mp = float(base.get("max_mp_mm") or 0.0)
    cand_mp = float(candidate.get("max_mp_mm") or 0.0)
    parts.append(f"最大 mp {base_mp:.3f} → {cand_mp:.3f} mm（{cand_mp - base_mp:+.3f}）")
    parts.append(
        f"观测数 {int(base.get('n_observations') or 0)} → "
        f"{int(candidate.get('n_observations') or 0)}"
    )
    if base.get("min_r") is not None and candidate.get("min_r") is not None:
        parts.append(
            f"min r_i {float(base['min_r']):.4f} → {float(candidate['min_r']):.4f}"
        )
    if base.get("max_mdb_arcsec") is not None and candidate.get("max_mdb_arcsec") is not None:
        parts.append(
            f"max MDB {float(base['max_mdb_arcsec']):.2f}″ → "
            f"{float(candidate['max_mdb_arcsec']):.2f}″"
        )
    return "；".join(parts)


def _build_suggestions(
    selected: Mapping[str, Any],
    scenario: Mapping[str, Any],
    summaries: Mapping[str, Mapping[str, Any]],
    comparison_rows: Sequence[Mapping[str, Any]],
) -> List[str]:
    summary = selected.get("summary") or {}
    suggestions: List[str] = []
    weak_points = summary.get("weakest_points") or []
    if weak_points:
        suggestions.append(
            "最弱点为 " + "、".join(weak_points) + "，建议优先在该点周围增加距离/角度检核，"
            "或提高其连接边数量。"
        )
    weak_edges = summary.get("weakest_edges") or []
    if weak_edges:
        suggestions.append(
            "最弱边为 " + "、".join(weak_edges) + "，可增加一条跨越该边的距离观测，"
            "或改用更高精度测距设备。"
        )
    min_r = summary.get("min_r")
    if min_r is not None and float(min_r) < 0.1:
        suggestions.append(
            f"最小多余观测分量 r_i={float(min_r):.4f} < 0.1，该观测对粗差较敏感；"
            "建议增加独立检核观测或改善网形，使 r_i 不低于 0.1。"
        )
    max_mdb = summary.get("max_mdb_arcsec")
    if max_mdb is not None and float(max_mdb) > 5.0:
        suggestions.append(
            f"最大角度 MDB={float(max_mdb):.2f}″，内部可靠性偏弱；"
            "可提高角度观测精度（如增加测回数）或增加方向/角度多余观测。"
        )
    max_ext = summary.get("max_external_mm")
    if max_ext is not None and float(max_ext) > 5.0:
        suggestions.append(
            f"外部可靠性最大影响 {float(max_ext):.2f} mm，未检出粗差可能显著影响点位；"
            "建议对该观测实施重复观测或独立检核。"
        )
    optimization = scenario.get("metadata", {}).get("optimization")
    if optimization:
        labels = optimization.get("selected_labels") or []
        suggestions.append(
            "本方案来自观测优化："
            f"准则 {optimization.get('criterion', 'max_mp')}，"
            f"预算 {optimization.get('budget', '—')}，"
            f"选中 {len(labels)} 个候选观测。"
            + ("选中：" + "；".join(labels) if labels else "")
        )
    for row in comparison_rows:
        if row.get("relation") == "parent":
            suggestions.append(
                f"与父方案相比，{row.get('candidate')}：{row.get('text')}。"
            )
    if not suggestions:
        suggestions.append("当前方案精度与可靠性指标均较均衡，未发现需要强制调整的薄弱环节。")
    suggestions.append(
        "以上为设计态先验建议；施工前应结合控制点稳定性、仪器检校与现场通视条件复核。"
    )
    return suggestions


def _collect(
    project_path: Path | str,
    scenario: Optional[str],
    *,
    confidence: float,
    title: Optional[str],
    out_dir: Path,
) -> Dict[str, Any]:
    project = load_project(project_path)
    selected_scenario = _select_scenario(project, scenario)
    options = {"confidence": float(confidence)}
    scenarios = list(project.get("scenarios") or [])

    results: Dict[str, Mapping[str, Any]] = {}
    errors: Dict[str, str] = {}
    for item in scenarios:
        sid = str(item["id"])
        try:
            results[sid] = get_or_compute_result(
                project_path, sid, options=options
            )
        except Exception as exc:  # 报告应容忍单个方案失败
            errors[sid] = str(exc)
    selected_id = str(selected_scenario["id"])
    if selected_id not in results:
        raise RuntimeError(f"方案 {selected_id!r} 计算结果失败：{errors.get(selected_id)}")
    selected = results[selected_id]
    selected_points = _scenario_points(project, selected_scenario)

    # 方案摘要（用于对比图/表）。
    summaries: Dict[str, Dict[str, Any]] = {}
    for item in scenarios:
        sid = str(item["id"])
        if sid in results:
            summaries[sid] = dict(results[sid].get("summary") or {})
        else:
            summaries[sid] = {
                "scenario_id": sid,
                "scenario_name": item.get("name"),
                "error": errors.get(sid, "计算失败"),
            }

    # 父子方案差异。
    comparison_rows: List[Dict[str, Any]] = []
    by_id = {str(item["id"]): item for item in scenarios}
    for item in scenarios:
        parent_id = item.get("parent_id")
        if not parent_id or parent_id not in results or str(item["id"]) not in results:
            continue
        parent = results[str(parent_id)]
        candidate = results[str(item["id"])]
        comparison_rows.append(
            {
                "relation": "parent",
                "parent": str(parent_id),
                "candidate": str(item["id"]),
                "text": _comparison_line(parent["summary"], candidate["summary"]),
            }
        )

    # 图件。
    assets_dir = out_dir / "assets"
    assets_dir.mkdir(parents=True, exist_ok=True)
    figures: List[Tuple[str, Path]] = []
    network_path = assets_dir / "design_network.png"
    _figure_network(project_path, selected_id, selected, options, network_path)
    figures.append(("网图与 95% 误差椭圆", network_path))

    reliability_path = assets_dir / "design_reliability.png"
    try:
        _figure_reliability(selected, reliability_path)
        if reliability_path.exists():
            figures.append(("可靠性 r_i", reliability_path))
    except Exception:
        pass

    comparison_path = assets_dir / "design_scenario_comparison.png"
    try:
        _figure_comparison(list(summaries.values()), comparison_path)
        if comparison_path.exists():
            figures.append(("方案对比（最大点位中误差）", comparison_path))
    except Exception:
        pass

    visibility = list(selected_scenario.get("metadata", {}).get("visibility") or [])
    point_names = {str(item["name"]) for item in selected_points}
    visibility = [
        row
        for row in visibility
        if str(row.get("from")) in point_names and str(row.get("to")) in point_names
    ]
    visibility_path = assets_dir / "design_visibility.png"
    if visibility:
        try:
            _figure_visibility(visibility, visibility_path)
            if visibility_path.exists():
                figures.append(("通视最小净空", visibility_path))
        except Exception:
            pass

    # 观测清单与可靠性行。
    reliability_map = _reliability_by_id(selected)
    observations = []
    for row in selected.get("observations") or []:
        enabled = True
        observations.append(row)
    # 采用快照中的完整观测清单（包含先验信息/观测值）。
    snap, _network = _snapshot_network(project_path, selected_id, options)
    obs_rows = []
    for row in snap["payload"].get("observations") or []:
        if not row.get("enabled", True):
            continue
        obs_rows.append(row)

    # 当前方案观测的可靠性信息按 id 对齐。
    obs_table_rows = []
    for index, row in enumerate(obs_rows, start=1):
        rel = reliability_map.get(str(row.get("id"))) or {}
        obs_table_rows.append(
            [
                index,
                KIND_LABELS.get(_kind(row), _kind(row)),
                _observation_text(row),
                _observation_prior(row),
                _observation_value(row),
                _fmt(rel.get("r_i"), 4),
            ]
        )

    # 点表。
    point_rows = []
    for row in selected.get("points") or []:
        metadata = next(
            (p for p in selected_points if str(p.get("name")) == str(row.get("name"))),
            {},
        )
        point_rows.append(
            [
                row.get("name"),
                ROLE_LABELS.get(str(row.get("role")), str(row.get("role"))),
                _fmt(row.get("E"), 3),
                _fmt(row.get("N"), 3),
                _fmt(metadata.get("elevation_m"), 2),
                _fmt(row.get("sigma_E_mm"), 3),
                _fmt(row.get("sigma_N_mm"), 3),
                _fmt(row.get("mp_mm"), 3),
                _fmt(row.get("ellipse", {}).get("a_m", 0.0) * 1000.0, 3),
                _fmt(row.get("ellipse", {}).get("b_m", 0.0) * 1000.0, 3),
                _fmt(row.get("ellipse", {}).get("azimuth_deg"), 2),
            ]
        )

    # 边表。
    edge_rows = []
    for row in selected.get("edges") or []:
        edge_rows.append(
            [
                row.get("label"),
                _fmt(row.get("length_m"), 3),
                _fmt(row.get("sigma_s_mm"), 3),
                row.get("ratio_text") or "—",
            ]
        )

    # 可靠性表。
    reliability_rows = []
    for row in selected.get("observations") or []:
        mdb_unit = row.get("mdb_unit")
        mdb = row.get("mdb")
        mdb_text = "∞" if mdb is None else (
            f"{float(mdb):.3f} mm" if mdb_unit == "mm" else f"{float(mdb):.3f}″"
        )
        reliability_rows.append(
            [
                row.get("label"),
                KIND_LABELS.get(_kind(row), _kind(row)),
                _fmt(row.get("r_i"), 4),
                mdb_text,
                _fmt(row.get("external_max_mm"), 3),
                row.get("external_point") or "—",
            ]
        )

    # 方案对比表。
    scenario_rows = []
    baseline_mp = float(
        next(
            (
                item.get("max_mp_mm")
                for item in summaries.values()
                if item.get("max_mp_mm") is not None
            ),
            0.0,
        )
    )
    for item in scenarios:
        sid = str(item["id"])
        summary = summaries.get(sid, {})
        scenario_rows.append(
            [
                sid,
                item.get("name"),
                f"v{item.get('version')}",
                item.get("parent_id") or "—",
                summary.get("n_observations", "—"),
                _fmt(summary.get("max_mp_mm"), 3),
                _fmt(summary.get("min_r"), 4),
                _fmt(summary.get("max_mdb_arcsec"), 2),
                _ratio_text(summary.get("worst_relative")),
            ]
        )

    # 通视表。
    visibility_rows = []
    for row in visibility:
        status = "通视" if row.get("visible") else (
            "临界" if row.get("status") == "marginal" else "遮挡"
        )
        visibility_rows.append(
            [
                f"{row.get('from')}–{row.get('to')}",
                status,
                _fmt(row.get("distance_m"), 1),
                _fmt(row.get("min_clearance_m"), 2),
                _fmt(row.get("min_distance_m"), 1),
                str(row.get("samples", "—")),
            ]
        )

    suggestions = _build_suggestions(selected, selected_scenario, summaries, comparison_rows)
    title_text = title or "平面控制网设计报告"
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    return {
        "project": project,
        "project_path": str(project_path),
        "scenario": selected_scenario,
        "scenario_id": selected_id,
        "results": results,
        "selected": selected,
        "summaries": summaries,
        "errors": errors,
        "comparison_rows": comparison_rows,
        "figures": figures,
        "observation_rows": obs_table_rows,
        "point_rows": point_rows,
        "edge_rows": edge_rows,
        "reliability_rows": reliability_rows,
        "scenario_rows": scenario_rows,
        "visibility_rows": visibility_rows,
        "visibility": visibility,
        "suggestions": suggestions,
        "snapshot": snap,
        "title": title_text,
        "generated_at": now,
    }


def render_markdown(data: Mapping[str, Any]) -> str:
    project = data["project"]
    scenario = data["scenario"]
    selected = data["selected"]
    summary = selected.get("summary") or {}
    metadata = project.get("metadata") or {}
    terrain = metadata.get("terrain") or {}
    lines: List[str] = []
    lines.append(f"# {data['title']}")
    lines.append("")
    lines.append(
        f"> 工程：**{project.get('name')}**（`{project.get('id')}`）  "
    )
    lines.append(
        f"> 方案：**{scenario.get('name')}**（`{scenario.get('id')}`，v{scenario.get('version')}）  "
    )
    lines.append(
        f"> 快照：`{data['snapshot'].get('input_hash')}`  "
    )
    lines.append(
        f"> 引擎：ctrlnet {ENGINE_VERSION}；生成时间：{data['generated_at']}  "
    )
    lines.append("> 本报告为设计态/先验精度，不含实测残差与单位权方差估计。")
    lines.append("")

    # 1. 工程概况
    lines.append("## 1. 工程概况")
    lines.append("")
    lines.append(
        f"- 工程名称：{project.get('name')}；CRS：{project.get('crs') or '未指定'}；"
        f"方案版本：v{scenario.get('version')}；父方案：{scenario.get('parent_id') or '无'}。"
    )
    lines.append(
        f"- 方案点数 {summary.get('n_points', 0)}（固定 {summary.get('n_fixed', 0)}），"
        f"观测数 {summary.get('n_observations', 0)}，参数数 {summary.get('n_params', 0)}，"
        f"秩 {summary.get('rank', 0)}，冗余数 {summary.get('redundancy', 0)}，"
        f"条件数 {_fmt(summary.get('condition_number'), 3)}。"
    )
    if terrain:
        dem = terrain.get("dem") or {}
        analysis = terrain.get("analysis") or {}
        lines.append(
            f"- DEM：{dem.get('path', '—')}，{dem.get('crs', '—')}，"
            f"{dem.get('resolution_m') or '—'} m，来源 {dem.get('source') or '—'}，"
            f"垂直基准 {dem.get('vertical_datum') or '—'}。"
        )
        lines.append(
            f"- 通视参数：k={_fmt(analysis.get('k'), 3)}，R={_fmt(analysis.get('R_m'), 0)} m，"
            f"仪器高/目标高 {_fmt(analysis.get('instrument_height_m'), 2)}/"
            f"{_fmt(analysis.get('target_height_m'), 2)} m。"
        )
    lines.append(
        f"- 方案说明：{scenario.get('description') or '—'}"
    )
    lines.append("")

    # 2. 点与观测清单
    lines.append("## 2. 点与观测清单")
    lines.append("")
    lines.append("### 2.1 控制点")
    lines.append("")
    lines.append(
        _md_table(
            ["点", "角色", "E/m", "N/m", "高程/m", "σE/mm", "σN/mm", "mp/mm", "a/mm", "b/mm", "方位/°"],
            data["point_rows"],
            ["---", "---", "---:", "---:", "---:", "---:", "---:", "---:", "---:", "---:", "---:"],
        )
    )
    lines.append("")
    lines.append("### 2.2 观测清单")
    lines.append("")
    lines.append(
        _md_table(
            ["#", "类型", "观测", "先验精度", "观测值", "r_i"],
            data["observation_rows"],
            ["---:", "---", "---", "---", "---:", "---:"],
        )
    )
    lines.append("")

    # 3. 先验精度模型
    lines.append("## 3. 先验精度模型")
    lines.append("")
    lines.append(
        "- 距离：`σ_s = sqrt(a² + (b·10⁻⁶·s)²)`，单位 m；默认 a=2 mm、b=2 ppm。"
    )
    lines.append("- 角度/方向：按角秒输入，内部转为弧度；默认 1.0″。")
    lines.append(
        "- 随机模型：对角权阵，设计态 `σ0=1`；`Cx=(AᵀQl⁻¹A)⁺`，"
        "固定点协方差为 0。"
    )
    lines.append(
        f"- 置信水平：{_fmt(summary.get('confidence'), 3)}；"
        f"95% 二维椭圆系数 `k=sqrt(-2ln0.05)={math.sqrt(5.991464547107979):.6f}`。"
    )
    lines.append("")

    # 4. 基准
    datum = selected.get("datum") or {}
    lines.append("## 4. 基准")
    lines.append("")
    lines.append(f"- 基准类型：{datum.get('kind')}（{datum.get('summary')}）。")
    lines.append(
        "- 固定点：" + ("、".join(datum.get("fixed_points") or []) or "无（自由网/加权基准）") + "。"
    )
    lines.append(
        f"- 参数顺序：{'、'.join(selected.get('network', {}).get('parameter_order') or []) or '—'}。"
    )
    lines.append("")

    # 5. 点位精度
    lines.append("## 5. 点位精度与误差椭圆")
    lines.append("")
    lines.append(
        _md_table(
            ["点", "角色", "E/m", "N/m", "高程/m", "σE/mm", "σN/mm", "mp/mm", "a/mm", "b/mm", "方位/°"],
            data["point_rows"],
            ["---", "---", "---:", "---:", "---:", "---:", "---:", "---:", "---:", "---:", "---:"],
        )
    )
    lines.append("")
    lines.append(
        f"最弱点：{'、'.join(summary.get('weakest_points') or []) or '—'}；"
        f"最大点位中误差 {_fmt(summary.get('max_mp_mm'), 3)} mm。"
    )
    lines.append("")

    # 6. 边相对精度
    lines.append("## 6. 边相对精度")
    lines.append("")
    lines.append(
        _md_table(
            ["边", "边长/m", "σs/mm", "相对精度"],
            data["edge_rows"],
            ["---", "---:", "---:", "---:"],
        )
    )
    lines.append("")
    lines.append(
        f"最弱边：{'、'.join(summary.get('weakest_edges') or []) or '—'}；"
        f"最弱相对精度 {_ratio_text(summary.get('worst_relative'))}。"
    )
    lines.append("")

    # 7. 可靠性
    lines.append("## 7. 可靠性（r_i / MDB / 外部）")
    lines.append("")
    rel = selected.get("reliability") or {}
    lines.append(
        f"- λ0={_fmt(rel.get('lambda0'), 6)}，α={_fmt(rel.get('alpha'), 3)}，"
        f"power={_fmt(rel.get('power'), 2)}；Σr_i={_fmt(rel.get('trace_r'), 6)}，"
        f"期望冗余数={rel.get('expected_redundancy', '—')}。"
    )
    lines.append(
        f"- min r_i={_fmt(rel.get('min_r'), 4)}；max MDB={_fmt(rel.get('max_mdb_arcsec'), 3)}″；"
        f"外部可靠性最大分量={_fmt(rel.get('max_external_mm'), 3)} mm。"
    )
    lines.append("")
    lines.append(
        _md_table(
            ["观测", "类型", "r_i", "MDB", "外部最大影响/mm", "影响点"],
            data["reliability_rows"],
            ["---", "---", "---:", "---:", "---:", "---"],
        )
    )
    lines.append("")

    # 8. 方案对比
    lines.append("## 8. 方案对比")
    lines.append("")
    lines.append(
        _md_table(
            ["方案", "名称", "版本", "父方案", "观测数", "max mp/mm", "min r_i", "max MDB/″", "最弱边相对精度"],
            data["scenario_rows"],
            ["---", "---", "---", "---", "---:", "---:", "---:", "---:", "---:"],
        )
    )
    lines.append("")
    if data["comparison_rows"]:
        for row in data["comparison_rows"]:
            lines.append(f"- {row['parent']} → {row['candidate']}：{row['text']}。")
    else:
        lines.append("- 本工程没有通过 `parent_id` 关联的可比方案对。")
    if data["errors"]:
        lines.append("")
        lines.append("计算失败/跳过的方案：")
        for sid, message in data["errors"].items():
            lines.append(f"- `{sid}`：{message}")
    lines.append("")
    lines.append(
        "> 注意：不同点集/基准的方案之间只做指标展示，不应当直接比较绝对精度；"
        "父子方案对才具有可比性。"
    )
    lines.append("")

    # 9. 优化建议
    lines.append("## 9. 优化建议")
    lines.append("")
    for suggestion in data["suggestions"]:
        lines.append(f"- {suggestion}")
    lines.append("")

    # 10. 通视结果
    lines.append("## 10. 通视结果")
    lines.append("")
    if data["visibility_rows"]:
        visible = sum(1 for row in data["visibility"] if row.get("visible"))
        lines.append(
            f"本方案共 {len(data['visibility'])} 对点，通视 {visible} 对，"
            f"遮挡/临界 {len(data['visibility']) - visible} 对。"
        )
        lines.append("")
        lines.append(
            _md_table(
                ["点对", "状态", "平距/m", "最小净空/m", "最小位置/m", "采样点"],
                data["visibility_rows"],
                ["---", "---", "---:", "---:", "---:", "---:"],
            )
        )
    else:
        lines.append("本方案未配置 DEM 通视元数据（或点集与通视结果不匹配）。")
    lines.append("")

    # 11. 图表
    lines.append("## 11. 图表")
    lines.append("")
    for caption, path in data["figures"]:
        rel_path = os.path.relpath(path, data.get("out_dir") or path.parent.parent)
        rel_path = rel_path.replace(os.sep, "/")
        lines.append(f"![{caption}]({rel_path})")
        lines.append("")
        lines.append(f"*图：{caption}*")
        lines.append("")

    # 12. 复现
    lines.append("## 12. 复现与数据版本")
    lines.append("")
    lines.append("```bash")
    lines.append(
        f".venv/bin/python -m ctrlnet.report --project {data['project_path']} "
        f"--scenario {data['scenario_id']} --out outputs/report"
    )
    lines.append("```")
    lines.append("")
    lines.append(
        f"- 快照哈希：`{data['snapshot'].get('input_hash')}`；"
        f"快照 ID：`{data['snapshot'].get('id')}`。"
    )
    lines.append(
        f"- 引擎版本：ctrlnet {ENGINE_VERSION}；schema {data['snapshot'].get('schema_version')}。"
    )
    lines.append("- 结果按 `input_hash` 缓存在 `data/sample/demo_project.sqlite` 的 `results` 表。")
    lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# HTML
# ---------------------------------------------------------------------------
_CSS = """
:root { --fg:#1f2937; --muted:#64748b; --line:#d8dee9; --bg:#ffffff; --accent:#1d4ed8; }
* { box-sizing: border-box; }
body { margin:0; background:#f1f5f9; color:var(--fg);
  font-family: "Inter","Noto Sans CJK SC","Source Han Sans SC","Microsoft YaHei",system-ui,sans-serif;
  font-size:14px; line-height:1.65; }
main { max-width: 1080px; margin: 24px auto 60px; background:var(--bg);
  padding: 38px 48px 54px; border:1px solid var(--line); border-radius:14px;
  box-shadow: 0 18px 50px rgba(15,23,42,.08); }
h1 { font-size: 26px; margin: 0 0 12px; color:#0f172a; letter-spacing:.2px; }
h2 { font-size: 19px; margin: 34px 0 10px; padding-bottom:6px; border-bottom:2px solid #e2e8f0; color:#0f172a; }
h3 { font-size: 15.5px; margin: 20px 0 8px; color:#334155; }
p { margin: 8px 0; }
blockquote { margin: 14px 0 20px; padding: 12px 16px; background:#f8fafc;
  border-left:4px solid var(--accent); color:#475569; border-radius:0 8px 8px 0; }
blockquote p { margin: 2px 0; }
table { border-collapse: collapse; width: 100%; margin: 12px 0 18px;
  font-size: 12px; font-variant-numeric: tabular-nums; }
th, td { border:1px solid var(--line); padding:5px 7px; text-align:left; }
th { background:#eef2f7; font-weight:650; color:#334155; }
tr:nth-child(even) td { background:#fafbfd; }
code { background:#eef2f7; border-radius:4px; padding:1px 5px;
  font-family: "JetBrains Mono","SFMono-Regular",Consolas,monospace; font-size:12px; }
pre { background:#0f172a; color:#e2e8f0; padding:12px 15px; border-radius:9px; overflow:auto; }
pre code { background:transparent; color:inherit; padding:0; }
img { max-width: 100%; display:block; margin: 10px auto 4px; border:1px solid var(--line);
  border-radius:9px; background:#fff; }
em { color: var(--muted); font-size: 12px; }
ul, ol { margin: 8px 0 12px; padding-left: 26px; }
li { margin: 4px 0; }
hr { border:0; border-top:1px solid var(--line); margin:26px 0; }
.footer { margin-top: 38px; color:#94a3b8; font-size:11.5px; text-align:center; }
@media print { body { background:#fff; } main { box-shadow:none; border:0; margin:0; padding:0; } }
"""


def _inline(text: str) -> str:
    text = html.escape(text)
    text = re.sub(r"`([^`]+)`", r"<code>\1</code>", text)
    text = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", text)
    text = re.sub(
        r"\[([^\]]+)\]\(([^)]+)\)",
        lambda m: f'<a href="{html.escape(m.group(2), quote=True)}">{m.group(1)}</a>',
        text,
    )
    return text


def _image_tag(alt: str, src: str, assets: Mapping[str, bytes], embed: bool) -> str:
    name = Path(src).name
    data = assets.get(name)
    if embed and data is not None:
        encoded = base64.b64encode(data).decode("ascii")
        src = f"data:image/png;base64,{encoded}"
    return f'<img alt="{html.escape(alt)}" src="{html.escape(src, quote=True)}">'


def markdown_to_html(
    markdown: str, assets: Optional[Mapping[str, bytes]] = None, *, embed: bool = True
) -> str:
    """把本模块生成的 Markdown 子集转为 HTML（标题/表格/列表/图片/引用）。"""
    assets = assets or {}
    lines = markdown.splitlines()
    out: List[str] = []
    i = 0
    paragraph: List[str] = []
    in_list = False
    in_code = False
    code_lines: List[str] = []

    def flush_paragraph() -> None:
        nonlocal paragraph
        if paragraph:
            out.append("<p>" + _inline(" ".join(paragraph)) + "</p>")
            paragraph = []

    def close_list() -> None:
        nonlocal in_list
        if in_list:
            out.append("</ul>")
            in_list = False

    while i < len(lines):
        line = lines[i]
        stripped = line.strip()
        if in_code:
            if stripped.startswith("```"):
                out.append("<pre><code>" + html.escape("\n".join(code_lines)) + "</code></pre>")
                code_lines = []
                in_code = False
            else:
                code_lines.append(line)
            i += 1
            continue
        if stripped.startswith("```"):
            flush_paragraph()
            close_list()
            in_code = True
            i += 1
            continue
        if not stripped:
            flush_paragraph()
            close_list()
            i += 1
            continue
        if stripped.startswith("|"):
            flush_paragraph()
            close_list()
            table_lines = []
            while i < len(lines) and lines[i].strip().startswith("|"):
                table_lines.append(lines[i].strip())
                i += 1
            out.append(_render_table(table_lines))
            continue
        if stripped.startswith("#"):
            flush_paragraph()
            close_list()
            level = len(stripped) - len(stripped.lstrip("#"))
            text = stripped[level:].strip()
            out.append(f"<h{level}>{_inline(text)}</h{level}>")
            i += 1
            continue
        if stripped.startswith(">"):
            flush_paragraph()
            close_list()
            quote = []
            while i < len(lines) and lines[i].strip().startswith(">"):
                content = lines[i].strip()[1:].strip()
                if content:
                    quote.append(content)
                i += 1
            out.append("<blockquote><p>" + _inline(" ".join(quote)) + "</p></blockquote>")
            continue
        image_match = re.match(r"!\[([^\]]*)\]\(([^)]+)\)", stripped)
        if image_match:
            flush_paragraph()
            close_list()
            out.append(_image_tag(image_match.group(1), image_match.group(2), assets, embed))
            i += 1
            continue
        if stripped.startswith("- "):
            flush_paragraph()
            if not in_list:
                out.append("<ul>")
                in_list = True
            out.append("<li>" + _inline(stripped[2:]) + "</li>")
            i += 1
            continue
        if stripped == "---":
            flush_paragraph()
            close_list()
            out.append("<hr>")
            i += 1
            continue
        paragraph.append(stripped)
        i += 1

    flush_paragraph()
    close_list()
    if in_code:
        out.append("<pre><code>" + html.escape("\n".join(code_lines)) + "</code></pre>")
    return "\n".join(out)


def _render_table(lines: Sequence[str]) -> str:
    rows = []
    for line in lines:
        text = line.strip().strip("|")
        cells = [cell.strip() for cell in text.split("|")]
        rows.append(cells)
    if len(rows) < 2:
        return ""
    header = rows[0]
    separator = rows[1]
    aligns = []
    for cell in separator:
        cell = cell.strip()
        if cell.endswith(":") and cell.startswith(":"):
            aligns.append("center")
        elif cell.endswith(":"):
            aligns.append("right")
        else:
            aligns.append("left")
    html_rows = ["<table>", "<thead><tr>"]
    for index, cell in enumerate(header):
        align = aligns[index] if index < len(aligns) else "left"
        html_rows.append(f'<th style="text-align:{align}">{_inline(cell)}</th>')
    html_rows.append("</tr></thead><tbody>")
    for row in rows[2:]:
        html_rows.append("<tr>")
        for index, cell in enumerate(row):
            align = aligns[index] if index < len(aligns) else "left"
            html_rows.append(f'<td style="text-align:{align}">{_inline(cell)}</td>')
        html_rows.append("</tr>")
    html_rows.append("</tbody></table>")
    return "\n".join(html_rows)


def render_html(data: Mapping[str, Any], markdown: str) -> str:
    assets: Dict[str, bytes] = {}
    for _caption, path in data["figures"]:
        try:
            assets[path.name] = Path(path).read_bytes()
        except OSError:
            continue
    body = markdown_to_html(markdown, assets, embed=True)
    title = html.escape(str(data["title"]))
    return (
        "<!doctype html>\n<html lang=\"zh-CN\">\n<head>\n<meta charset=\"utf-8\">\n"
        "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">\n"
        f"<title>{title}</title>\n<style>{_CSS}</style>\n</head>\n<body>\n<main>\n"
        f"{body}\n"
        "<div class=\"footer\">CTRLNET 设计报告 · 由 ctrlnet.report 自动生成 · "
        "设计态精度，施工前请复核</div>\n"
        "</main>\n</body>\n</html>\n"
    )


# ---------------------------------------------------------------------------
# 对外接口
# ---------------------------------------------------------------------------
def build_report(
    project_path: Path | str,
    *,
    scenario: Optional[str] = None,
    title: Optional[str] = None,
    confidence: float = 0.95,
    out_dir: Path | str = "outputs/report",
) -> Dict[str, Any]:
    """收集数据、生成图件与 Markdown/HTML，返回报告数据字典。"""
    out = Path(out_dir).expanduser().resolve()
    out.mkdir(parents=True, exist_ok=True)
    data = _collect(
        Path(project_path).expanduser().resolve(),
        scenario,
        confidence=confidence,
        title=title,
        out_dir=out,
    )
    data["out_dir"] = str(out)
    markdown = render_markdown(data)
    html_text = render_html(data, markdown)
    data["markdown"] = markdown
    data["html"] = html_text
    return data


def write_report(
    project_path: Path | str,
    out_dir: Path | str = "outputs/report",
    *,
    scenario: Optional[str] = None,
    title: Optional[str] = None,
    confidence: float = 0.95,
    docx: bool = True,
    basename: str = "design_report",
) -> Dict[str, Any]:
    """写出 ``design_report.md``/``.html``，并尝试用 pandoc 生成 ``.docx``。"""
    data = build_report(
        project_path,
        scenario=scenario,
        title=title,
        confidence=confidence,
        out_dir=out_dir,
    )
    out = Path(data["out_dir"])
    md_path = out / f"{basename}.md"
    html_path = out / f"{basename}.html"
    md_path.write_text(data["markdown"], encoding="utf-8")
    html_path.write_text(data["html"], encoding="utf-8")
    data["markdown_path"] = md_path
    data["html_path"] = html_path
    data["docx_path"] = None
    if docx:
        docx_path = out / f"{basename}.docx"
        try:
            if docx_path.exists():
                docx_path.unlink()
            if shutil.which("pandoc"):
                completed = subprocess.run(
                    [
                        "pandoc",
                        str(md_path),
                        "--from=gfm",
                        "--to=docx",
                        "-o",
                        str(docx_path),
                        f"--resource-path={out}",
                    ],
                    cwd=str(out),
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    timeout=180,
                )
                if completed.returncode == 0 and docx_path.exists() and docx_path.stat().st_size > 0:
                    data["docx_path"] = docx_path
                else:
                    data["docx_error"] = completed.stderr.decode("utf-8", "replace")[-800:]
            else:
                data["docx_error"] = "未找到 pandoc，已跳过 DOCX"
        except Exception as exc:  # pragma: no cover - 环境相关
            data["docx_error"] = str(exc)
    return data


def render_html_report(
    project_path: Path | str,
    *,
    scenario: Optional[str] = None,
    title: Optional[str] = None,
    confidence: float = 0.95,
) -> str:
    """生成自包含 HTML（图片 base64），用于网页“下载报告”。"""
    with tempfile.TemporaryDirectory(prefix="ctrlnet-report-") as tmp:
        data = build_report(
            project_path,
            scenario=scenario,
            title=title,
            confidence=confidence,
            out_dir=tmp,
        )
        return str(data["html"])


def main(argv: Optional[Sequence[str]] = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(
        prog="python -m ctrlnet.report",
        description="生成 CTRLNET 平面控制网设计报告（Markdown/HTML/DOCX）",
    )
    parser.add_argument(
        "--project",
        type=Path,
        default=None,
        help="SQLite 工程路径（默认 data/sample/demo_project.sqlite）",
    )
    parser.add_argument("--out", type=Path, default=Path("outputs/report"), help="输出目录")
    parser.add_argument("--scenario", default=None, help="方案 id 或名称（默认工程默认方案）")
    parser.add_argument("--title", default=None, help="报告标题")
    parser.add_argument("--confidence", type=float, default=0.95, help="椭圆置信水平")
    parser.add_argument("--no-docx", action="store_true", help="不调用 pandoc 生成 DOCX")
    parser.add_argument("--basename", default="design_report", help="输出文件基名")
    args = parser.parse_args(argv)

    project = args.project
    if project is None:
        default = Path(__file__).resolve().parents[2] / "data" / "sample" / "demo_project.sqlite"
        project = default if default.exists() else Path("data/sample/demo_project.sqlite")
    if not Path(project).exists():
        print(f"[error] 工程文件不存在：{project}")
        return 2
    try:
        data = write_report(
            project,
            args.out,
            scenario=args.scenario,
            title=args.title,
            confidence=args.confidence,
            docx=not args.no_docx,
            basename=args.basename,
        )
    except Exception as exc:
        print(f"[error] 报告生成失败：{exc}")
        return 1
    print(f"[ok] 方案：{data['scenario_id']}；快照：{data['snapshot'].get('input_hash')}")
    print(f"[ok] Markdown: {data['markdown_path']}")
    print(f"[ok] HTML:     {data['html_path']}")
    if data.get("docx_path"):
        print(f"[ok] DOCX:     {data['docx_path']}")
    else:
        print(f"[skip] DOCX:  {data.get('docx_error', '未生成')}")
    return 0


__all__ = [
    "build_report",
    "write_report",
    "render_html_report",
    "render_markdown",
    "render_html",
    "markdown_to_html",
    "main",
]
