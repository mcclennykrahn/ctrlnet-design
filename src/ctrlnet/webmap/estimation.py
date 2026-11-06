"""Stored planar observations -> explicit measured-value robust estimation.

Templates contain coordinate predictions, never synthetic field measurements.
"""
import math
import json
import hashlib
import numpy as np
from ..robust import simulate_observations, estimate_network, robust_estimate
from ..reportgen import _snapshot_network


def observation_template(path, sid):
    snap, network = _snapshot_network(path, sid, {})
    if len(network.unknown_points) > 200 or len(network.observations) > 500:
        raise ValueError('交互实测估计限 200 个待定点 / 500 条观测')
    dataset = simulate_observations(network, noise=False)
    return snap, dataset


def template_payload(snap, dataset):
    return dict(input_hash=snap['input_hash'], source='coordinate_predictions_not_measurements',
                datum='fixed', observations=[dict(index=r.index, label=r.label, kind=r.kind,
                    unit='rad' if r.kind in ('angle', 'direction') else 'm', values=r.values.tolist())
                    for r in dataset.records])


def estimate_payload(path, sid, payload):
    if set(payload) - {'input_hash', 'values', 'method', 'c', 'k0', 'k1', 'max_iter'}:
        raise ValueError('未知实测估计参数')
    snap, dataset = observation_template(path, sid)
    if payload.get('input_hash') != snap['input_hash']:
        raise ValueError('观测模板与方案不匹配，请重新载入模板')
    values = payload.get('values')
    if not isinstance(values, list) or len(values) != len(dataset.records):
        raise ValueError('必须按模板顺序输入全部观测值')
    for row, record in zip(values, dataset.records):
        if not isinstance(row, list) or len(row) != record.n_rows:
            raise ValueError('观测分量数与模板不一致')
        if any(isinstance(v, bool) or not isinstance(v, (float, int)) or not math.isfinite(v) for v in row):
            raise ValueError('观测值必须为有限数值')
        if record.kind == 'distance' and row[0] <= 0:
            raise ValueError('距离观测值须为正')
        if record.kind in ('angle', 'direction') and not 0 <= row[0] < 2*math.pi:
            raise ValueError('角观测须以弧度输入，范围 [0,2π)')
        record.values = np.asarray(row, dtype=float)
    method = payload.get('method', 'huber')
    if method not in ('ls', 'huber', 'igg3'):
        raise ValueError('方法须为 ls/huber/igg3')
    params = {k:float(payload.get(k, default)) for k,default in [('c',1.345),('k0',1.5),('k1',3.)]}
    if not all(math.isfinite(v) for v in params.values()) or params['c'] <= 0 or not 0 < params['k0'] < params['k1']:
        raise ValueError('要求有限 c>0 和 0<k0<k1')
    iterations = payload.get('max_iter', 50)
    if isinstance(iterations, bool) or not isinstance(iterations, int) or not 1 <= iterations <= 100:
        raise ValueError('迭代上限须为 1–100 整数')
    dataset.metadata['source'] = 'user_entered_values'
    result = estimate_network(dataset, max_iter=iterations) if method == 'ls' else robust_estimate(dataset, method=method, max_iter=iterations, **params)
    output = dict(input_hash=snap['input_hash'], source='user_entered_values', datum='fixed', method=method,
        parameters=dict(**params, max_iter=iterations), converged=result.converged, iterations=result.iterations,
        status='converged' if result.converged else 'not_converged', coordinate_max_update_m=result.max_update, rank=result.rank, redundancy=result.redundancy,
        coordinates={k:list(v) for k,v in result.coordinates.items()}, residuals=result.residuals.tolist(),
        row_units=[('rad' if r.kind in ('angle','direction') else 'm') for r in dataset.records for _ in r.values],
        weights=result.row_weight_factors.tolist(), history=result.robust_history,
        observations=[dict(index=r.index,label=r.label,values=r.values.tolist()) for r in dataset.records])

    canonical = dict(input_hash=snap['input_hash'], values=[r.values.tolist() for r in dataset.records], method=method, **output['parameters'])
    output['estimation_hash'] = hashlib.sha256(json.dumps(canonical,sort_keys=True,allow_nan=False).encode()).hexdigest()
    # Fail as a validation error before FastAPI encounters non-JSON numeric output.
    json.dumps(output, allow_nan=False)
    return output
