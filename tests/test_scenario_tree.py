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
    key = 'point:' + service.state['points'][1]['id']
    assert plan['conflicts'] == [key]
    for choice, expected in [('target',left),('source',right)]:
        r = c.post('/api/engineering/merge',json=dict(plan,name=choice,resolutions={key:choice}))
        assert r.status_code == 200, r.text
        actual = store.get_scenario(service.repository.path,r.json()['scenario_id'])
        parent = store.get_scenario(service.repository.path,expected['scenario_id'])
        from ctrlnet.webmap.scenario_tree import _same
        assert _same('topology', actual['metadata']['thesis_state'], parent['metadata']['thesis_state'])


def test_disjoint_point_coordinates_merge_and_refresh(bridge):
    from ctrlnet.webmap.thesis_web import _refresh_derived
    c, service = bridge
    root = save(c, 'base')
    service.state['points'][0]['x'] += 5
    left = save(c, 'left', root)
    left_state = copy.deepcopy(service.state)
    c.post('/api/engineering/open/'+root['scenario_id'], json={})
    service.state['points'][1]['y'] -= 7
    right = save(c, 'right', root, [GNSS])
    expected = copy.deepcopy(left_state)
    expected['points'][1] = copy.deepcopy(service.state['points'][1])
    _refresh_derived(expected)
    plan = preview(c, left, right)
    assert plan['conflicts'] == []
    before = [store.get_scenario(service.repository.path, r['scenario_id']) for r in (left, right)]
    result = c.post('/api/engineering/merge', json=dict(plan, name='combined', resolutions={}))
    assert result.status_code == 200, result.text
    sid = result.json()['scenario_id']
    actual = store.get_scenario(service.repository.path, sid)
    assert actual['metadata']['thesis_state']['points'] == expected['points']
    assert actual['metadata']['thesis_state']['lines'] == expected['lines']
    assert actual['metadata']['thesis_state']['angles'] == expected['angles']
    assert c.get('/api/engineering/settings/'+sid).json()['gnss'] == [GNSS]
    assert [store.get_scenario(service.repository.path, r['scenario_id']) for r in (left, right)] == before
    assert c.post('/api/engineering/open/'+sid, json={}).status_code == 200
    assert service.state['points'] == expected['points']


@pytest.mark.parametrize('mutation', ['projection', 'reorder', 'delete'])
def test_coordinate_merge_declines_other_authored_changes(bridge, mutation):
    c, service = bridge
    root = save(c, 'base')
    service.state['points'][0]['x'] += 1
    left = save(c, 'left', root)
    c.post('/api/engineering/open/'+root['scenario_id'], json={})
    service.state['points'][1]['y'] += 2
    if mutation == 'projection':
        service.state['projection'] = {'unsupported_change': True}
    elif mutation == 'reorder':
        service.state['points'].reverse()
    elif mutation == 'delete':
        # Exercise the planner helper: saving dangling edges is already rejected.
        from ctrlnet.webmap.scenario_tree import _merge_point_coordinates
        base = store.get_scenario(service.repository.path, root['scenario_id'])['metadata']['thesis_state']
        target = store.get_scenario(service.repository.path, left['scenario_id'])['metadata']['thesis_state']
        source = copy.deepcopy(service.state)
        source['points'].pop()
        assert _merge_point_coordinates(base, target, source) is None
        return
    right = save(c, 'right', root)
    assert preview(c, left, right)['conflicts'] == ['topology']


@pytest.mark.parametrize('field,value', [('name', 900), ('fixed', True)])
def test_existing_point_field_merge_reopens(bridge, field, value):
    c, service = bridge
    root = save(c, 'base')
    index = next(i for i, p in enumerate(service.state['points']) if not p['fixed'])
    service.state['points'][index]['x'] += 5
    left = save(c, 'coordinates', root)
    expected_x = service.state['points'][index]['x']
    c.post('/api/engineering/open/'+root['scenario_id'], json={})
    service.state['points'][index][field] = value
    right = save(c, 'field', root)
    plan = preview(c, left, right)
    assert plan['conflicts'] == []
    r = c.post('/api/engineering/merge', json=dict(plan, name='fields', resolutions={}))
    assert r.status_code == 200, r.text
    assert c.post('/api/engineering/open/'+r.json()['scenario_id'], json={}).status_code == 200
    assert service.state['points'][index]['x'] == expected_x
    assert service.state['points'][index][field] == value


def test_conflicting_names_choose_whole_point(bridge):
    c, service = bridge
    root = save(c, 'base')
    service.state['points'][0]['name'] = 900
    left = save(c, 'left', root)
    c.post('/api/engineering/open/'+root['scenario_id'], json={})
    service.state['points'][0]['name'] = 901
    right = save(c, 'right', root)
    plan = preview(c, left, right)
    key = 'point:' + service.state['points'][0]['id']
    assert plan['conflicts'] == [key]
    r = c.post('/api/engineering/merge', json=dict(plan, name='choice', resolutions={key: 'source'}))
    assert r.status_code == 200, r.text
    actual = store.get_scenario(service.repository.path, r.json()['scenario_id'])
    assert actual['metadata']['thesis_state']['points'][0]['name'] == 901


@pytest.mark.parametrize('field', ['length', 'azimuth'])
def test_measured_override_merges_with_coordinates_and_reopens(bridge, field):
    c, service = bridge
    root = save(c, 'base')
    service.state['points'][0]['x'] += 5
    left = save(c, 'coordinates', root)
    expected_x = service.state['points'][0]['x']
    c.post('/api/engineering/open/'+root['scenario_id'], json={})
    service.state['lines'][0].update({field: 123.25, '_keep_'+field: True})
    right = save(c, 'measurement', root)
    before = [store.get_scenario(service.repository.path, x['scenario_id']) for x in (left, right)]
    plan = preview(c, left, right)
    assert plan['conflicts'] == []
    r = c.post('/api/engineering/merge', json=dict(plan, name='combined', resolutions={}))
    assert r.status_code == 200, r.text
    assert c.post('/api/engineering/open/'+r.json()['scenario_id'], json={}).status_code == 200
    assert service.state['points'][0]['x'] == expected_x
    assert service.state['lines'][0][field] == 123.25
    assert service.state['lines'][0]['_keep_'+field] is True
    assert [store.get_scenario(service.repository.path, x['scenario_id']) for x in (left, right)] == before


def test_line_override_units_and_clear_conflict(bridge):
    c, service = bridge
    service.state['lines'][0].update(length=123., _keep_length=True)
    root = save(c, 'measured base')
    # Independent length and azimuth changes on the same line combine.
    service.state['lines'][0]['length'] = 124.
    left = save(c, 'length', root)
    c.post('/api/engineering/open/'+root['scenario_id'], json={})
    service.state['lines'][0].update(azimuth=42., _keep_azimuth=True)
    right = save(c, 'azimuth', root)
    plan = preview(c, left, right)
    assert plan['conflicts'] == []
    r = c.post('/api/engineering/merge', json=dict(plan, name='both', resolutions={}))
    assert r.status_code == 200, r.text
    state = store.get_scenario(service.repository.path, r.json()['scenario_id'])['metadata']['thesis_state']
    assert state['lines'][0]['length'] == 124.
    assert state['lines'][0]['azimuth'] == 42.
    # Clearing an override competes with editing its measured value.
    c.post('/api/engineering/open/'+root['scenario_id'], json={})
    service.state['lines'][0].pop('_keep_length')
    clear = save(c, 'clear', root)
    plan = preview(c, left, clear)
    assert plan['conflicts'] == ['topology']
    before = c.get('/api/engineering/projects').json()
    assert c.post('/api/engineering/merge', json=dict(plan, name='unresolved', resolutions={})).status_code == 400
    assert c.get('/api/engineering/projects').json() == before
    r = c.post('/api/engineering/merge', json=dict(plan, name='cleared', resolutions={'topology': 'source'}))
    assert r.status_code == 200, r.text
    state = store.get_scenario(service.repository.path, r.json()['scenario_id'])['metadata']['thesis_state']
    assert '_keep_length' not in state['lines'][0]


@pytest.mark.parametrize('reverse', [False, True])
def test_network_unit_merges_with_geometry_and_reopens(bridge, reverse):
    c, service = bridge
    root = save(c, 'base')
    service.state['points'][0]['x'] += 5
    left = save(c, 'geometry', root)
    expected_point = copy.deepcopy(service.state['points'][0])
    c.post('/api/engineering/open/'+root['scenario_id'], json={})
    service.configure_network({'tolerance_mm': 35, 'ellipse_scale': 300})
    expected_network = copy.deepcopy(service.state['network'])
    right = save(c, 'settings', root)
    parents = [store.get_scenario(service.repository.path, x['scenario_id']) for x in (left, right)]
    plan = preview(c, right, left) if reverse else preview(c, left, right)
    assert plan['conflicts'] == []
    r = c.post('/api/engineering/merge', json=dict(plan, name='combined', resolutions={}))
    assert r.status_code == 200, r.text
    assert c.post('/api/engineering/open/'+r.json()['scenario_id'], json={}).status_code == 200
    assert service.state['network'] == expected_network
    assert service.state['points'][0] == expected_point
    assert [store.get_scenario(service.repository.path, x['scenario_id']) for x in (left, right)] == parents


def test_network_competing_changes_keep_whole_topology_choice(bridge):
    c, service = bridge
    root = save(c, 'base')
    service.configure_network({'tolerance_mm': 35})
    left = save(c, 'tolerance', root)
    c.post('/api/engineering/open/'+root['scenario_id'], json={})
    service.configure_network({'ellipse_scale': 300})
    right = save(c, 'scale', root)
    expected = copy.deepcopy(service.state)
    plan = preview(c, left, right)
    assert plan['conflicts'] == ['topology']
    before = c.get('/api/engineering/projects').json()
    assert c.post('/api/engineering/merge', json=dict(plan, name='unresolved', resolutions={})).status_code == 400
    assert c.get('/api/engineering/projects').json() == before
    r = c.post('/api/engineering/merge', json=dict(plan, name='source', resolutions={'topology': 'source'}))
    assert r.status_code == 200, r.text
    assert store.get_scenario(service.repository.path, r.json()['scenario_id'])['metadata']['thesis_state'] == expected


def test_multiple_point_choices_preserve_independent_edits_and_atomicity(bridge):
    c, service = bridge
    root = save(c, 'base')
    ids = [p['id'] for p in service.state['points'][:3]]
    service.state['points'][0]['x'] += 3
    service.state['points'][0]['name'] = 801
    service.state['points'][1]['name'] = 802
    left = save(c, 'target', root)
    target = copy.deepcopy(service.state)
    c.post('/api/engineering/open/'+root['scenario_id'], json={})
    service.state['points'][0]['x'] -= 4
    service.state['points'][1]['name'] = 803
    service.state['points'][2]['y'] += 6
    right = save(c, 'source', root)
    source = copy.deepcopy(service.state)
    plan = preview(c, left, right)
    keys = ['point:' + i for i in ids[:2]]
    assert plan['conflicts'] == keys
    before = c.get('/api/engineering/projects').json()
    for choices in ({}, {keys[0]: 'target'}, {keys[0]: 'target', keys[1]: ''},
                    {keys[0]: 'target', keys[1]: 'source', 'topology': 'source'}):
        r = c.post('/api/engineering/merge', json=dict(plan, name='bad', resolutions=choices))
        assert r.status_code == 400
        assert c.get('/api/engineering/projects').json() == before
    choices = {keys[0]: 'source', keys[1]: 'target'}
    r = c.post('/api/engineering/merge', json=dict(plan, name='mixed', resolutions=choices))
    assert r.status_code == 200, r.text
    saved = store.get_scenario(service.repository.path, r.json()['scenario_id'])
    assert saved['metadata']['merge_resolutions'] == choices
    assert c.post('/api/engineering/open/'+saved['id'], json={}).status_code == 200
    assert service.state['points'][0] == source['points'][0]  # whole point, including name
    assert service.state['points'][1] == target['points'][1]
    assert service.state['points'][2] == source['points'][2]
    c.post('/api/engineering/rename/'+left['scenario_id'],
           json=dict(name='changed', version=left['version']))
    assert c.post('/api/engineering/merge', json=dict(plan, name='stale', resolutions=choices)).status_code == 409


def test_point_conflict_with_network_conflict_retains_topology_choice(bridge):
    c, service = bridge
    root = save(c, 'base')
    service.state['points'][0]['x'] += 3
    service.state['network']['tolerance_mm'] = 31
    left = save(c, 'target', root)
    c.post('/api/engineering/open/'+root['scenario_id'], json={})
    service.state['points'][0]['x'] -= 4
    service.state['network']['tolerance_mm'] = 32
    right = save(c, 'source', root)
    assert preview(c, left, right)['conflicts'] == ['topology']
