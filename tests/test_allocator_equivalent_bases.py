"""Allocator-only ancestor disagreement retains independent field choices."""
import copy
import pytest
from test_v08 import bridge
from test_scenario_tree import save, preview
from test_equivalent_merge_bases import merge
from ctrlnet import store


@pytest.mark.parametrize('reverse', [False, True])
@pytest.mark.parametrize('choice', ['target', 'source', 'stale'])
def test_allocator_equivalent_bases_field_choices(bridge, reverse, choice):
    c, service = bridge
    root = save(c, 'root')
    service.state['seq'].update(point=200, line=300, angle=400)
    a = save(c, 'a', root)
    c.post('/api/engineering/open/'+root['scenario_id'], json={})
    service.state['seq'].update(point=500, line=100, angle=200)
    b = save(c, 'b', root)
    left, right = merge(c, a, b, 'left'), merge(c, b, a, 'right')
    tips = []
    expected = []
    for i, parent in enumerate((left, right)):
        c.post('/api/engineering/open/'+parent['scenario_id'], json={})
        service.state['seq'].update(point=20, line=30, angle=40)
        service.state['name'] = 'title '+str(i)
        service.state['points'][i]['x'] += 7
        expected.append(copy.deepcopy(service.state['points'][i]))
        tips.append(save(c, 'tip', parent))
    if reverse:
        tips.reverse()
    before = [store.get_scenario(service.repository.path, x['scenario_id']) for x in (a,b)]
    plan = preview(c, *tips)
    assert plan['differing_base_units'] == []
    assert plan['conflicts'] == ['title']
    if choice == 'stale':
        sid = plan['bases'][-1]
        assert c.post('/api/engineering/rename/'+sid, json=dict(name='renamed', version=plan['versions'][sid])).status_code == 200
        assert c.post('/api/engineering/merge', json=dict(plan, name='stale', resolutions={'title':'target'})).status_code == 409
        return
    r = c.post('/api/engineering/merge', json=dict(plan, name='merged', resolutions={'title':choice}))
    assert r.status_code == 200, r.text
    saved = store.get_scenario(service.repository.path, r.json()['scenario_id'])
    state = saved['metadata']['thesis_state']
    assert state['seq'] == dict(point=500, line=300, angle=400)
    for i in range(2):
        assert state['points'][i] == expected[i]
    chosen = tips[0 if choice == 'target' else 1]
    assert state['name'] == store.get_scenario(service.repository.path, chosen['scenario_id'])['metadata']['thesis_state']['name']
    assert before == [store.get_scenario(service.repository.path, x['scenario_id']) for x in (a,b)]
    assert set(saved['metadata']['merge_bases']) == {a['scenario_id'], b['scenario_id']}
