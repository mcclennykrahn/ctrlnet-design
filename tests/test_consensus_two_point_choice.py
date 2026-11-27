"""Exactly two point choices require every joint outcome at every best base."""
from itertools import product
import pytest
from test_v08 import bridge
from test_consensus_point_choice import point_tips
from test_scenario_tree import preview, save
from ctrlnet import store
from ctrlnet.webmap import scenario_tree as tree


@pytest.mark.parametrize('reverse', [False, True])
@pytest.mark.parametrize('outcomes', list(product(('target', 'source'), repeat=2)))
def test_two_point_choices_reopen(bridge, reverse, outcomes):
    c, service = bridge
    a, b, children = point_tips(c, service, 'multiple')
    if reverse:
        children.reverse()
    rows = [store.get_scenario(service.repository.path, x['scenario_id']) for x in (a, b, *children)]
    states = [r['metadata']['thesis_state'] for r in rows]
    keys = ['point:'+states[2]['points'][i]['id'] for i in (0, 3)]
    plan = preview(c, *children)
    assert plan['conflicts'] == keys
    assert set(plan['bases']) == {a['scenario_id'], b['scenario_id']}
    choices = dict(zip(keys, outcomes))
    for bad in ({}, {keys[0]: 'source'}, dict(choices, topology='target')):
        assert c.post('/api/engineering/merge', json=dict(plan, name='bad', resolutions=bad)).status_code == 400
    r = c.post('/api/engineering/merge', json=dict(plan, name='two points', resolutions=choices))
    assert r.status_code == 200, r.text
    saved = store.get_scenario(service.repository.path, r.json()['scenario_id'])
    assert saved['metadata']['merge_versions'] == plan['versions']
    assert saved['metadata']['merge_resolutions'] == choices
    assert saved['metadata']['merge_bases'] == plan['bases']
    assert c.post('/api/engineering/open/'+saved['id'], json={}).status_code == 200
    for i, choice in zip((0, 3), outcomes):
        assert service.state['points'][i] == states[2 if choice == 'target' else 3]['points'][i]
    for i in (1, 2):
        assert service.state['points'][i]['y'] == states[0]['points'][i]['y']+10
    assert [p['id'] for p in service.state['points']] == [p['id'] for p in states[2]['points']]
    for k in ('point', 'line', 'angle'):
        assert service.state['seq'][k] == max(s['seq'][k] for s in states)
    assert rows == [store.get_scenario(service.repository.path, x['scenario_id']) for x in (a, b, *children)]


@pytest.mark.parametrize('outcomes', list(product(('target', 'source'), repeat=2)))
def test_each_joint_outcome_checked(bridge, monkeypatch, outcomes):
    c, service = bridge
    _, _, children = point_tips(c, service, 'multiple')
    keys = ['point:'+service.state['points'][i]['id'] for i in (0, 3)]
    real = tree._merge_point_coordinates
    def poisoned(base, target, source, point_conflicts=None, choices=None):
        value = real(base, target, source, point_conflicts, choices)
        if (value and choices == dict(zip(keys, outcomes))
                and base['points'][0]['x'] == target['points'][0]['x']):
            value['points'][1]['y'] += 123
        return value
    monkeypatch.setattr(tree, '_merge_point_coordinates', poisoned)
    assert preview(c, *children)['conflicts'] == ['topology']


@pytest.mark.parametrize('index', [0, 1])
def test_two_point_base_versions_guarded(bridge, index):
    c, service = bridge
    _, _, children = point_tips(c, service, 'multiple')
    plan = preview(c, *children)
    sid = plan['bases'][index]
    assert c.post('/api/engineering/rename/'+sid, json=dict(name='changed', version=plan['versions'][sid])).status_code == 200
    before = c.get('/api/engineering/projects').json()
    assert c.post('/api/engineering/merge', json=dict(plan, name='stale', resolutions=dict.fromkeys(plan['conflicts'], 'source'))).status_code == 409
    assert c.get('/api/engineering/projects').json() == before


@pytest.mark.parametrize('extra', ['title', 'third-point'])
def test_extra_conflicts_stay_conservative(bridge, extra):
    c, service = bridge
    _, _, children = point_tips(c, service, 'multiple')
    tips = []
    for i, child in enumerate(children):
        c.post('/api/engineering/open/'+child['scenario_id'], json={})
        if extra == 'title':
            service.state['name'] = 'title '+str(i)
        else:
            service.state['points'][1]['x'] += 20+i
        tips.append(save(c, 'extra', child))
    assert preview(c, *tips)['conflicts'] == ['topology']


@pytest.mark.parametrize('reverse', [False, True])
def test_every_outcome_requires_unique_point_names(bridge, reverse):
    c, service = bridge
    _, _, children = point_tips(c, service, 'multiple')
    tips = []
    for i, child in enumerate(children):
        c.post('/api/engineering/open/'+child['scenario_id'], json={})
        service.state['points'][0]['name'] = 'shared' if i == 0 else 'other0'
        service.state['points'][3]['name'] = 'other3' if i == 0 else 'shared'
        tips.append(save(c, 'names', child))
    if reverse:
        tips.reverse()
    assert preview(c, *tips)['conflicts'] == ['topology']
