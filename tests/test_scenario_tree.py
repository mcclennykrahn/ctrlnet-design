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


@pytest.mark.parametrize('mutation', ['projection', 'delete'])
def test_coordinate_merge_declines_other_authored_changes(bridge, mutation):
    c, service = bridge
    root = save(c, 'base')
    service.state['points'][0]['x'] += 1
    left = save(c, 'left', root)
    c.post('/api/engineering/open/'+root['scenario_id'], json={})
    service.state['points'][1]['y'] += 2
    if mutation == 'projection':
        service.state['projection'] = {'unsupported_change': True}
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
    key = 'line:' + service.state['lines'][0]['id']
    assert plan['conflicts'] == [key]
    before = c.get('/api/engineering/projects').json()
    assert c.post('/api/engineering/merge', json=dict(plan, name='unresolved', resolutions={})).status_code == 400
    assert c.get('/api/engineering/projects').json() == before
    r = c.post('/api/engineering/merge', json=dict(plan, name='cleared', resolutions={key: 'source'}))
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


def test_network_competing_changes_choose_whole_settings(bridge):
    c, service = bridge
    root = save(c, 'base')
    service.configure_network({'tolerance_mm': 35})
    left = save(c, 'tolerance', root)
    c.post('/api/engineering/open/'+root['scenario_id'], json={})
    service.configure_network({'ellipse_scale': 300})
    right = save(c, 'scale', root)
    expected = copy.deepcopy(service.state)
    plan = preview(c, left, right)
    assert plan['conflicts'] == ['network']
    before = c.get('/api/engineering/projects').json()
    assert c.post('/api/engineering/merge', json=dict(plan, name='unresolved', resolutions={})).status_code == 400
    assert c.get('/api/engineering/projects').json() == before
    r = c.post('/api/engineering/merge', json=dict(plan, name='source', resolutions={'network': 'source'}))
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


def test_point_conflict_with_network_conflict_offers_both_choices(bridge):
    c, service = bridge
    root = save(c, 'base')
    service.state['points'][0]['x'] += 3
    service.state['network']['tolerance_mm'] = 31
    left = save(c, 'target', root)
    c.post('/api/engineering/open/'+root['scenario_id'], json={})
    service.state['points'][0]['x'] -= 4
    service.state['network']['tolerance_mm'] = 32
    right = save(c, 'source', root)
    plan = preview(c, left, right)
    point_key = 'point:' + service.state['points'][0]['id']
    assert plan['conflicts'] == ['network', point_key]
    target = store.get_scenario(service.repository.path, left['scenario_id'])['metadata']['thesis_state']
    source = copy.deepcopy(service.state)
    choices = {'network': 'source', point_key: 'target'}
    r = c.post('/api/engineering/merge', json=dict(plan, name='mixed', resolutions=choices))
    assert r.status_code == 200, r.text
    assert c.post('/api/engineering/open/'+r.json()['scenario_id'], json={}).status_code == 200
    assert service.state['network'] == source['network']
    assert service.state['points'][0] == target['points'][0]


@pytest.mark.parametrize('choice', ['target', 'source'])
def test_network_choice_preserves_other_merges_and_guards(bridge, choice):
    c, service = bridge
    root = save(c, 'base')
    service.state['points'][0]['x'] += 3
    service.state['network']['tolerance_mm'] = 31
    left = save(c, 'target', root)
    target = copy.deepcopy(service.state)
    c.post('/api/engineering/open/'+root['scenario_id'], json={})
    service.state['points'][1]['y'] += 4
    service.state['lines'][0].update(length=123., _keep_length=True)
    service.state['network']['ellipse_scale'] = 300
    right = save(c, 'source', root)
    source = copy.deepcopy(service.state)
    parents = [store.get_scenario(service.repository.path, x['scenario_id']) for x in (left, right)]
    plan = preview(c, left, right)
    assert plan['conflicts'] == ['network']
    before = c.get('/api/engineering/projects').json()
    for resolutions in ({}, {'network': ''}, {'network': 'source', 'topology': 'target'}):
        assert c.post('/api/engineering/merge', json=dict(plan, name='bad', resolutions=resolutions)).status_code == 400
        assert c.get('/api/engineering/projects').json() == before
    r = c.post('/api/engineering/merge', json=dict(plan, name='choice', resolutions={'network': choice}))
    assert r.status_code == 200, r.text
    saved = store.get_scenario(service.repository.path, r.json()['scenario_id'])
    assert saved['metadata']['merge_resolutions'] == {'network': choice}
    assert c.post('/api/engineering/open/'+saved['id'], json={}).status_code == 200
    assert service.state['network'] == (target if choice == 'target' else source)['network']
    assert service.state['points'][0] == target['points'][0]
    assert service.state['points'][1] == source['points'][1]
    assert service.state['lines'][0]['length'] == 123.
    assert [store.get_scenario(service.repository.path, x['scenario_id']) for x in (left, right)] == parents
    c.post('/api/engineering/rename/'+left['scenario_id'], json=dict(name='changed', version=left['version']))
    assert c.post('/api/engineering/merge', json=dict(plan, name='stale', resolutions={'network': choice})).status_code == 409


def test_network_choice_declines_structural_changes(bridge):
    c, service = bridge
    root = save(c, 'base')
    service.state['network']['tolerance_mm'] = 31
    left = save(c, 'target', root)
    c.post('/api/engineering/open/'+root['scenario_id'], json={})
    service.state['network']['tolerance_mm'] = 32
    service.state['projection'] = {'unsupported_change': True}
    right = save(c, 'source', root)
    assert preview(c, left, right)['conflicts'] == ['topology']


@pytest.mark.parametrize('choice', ['target', 'source'])
@pytest.mark.parametrize('field', ['length', 'azimuth'])
def test_whole_line_choice_preserves_other_merges_and_guards(bridge, choice, field):
    c, service = bridge
    root = save(c, 'base')
    service.state['lines'][0].update({field: 123., '_keep_'+field: True})
    service.state['lines'][0].update(azimuth=41., _keep_azimuth=True)
    if field == 'azimuth':
        # A later azimuth conflict must discard the earlier length merge
        # when choosing the source's whole line.
        service.state['lines'][0].update(length=124., _keep_length=True)
    service.state['points'][0]['x'] += 3
    left = save(c, 'target', root)
    target = copy.deepcopy(service.state)
    c.post('/api/engineering/open/'+root['scenario_id'], json={})
    service.state['lines'][0].update({field: 125., '_keep_'+field: True})
    service.state['points'][1]['y'] += 4
    service.state['network']['tolerance_mm'] = 35
    right = save(c, 'source', root)
    source = copy.deepcopy(service.state)
    parents = [store.get_scenario(service.repository.path, x['scenario_id']) for x in (left, right)]
    plan = preview(c, left, right)
    key = 'line:' + source['lines'][0]['id']
    assert plan['conflicts'] == [key]
    before = c.get('/api/engineering/projects').json()
    for resolutions in ({}, {key: ''}, {key: 'source', 'topology': 'target'}):
        assert c.post('/api/engineering/merge', json=dict(plan, name='bad', resolutions=resolutions)).status_code == 400
        assert c.get('/api/engineering/projects').json() == before
    r = c.post('/api/engineering/merge', json=dict(plan, name='choice', resolutions={key: choice}))
    assert r.status_code == 200, r.text
    saved = store.get_scenario(service.repository.path, r.json()['scenario_id'])
    assert saved['metadata']['merge_resolutions'] == {key: choice}
    assert c.post('/api/engineering/open/'+saved['id'], json={}).status_code == 200
    expected = (target if choice == 'target' else source)['lines'][0]
    for measured in ('length', 'azimuth'):
        assert service.state['lines'][0].get('_keep_'+measured) == expected.get('_keep_'+measured)
        if expected.get('_keep_'+measured):
            assert service.state['lines'][0][measured] == expected[measured]
    assert service.state['points'][0] == target['points'][0]
    assert service.state['points'][1] == source['points'][1]
    assert service.state['network'] == source['network']
    assert [store.get_scenario(service.repository.path, x['scenario_id']) for x in (left, right)] == parents
    c.post('/api/engineering/rename/'+left['scenario_id'], json=dict(name='changed', version=left['version']))
    assert c.post('/api/engineering/merge', json=dict(plan, name='stale', resolutions={key: choice})).status_code == 409


def test_line_choices_coexist_and_structural_changes_fall_back(bridge):
    c, service = bridge
    root = save(c, 'base')
    service.state['points'][0]['x'] += 3
    service.state['network']['tolerance_mm'] = 31
    for line in service.state['lines'][:2]:
        line.update(length=123., _keep_length=True)
    left = save(c, 'target', root)
    target = copy.deepcopy(service.state)
    c.post('/api/engineering/open/'+root['scenario_id'], json={})
    service.state['points'][0]['x'] -= 4
    service.state['network']['tolerance_mm'] = 32
    for line in service.state['lines'][:2]:
        line.update(length=125., _keep_length=True)
    right = save(c, 'source', root)
    source = copy.deepcopy(service.state)
    point = 'point:' + source['points'][0]['id']
    lines = ['line:' + line['id'] for line in source['lines'][:2]]
    plan = preview(c, left, right)
    assert plan['conflicts'] == ['network', point, *lines]
    choices = {'network': 'source', point: 'target', lines[0]: 'target', lines[1]: 'source'}
    r = c.post('/api/engineering/merge', json=dict(plan, name='mixed', resolutions=choices))
    assert r.status_code == 200, r.text
    assert c.post('/api/engineering/open/'+r.json()['scenario_id'], json={}).status_code == 200
    assert service.state['points'][0] == target['points'][0]
    assert service.state['network'] == source['network']
    assert [line['length'] for line in service.state['lines'][:2]] == [123., 125.]
    c.post('/api/engineering/open/'+right['scenario_id'], json={})
    service.state['lines'].reverse()
    assert preview(c, left, save(c, 'reordered', root))['conflicts'] == ['network', point, *lines]
    service.state['projection'] = {'unsupported_change': True}
    structural = save(c, 'changed projection', root)
    assert preview(c, left, structural)['conflicts'] == ['topology']


@pytest.mark.parametrize('reordered', ['target', 'source', 'both'])
@pytest.mark.parametrize('conflict', [False, True])
def test_identity_merge_across_point_and_line_order(bridge, reordered, conflict):
    c, service = bridge
    root = save(c, 'base')
    base = copy.deepcopy(service.state)
    pid = base['points'][0]['id']
    lid = base['lines'][0]['id']
    other_lid = base['lines'][1]['id']
    service.state['points'][0]['name'] = 'target point'
    service.state['lines'][0].update(length=111.25, _keep_length=True)
    if reordered in ('target', 'both'):
        service.state['points'].reverse()
        service.state['lines'].reverse()
    left = save(c, 'target', root)
    target = copy.deepcopy(service.state)
    c.post('/api/engineering/open/'+root['scenario_id'], json={})
    service.state['points'][0]['fixed'] = not base['points'][0]['fixed']
    if conflict:
        service.state['points'][0]['name'] = 'source point'
        service.state['lines'][0].update(length=222.5, _keep_length=True)
    service.state['lines'][1].update(length=333.75, _keep_length=True)
    if reordered in ('source', 'both'):
        service.state['points'].reverse()
        service.state['lines'].reverse()
    right = save(c, 'source', root)
    parents = [store.get_scenario(service.repository.path, x['scenario_id']) for x in (left, right)]
    plan = preview(c, left, right)
    choices = {'point:'+pid: 'source', 'line:'+lid: 'target'} if conflict else {}
    assert set(plan['conflicts']) == set(choices)
    r = c.post('/api/engineering/merge', json=dict(plan, name='ordered merge', resolutions=choices))
    assert r.status_code == 200, r.text
    saved = store.get_scenario(service.repository.path, r.json()['scenario_id'])
    state = saved['metadata']['thesis_state']
    for collection in ('points', 'lines'):
        assert [x['id'] for x in state[collection]] == [x['id'] for x in target[collection]]
    point = next(x for x in state['points'] if x['id'] == pid)
    assert point['name'] == ('source point' if conflict else 'target point')
    assert point['fixed'] == (not base['points'][0]['fixed'])
    lines = {x['id']: x for x in state['lines']}
    assert lines[lid]['length'] == 111.25
    assert lines[other_lid]['length'] == 333.75
    assert [store.get_scenario(service.repository.path, x['scenario_id']) for x in (left, right)] == parents
    assert c.post('/api/engineering/open/'+saved['id'], json={}).status_code == 200
    assert service.state['points'] == state['points']
    assert service.state['lines'] == state['lines']


@pytest.mark.parametrize('mutation', ['duplicate_point', 'duplicate_line', 'endpoint', 'added_point'])
def test_reordered_merge_still_declines_changed_structure(bridge, mutation):
    from ctrlnet.webmap.scenario_tree import _merge_point_coordinates
    _, service = bridge
    base = copy.deepcopy(service.state)
    target, source = copy.deepcopy(base), copy.deepcopy(base)
    target['points'].reverse()
    source['lines'].reverse()
    if mutation == 'duplicate_point':
        source['points'][1]['id'] = source['points'][0]['id']
    elif mutation == 'duplicate_line':
        source['lines'][1]['id'] = source['lines'][0]['id']
    elif mutation == 'endpoint':
        source['lines'][0]['from'] = 'missing'
    else:
        extra = copy.deepcopy(source['points'][0])
        extra['id'] = 'new-point'
        source['points'].append(extra)
    assert _merge_point_coordinates(base, target, source) is None


@pytest.mark.parametrize('reordered', ['target', 'source', 'both'])
@pytest.mark.parametrize('conflict', [False, True])
def test_identity_merge_across_angle_order(bridge, reordered, conflict):
    c, service = bridge
    root = save(c, 'base')
    base = copy.deepcopy(service.state)
    pid = base['points'][0]['id']
    lid = base['lines'][0]['id']
    other_lid = base['lines'][1]['id']
    service.state['points'][0]['name'] = 'target point'
    service.state['lines'][0].update(length=111.25, _keep_length=True)
    if reordered in ('target', 'both'):
        service.state['points'].reverse()
        service.state['lines'].reverse()
        service.state['angles'].reverse()
    left = save(c, 'target', root)
    target = copy.deepcopy(service.state)
    c.post('/api/engineering/open/'+root['scenario_id'], json={})
    service.state['points'][0]['fixed'] = not base['points'][0]['fixed']
    if conflict:
        service.state['points'][0]['name'] = 'source point'
        service.state['lines'][0].update(length=222.5, _keep_length=True)
    service.state['lines'][1].update(length=333.75, _keep_length=True)
    if reordered in ('source', 'both'):
        service.state['points'].reverse()
        service.state['lines'].reverse()
        service.state['angles'].reverse()
    right = save(c, 'source', root)
    parents = [store.get_scenario(service.repository.path, x['scenario_id']) for x in (left, right)]
    plan = preview(c, left, right)
    choices = {'point:'+pid: 'source', 'line:'+lid: 'target'} if conflict else {}
    assert set(plan['conflicts']) == set(choices)
    r = c.post('/api/engineering/merge', json=dict(plan, name='ordered merge', resolutions=choices))
    assert r.status_code == 200, r.text
    saved = store.get_scenario(service.repository.path, r.json()['scenario_id'])
    state = saved['metadata']['thesis_state']
    for collection in ('points', 'lines', 'angles'):
        assert [x['id'] for x in state[collection]] == [x['id'] for x in target[collection]]
    point = next(x for x in state['points'] if x['id'] == pid)
    assert point['name'] == ('source point' if conflict else 'target point')
    assert point['fixed'] == (not base['points'][0]['fixed'])
    lines = {x['id']: x for x in state['lines']}
    assert lines[lid]['length'] == 111.25
    assert lines[other_lid]['length'] == 333.75
    assert [store.get_scenario(service.repository.path, x['scenario_id']) for x in (left, right)] == parents
    assert c.post('/api/engineering/open/'+saved['id'], json={}).status_code == 200
    assert service.state['points'] == state['points']
    assert service.state['lines'] == state['lines']



@pytest.mark.parametrize('mutation', ['duplicate', 'missing_id', 'added', 'deleted', 'station', 'backsight', 'foresight', 'extra'])
def test_angle_order_merge_declines_authored_structure_changes(bridge, mutation):
    from ctrlnet.webmap.scenario_tree import _merge_point_coordinates
    _, service = bridge
    base = copy.deepcopy(service.state)
    assert len(base['angles']) > 1
    target, source = copy.deepcopy(base), copy.deepcopy(base)
    target['points'][0]['name'] = 'target name'
    source['angles'].reverse()
    angle = source['angles'][0]
    if mutation == 'duplicate':
        angle['id'] = source['angles'][1]['id']
    elif mutation == 'missing_id':
        angle.pop('id')
    elif mutation == 'added':
        extra = copy.deepcopy(angle)
        extra['id'] = 'new-angle'
        source['angles'].append(extra)
    elif mutation == 'deleted':
        source['angles'].pop()
    else:
        angle[mutation] = 'changed'
    assert _merge_point_coordinates(base, target, source) is None


@pytest.mark.parametrize('choice', [None, 'target', 'source'])
def test_angle_name_merge_and_choices(bridge, choice):
    c, service = bridge
    root = save(c, 'base')
    aid = service.state['angles'][0]['id']
    service.state['points'][0]['name'] = 'retained point'
    if choice:
        service.state['angles'][0]['name'] = 801
    left = save(c, 'target', root)
    target = copy.deepcopy(service.state)
    c.post('/api/engineering/open/'+root['scenario_id'], json={})
    service.state['angles'][0]['name'] = 802
    service.state['angles'].reverse()
    right = save(c, 'source', root)
    parents = [store.get_scenario(service.repository.path, x['scenario_id']) for x in (left, right)]
    plan = preview(c, left, right)
    resolutions = {'angle:'+aid: choice} if choice else {}
    assert plan['conflicts'] == list(resolutions)
    if choice:
        before = c.get('/api/engineering/projects').json()
        for bad in ({}, {'angle:'+aid: 'invalid'}, dict(resolutions, topology='target')):
            assert c.post('/api/engineering/merge', json=dict(plan, name='bad', resolutions=bad)).status_code == 400
            assert c.get('/api/engineering/projects').json() == before
    r = c.post('/api/engineering/merge', json=dict(plan, name='angle merge', resolutions=resolutions))
    assert r.status_code == 200, r.text
    state = store.get_scenario(service.repository.path, r.json()['scenario_id'])['metadata']['thesis_state']
    assert [a['id'] for a in state['angles']] == [a['id'] for a in target['angles']]
    assert next(a for a in state['angles'] if a['id'] == aid)['name'] == (801 if choice == 'target' else 802)
    assert state['points'][0]['name'] == 'retained point'
    assert [store.get_scenario(service.repository.path, x['scenario_id']) for x in (left, right)] == parents
    assert c.post('/api/engineering/open/'+r.json()['scenario_id'], json={}).status_code == 200
    assert service.state['angles'] == state['angles']


@pytest.mark.parametrize('choice', [None, 'target', 'source'])
def test_line_name_merge_and_choices(bridge, choice):
    c, service = bridge
    root = save(c, 'base')
    lid = service.state['lines'][0]['id']
    service.state['points'][0]['name'] = 'retained point'
    if choice:
        service.state['lines'][0]['name'] = 901
    left = save(c, 'target', root)
    target = copy.deepcopy(service.state)
    c.post('/api/engineering/open/'+root['scenario_id'], json={})
    service.state['lines'][0]['name'] = 902
    service.state['lines'].reverse()
    right = save(c, 'source', root)
    parents = [store.get_scenario(service.repository.path, x['scenario_id']) for x in (left, right)]
    plan = preview(c, left, right)
    resolutions = {'line:'+lid: choice} if choice else {}
    assert plan['conflicts'] == list(resolutions)
    if choice:
        before = c.get('/api/engineering/projects').json()
        for bad in ({}, {'line:'+lid: 'invalid'}, dict(resolutions, topology='target')):
            assert c.post('/api/engineering/merge', json=dict(plan, name='bad', resolutions=bad)).status_code == 400
            assert c.get('/api/engineering/projects').json() == before
    r = c.post('/api/engineering/merge', json=dict(plan, name='line merge', resolutions=resolutions))
    assert r.status_code == 200, r.text
    state = store.get_scenario(service.repository.path, r.json()['scenario_id'])['metadata']['thesis_state']
    assert [a['id'] for a in state['lines']] == [a['id'] for a in target['lines']]
    assert next(a for a in state['lines'] if a['id'] == lid)['name'] == (901 if choice == 'target' else 902)
    assert state['points'][0]['name'] == 'retained point'
    assert [store.get_scenario(service.repository.path, x['scenario_id']) for x in (left, right)] == parents
    assert c.post('/api/engineering/open/'+r.json()['scenario_id'], json={}).status_code == 200
    assert service.state['lines'] == state['lines']


@pytest.mark.parametrize('conflict', ['name', 'length', None])
@pytest.mark.parametrize('choice', ['target', 'source'])
def test_line_name_with_measurement_merge(bridge, conflict, choice):
    c, service = bridge
    root = save(c, 'base')
    lid = service.state['lines'][0]['id']
    service.state['lines'][0]['name'] = 901
    if conflict == 'length':
        service.state['lines'][0].update(length=111.25, _keep_length=True)
    left = save(c, 'target', root)
    c.post('/api/engineering/open/'+root['scenario_id'], json={})
    service.state['lines'][0].update(length=222.5, _keep_length=True)
    if conflict == 'name':
        service.state['lines'][0]['name'] = 902
    right = save(c, 'source', root)
    parents = [store.get_scenario(service.repository.path, x['scenario_id']) for x in (left, right)]
    plan = preview(c, left, right)
    resolutions = {'line:'+lid: choice} if conflict else {}
    assert plan['conflicts'] == list(resolutions)
    r = c.post('/api/engineering/merge', json=dict(plan, name='line fields', resolutions=resolutions))
    assert r.status_code == 200, r.text
    state = store.get_scenario(service.repository.path, r.json()['scenario_id'])['metadata']['thesis_state']
    line = next(x for x in state['lines'] if x['id'] == lid)
    if conflict:
        assert line == parents[0 if choice == 'target' else 1]['metadata']['thesis_state']['lines'][0]
    else:
        assert line['name'] == 901
        assert line['length'] == 222.5
    assert [store.get_scenario(service.repository.path, x['scenario_id']) for x in (left, right)] == parents
