"""Reordered stable-ID best bases retain ordinary conflict choices."""
import copy
import pytest
from test_v08 import bridge
from test_scenario_tree import save, preview
from test_equivalent_merge_bases import merge
from ctrlnet import store
from ctrlnet.webmap.scenario_tree import _same_base


@pytest.mark.parametrize('collection', ['points', 'lines', 'angles', 'all'])
@pytest.mark.parametrize('choice', ['target', 'source', 'stale'])
@pytest.mark.parametrize('reverse', [False, True])
def test_reordered_bases_field_choice(bridge, collection, choice, reverse):
    c, service = bridge
    root = save(c, 'root')
    service.state['seq'].update(point=200, line=300, angle=400)
    a = save(c, 'a', root)
    c.post('/api/engineering/open/'+root['scenario_id'], json={})
    for key in ('points', 'lines', 'angles'):
        if collection in (key, 'all'):
            assert len(service.state[key]) > 1
            service.state[key].reverse()
    service.state['seq'].update(point=500, line=100, angle=200)
    b = save(c, 'b', root)
    left, right = merge(c, a, b, 'left'), merge(c, b, a, 'right')
    tips, expected = [], {}
    for i, parent in enumerate((left, right)):
        c.post('/api/engineering/open/'+parent['scenario_id'], json={})
        # Pick by ID despite different branch presentation orders.
        pid = store.get_scenario(service.repository.path, root['scenario_id'])['metadata']['thesis_state']['points'][i]['id']
        point = next(p for p in service.state['points'] if p['id'] == pid)
        point['x'] += 7
        expected[pid] = copy.deepcopy(point)
        service.state['name'] = 'title '+str(i)
        service.state['seq'].update(point=20, line=30, angle=40)
        tips.append(save(c, 'tip', parent))
    if reverse:
        tips.reverse()
    before = [store.get_scenario(service.repository.path, x['scenario_id']) for x in (a, b)]
    plan = preview(c, *tips)
    assert plan['differing_base_units'] == []
    assert plan['conflicts'] == ['title']
    assert set(plan['bases']) == {a['scenario_id'], b['scenario_id']}
    if choice == 'stale':
        sid = plan['bases'][-1]
        assert c.post('/api/engineering/rename/'+sid, json=dict(name='renamed', version=plan['versions'][sid])).status_code == 200
        assert c.post('/api/engineering/merge', json=dict(plan, name='stale', resolutions={'title':'source'})).status_code == 409
        return
    r = c.post('/api/engineering/merge', json=dict(plan, name='merged', resolutions={'title':choice}))
    assert r.status_code == 200, r.text
    saved = store.get_scenario(service.repository.path, r.json()['scenario_id'])
    state = saved['metadata']['thesis_state']
    chosen = tips[0 if choice == 'target' else 1]
    assert state['name'] == store.get_scenario(service.repository.path, chosen['scenario_id'])['metadata']['thesis_state']['name']
    assert state['seq'] == dict(point=500, line=300, angle=400)
    for point in state['points']:
        if point['id'] in expected:
            assert point == expected[point['id']]
    target_state = store.get_scenario(service.repository.path, tips[0]['scenario_id'])['metadata']['thesis_state']
    for key in ('points', 'lines', 'angles'):
        assert [x['id'] for x in state[key]] == [x['id'] for x in target_state[key]]
    assert before == [store.get_scenario(service.repository.path, x['scenario_id']) for x in (a,b)]
    assert saved['metadata']['merge_bases'] == plan['bases']
    assert saved['metadata']['merge_versions'] == plan['versions']
    assert c.post('/api/engineering/open/'+saved['id'], json={}).status_code == 200
    assert service.state['name'] == state['name']


@pytest.mark.parametrize('mutation', ['unknown', 'point', 'duplicate', 'missing_id', 'seq_unknown'])
def test_reordered_base_authored_and_identity_guards(bridge, mutation):
    _, service = bridge
    base = copy.deepcopy(service.state)
    other = copy.deepcopy(base)
    other['points'].reverse()
    if mutation == 'unknown':
        other['points'][0]['future'] = True
    elif mutation == 'point':
        other['points'][0]['x'] += 1
    elif mutation == 'duplicate':
        other['points'][0]['id'] = other['points'][1]['id']
    elif mutation == 'missing_id':
        other['points'][0].pop('id')
    else:
        other['seq']['future'] = 1
    assert not _same_base('topology', base, other)


@pytest.mark.parametrize('reverse', [False, True])
def test_reordered_bases_trivial_title_keeps_target_order(bridge, reverse):
    c, service = bridge
    from test_equivalent_merge_bases import cross
    a, b, left, right = cross(c, service, 'order')
    # Match the representative base exactly to exercise the trivial shortcut;
    # a source-only title must not choose source order based on random base ID.
    bases = sorted([a['scenario_id'], b['scenario_id']], reverse=reverse)
    tips, states = [], []
    for i, parent in enumerate((left, right)):
        service.state = copy.deepcopy(store.get_scenario(service.repository.path, bases[i])['metadata']['thesis_state'])
        if i:
            service.state['name'] = 'source title'
        states.append(copy.deepcopy(service.state))
        tips.append(save(c, 'tip', parent))
    plan = preview(c, *tips)
    assert plan['differing_base_units'] == []
    assert plan['conflicts'] == []
    result = c.post('/api/engineering/merge', json=dict(plan, name='merged', resolutions={}))
    assert result.status_code == 200, result.text
    actual = store.get_scenario(service.repository.path, result.json()['scenario_id'])['metadata']['thesis_state']
    assert actual['name'] == 'source title'
    for key in ('points', 'lines', 'angles'):
        assert [x['id'] for x in actual[key]] == [x['id'] for x in states[0][key]]


def test_reordered_bases_preserve_structural_convergence_with_counter_drift(bridge):
    c, service = bridge
    from test_equivalent_merge_bases import cross
    a, b, left, right = cross(c, service, 'order')
    shared = copy.deepcopy(store.get_scenario(service.repository.path, a['scenario_id'])['metadata']['thesis_state'])
    added = copy.deepcopy(shared['points'][0])
    added.update(id='p100', name='100', future_authored=True)
    shared['points'].append(added)
    tips = []
    for i, parent in enumerate((left, right)):
        service.state = copy.deepcopy(shared)
        service.state['seq']['point'] = 100 + i
        tips.append(save(c, 'converged', parent))
    plan = preview(c, *tips)
    assert plan['differing_base_units'] == []
    assert plan['conflicts'] == []
    r = c.post('/api/engineering/merge', json=dict(plan, name='merged', resolutions={}))
    assert r.status_code == 200, r.text
    actual = store.get_scenario(service.repository.path, r.json()['scenario_id'])['metadata']['thesis_state']
    assert actual['points'] == shared['points']
    assert actual['seq']['point'] == 101
