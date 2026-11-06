"""Scenario rename and conservative merge: persistence, conflicts, atomicity."""
import copy
import pytest
from test_v08 import bridge, GNSS
from ctrlnet import store


def save(c, name, parent=None, gnss=None):
    data = dict(name=name, gnss=gnss or [])
    if parent:
        data.update(project_id=parent['project_id'], parent_snapshot=parent['snapshot_id'])
    r = c.post('/api/engineering/save', json=data)
    assert r.status_code == 200, r.text
    return r.json()


def preview(c, a, b):
    r = c.get('/api/engineering/merge/preview', params=dict(target=a['scenario_id'], source=b['scenario_id']))
    assert r.status_code == 200, r.text
    return r.json()


def test_merge_independent_units_reopen_and_lineage(bridge):
    c, service = bridge
    root = save(c, 'base')
    service.state['points'][0]['x'] += 1
    left = save(c, 'geometry', root)
    geometry = copy.deepcopy(service.state)
    c.post('/api/engineering/open/'+root['scenario_id'], json={})
    right = save(c, 'gnss', root, [GNSS])
    plan = preview(c, left, right)
    assert plan['conflicts'] == []
    assert plan['base'] == root['scenario_id']
    before = store.get_scenario(service.repository.path, left['scenario_id'])
    r = c.post('/api/engineering/merge', json=dict(plan, name='merged', resolutions={}))
    assert r.status_code == 200, r.text
    merged = r.json()
    s = store.get_scenario(service.repository.path, merged['scenario_id'])
    assert s['metadata']['merge_parents'] == [left['scenario_id'], right['scenario_id']]
    assert s['metadata']['thesis_state'] == geometry
    assert store.get_scenario(service.repository.path, left['scenario_id']) == before
    assert c.get('/api/engineering/settings/'+s['id']).json()['gnss'] == [GNSS]
    assert c.post('/api/engineering/open/'+s['id'], json={}).status_code == 200
    assert service.state['points'] == geometry['points']
    # Rename persists without rewriting old snapshot content.
    snapshot = store.get_snapshot(service.repository.path, merged['snapshot_id'])
    r = c.post('/api/engineering/rename/'+s['id'], json=dict(name=' renamed ',version=s['version']))
    assert r.status_code == 200
    assert store.get_scenario(service.repository.path,s['id'])['name'] == 'renamed'
    assert store.get_snapshot(service.repository.path,merged['snapshot_id']) == snapshot
    assert c.post('/api/engineering/rename/'+s['id'],json=dict(name='stale',version=s['version'])).status_code == 409
    rows = c.get('/api/engineering/projects').json()['projects'][0]['scenarios']
    assert next(x for x in rows if x['id']==s['id'])['merge_parents'] == [left['scenario_id'],right['scenario_id']]
    # A descendant of a merge can merge again against the earlier source.
    child = save(c, 'child', merged, [GNSS])
    assert preview(c, child, right)['base'] == right['scenario_id']


def test_conflicts_stale_and_invalid_are_atomic(bridge):
    c, service = bridge
    root = save(c,'base')
    a = save(c,'a',root,[GNSS])
    changed = dict(GNSS, sigma_E=.02)
    b = save(c,'b',root,[changed])
    plan = preview(c,a,b)
    assert plan['conflicts'] == ['gnss']
    before = c.get('/api/engineering/projects').json()
    for resolutions in ({},{'gnss':''},{'gnss':'invalid'},{'gnss':'source','topology':'target'}):
        r = c.post('/api/engineering/merge',json=dict(plan,name='bad',resolutions=resolutions))
        assert r.status_code == 400, r.text
        assert c.get('/api/engineering/projects').json() == before
    good = c.post('/api/engineering/merge',json=dict(plan,name='good',resolutions={'gnss':'source'}))
    assert good.status_code == 200, good.text
    assert c.get('/api/engineering/settings/'+good.json()['scenario_id']).json()['gnss'] == [changed]
    c.post('/api/engineering/rename/'+a['scenario_id'],json=dict(name='a2',version=a['version']))
    assert c.post('/api/engineering/merge',json=dict(plan,name='stale',resolutions={'gnss':'target'})).status_code == 409
    other = save(c,'other')
    for target,source in ((a,a),(a,other)):
        assert c.get('/api/engineering/merge/preview',params=dict(target=target['scenario_id'],source=source['scenario_id'])).status_code == 400
    for name in ('',' '*4,'a'*121,None,42):
        assert c.post('/api/engineering/rename/'+a['scenario_id'],json=dict(name=name,version=3)).status_code == 400


def test_incompatible_units_roll_back(bridge):
    c, service = bridge
    root = save(c,'base')
    # A valid saved topology whose names differ from the GNSS branch.
    service.state['points'][0]['name'] = 900
    a = save(c,'new names',root)
    c.post('/api/engineering/open/'+root['scenario_id'],json={})
    b = save(c,'gnss',root,[GNSS])
    plan = preview(c,a,b)
    before = c.get('/api/engineering/projects').json()
    r = c.post('/api/engineering/merge',json=dict(plan,name='incompatible',resolutions={}))
    assert r.status_code == 400, r.text
    assert c.get('/api/engineering/projects').json() == before


def test_noop_ui_save_and_topology_conflict(bridge):
    c, service = bridge
    root = save(c,'base')
    # Browser save syncs network, updating timestamps and derived geometry.
    service.configure_network({})
    service.state['updated_at'] = '2001-01-01T00:00:00+00:00'
    a = save(c,'a',root,[GNSS])
    c.post('/api/engineering/open/'+root['scenario_id'],json={})
    service.configure_network({})
    service.state['updated_at'] = '2002-01-01T00:00:00+00:00'
    b = save(c,'b',root)
    assert preview(c,a,b)['conflicts'] == []
    service.state['points'][1]['x'] += 2
    left = save(c,'left',root)
    c.post('/api/engineering/open/'+root['scenario_id'],json={})
    service.state['points'][1]['x'] -= 3
    right = save(c,'right',root)
    plan = preview(c,left,right)
    assert plan['conflicts'] == ['topology']
    for choice, expected in [('target',left),('source',right)]:
        r = c.post('/api/engineering/merge',json=dict(plan,name=choice,resolutions={'topology':choice}))
        assert r.status_code == 200, r.text
        actual = store.get_scenario(service.repository.path,r.json()['scenario_id'])
        parent = store.get_scenario(service.repository.path,expected['scenario_id'])
        assert actual['metadata']['thesis_state'] == parent['metadata']['thesis_state']
