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
def test_competing_titles_preserve_independent_geometry(bridge, choice):
    c, service = bridge
    root = save(c, 'root')
    service.state['name'] = 'left'
    left = save(c, 'left snapshot', root)
    c.post('/api/engineering/open/'+root['scenario_id'], json={})
    service.state['name'] = 'right'
    service.state['points'][0]['x'] += 5
    right = save(c, 'right snapshot', root)
    plan = preview(c, left, right)
    assert plan['conflicts'] == ['title']
    r = c.post('/api/engineering/merge', json=dict(plan, name='resolved', resolutions={'title': choice}))
    assert r.status_code == 200, r.text
    state = store.get_scenario(service.repository.path, r.json()['scenario_id'])['metadata']['thesis_state']
    assert state['name'] == ('left' if choice == 'target' else 'right')
    assert state['points'][0]['x'] == service.state['points'][0]['x']


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


@pytest.mark.parametrize('choice', ['target', 'source'])
@pytest.mark.parametrize('structure', ['addition', 'deletion', 'point_conflict'])
def test_title_choice_composes_with_structural_and_point_choices(bridge, choice, structure):
    c, service = bridge
    root = save(c, 'root')
    service.state['name'] = 'left'
    if structure == 'addition':
        service.state['points'].append(dict(id='title-point', name='title-point',
            x=12., y=34., lon=117., lat=30., fixed=False))
        service.state['seq']['point'] += 1
    elif structure == 'deletion':
        service.state['lines'].pop()
        # Avoid selections affecting the unchanged-deletion precondition.
        for key in ('observed_edges', 'added_edges'):
            service.state['network'][key] = []
    else:
        service.state['points'][0]['x'] += 2
    left = save(c, 'left', root)
    left_state = copy.deepcopy(service.state)
    c.post('/api/engineering/open/'+root['scenario_id'], json={})
    service.state['name'] = 'right'
    service.state['points'][0]['x'] += 5
    right = save(c, 'right', root)
    plan = preview(c, left, right)
    keys = ['title'] + (['point:'+service.state['points'][0]['id']] if structure == 'point_conflict' else [])
    assert plan['conflicts'] == keys
    resolutions = {key: choice for key in keys}
    r = c.post('/api/engineering/merge', json=dict(plan, name='resolved', resolutions=resolutions))
    assert r.status_code == 200, r.text
    saved = store.get_scenario(service.repository.path, r.json()['scenario_id'])
    state = saved['metadata']['thesis_state']
    assert state['name'] == ('left' if choice == 'target' else 'right')
    expected = left_state if structure == 'point_conflict' and choice == 'target' else service.state
    assert state['points'][0]['x'] == expected['points'][0]['x']
    if structure == 'deletion':
        assert [line['id'] for line in state['lines']] == [line['id'] for line in left_state['lines']]
    if structure == 'addition':
        assert state['points'][-1] == left_state['points'][-1]
    assert state['seq'] == left_state['seq']
    assert saved['metadata']['merge_resolutions'] == resolutions


@pytest.mark.parametrize('resolutions', [{}, {'title': 'bad'}, {'topology': 'source'}, {'title': 'source', 'network': 'target'}])
def test_title_choice_rejects_incomplete_invalid_or_extra_choices_atomically(bridge, resolutions):
    c, service = bridge
    root = save(c, 'root')
    service.state['name'] = 'left'
    left = save(c, 'left', root)
    c.post('/api/engineering/open/'+root['scenario_id'], json={})
    service.state['name'] = 'right'
    right = save(c, 'right', root)
    plan = preview(c, left, right)
    before = c.get('/api/engineering/projects').json()
    assert c.post('/api/engineering/merge', json=dict(plan, name='bad', resolutions=resolutions)).status_code == 400
    assert c.get('/api/engineering/projects').json() == before


@pytest.mark.parametrize('differing', [False, True])
def test_competing_title_multibase_guard(bridge, differing):
    c, service = bridge
    a, b, left, right = cross(c, service, 'point' if differing else None)
    tips = []
    for i, parent in enumerate((left, right)):
        c.post('/api/engineering/open/'+parent['scenario_id'], json={})
        service.state['name'] = 'title '+str(i)
        tips.append(save(c, 'tip', parent))
    plan = preview(c, *tips)
    assert plan['conflicts'] == ['title']
    key = plan['conflicts'][0]
    r = c.post('/api/engineering/merge', json=dict(plan, name='resolved', resolutions={key: 'source'}))
    assert r.status_code == 200, r.text
    assert store.get_scenario(service.repository.path, r.json()['scenario_id'])['metadata']['merge_bases'] == sorted([a['scenario_id'], b['scenario_id']])


def test_title_choice_presence_unknown_guard_and_input_immutability(bridge):
    _, service = bridge
    base = copy.deepcopy(service.state)
    base['name'] = 'base'
    target, source = copy.deepcopy(base), copy.deepcopy(base)
    target.pop('name')
    source['name'] = None
    before = copy.deepcopy((base, target, source))
    for choice in ('target', 'source'):
        conflicts = []
        result = _merge_point_coordinates(base, target, source, conflicts, {'title': choice})
        assert conflicts == ['title']
        assert ('name' in result) == (choice == 'source')
        assert result.get('name') is None
    assert (base, target, source) == before
    source['future_authored_field'] = True
    assert _merge_point_coordinates(base, target, source, [], {'title': 'source'}) is None
