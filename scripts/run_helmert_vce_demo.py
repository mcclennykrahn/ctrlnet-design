#!/usr/bin/env python3
"""复用 terrain_project 控制点，演示七参数恢复和独立两组 VCE。"""
import json
from itertools import combinations
from pathlib import Path

import numpy as np
from ctrlnet.helmert import estimate, forward, inverse
from ctrlnet.gnss import GnssPoint, GnssBaseline, GnssNetwork, solve_gnss
from ctrlnet.model import Distance
from ctrlnet.vce import estimate_gnss_ground

ROOT = Path(__file__).resolve().parents[1]


def main():
    raw = json.loads((ROOT / 'data/sample/terrain_project.json').read_text())['points']
    src = np.array([[p['E'], p['N'], p['elevation_m']] for p in raw])
    src -= src.mean(axis=0)
    truth = np.array([1.2, -2.3, .7, 2e-6, -3e-6, 1e-6, 2.5])
    dst = forward(src, truth)
    h = estimate(src, dst)
    assert np.max(np.abs(forward(src, h.params) - dst)) < 1e-8
    out = ROOT / 'outputs'
    out.mkdir(exist_ok=True)
    report = ['# Helmert 相似变换恢复', '', '现有 terrain_project 七个控制点，中心化米制坐标；合成无噪声目标。', '', '| 参数 | 真值 | 恢复值 |', '|---|---:|---:|']
    report += [f'| {n} | {t:.12g} | {v:.12g} |' for n, t, v in zip(['TX (m)', 'TY (m)', 'TZ (m)', 'RX (rad)', 'RY (rad)', 'RZ (rad)', 's (ppm)'], truth, h.params)]
    report += ['', f'逆变换最大误差：{np.max(np.abs(inverse(dst, h.params)-src)):.3e} m。']
    (out / 'helmert_results.md').write_text('\n'.join(report) + '\n')
    points = [GnssPoint(p['name'], p['lat'], p['lon'], p['elevation_m'], fixed=(i == 0)) for i, p in enumerate(raw)]
    baselines, distances = [], []
    # 8 次独立重复观测增加两组冗余；实际方差因子 1 与 9。
    for _ in range(8):
        for p, q in combinations(points, 2):
            baselines.append(GnssBaseline(p.name, q.name, q.ecef-p.ecef, np.eye(3)*.002**2))
            distances.append(Distance(p.name, q.name, a=.002, b_ppm=0))
    adjusted = solve_gnss(GnssNetwork(points, baselines, distances), compute_reliability=False)
    rng = np.random.default_rng(20261105)
    l = np.zeros(len(adjusted.A))
    for b in adjusted.design.blocks:
        factor = 1 if b.kind == 'gnss' else 9
        l[b.row_slice] = np.linalg.cholesky(adjusted.Ql[b.row_slice, b.row_slice]) @ rng.normal(size=b.row_count) * np.sqrt(factor)
    v = estimate_gnss_ground(adjusted, l)
    ratio = v.variance_factors['ground']/v.variance_factors['gnss']
    assert abs(ratio / 9 - 1) < .3
    report = ['# 方差分量估计 VCE', '', '现有地形控制点网，固定首点；GNSS 基线与地面水平边各 8 次独立重复。', '固定几何线性化，合成误差，不代表实测成果。', '', '| 组 | 真方差因子 | 估计方差因子 |', '|---|---:|---:|']
    report += [f'| {n} | {t} | {v.variance_factors[n]:.6f} |' for n, t in [('gnss', 1), ('ground', 9)]]
    report += ['', f'方差比：{ratio:.6f}（真值 9）；迭代次数：{len(v.history)}。', f"更新权后 σ₀²：{v.precision_summary['sigma0_sq']:.8f}；冗余数：{v.precision_summary['redundancy']}。", f"参数最大标准差：{max(v.precision_summary['parameter_std']):.6g} m。", '', '| 迭代 | GNSS | 地面边 | 最大相对变化 |', '|---|---:|---:|---:|']
    report += [f"| {r['iteration']} | {r['variance_factors']['gnss']:.8f} | {r['variance_factors']['ground']:.8f} | {r['relative_change']:.3e} |" for r in v.history]
    (out / 'vce_results.md').write_text('\n'.join(report) + '\n')
    print('outputs/helmert_results.md\noutputs/vce_results.md')


if __name__ == '__main__':
    main()
