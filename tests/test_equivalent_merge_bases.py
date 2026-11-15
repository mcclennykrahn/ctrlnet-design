"""Equivalent criss-cross bases: real DAGs, version guards and conservative limits."""
import copy
import pytest
from test_v08 import bridge, GNSS
from test_scenario_tree import save, preview
from ctrlnet import store


def merge(c, a, b, name):
    plan = preview(c, a, b)
    assert plan['conflicts'] == []
    r = c.post('/api/engineering/merge', json=dict(plan, name=name, resolutions={}))
    assert r.status_code == 200, r.text
    return r.json()


def cross(c, service, mutation=None):
    root = save(c, 'root')
    a = save(c, 'a', root)
    c.post('/api/engineering/open/'+root['scenario_id'], json={})
    if mutation == 'point':
        service.state['points'][0]['x'] += 1
    elif mutation == 'unknown':
        service.state['future_authored'] = True
    elif mutation == 'order':
        service.state['points'].reverse()
    elif mutation == 'timestamp':
        service.state['updated_at'] = '2000-01-01T00:00:00+00:00'
    b = save(c, 'b', root, [GNSS] if mutation == 'gnss' else None)
    left = merge(c, a, b, 'left')
    right = merge(c, b, a, 'right')
    return a, b, left, right


@pytest.mark.parametrize('timestamps', [False, True])
def test_equivalent_criss_cross_merge_reopen(bridge, timestamps):
    c, service = bridge
    a, b, left, right = cross(c, service, 'timestamp' if timestamps else None)
    c.post('/api/engineering/open/'+left['scenario_id'], json={})
    service.state['points'][0]['x'] += 2
    left = save(c, 'left child', left)
    expected = copy.deepcopy(service.state['points'][0])
    c.post('/api/engineering/open/'+right['scenario_id'], json={})
    service.state['points'][1]['x'] += 3
    right = save(c, 'right child', right)
    other = copy.deepcopy(service.state['points'][1])
    plan = preview(c, left, right)
    bases = sorted([a['scenario_id'], b['scenario_id']])
    assert plan['bases'] == bases
    assert plan['base'] == bases[0]
    assert set(plan['versions']) == set(bases + [left['scenario_id'], right['scenario_id']])
    assert preview(c, right, left)['bases'] == bases
    result = merge(c, left, right, 'equivalent bases')
    stored = store.get_scenario(service.repository.path, result['scenario_id'])
    assert stored['metadata']['merge_bases'] == bases
    assert c.post('/api/engineering/open/'+result['scenario_id'], json={}).status_code == 200
    assert service.state['points'][0] == expected
    assert service.state['points'][1] == other
    rows = c.get('/api/engineering/projects').json()['projects'][0]['scenarios']
    assert next(s for s in rows if s['id'] == result['scenario_id'])['merge_bases'] == bases


@pytest.mark.parametrize('mutation', ['point', 'gnss', 'unknown', 'order'])
def test_different_criss_cross_bases_with_converged_tips(bridge, mutation):
    c, service = bridge
    a, b, left, right = cross(c, service, mutation)
    for target, source in [(left, right), (right, left)]:
        plan = preview(c, target, source)
        assert plan['conflicts'] == []
        assert plan['bases'] == sorted([a['scenario_id'], b['scenario_id']])
        merge(c, target, source, 'converged')


@pytest.mark.parametrize('base_index', [0, 1])
def test_every_equivalent_base_version_is_guarded(bridge, base_index):
    c, service = bridge
    a, b, left, right = cross(c, service)
    plan = preview(c, left, right)
    sid = plan['bases'][base_index]
    version = plan['versions'][sid]
    assert c.post('/api/engineering/rename/'+sid, json=dict(name='renamed base', version=version)).status_code == 200
    before = c.get('/api/engineering/projects').json()
    assert c.post('/api/engineering/merge', json=dict(plan, name='stale', resolutions={})).status_code == 409
    assert c.get('/api/engineering/projects').json() == before
