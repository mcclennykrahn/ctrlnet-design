"""v0.8 参数的 API/计算路径，全部使用临时数据库。"""
import copy
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from ctrlnet.webmap.thesis_web import ThesisService
from ctrlnet.webmap.project_bridge import create_bridge_router

@pytest.fixture
def bridge(tmp_path):
    service = ThesisService(tmp_path/'v08.sqlite')
    service.load_example('1')
    app = FastAPI()
    app.include_router(create_bridge_router(service))
    return TestClient(app), service

GNSS = {'from':'8','to':'1','sigma_E':.005,'sigma_N':.007,'correlation':.3}

def test_gnss_persistence_and_computation(bridge):
    c, _ = bridge
    a = c.post('/api/engineering/save',json={'name':'base'}).json()
    b = c.post('/api/engineering/save',json={'name':'gnss','project_id':a['project_id'],'parent_snapshot':a['snapshot_id'],'gnss':[GNSS]}).json()
    assert b['version'] == 2
    assert c.get('/api/engineering/settings/'+b['scenario_id']).json()['gnss'] == [GNSS]
    low = c.post('/api/engineering/calculate/'+a['scenario_id'],json={}).json()
    high = c.post('/api/engineering/calculate/'+b['scenario_id'],json={}).json()
    assert high['network']['n_observations'] > low['network']['n_observations']
    assert high['summary']['max_mp_mm'] < low['summary']['max_mp_mm']
    assert high['input_hash'] != low['input_hash']
    for key,value in [('sigma_E',.02),('sigma_N',.02),('correlation',-.6)]:
        changed = dict(GNSS, **{key:value})
        d = c.post('/api/engineering/save',json={'name':'changed','gnss':[changed]}).json()
        result = c.post('/api/engineering/calculate/'+d['scenario_id'],json={}).json()
        assert result['summary']['max_mp_mm'] != high['summary']['max_mp_mm'], key
    assert c.post('/api/engineering/open/'+b['scenario_id'],json={}).status_code == 200
    assert c.get('/api/engineering/settings/'+a['scenario_id']).json()['gnss'] == []

@pytest.mark.parametrize('change',[{'to':'missing'},{'to':'8'},{'sigma_E':0},{'sigma_N':-1},{'correlation':1},{'correlation':'NaN'},{'extra':1},{'sigma_E':1e-200,'sigma_N':1e-200},{'sigma_E':1e200,'sigma_N':1e200}])
def test_gnss_invalid_atomic(bridge,change):
    c, _ = bridge
    before = c.get('/api/engineering/projects').json()
    r = c.post('/api/engineering/save',json={'name':'bad','gnss':[dict(GNSS,**change)]})
    assert r.status_code == 400, r.text
    assert c.get('/api/engineering/projects').json() == before

def measured_case(c, service):
    service.state['network']['observed_edges'] = [l['id'] for l in service.state['lines']]
    saved = c.post('/api/engineering/save',json={'name':'实测网','gnss':[GNSS]}).json()
    sid = saved['scenario_id']
    template = c.get('/api/engineering/observations/'+sid).json()
    values = [r['values'] for r in template['observations']]
    # Deterministic small measurement errors and one gross distance error.
    import numpy as np
    rng = np.random.default_rng(30)
    for row, obs in zip(values, template['observations']):
        sigma = 2e-6 if obs['unit'] == 'rad' else .005
        for i in range(len(row)):
            row[i] += float(rng.normal(0, sigma))
    values[0][0] += .3
    return sid, dict(input_hash=template['input_hash'], values=values)

def test_measured_robust_parameters_reach_core(bridge):
    import numpy as np
    from ctrlnet.webmap.estimation import observation_template
    from ctrlnet.robust import robust_estimate
    c, service = bridge
    sid, payload = measured_case(c, service)
    results = {}
    for method, c_value in [('ls',1.345),('huber',.8),('huber',3.),('igg3',1.345)]:
        request = dict(payload, method=method, c=c_value, max_iter=100)
        response = c.post('/api/engineering/estimate/'+sid,json=request)
        assert response.status_code == 200, response.text
        results[method,c_value] = response.json()
    small, large = results['huber',.8], results['huber',3.]
    assert min(small['weights']) < 1
    assert not np.allclose(small['weights'], large['weights'])
    assert not np.allclose(small['residuals'], results['ls',1.345]['residuals'])
    _, dataset = observation_template(service.repository.path, sid)
    for rec, values in zip(dataset.records, payload['values']):
        rec.values = np.array(values)
    direct = robust_estimate(dataset,method='huber',c=.8,max_iter=100)
    assert np.allclose(small['weights'],direct.row_weight_factors)
    assert np.allclose(small['residuals'],direct.residuals)
    assert small['source'] == 'user_entered_values'
    assert small['converged'] == direct.converged
    assert c.get('/api/engineering/observations/'+sid).json()['source'] == 'coordinate_predictions_not_measurements'
    igg = c.post('/api/engineering/estimate/'+sid,json=dict(payload,method='igg3',k0=2.,k1=5.,max_iter=100)).json()
    assert not np.allclose(igg['weights'], results['igg3',1.345]['weights'])

@pytest.mark.parametrize('bad',[{'input_hash':'wrong'},{'values':[]},{'method':'bad'},{'c':0},{'c':'NaN'},{'k0':3,'k1':1},{'max_iter':101},{'max_iter':1.5},{'datum':'free'}])
def test_estimate_invalid(bridge,bad):
    c, service = bridge
    sid, payload = measured_case(c, service)
    assert c.post('/api/engineering/estimate/'+sid,json=dict(payload,**bad)).status_code == 400

def test_estimate_bad_values_and_not_converged(bridge):
    c, service = bridge
    sid, payload = measured_case(c, service)
    for row in ([],[True],[-1],['NaN'],[1,2]):
        bad = copy.deepcopy(payload)
        bad['values'][0] = row
        assert c.post('/api/engineering/estimate/'+sid,json=bad).status_code == 400
    limited = c.post('/api/engineering/estimate/'+sid,json=dict(payload,method='huber',max_iter=1))
    assert limited.status_code == 200, limited.text
    assert limited.json()['status'] == 'not_converged'


def test_robust_requires_coordinate_convergence_and_rejects_overflow(bridge):
    c, service = bridge
    sid, payload = measured_case(c, service)
    for method in ('ls','huber'):
        r = c.post('/api/engineering/estimate/'+sid,json=dict(payload,method=method,c=1e12,max_iter=1))
        assert r.status_code == 200, r.text
        assert r.json()['status'] == 'not_converged'
        assert r.json()['coordinate_max_update_m'] > 1e-7
    huge = copy.deepcopy(payload)
    huge['values'][0][0] = 10**400
    assert c.post('/api/engineering/estimate/'+sid,json=huge).status_code == 400
    assert c.post('/api/engineering/estimate/'+sid,json=dict(payload,c=10**400)).status_code == 400
