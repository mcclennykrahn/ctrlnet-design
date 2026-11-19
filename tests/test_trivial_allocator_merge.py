"""Content convergence must not recycle ancestor stable IDs."""
import copy
import pytest
from test_v08 import bridge
from test_scenario_tree import save, preview
from test_equivalent_merge_bases import merge
from ctrlnet import store


@pytest.mark.parametrize('equivalent', [False, True])
@pytest.mark.parametrize('reverse', [False, True])
@pytest.mark.parametrize('mode', ['converged', 'unchanged', 'structural', 'stale'])
def test_trivial_merge_keeps_ancestor_allocators(bridge, equivalent, reverse, mode):
    c, service = bridge
    service.state['seq'].update(point=200, line=300, angle=400)
    root = save(c, 'root')
    baseline = copy.deepcopy(service.state)
    bases = [root]
    parents = [root, root]
    if equivalent:
        a = save(c, 'a', root)
        c.post('/api/engineering/open/'+root['scenario_id'], json={})
        b = save(c, 'b', root)
        parents = [merge(c, a, b, 'left'), merge(c, b, a, 'right')]
        bases = [a, b]
    tips = []
    for i, parent in enumerate(parents):
        c.post('/api/engineering/open/'+parent['scenario_id'], json={})
        if mode != 'unchanged' or i == 0:
            service.state['seq'].update(point=50, line=60, angle=70)
            service.state['name'] = 'converged title'
        if mode == 'structural':
            service.state['angles'] = []
            service.state['network']['observed_angles'] = []
            service.state['network']['added_angles'] = []
        tips.append(save(c, 'tip', parent))
    if reverse:
        tips.reverse()
    before = [store.get_scenario(service.repository.path, x['scenario_id']) for x in [*bases, *tips]]
    plan = preview(c, *tips)
    assert plan['conflicts'] == []
    assert set(plan['bases']) == {x['scenario_id'] for x in bases}
    if mode == 'stale':
        sid = bases[-1]['scenario_id']
        assert c.post('/api/engineering/rename/'+sid, json=dict(name='renamed', version=plan['versions'][sid])).status_code == 200
        assert c.post('/api/engineering/merge', json=dict(plan, name='stale', resolutions={})).status_code == 409
        return
    result = merge(c, *tips, 'merged')
    assert c.post('/api/engineering/open/'+result['scenario_id'], json={}).status_code == 200
    assert service.state['seq'] == baseline['seq']
    assert service.state['name'] == 'converged title'
    assert service.state['points'] == baseline['points']
    if mode == 'structural':
        assert service.state['angles'] == []
    assert before == [store.get_scenario(service.repository.path, x['scenario_id']) for x in [*bases, *tips]]
