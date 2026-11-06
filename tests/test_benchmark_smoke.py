"""压测命令冒烟与热点优化的独立稠密公式对照。"""
import importlib.util
import os
from pathlib import Path
import subprocess
import time

import numpy as np
import pytest
from ctrlnet import analyze_precision, analyze_reliability, solve
from ctrlnet.precision import edge_gradient

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('benchmark', ROOT/'scripts/benchmark.py')
benchmark = importlib.util.module_from_spec(spec)
spec.loader.exec_module(benchmark)


def test_benchmark_smoke(tmp_path):
    output = tmp_path/'benchmark.md'
    start = time.perf_counter()
    process = subprocess.run(
        [str(ROOT/'.venv/bin/python'), str(ROOT/'scripts/benchmark.py'), '--sizes', '8',
         '--io-count', '2', '--output', str(output)],
        cwd=ROOT, capture_output=True, text=True, timeout=9,
    )
    assert process.returncode == 0, process.stdout + process.stderr
    assert time.perf_counter()-start < 10
    report = output.read_text()
    for text in ['平差', '精度评定', '可靠性', '优化', 'DEM 通视', '瓦片读取', 'CPU', 'NumPy', 'MiB']:
        assert text in report


@pytest.mark.parametrize('correlated', [False, True])
def test_hotspots_match_dense_reference(correlated):
    from ctrlnet import GnssBaseline2D
    net = benchmark.random_network(8)
    if correlated:
        net.observations.append(GnssBaseline2D('P0', 'P3', sigma_E=0.003, sigma_N=0.004, correlation=0.4))
    result = solve(net)
    precision = analyze_precision(result)
    for edge in precision.edges.values():
        gradient = edge_gradient(result, edge.frm, edge.to)
        assert edge.sigma_s**2 == pytest.approx(float(gradient @ result.Cx @ gradient), rel=1e-12, abs=1e-18)
    rel = analyze_reliability(result)
    inverse = np.linalg.inv(result.Ql)
    qv = result.Ql-result.A @ result.Cx @ result.A.T
    qv = (qv+qv.T)/2
    np.testing.assert_allclose(rel.Qv, qv, atol=1e-18)
    np.testing.assert_allclose(rel.R, qv @ inverse, atol=1e-12)
    k = inverse @ qv @ inverse
    for record in rel.records:
        candidates = []
        for row, mdb in zip(record.rows, record.mdb_components):
            assert mdb == pytest.approx(np.sqrt(rel.lambda0_value/k[row, row]), rel=1e-12)
            # 旧实现逐观测乘法；与预计算整块影响矩阵比较。
            dx = result.Cx @ result.A.T @ inverse[:, row] * mdb
            max_norm = max(np.linalg.norm(dx[list(cols)]) for cols in result.index.point_columns.values())
            candidates.append((max_norm, dx))
        _, expected = max(candidates, key=lambda item: item[0])
        np.testing.assert_allclose(record.external_dx, expected, rtol=1e-11, atol=1e-14)
        for name, cols in result.index.point_columns.items():
            np.testing.assert_allclose(record.external_by_point[name], expected[list(cols)], rtol=1e-11, atol=1e-14)
