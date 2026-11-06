"""共享存储桥接：每个测试独立 SQLite，不触碰示例数据库。"""
import copy
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from ctrlnet import store
from ctrlnet.webmap.thesis_web import ThesisService
from ctrlnet.webmap.project_bridge import create_bridge_router

@pytest.fixture
def bridge(tmp_path):
    service = ThesisService(tmp_path/'engineering.sqlite')
    service.load_example('1')
    app = FastAPI()
    app.include_router(create_bridge_router(service))
    return TestClient(app), service

def test_save_branch_reload_compare(bridge):
    c, service = bridge
    before = copy.deepcopy(service.state)
    a = c.post('/api/engineering/save', json={'name':'共享工程'}).json()
    project = store.load_project(service.repository.path, a['project_id'])
    assert project['name'] == '共享工程'
    service.state['points'][0]['name'] = '101'
    b = c.post('/api/engineering/save', json={'name':'子方案', 'project_id':a['project_id'], 'parent_snapshot':a['snapshot_id']}).json()
    assert b['version'] == 2
    child = store.get_scenario(service.repository.path, b['scenario_id'])
    assert child['parent_id'] == a['scenario_id']
    assert child['metadata']['parent_snapshot'] == a['snapshot_id']
    assert c.post('/api/engineering/open/'+a['scenario_id'],json={}).status_code == 200
    for key in ('points','lines','angles','network'):
        assert service.state[key] == before[key]
    result = c.get('/api/engineering/compare',params={'base':a['scenario_id'],'candidate':b['scenario_id']})
    assert result.status_code == 200, result.text
    assert result.json()['base_hash'] != result.json()['candidate_hash']
    assert c.get('/api/engineering/projects').json()['projects'][0]['status']['version'] == 2

def test_options_and_atomic_failure(bridge):
    c, service = bridge
    a = c.post('/api/engineering/save',json={'name':'参数工程'}).json()
    url = '/api/engineering/calculate/'+a['scenario_id']
    low = c.post(url,json={'datum':'fixed','confidence':.95})
    high = c.post(url,json={'datum':'fixed','confidence':.99})
    assert low.status_code == high.status_code == 200, (low.text, high.text)
    l,h = low.json(),high.json()
    assert l['input_hash'] != h['input_hash']
    assert max(p['ellipse']['a_m'] for p in h['points']) > max(p['ellipse']['a_m'] for p in l['points'])
    for options in ({'datum':'bogus'},{'confidence':2},{'robust':'huber'}):
        assert c.post(url,json=options).status_code == 400
    prior = c.get('/api/engineering/projects').json()
    assert c.post('/api/engineering/save',json={'name':'坏父','project_id':a['project_id'],'parent_snapshot':'missing'}).status_code == 400
    assert c.get('/api/engineering/projects').json() == prior
    # 快照组装失败发生在 SQL 插入之后，事务必须整体回滚。
    service.state['network']['observed_edges'] = []
    service.state['network']['observed_angles'] = []
    service.state['points'][0]['x'] = float('nan')
    assert c.post('/api/engineering/save',json={'name':'失败工程'}).status_code == 400
    assert c.get('/api/engineering/projects').json() == prior

def test_multiple_projects_and_branch_points(bridge):
    c, service = bridge
    a = c.post('/api/engineering/save', json={'name':'甲工程'}).json()
    second = c.post('/api/engineering/save', json={'name':'乙工程'}).json()
    snap = store.snapshot(service.repository.path, second['scenario_id'])
    assert snap['project_id'] == second['project_id']
    with pytest.raises(ValueError):
        store.snapshot(service.repository.path, second['scenario_id'], project_id=a['project_id'])
    point = service.state['points'][0]
    service.move_point(point['id'], point['lon']+.00001, point['lat'])
    b = c.post('/api/engineering/save', json={'name':'改点分支','project_id':a['project_id'],'parent_snapshot':a['snapshot_id']}).json()
    old = store.snapshot(service.repository.path,a['scenario_id'])['payload']['points'][0]
    new = store.snapshot(service.repository.path,b['scenario_id'])['payload']['points'][0]
    assert old['e'] != new['e']
    for datum in ('free','minimal'):
        r = c.post('/api/engineering/calculate/'+b['scenario_id'], json={'datum':datum,'confidence':False})
        assert r.status_code == 200, r.text
        assert r.json()['datum']['kind'] == datum

def test_rank_defect_rejected_and_joint_observations(bridge):
    c, service = bridge
    service.state['network']['observed_edges'] = [service.state['lines'][0]['id']]
    a = c.post('/api/engineering/save',json={'name':'联合网'}).json()
    result = c.post('/api/engineering/calculate/'+a['scenario_id'],json={'datum':'fixed','confidence':.95})
    assert result.status_code == 200, result.text
    assert {o['kind'] for o in result.json()['observations']} == {'angle','distance'}
    service.state['network']['observed_angles'] = []
    b = c.post('/api/engineering/save',json={'name':'欠约束网'}).json()
    r = c.post('/api/engineering/calculate/'+b['scenario_id'],json={'datum':'fixed'})
    assert r.status_code == 400
    assert '平差校验/计算失败' in r.json()['detail']
