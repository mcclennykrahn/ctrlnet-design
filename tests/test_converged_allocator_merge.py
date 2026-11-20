"""Converged criss-cross tips retain every best base's consumed IDs."""
import copy
import pytest
from test_v08 import bridge
from test_scenario_tree import save, preview
from test_equivalent_merge_bases import merge
from ctrlnet import store


@pytest.mark.parametrize('reverse', [False, True])
@pytest.mark.parametrize('reordered', [False, True])
@pytest.mark.parametrize('structural_drift', [False, True])
@pytest.mark.parametrize('guard', [None, 'unknown_seq', 'authored', 'invalid', 'stale'])
def test_converged_tips_keep_all_base_counters(bridge, reverse, structural_drift, guard, reordered):
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
    for i, parent in enumerate((left, right), 1):
        c.post('/api/engineering/open/'+parent['scenario_id'], json={})
        service.state['seq'] = copy.deepcopy(original['seq'])
        if structural_drift:
            # Converged deletion of a referenced point and its incident geometry
            # is safe without replaying the differing ancestor edits.
            state = service.state
            pid = state['points'][-1]['id']
            state['points'] = [p for p in state['points'] if p['id'] != pid]
            state['lines'] = [l for l in state['lines'] if pid not in (l['from'], l['to'])]
            state['angles'] = [a for a in state['angles'] if pid not in
                               (a['station'], a['backsight'], a['foresight'])]
            for key in ('observed_edges', 'added_edges', 'observed_angles', 'added_angles'):
                state['network'][key] = []
            state['seq']['point'] += i
            state['seq']['line'] += i*50
        if i == 2 and reordered:
            for collection in ('points', 'lines', 'angles'):
                service.state[collection].reverse()
        if i == 2:
            if guard == 'unknown_seq':
                service.state['seq']['future'] = 1
            elif guard == 'authored':
                service.state['future_setting'] = 'changed'
            elif guard == 'invalid':
                service.state['seq']['point'] = True
        tips.append(save(c, 'reset', parent))
    if reverse:
        tips.reverse()
    before = [store.get_scenario(service.repository.path, x['scenario_id']) for x in (a,b,*tips)]
    plan = preview(c, *tips)
    if guard in ('unknown_seq', 'authored', 'invalid'):
        assert plan['conflicts'] == ['topology']
        return
    assert plan['conflicts'] == []
    assert set(plan['bases']) == {a['scenario_id'], b['scenario_id']}
    assert len(plan['versions']) == 4
    if guard == 'stale':
        sid = b['scenario_id']
        assert c.post('/api/engineering/rename/'+sid,
                      json=dict(name='changed', version=plan['versions'][sid])).status_code == 200
        assert c.post('/api/engineering/merge', json=dict(plan, name='stale', resolutions={})).status_code == 409
        return
    result = merge(c, *tips, 'converged')
    c.post('/api/engineering/open/'+result['scenario_id'], json={})
    assert service.state['seq'] == dict(original['seq'], point=original['seq']['point']+20,
        line=original['seq']['line']+(100 if structural_drift else 30), angle=original['seq']['angle']+40)
    expected_x = original['points'][0]['x']+1
    assert next(p for p in service.state['points'] if p['id'] == original['points'][0]['id'])['x'] == expected_x
    target_state = before[2]['metadata']['thesis_state']
    for collection in ('points', 'lines', 'angles'):
        assert [p['id'] for p in service.state[collection]] == [p['id'] for p in target_state[collection]]
    if structural_drift:
        assert pid not in [p['id'] for p in service.state['points']]
    assert before == [store.get_scenario(service.repository.path, x['scenario_id']) for x in (a,b,*tips)]
