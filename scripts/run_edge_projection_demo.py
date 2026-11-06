#!/usr/bin/env python3
"""E9：逐边积分与独立求积对照，输出确定性的中文报告。"""
from pathlib import Path
from math import hypot
from geographiclib.geodesic import Geodesic
from scipy.integrate import quad
from ctrlnet.projection import ProjectionSpec, edge_reduction

ROOT = Path(__file__).resolve().parents[1]


def main():
    rows = ['# E9 逐边尺度积分与方向弧弦改正', '',
            '地面距离按沿测地线线性变化的大地高归算；δ=弦方位角−起点投影切线方位角。', '',
            '| 场景 | 椭球边长 m | 平均投影尺度 | 地面→网格改正 mm | δ ″ | Simpson−quad 弧长 mm | 积分弦−端点弦 mm |',
            '|---|---:|---:|---:|---:|---:|---:|']
    for label, a, b, k0 in [
        ('中央经线',(39,117),(40,117),1),
        ('高斯短边',(40,117.5),(40.01,117.51),1),
        ('高斯长边',(40,117.8),(40.4,118.1),1),
        ('UTM 南半球',(-35,116),(-34.6,116.3),.9996),
    ]:
        spec = ProjectionSpec(central_meridian=117,scale_factor=k0)
        r = edge_reduction(*a,*b,spec=spec,height1_m=200,height2_m=800)
        ell = spec.ellipsoid_model
        line = Geodesic(ell.a,ell.f).InverseLine(*a,*b)
        def scale(s):
            p = line.Position(s)
            return spec.scale(p['lat2'],p['lon2'])
        ref = quad(scale,0,line.s13,epsabs=1e-7)[0]
        e1,n1 = spec.forward(*a)
        e2,n2 = spec.forward(*b)
        chord = hypot(e2-e1,n2-n1)
        rows.append(f'| {label} | {r.ellipsoid_distance_m:.6f} | {r.projection_scale:.12f} | '
                    f'{r.distance_correction(r.ground_distance_m)*1000:.6f} | '
                    f'{r.delta_rad*206264.806247:.9f} | {(r.grid_arc_m-ref)*1000:.9f} | '
                    f'{(r.grid_chord_m-chord)*1000:.9f} |')
    rows += ['', '复合 Simpson 默认 32 个偶数分段；独立对照使用 scipy.integrate.quad。',
             '平差接入、协方差归算及默认兼容性见 tests/test_edge_projection.py。', '']
    output = ROOT/'outputs'/'edge_projection_results.md'
    output.write_text('\n'.join(rows),encoding='utf-8')
    print(output)


if __name__ == '__main__':
    main()
