"""论文编辑器与仪表盘共用的 SQLite 工程桥接，不切换全局地图工程。"""
import copy
import json
import math
import sqlite3
import numpy as np
from fastapi import APIRouter, Body, HTTPException
from .. import store
from ..exceptions import CtrlnetError
from .thesis_web import _grade_payload


def editor_records(state):
    points = [dict(name=str(p['name']), E=p['y'], N=p['x'], fixed=p.get('fixed', False)) for p in state['points']]
    names = {p['id']: str(p['name']) for p in state['points']}
    net = state['network']
    grade = _grade_payload(net['grade'])
    edges = set(net['observed_edges'] + net['added_edges'])
    angles = set(net['observed_angles'] + net['added_angles'])
    obs = [dict(kind='distance', **{'from':names[l['from']], 'to':names[l['to']]},
                a_m=grade['a_mm']/1000, b_ppm=grade['b_ppm'], sigma_model='linear')
           for l in state['lines'] if l['id'] in edges]
    obs += [dict(kind='angle', rear=names[a['backsight']], station=names[a['station']],
                 front=names[a['foresight']], sigma_arcsec=grade['angle_sigma_arcsec'])
            for a in state['angles'] if a['id'] in angles]
    return points, obs


def gnss_records(rows, points):
    """二维工程坐标基线：单位米，协方差必须正定。"""
    if not isinstance(rows, list) or len(rows) > 500:
        raise ValueError('GNSS 基线须为数组且最多 500 条')
    names = {p['name'] for p in points}
    result = []
    for row in rows:
        if not isinstance(row, dict) or set(row) != {'from', 'to', 'sigma_E', 'sigma_N', 'correlation'}:
            raise ValueError('GNSS 字段须为 from/to/sigma_E/sigma_N/correlation')
        a, b = str(row['from']), str(row['to'])
        se, sn, rho = (float(row[k]) for k in ('sigma_E', 'sigma_N', 'correlation'))
        if a not in names or b not in names or a == b:
            raise ValueError('GNSS 端点须引用两个不同的工程点号')
        if not all(math.isfinite(v) for v in (se, sn, rho)) or se <= 0 or sn <= 0 or abs(rho) >= 1:
            raise ValueError('GNSS σ须有限且为正，相关系数须在 (-1,1)')
        covariance = np.array([[se*se, rho*se*sn], [rho*se*sn, sn*sn]])
        if not np.isfinite(covariance).all():
            raise ValueError('GNSS 协方差含非有限值')
        try:
            np.linalg.cholesky(covariance)
            if not np.isfinite(np.linalg.inv(covariance)).all():
                raise ValueError('GNSS 协方差无法稳定求权')
        except np.linalg.LinAlgError as exc:
            raise ValueError('GNSS 协方差须正定') from exc
        result.append(dict(kind='gnss', **{'from':a, 'to':b}, sigma_E=se, sigma_N=sn, correlation=rho))
    return result


def create_bridge_router(service):
    router = APIRouter(prefix='/api/engineering')
    path = service.repository.path

    @router.get('/projects')
    def projects():
        conn = store.connect(path)
        try:
            items = []
            for row in conn.execute('SELECT id,name,metadata_json FROM projects ORDER BY created_at'):
                scenarios = store.list_scenarios(path, row['id'], include_observations=False)
                for s in scenarios:
                    s['snapshots'] = [dict(r) for r in conn.execute('SELECT id,input_hash FROM snapshots WHERE scenario_id=? ORDER BY created_at', (s['id'],))]
                    s['merge_parents'] = s['metadata'].get('merge_parents', [])
                    s['merge_base'] = s['metadata'].get('merge_base')
                    s['merge_bases'] = s['metadata'].get('merge_bases', [s['merge_base']] if s['merge_base'] else [])
                    s['editable'] = 'thesis_state' in s['metadata']
                    from ..lifecycle import describe
                    s['lifecycle'] = describe(s['metadata'])
                    s.pop('metadata', None)
                items.append(dict(id=row['id'], name=row['name'], status=json.loads(row['metadata_json']), scenarios=scenarios))
            return {'projects':items}
        finally:
            conn.close()

    @router.post('/lifecycle/{sid}')
    def lifecycle(sid: str, payload: dict = Body(...)):
        from ..lifecycle import transition
        try:
            return transition(path, sid, payload.get('target'), payload.get('version'), payload.get('note'))
        except store.VersionConflictError as exc:
            raise HTTPException(409, str(exc)) from exc
        except (ValueError, KeyError) as exc:
            raise HTTPException(400, str(exc)) from exc

    @router.post('/rename/{sid}')
    def rename(sid: str, payload: dict = Body(...)):
        from . import scenario_tree
        try:
            return scenario_tree.rename(path, sid, payload.get('name'), payload.get('version'))
        except store.VersionConflictError as exc:
            raise HTTPException(409, str(exc)) from exc
        except (ValueError, KeyError) as exc:
            raise HTTPException(400, str(exc)) from exc

    @router.get('/merge/preview')
    def merge_preview(target: str, source: str):
        from . import scenario_tree
        try:
            return scenario_tree.preview(path, target, source)
        except (ValueError, KeyError) as exc:
            raise HTTPException(400, str(exc)) from exc

    @router.post('/merge')
    def merge(payload: dict = Body(...)):
        from . import scenario_tree
        try:
            return scenario_tree.merge(path, payload)
        except store.VersionConflictError as exc:
            raise HTTPException(409, str(exc)) from exc
        except (ValueError, KeyError, TypeError, sqlite3.IntegrityError, CtrlnetError) as exc:
            raise HTTPException(400, str(exc)) from exc

    @router.post('/save')
    def save(payload: dict = Body(...)):
        try:
            name = str(payload.get('name', '')).strip()
            if not name or len(name) > 120:
                raise ValueError('工程/方案名称须为 1–120 字')
            with service._lock:
                state = copy.deepcopy(service.state)
            points, observations = editor_records(state)
            observations += gnss_records(payload.get('gnss', []), points)
            return store.save_editor_version(path, dict(id=payload.get('project_id'), name=name, points=points),
                dict(name=name, observations=observations, metadata={'thesis_state':state}),
                parent_snapshot=payload.get('parent_snapshot'))
        except (ValueError, KeyError, TypeError, OverflowError, sqlite3.IntegrityError, CtrlnetError) as exc:
            raise HTTPException(400, str(exc)) from exc

    @router.get('/settings/{sid}')
    def settings(sid: str):
        try:
            scenario = store.get_scenario(path, sid)
            return {'gnss': [{k:o[k] for k in ('from', 'to', 'sigma_E', 'sigma_N', 'correlation')}
                             for o in scenario['observations'] if o['kind'] == 'gnss']}
        except (KeyError, ValueError) as exc:
            raise HTTPException(400, str(exc)) from exc

    @router.post('/open/{sid}')
    def open_version(sid: str):
        try:
            scenario = store.get_scenario(path, sid)
            state = copy.deepcopy(scenario['metadata']['thesis_state'])
            # 保存的是已校验的完整编辑状态，保留论文算例的长度与局部坐标语义。
            from .thesis_web import _public_state
            result = _public_state(state)
            with service._lock:
                service.replace_draft(state)
            return result
        except KeyError as exc:
            raise HTTPException(400, '此方案没有论文编辑拓扑') from exc

    @router.post('/calculate/{sid}')
    def calculate(sid: str, options: dict = Body(...)):
        try:
            if set(options) - {'datum', 'confidence'}:
                raise ValueError('仅支持 datum / confidence；GNSS基线与稳健估计编辑尚未接线')
            if options.get('datum', 'fixed') not in ('fixed', 'free', 'minimal'):
                raise ValueError('基准仅支持 fixed/free/minimal')
            confidence = options.get('confidence', .95)
            if confidence is not False and (isinstance(confidence, bool) or not math.isfinite(float(confidence)) or not 0 < float(confidence) < 1):
                raise ValueError('置信度必须在 0 与 1 之间，或 false（标准椭圆）')
            return store.get_or_compute_result(path, sid, options=options)
        except (ValueError, KeyError, TypeError, OverflowError, RuntimeError, CtrlnetError) as exc:
            raise HTTPException(400, f'平差校验/计算失败：{exc}') from exc

    @router.get('/observations/{sid}')
    def observations(sid: str):
        try:
            from .estimation import observation_template, template_payload
            return template_payload(*observation_template(path, sid))
        except (ValueError, KeyError, TypeError, OverflowError, RuntimeError, CtrlnetError) as exc:
            raise HTTPException(400, f'观测模板失败：{exc}') from exc

    @router.post('/estimate/{sid}')
    def estimate(sid: str, payload: dict = Body(...)):
        try:
            from .estimation import estimate_payload
            return estimate_payload(path, sid, payload)
        except (ValueError, KeyError, TypeError, OverflowError, RuntimeError, CtrlnetError) as exc:
            raise HTTPException(400, f'实测估计失败：{exc}') from exc

    @router.get('/compare')
    def compare(base: str, candidate: str):
        try:
            from ..compare import compare
            from ..reportgen import _snapshot_network
            bs, bn = _snapshot_network(path, base, {})
            cs, cn = _snapshot_network(path, candidate, {})
            result = compare(bn, cn, base_name=base, candidate_name=candidate)
            return dict(base_hash=bs['input_hash'], candidate_hash=cs['input_hash'], summary=result.to_text())
        except (ValueError, KeyError, RuntimeError, CtrlnetError) as exc:
            raise HTTPException(400, str(exc)) from exc
    return router
