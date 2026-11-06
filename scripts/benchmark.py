#!/usr/bin/env python3
"""可复现的 P5 压测；默认单线程 BLAS，内存为各阶段 tracemalloc 峰值。"""
from __future__ import annotations

import argparse
import gc
import io
import os
import platform
from pathlib import Path
import tempfile
import time
import tracemalloc
from datetime import datetime, timezone

# 在导入 NumPy 前限制线程，避免小矩阵线程调度主导耗时。
for key in ('OPENBLAS_NUM_THREADS', 'OMP_NUM_THREADS', 'MKL_NUM_THREADS'):
    os.environ[key] = '1'

import numpy as np
from PIL import Image
from ctrlnet import Distance, Network, Point, solve, analyze_precision, analyze_reliability, greedy_optimize
from ctrlnet.terrain import DEM
from ctrlnet.tiles import MBTiles

ROOT = Path(__file__).resolve().parents[1]


def random_network(size: int, seed: int = 20261105) -> Network:
    """三固定锚点 + 每个随机待定点到三锚点的距离，观测数 3(n-3)。"""
    if size < 4:
        raise ValueError('至少需要 4 点')
    rng = np.random.default_rng(seed)
    xy = np.vstack(([[0, 0], [1000, 0], [0, 1000]], rng.uniform(100, 900, (size-3, 2))))
    points = [Point(f'P{i}', *p, fixed=i < 3) for i, p in enumerate(xy)]
    obs = [Distance(f'P{a}', f'P{i}') for i in range(3, size) for a in range(3)]
    return Network(points, obs, name=f'random-{size}')


def measure(fn):
    gc.collect()
    tracemalloc.start()
    start = time.perf_counter()
    try:
        value = fn()
        elapsed = time.perf_counter()-start
        peak = tracemalloc.get_traced_memory()[1] / 1024**2
    finally:
        tracemalloc.stop()
    return value, elapsed, peak


def run_benchmark(sizes=(50, 200, 1000), output=ROOT/'outputs/benchmark_results.md', *, io_count=100):
    rows = []
    def record(n, stage, fn, detail):
        value, elapsed, peak = measure(fn)
        rows.append((n, stage, elapsed, peak, detail))
        print(f'{n} {stage}: {elapsed:.4f}s / {peak:.2f} MiB', flush=True)
        return value

    # 输入构造不计入阶段计时；所有阶段仅测一次，保留真实 API 返回值。
    with tempfile.TemporaryDirectory(dir=ROOT/'.tmp', prefix='benchmark-') as folder:
        tile_path = Path(folder)/'sample.mbtiles'
        buf = io.BytesIO()
        Image.new('RGB', (256, 256), (80, 120, 160)).save(buf, format='PNG')
        png = buf.getvalue()
        with MBTiles(tile_path) as db:
            db.put_tile(0, 0, 0, png)
        dem = DEM(np.random.default_rng(42).uniform(0, 10, (128, 128)), (10, 0, 0, 0, -10, 1280))
        for n in sizes:
            net = random_network(n)
            result = record(n, '平差', lambda: solve(net), f'{len(net.observations)} 观测 / {2*(n-3)} 参数')
            precision = record(n, '精度评定', lambda: analyze_precision(result), '全部点与全部距离边')
            assert np.isfinite(precision.max_mp)
            del precision
            rel = record(n, '可靠性', lambda: analyze_reliability(result), '完整 Qv/R、MDB 与逐点外部影响')
            assert abs(rel.trace_r-result.redundancy) < 1e-6
            del rel, result
            if n <= 50:
                candidates = [Distance('P3', f'P{i}') for i in range(4, min(n, 8))]
                opt = record(n, '优化（小规模）', lambda: greedy_optimize(net, candidates, budget=1, max_steps=1), f'{len(candidates)} 候选，greedy，最多 1 步')
                assert opt.final_metrics.objective <= opt.initial_metrics.objective + 1e-12
                del opt
            else:
                rows.append((n, '优化（小规模）', None, None, '跳过：仅 ≤50 点运行'))
            def visibility():
                for _ in range(io_count):
                    dem.intervisibility((105, 105), (1105, 1105), inst_h=1.5, target_h=1.5)
            record(n, 'DEM 通视', visibility, f'128×128 合成 DEM，{io_count} 条相同剖面')
            def read_tiles():
                with MBTiles(tile_path, readonly=True) as db:
                    for _ in range(io_count):
                        assert db.get_tile(0, 0, 0) == png
            record(n, '瓦片读取', read_tiles, f'{io_count} 次 SQLite PNG BLOB 读取（含打开，不含解码）')
            del net
    cpu = platform.processor()
    cpuinfo = Path('/proc/cpuinfo')
    if cpuinfo.exists():
        cpu = next((line.split(':', 1)[1].strip() for line in cpuinfo.read_text().splitlines() if line.startswith('model name')), cpu)
    meminfo = Path('/proc/meminfo')
    memory = meminfo.read_text().splitlines()[0] if meminfo.exists() else 'unknown'
    lines = ['# P5 性能压测', '', f'时间：{datetime.now(timezone.utc).isoformat()}', '',
             f'- 系统：{platform.platform()}', f'- CPU：{cpu}；逻辑核：{os.cpu_count()}', f'- 内存：{memory}',
             f'- Python：{platform.python_version()}；NumPy：{np.__version__}；BLAS 线程：1',
             '- 随机种子：20261105；三固定锚点随机距离网；50/200/1000 为总点数。',
             '- 耗时为单次墙钟时间，包含 tracemalloc 开销；峰值为该阶段新分配的可追踪内存，非进程 RSS，既有输入不计入。',
             '- DEM/瓦片是独立固定工作量；瓦片重复读可能命中系统缓存。输入生成不计时，无网络访问。',
             '- 优化：可靠性参数影响矩阵移至循环外；边精度仅访问非零梯度对应的协方差子块。仍使用稠密 SVD 与完整可靠性结果，大网内存按平方增长。', '',
             '| 点数 | 阶段 | 耗时 / s | 峰值 / MiB | 工作量 |', '|---:|---|---:|---:|---|']
    for n, stage, elapsed, peak, detail in rows:
        values = ('—', '—') if elapsed is None else (f'{elapsed:.6f}', f'{peak:.3f}')
        lines.append(f'| {n} | {stage} | {values[0]} | {values[1]} | {detail} |')
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text('\n'.join(lines)+'\n', encoding='utf-8')
    return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--sizes', nargs='+', type=int, default=[50, 200, 1000])
    parser.add_argument('--output', type=Path, default=ROOT/'outputs/benchmark_results.md')
    parser.add_argument('--io-count', type=int, default=100)
    args = parser.parse_args()
    if min(args.sizes) < 4 or args.io_count < 1:
        parser.error('点数须 ≥4，io-count 须 ≥1')
    (ROOT/'.tmp').mkdir(exist_ok=True)
    run_benchmark(args.sizes, args.output, io_count=args.io_count)


if __name__ == '__main__':
    main()
