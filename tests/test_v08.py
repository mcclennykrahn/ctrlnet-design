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
