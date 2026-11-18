"""Converged criss-cross tips retain every best base's consumed IDs."""
import copy
import pytest
from test_v08 import bridge
from test_scenario_tree import save, preview
from test_equivalent_merge_bases import merge
from ctrlnet import store


@pytest.mark.parametrize('reverse', [False, True])
def test_converged_tips_keep_all_base_counters(bridge, reverse):
    c, service = bridge
    root = save(c, 'root')
    original = copy.deepcopy(service.state)
    service.state['seq']['point'] += 20
    a = save(c, 'a', root)
    c.post('/api/engineering/open/'+root['scenario_id'], json={})
    service.state['seq']['line'] += 30
    service.state['seq']['angle'] += 40
    service.state['points'][0]['x'] += 1
    b = save(c, 'b', root)
    left = merge(c, a, b, 'left')
    right = merge(c, b, a, 'right')
    tips = []
    for parent in (left, right):
        c.post('/api/engineering/open/'+parent['scenario_id'], json={})
        service.state['seq'] = copy.deepcopy(original['seq'])
        tips.append(save(c, 'reset', parent))
    if reverse:
        tips.reverse()
    before = [store.get_scenario(service.repository.path, x['scenario_id']) for x in (a,b,*tips)]
    plan = preview(c, *tips)
    assert plan['conflicts'] == []
    assert set(plan['bases']) == {a['scenario_id'], b['scenario_id']}
    assert len(plan['versions']) == 4
    result = merge(c, *tips, 'converged')
    c.post('/api/engineering/open/'+result['scenario_id'], json={})
    assert service.state['seq'] == dict(original['seq'], point=original['seq']['point']+20,
        line=original['seq']['line']+30, angle=original['seq']['angle']+40)
    assert service.state['points'][0]['x'] == original['points'][0]['x']+1
    assert before == [store.get_scenario(service.repository.path, x['scenario_id']) for x in (a,b,*tips)]
