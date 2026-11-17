"""Allocator drift merges without reusing consumed stable IDs."""
import copy
import pytest
from test_v08 import bridge
from test_scenario_tree import save, preview
from ctrlnet import store
from ctrlnet.webmap.scenario_tree import _merge_point_coordinates


@pytest.mark.parametrize('reverse', [False, True])
def test_allocator_drift_preserves_edits_and_high_water(bridge, reverse):
    c, service = bridge
    root = save(c, 'root')
    original = copy.deepcopy(service.state)
    tips = []
    for i in range(2):
        c.post('/api/engineering/open/'+root['scenario_id'], json={})
        service.state['points'][i]['x'] += 7
        service.state['seq']['point'] += 100*(i+1)
        service.state['seq']['line'] += 100*(2-i)
        tips.append(save(c, 'tip', root))
    if reverse:
        tips.reverse()
    plan = preview(c, *tips)
    assert plan['conflicts'] == []
    r = c.post('/api/engineering/merge', json=dict(plan, name='merged', resolutions={}))
    assert r.status_code == 200, r.text
    state = store.get_scenario(service.repository.path, r.json()['scenario_id'])['metadata']['thesis_state']
    assert state['seq'] == dict(original['seq'], point=original['seq']['point']+200, line=original['seq']['line']+200)
    for i in range(2):
        assert state['points'][i]['x'] == original['points'][i]['x']+7


@pytest.mark.parametrize('bad', [True, -1, 1.5, None])
def test_invalid_allocator_remains_conservative(bridge, bad):
    _, service = bridge
    base = copy.deepcopy(service.state)
    target, source = copy.deepcopy(base), copy.deepcopy(base)
    target['seq']['point'] = bad
    assert _merge_point_coordinates(base, target, source) is None


def test_unknown_allocator_field_and_input_immutability(bridge):
    _, service = bridge
    states = [copy.deepcopy(service.state) for _ in range(3)]
    states[1]['seq']['future'] = 1
    before = copy.deepcopy(states)
    assert _merge_point_coordinates(*states) is None
    assert states == before
