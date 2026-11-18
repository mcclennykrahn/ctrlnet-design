"""Differing-base consensus preserves counters from every candidate ancestor."""
import copy
import pytest
from test_v08 import bridge
from test_scenario_tree import save, preview
from test_equivalent_merge_bases import merge
from ctrlnet import store


@pytest.mark.parametrize('reverse', [False, True])
@pytest.mark.parametrize('stale', [None, 0, 1])
def test_all_base_allocator_consensus(bridge, reverse, stale):
    c, service = bridge
    root = save(c, 'root')
    original = copy.deepcopy(service.state)
    ancestors = []
    for i in range(2):
        c.post('/api/engineering/open/'+root['scenario_id'], json={})
        service.state['points'][0]['x'] += i
        service.state['seq']['point'] += 20*(i+1)
        service.state['seq']['line'] += 20*(2-i)
        ancestors.append(save(c, 'ancestor', root))
    a, b = ancestors
    left = merge(c, a, b, 'left')
    right = merge(c, b, a, 'right')
    tips = []
    expected = {}
    for i, parent in enumerate((left, right), 1):
        c.post('/api/engineering/open/'+parent['scenario_id'], json={})
        service.state['seq'] = copy.deepcopy(original['seq'])
        service.state['seq']['angle'] += i
        service.state['points'][i]['x'] += 7
        expected[i] = copy.deepcopy(service.state['points'][i])
        tips.append(save(c, 'tip', parent))
    if reverse:
        tips.reverse()
    plan = preview(c, *tips)
    assert plan['conflicts'] == []
    assert set(plan['bases']) == {a['scenario_id'], b['scenario_id']}
    if stale is not None:
        sid = ancestors[stale]['scenario_id']
        assert c.post('/api/engineering/rename/'+sid, json=dict(name='changed', version=plan['versions'][sid])).status_code == 200
    r = c.post('/api/engineering/merge', json=dict(plan, name='consensus', resolutions={}))
    assert r.status_code == (409 if stale is not None else 200), r.text
    if stale is not None:
        return
    saved = store.get_scenario(service.repository.path, r.json()['scenario_id'])
    state = saved['metadata']['thesis_state']
    assert state['seq'] == dict(original['seq'], point=original['seq']['point']+40,
                                line=original['seq']['line']+40, angle=original['seq']['angle']+2)
    assert saved['metadata']['merge_versions'] == plan['versions']
    assert [p['id'] for p in state['points']] == [p['id'] for p in original['points']]
    for i, point in expected.items():
        assert state['points'][i] == point
