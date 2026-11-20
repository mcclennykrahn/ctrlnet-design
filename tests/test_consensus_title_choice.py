"""Title choices retain independently verified all-base geometry consensus."""
import copy
import pytest
from test_v08 import bridge
from test_scenario_tree import save, preview
from test_equivalent_merge_bases import merge
from ctrlnet import store


def tips(c, service, guard=None):
    root = save(c, 'root')
    original_seq = copy.deepcopy(service.state['seq'])
    service.state['seq']['point'] += 40
    a = save(c, 'a', root)
    c.post('/api/engineering/open/'+root['scenario_id'], json={})
    service.state['seq']['line'] += 50
    service.state['seq']['angle'] += 60
    service.state['points'][0]['x'] += 1
    b = save(c, 'b', root)
    left = merge(c, a, b, 'left')
    right = merge(c, b, a, 'right')
    children = []
    for i, parent in enumerate((left, right)):
        c.post('/api/engineering/open/'+parent['scenario_id'], json={})
        service.state['name'] = ['Target title', 'Source title'][i]
        service.state['points'][i+1]['x'] += 10
        service.state['seq'] = copy.deepcopy(original_seq)
        service.state['seq'][['point', 'line'][i]] += 30
        if guard == 'point':
            service.state['points'][3]['x'] += i+1
        elif guard == 'unknown' and i:
            service.state['future_authored'] = True
        elif guard == 'invalid' and i:
            service.state['seq']['angle'] = True
        children.append(save(c, 'tip', parent))
    return a, b, children


@pytest.mark.parametrize('reverse', [False, True])
@pytest.mark.parametrize('choice', ['target', 'source'])
def test_consensus_title_choice_reopen(bridge, reverse, choice):
    c, service = bridge
    a, b, children = tips(c, service)
    if reverse:
        children.reverse()
    rows = [store.get_scenario(service.repository.path, x['scenario_id']) for x in (a,b,*children)]
    plan = preview(c, *children)
    assert plan['conflicts'] == ['title']
    assert plan['differing_base_units'] == ['topology']
    assert set(plan['bases']) == {a['scenario_id'], b['scenario_id']}
    assert len(plan['versions']) == 4
    before = c.get('/api/engineering/projects').json()
    for resolutions in ({}, {'title': 'bad'}, {'title': choice, 'topology': choice}):
        assert c.post('/api/engineering/merge', json=dict(plan, name='bad', resolutions=resolutions)).status_code == 400
        assert c.get('/api/engineering/projects').json() == before
    result = c.post('/api/engineering/merge', json=dict(plan, name='consensus', resolutions={'title': choice}))
    assert result.status_code == 200, result.text
    saved = store.get_scenario(service.repository.path, result.json()['scenario_id'])
    assert saved['metadata']['merge_resolutions'] == {'title': choice}
    assert saved['metadata']['merge_bases'] == plan['bases']
    assert saved['metadata']['merge_versions'] == plan['versions']
    assert c.post('/api/engineering/open/'+saved['id'], json={}).status_code == 200
    state = service.state
    expected = rows[2 if choice == 'target' else 3]['metadata']['thesis_state']
    assert state['name'] == expected['name']
    for index in (1, 2):
        assert state['points'][index]['x'] == rows[0]['metadata']['thesis_state']['points'][index]['x']+10
    for key in ('point', 'line', 'angle'):
        assert state['seq'][key] == max(row['metadata']['thesis_state']['seq'][key] for row in rows)
    for collection in ('points', 'lines', 'angles'):
        assert [v['id'] for v in state[collection]] == [v['id'] for v in rows[2]['metadata']['thesis_state'][collection]]
    assert rows == [store.get_scenario(service.repository.path, x['scenario_id']) for x in (a,b,*children)]


@pytest.mark.parametrize('guard', ['point', 'unknown', 'invalid'])
def test_non_title_conflicts_stay_whole_topology(bridge, guard):
    c, service = bridge
    _, _, children = tips(c, service, guard)
    assert preview(c, *children)['conflicts'] == ['topology']


@pytest.mark.parametrize('base_index', [0, 1])
def test_title_choice_guards_every_base(bridge, base_index):
    c, service = bridge
    _, _, children = tips(c, service)
    plan = preview(c, *children)
    assert plan['conflicts'] == ['title']
    sid = plan['bases'][base_index]
    assert c.post('/api/engineering/rename/'+sid, json=dict(name='changed', version=plan['versions'][sid])).status_code == 200
    before = c.get('/api/engineering/projects').json()
    assert c.post('/api/engineering/merge', json=dict(plan, name='stale', resolutions={'title':'source'})).status_code == 409
    assert c.get('/api/engineering/projects').json() == before
