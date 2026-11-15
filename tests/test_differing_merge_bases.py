"""Differing best bases require whole-unit choices, never arbitrary-base merges."""
import copy
import pytest
from test_v08 import bridge, GNSS
from test_scenario_tree import save, preview
from test_equivalent_merge_bases import cross
from ctrlnet import store


@pytest.mark.parametrize('mutation', ['point', 'gnss', 'unknown', 'order'])
@pytest.mark.parametrize('choice', ['target', 'source'])
def test_differing_bases_explicit_whole_unit_reopen(bridge, mutation, choice):
    c, service = bridge
    a, b, left, right = cross(c, service, mutation)
    # The criss-cross tips initially converge. Diverge both tips independently.
    children = []
    for i, parent in enumerate((left, right)):
        c.post('/api/engineering/open/'+parent['scenario_id'], json={})
        service.state['points'][i]['x'] += 10 + i
        children.append(save(c, 'child', parent, [dict(GNSS, sigma_E=0.01+i)] if mutation == 'gnss' else None))
    left, right = children
    unit = 'gnss' if mutation == 'gnss' else 'topology'
    plan = preview(c, left, right)
    assert plan['conflicts'] == [unit]
    assert plan['differing_base_units'] == [unit]
    assert preview(c, right, left)['conflicts'] == [unit]
    assert plan['bases'] == sorted([a['scenario_id'], b['scenario_id']])
    assert set(plan['versions']) == set(plan['bases'] + [left['scenario_id'], right['scenario_id']])
    before = c.get('/api/engineering/projects').json()
    for resolutions in ({}, {unit: 'invalid'}, {unit: choice, 'point:bad': 'target'}):
        r = c.post('/api/engineering/merge', json=dict(plan, name='bad', resolutions=resolutions))
        assert r.status_code == 400, r.text
        assert c.get('/api/engineering/projects').json() == before
    selected = left if choice == 'target' else right
    expected = store.get_scenario(service.repository.path, selected['scenario_id'])
    r = c.post('/api/engineering/merge', json=dict(plan, name='resolved', resolutions={unit: choice}))
    assert r.status_code == 200, r.text
    result = store.get_scenario(service.repository.path, r.json()['scenario_id'])
    assert result['metadata']['merge_bases'] == plan['bases']
    assert result['metadata']['merge_versions'] == plan['versions']
    assert result['metadata']['merge_resolutions'] == {unit: choice}
    c.post('/api/engineering/open/'+r.json()['scenario_id'], json={})
    if unit == 'topology':
        from ctrlnet.webmap.thesis_web import _ensure_geometry, _refresh_derived
        state = copy.deepcopy(expected['metadata']['thesis_state'])
        _ensure_geometry(state)
        _refresh_derived(state)
        for field in ('points', 'lines', 'angles', 'seq', 'network'):
            assert service.state[field] == state[field]
    else:
        from ctrlnet.webmap.scenario_tree import _units
        assert _units(result)['gnss'] == _units(expected)['gnss']
        for i, parent in enumerate((left, right)):
            point = store.get_scenario(service.repository.path, parent['scenario_id'])[
                'metadata']['thesis_state']['points'][i]
            assert service.state['points'][i] == point


@pytest.mark.parametrize('base_index', [0, 1])
def test_differing_base_version_guards(bridge, base_index):
    c, service = bridge
    a, b, left, right = cross(c, service, 'point')
    c.post('/api/engineering/open/'+left['scenario_id'], json={})
    service.state['points'][1]['x'] += 3
    left = save(c, 'child', left)
    plan = preview(c, left, right)
    assert plan['conflicts'] == ['topology']
    sid = plan['bases'][base_index]
    c.post('/api/engineering/rename/'+sid, json=dict(name='changed', version=plan['versions'][sid]))
    before = c.get('/api/engineering/projects').json()
    r = c.post('/api/engineering/merge', json=dict(plan, name='stale', resolutions={'topology': 'source'}))
    assert r.status_code == 409
    assert c.get('/api/engineering/projects').json() == before
