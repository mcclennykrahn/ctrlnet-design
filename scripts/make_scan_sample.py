#!/usr/bin/env python3
"""生成 B3 网页“导入影像”演示用的示例扫描地形图。

输出
----
* ``data/sample/scan_sample.png``：以已知六参数仿射生成的扫描图（含等高线、
  晕渲、图廓与格网），用于演示影像配准；
* ``data/sample/registration_demo.json``：4 对带少量量测噪声的控制点、
  2 个独立检查点、扫描图已知仿射与像素约定。

运行::

    .venv/bin/python scripts/make_scan_sample.py
"""

from __future__ import annotations

import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
os.environ.setdefault(
    "MPLCONFIGDIR", str(Path(os.environ.get("TMPDIR", "/tmp")) / "ctrlnet-mplconfig")
)
Path(os.environ["MPLCONFIGDIR"]).mkdir(parents=True, exist_ok=True)

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from matplotlib import font_manager

from ctrlnet import DEM
from ctrlnet.terrain import AffineTransform, hillshade

SAMPLE = ROOT / "data" / "sample"
DEM_PATH = SAMPLE / "dem_sample.tif"
PROJECT_PATH = SAMPLE / "terrain_project.json"
OUTPUT_PNG = SAMPLE / "scan_sample.png"
OUTPUT_JSON = SAMPLE / "registration_demo.json"

WIDTH = 780
HEIGHT = 820
# 已知“扫描仿射”：E=a·col+b·row+c, N=d·col+e·row+f（像素角点）。
SOURCE_AFFINE = (10.0, 1.0, 414400.0, -0.8, -12.0, 4427200.0)
GCP_NAMES = ("P1", "P2", "P6", "P7")
CHECK_NAMES = ("P3", "P4")
# 模拟同名点点位量测误差（像素），单位为 pixel；用于得到非零 RMS。
PIXEL_NOISE = {
    "P1": (0.42, -0.31),
    "P2": (-0.35, 0.28),
    "P6": (0.30, 0.38),
    "P7": (-0.27, -0.34),
    "P3": (0.24, -0.19),
    "P4": (-0.18, 0.22),
}

_available_fonts = {f.name for f in font_manager.fontManager.ttflist}
_CJK_CANDIDATES = ["Noto Sans CJK SC", "Noto Sans CJK JP", "WenQuanYi Zen Hei", "Droid Sans Fallback"]
_CJK_FONT = next((name for name in _CJK_CANDIDATES if name in _available_fonts), None)
if _CJK_FONT:
    plt.rcParams["font.family"] = "sans-serif"
    plt.rcParams["font.sans-serif"] = [_CJK_FONT, "DejaVu Sans"]
plt.rcParams["axes.unicode_minus"] = False


def T(zh: str, en: str) -> str:
    return zh if _CJK_FONT else en


def sample_scan_grid(dem: DEM, transform: AffineTransform) -> np.ndarray:
    """把 DEM 采样到扫描图像素网格（像素中心）。"""
    cols, rows = np.meshgrid(np.arange(WIDTH) + 0.5, np.arange(HEIGHT) + 0.5)
    E = transform.a * cols + transform.b * rows + transform.c
    N = transform.d * cols + transform.e * rows + transform.f
    return np.asarray(dem.elevation(E, N), dtype=float)


def hypsometric_rgb(z: np.ndarray, shade: np.ndarray) -> np.ndarray:
    valid = np.isfinite(z)
    zmin = float(np.nanmin(z[valid]))
    zmax = float(np.nanmax(z[valid]))
    stops = np.array([0.0, 0.18, 0.38, 0.58, 0.78, 1.0])
    colors = np.array(
        [
            [0.42, 0.62, 0.34],
            [0.60, 0.72, 0.42],
            [0.82, 0.80, 0.52],
            [0.78, 0.63, 0.40],
            [0.64, 0.48, 0.34],
            [0.86, 0.85, 0.82],
        ]
    )
    t = np.clip((z - zmin) / max(zmax - zmin, 1e-9), 0.0, 1.0)
    rgb = np.empty(z.shape + (3,), dtype=float)
    for channel in range(3):
        rgb[..., channel] = np.interp(t, stops, colors[:, channel])
    shade_strength = 0.42
    rgb *= (1.0 - shade_strength + shade_strength * shade[..., None])
    # 轻微纸张色调与颗粒，模拟扫描件。
    rgb = 0.86 * rgb + 0.14 * np.array([0.94, 0.89, 0.77])
    rng = np.random.default_rng(20261104)
    rgb += rng.normal(0.0, 0.012, size=rgb.shape)
    rgb[~valid] = np.array([0.94, 0.89, 0.77])
    return np.clip(rgb, 0.0, 1.0)


def make_scan(dem: DEM, transform: AffineTransform) -> None:
    z = sample_scan_grid(dem, transform)
    filled = np.where(np.isfinite(z), z, float(np.nanmedian(z)))
    shade = hillshade(filled, azimuth=315.0, altitude=45.0, resolution=(10.0, 12.0))
    shade = np.where(np.isfinite(z), shade, 0.55)
    rgb = hypsometric_rgb(z, shade)

    dpi = 100
    fig = plt.figure(figsize=(WIDTH / dpi, HEIGHT / dpi), dpi=dpi, facecolor="#f4ecd7")
    ax = fig.add_axes([0.0, 0.0, 1.0, 1.0])
    ax.set_xlim(0, WIDTH)
    ax.set_ylim(HEIGHT, 0)
    ax.imshow(rgb, extent=(0, WIDTH, HEIGHT, 0), origin="upper", interpolation="bilinear")

    levels = np.arange(
        np.floor(float(np.nanmin(z)) / 50.0) * 50.0,
        float(np.nanmax(z)) + 50.0,
        50.0,
    )
    masked = np.ma.masked_invalid(z)
    ax.contour(np.arange(WIDTH), np.arange(HEIGHT), masked, levels=levels,
               colors="#5f4a2a", linewidths=0.42, alpha=0.72)
    ax.contour(np.arange(WIDTH), np.arange(HEIGHT), masked, levels=levels[::5],
               colors="#3f321e", linewidths=0.85, alpha=0.85)

    # 10×10 图廓格网与行列注记。
    for x in range(0, WIDTH + 1, 100):
        ax.axvline(x, color="#3b3222", lw=0.25, alpha=0.32)
        ax.text(x + 3, 16, f"{x}", fontsize=5.2, color="#3b3222", alpha=0.75)
    for y in range(0, HEIGHT + 1, 100):
        ax.axhline(y, color="#3b3222", lw=0.25, alpha=0.32)
        ax.text(4, y + 12, f"{y}", fontsize=5.2, color="#3b3222", alpha=0.75)

    ax.add_patch(
        plt.Rectangle((5, 5), WIDTH - 10, HEIGHT - 10, fill=False, ec="#4b3b24", lw=1.2)
    )
    ax.add_patch(
        plt.Rectangle((13, 13), WIDTH - 26, HEIGHT - 26, fill=False, ec="#4b3b24", lw=0.45)
    )
    ax.text(
        28,
        44,
        T("示例扫描地形图 · 北京西山", "Sample scanned topo map - Beijing Xishan"),
        fontsize=13,
        color="#332714",
        fontweight="bold",
        bbox=dict(boxstyle="round,pad=0.25", fc="#f4ecd7", ec="none", alpha=0.82),
    )
    ax.text(
        28,
        64,
        T(
            "等高距 50 m · 扫描件仅用于配准演示 · 无地理参考",
            "Contour interval 50 m - registration demo only - no georeference",
        ),
        fontsize=7.0,
        color="#4b3b24",
        bbox=dict(boxstyle="round,pad=0.18", fc="#f4ecd7", ec="none", alpha=0.7),
    )
    # 指北针。
    ax.annotate(
        "N",
        xy=(WIDTH - 40, 70),
        xytext=(WIDTH - 40, 112),
        ha="center",
        va="center",
        fontsize=10,
        color="#332714",
        arrowprops=dict(arrowstyle="-|>", color="#332714", lw=1.2),
    )
    # 比例尺（约 1000 m）。
    x0, y0 = WIDTH - 240, HEIGHT - 45
    ax.plot([x0, x0 + 100, x0 + 100, x0 + 200], [y0, y0, y0 - 5, y0 - 5],
            color="#332714", lw=1.0)
    ax.text(x0, y0 - 14, "0", fontsize=6, ha="center", color="#332714")
    ax.text(x0 + 100, y0 - 14, "≈1 km", fontsize=6, ha="center", color="#332714")
    ax.text(x0 + 200, y0 - 14, "2 km", fontsize=6, ha="center", color="#332714")
    ax.axis("off")

    fig.savefig(OUTPUT_PNG, dpi=dpi, facecolor=fig.get_facecolor())
    plt.close(fig)


def build_demo_json(project: dict) -> dict:
    by_name = {p["name"]: p for p in project["points"]}
    transform = AffineTransform(*SOURCE_AFFINE)

    def make_pair(name: str) -> dict:
        p = by_name[name]
        col, row = transform.rowcol(p["E"], p["N"])
        dc, dr = PIXEL_NOISE[name]
        return {
            "label": name,
            "col": round(float(col + dc), 3),
            "row": round(float(row + dr), 3),
            "E": float(p["E"]),
            "N": float(p["N"]),
            "nominal_col": round(float(col), 3),
            "nominal_row": round(float(row), 3),
            "pixel_offset": [dc, dr],
        }

    return {
        "schema": "ctrlnet.registration_demo/1",
        "generated_by": "scripts/make_scan_sample.py",
        "description": "示例扫描地形图 + 4 对控制点 + 2 个独立检查点",
        "image": "scan_sample.png",
        "image_width": WIDTH,
        "image_height": HEIGHT,
        "pixel_convention": "origin at upper-left pixel corner, col right, row down",
        "source_affine": list(SOURCE_AFFINE),
        "source_affine_convention": "E=a*col+b*row+c, N=d*col+e*row+f",
        "source_affine_note": "生成扫描图时使用的已知仿射；配准时只使用 control_points",
        "control_points": [make_pair(name) for name in GCP_NAMES],
        "check_points": [make_pair(name) for name in CHECK_NAMES],
        "opacity": 0.48,
        "crs": project["dem"]["crs"],
    }


def main() -> None:
    dem = DEM.from_geotiff(DEM_PATH)
    project = json.loads(PROJECT_PATH.read_text(encoding="utf-8"))
    transform = AffineTransform(*SOURCE_AFFINE)
    make_scan(dem, transform)
    payload = build_demo_json(project)
    OUTPUT_JSON.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    size_kb = OUTPUT_PNG.stat().st_size / 1024.0
    print(f"wrote {OUTPUT_PNG.relative_to(ROOT)} ({WIDTH}x{HEIGHT}, {size_kb:.1f} KiB)")
    print(f"wrote {OUTPUT_JSON.relative_to(ROOT)}")
    print("GCPs:", ", ".join(p["label"] for p in payload["control_points"]))


if __name__ == "__main__":
    main()
