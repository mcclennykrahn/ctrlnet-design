"""Editor title is one bounded authored field; snapshot names remain separate."""
import copy
import pytest
from test_v08 import bridge
from test_scenario_tree import save, preview
from test_equivalent_merge_bases import cross
from ctrlnet import store
from ctrlnet.webmap.scenario_tree import _merge_point_coordinates


@pytest.mark.parametrize('reverse', [False, True])
@pytest.mark.parametrize('mutation', ['point', 'network', 'addition'])
def test_title_with_independent_edit(bridge, reverse, mutation):
    c, service = bridge
    root = save(c, 'root')
    service.state['name'] = 'Edited editor title'
    title = save(c, 'title snapshot', root)
    c.post('/api/engineering/open/'+root['scenario_id'], json={})
    if mutation == 'point':
        service.state['points'][0]['x'] += 7
    elif mutation == 'network':
        service.state['network']['ellipse_scale'] += 10
    else:
        service.state['seq']['point'] += 1
        service.state['points'].append(dict(id='title-new', name='title-new',
            x=12., y=34., lon=117., lat=30., fixed=False))
    expected = copy.deepcopy(service.state)
    edit = save(c, 'edit', root)
    parents = [title, edit] if not reverse else [edit, title]
    before = [store.get_scenario(service.repository.path, p['scenario_id']) for p in parents]
    plan = preview(c, *parents)
    assert plan['conflicts'] == []
    r = c.post('/api/engineering/merge', json=dict(plan, name='Snapshot name', resolutions={}))
    assert r.status_code == 200, r.text
    saved = store.get_scenario(service.repository.path, r.json()['scenario_id'])
    state = saved['metadata']['thesis_state']
    assert saved['name'] == 'Snapshot name'
    assert state['name'] == 'Edited editor title'
    for field in ('points', 'network', 'seq'):
        assert state[field] == expected[field]
    assert saved['metadata']['merge_parents'] == [p['scenario_id'] for p in parents]
    assert before == [store.get_scenario(service.repository.path, p['scenario_id']) for p in parents]
    assert c.post('/api/engineering/open/'+saved['id'], json={}).status_code == 200
    assert service.state['name'] == 'Edited editor title'


@pytest.mark.parametrize('choice', ['target', 'source'])
def test_competing_titles_require_whole_topology(bridge, choice):
    c, service = bridge
    root = save(c, 'root')
    service.state['name'] = 'left'
    left = save(c, 'left snapshot', root)
    c.post('/api/engineering/open/'+root['scenario_id'], json={})
    service.state['name'] = 'right'
    service.state['points'][0]['x'] += 5
    right = save(c, 'right snapshot', root)
    plan = preview(c, left, right)
    assert plan['conflicts'] == ['topology']
    r = c.post('/api/engineering/merge', json=dict(plan, name='resolved', resolutions={'topology': choice}))
    assert r.status_code == 200, r.text
    state = store.get_scenario(service.repository.path, r.json()['scenario_id'])['metadata']['thesis_state']
    assert state['name'] == ('left' if choice == 'target' else 'right')


def test_title_presence_and_unknown_field_guard(bridge):
    _, service = bridge
    base = copy.deepcopy(service.state)
    base.pop('name', None)
    target, source = copy.deepcopy(base), copy.deepcopy(base)
    target['name'] = None
    source['points'][0]['x'] += 3
    result = _merge_point_coordinates(base, target, source)
    assert 'name' in result and result['name'] is None
    source['future_authored_field'] = True
    assert _merge_point_coordinates(base, target, source) is None


def test_title_differing_base_consensus(bridge):
    c, service = bridge
    a, b, left, right = cross(c, service, 'point')
    tips = []
    for i, parent in enumerate((left, right)):
        c.post('/api/engineering/open/'+parent['scenario_id'], json={})
        if i == 0:
            service.state['name'] = 'Consensus title'
        else:
            service.state['points'][1]['x'] += 5
        tips.append(save(c, 'tip', parent))
    plan = preview(c, *tips)
    assert plan['conflicts'] == []
    assert plan['bases'] == sorted([a['scenario_id'], b['scenario_id']])
    r = c.post('/api/engineering/merge', json=dict(plan, name='merged', resolutions={}))
    assert r.status_code == 200, r.text
    state = store.get_scenario(service.repository.path, r.json()['scenario_id'])['metadata']['thesis_state']
    assert state['name'] == 'Consensus title'
    assert state['points'][1] == service.state['points'][1]
