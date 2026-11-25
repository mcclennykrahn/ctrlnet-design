"""Differing bases may agree on both outcomes of a network-only conflict."""
import copy
import pytest
from test_v08 import bridge
from test_consensus_title_choice import tips
from test_scenario_tree import save, preview
from ctrlnet import store


def network_tips(c, service, guard=None):
    a, b, children = tips(c, service, guard)
    result = []
    for i, child in enumerate(children):
        c.post('/api/engineering/open/'+child['scenario_id'], json={})
        service.state['name'] = 'Shared title'
        service.state['network']['tolerance_mm'] = 35+i
        if guard == 'point':
            # Two point conflicts remain unsupported alongside the network choice.
            service.state['points'][0]['y'] += 50+i
        result.append(save(c, 'network tip', child))
    return a, b, result


@pytest.mark.parametrize('reverse', [False, True])
@pytest.mark.parametrize('choice', ['target', 'source'])
def test_network_consensus_choice(bridge, reverse, choice):
    c, service = bridge
    a, b, children = network_tips(c, service)
    if reverse:
        children.reverse()
    rows = [store.get_scenario(service.repository.path, x['scenario_id']) for x in (a,b,*children)]
    plan = preview(c, *children)
    assert plan['conflicts'] == ['network']
    assert plan['differing_base_units'] == ['topology']
    before = c.get('/api/engineering/projects').json()
    for resolutions in ({}, {'network':'bad'}, {'network':choice, 'title':choice}):
        assert c.post('/api/engineering/merge', json=dict(plan, name='bad', resolutions=resolutions)).status_code == 400
        assert c.get('/api/engineering/projects').json() == before
    r = c.post('/api/engineering/merge', json=dict(plan, name='network consensus', resolutions={'network':choice}))
    assert r.status_code == 200, r.text
    saved = store.get_scenario(service.repository.path, r.json()['scenario_id'])
    assert saved['metadata']['merge_versions'] == plan['versions']
    assert saved['metadata']['merge_resolutions'] == {'network':choice}
    assert c.post('/api/engineering/open/'+saved['id'], json={}).status_code == 200
    expected = rows[2 if choice == 'target' else 3]['metadata']['thesis_state']
    assert service.state['network'] == expected['network']
    for index in (1,2):
        assert service.state['points'][index]['x'] == rows[0]['metadata']['thesis_state']['points'][index]['x']+10
    for key in ('point','line','angle'):
        assert service.state['seq'][key] == max(row['metadata']['thesis_state']['seq'][key] for row in rows)
    assert rows == [store.get_scenario(service.repository.path, x['scenario_id']) for x in (a,b,*children)]


@pytest.mark.parametrize('guard', ['point','unknown','invalid'])
def test_other_conflicts_remain_conservative(bridge, guard):
    c, service = bridge
    _, _, children = network_tips(c, service, guard)
    assert preview(c, *children)['conflicts'] == ['topology']


@pytest.mark.parametrize('index', [0,1])
def test_all_network_consensus_bases_guarded(bridge, index):
    c, service = bridge
    _, _, children = network_tips(c, service)
    plan = preview(c, *children)
    sid = plan['bases'][index]
    assert c.post('/api/engineering/rename/'+sid, json=dict(name='changed', version=plan['versions'][sid])).status_code == 200
    assert c.post('/api/engineering/merge', json=dict(plan, name='stale', resolutions={'network':'source'})).status_code == 409


@pytest.mark.parametrize('reverse', [False, True])
@pytest.mark.parametrize('choice', ['target', 'source'])
def test_network_choice_does_not_restore_deleted_selection(bridge, reverse, choice):
    from test_equivalent_merge_bases import cross
    c, service = bridge
    deleted = service.state['lines'][0]['id']
    service.state['network']['observed_edges'] = [deleted]
    _, _, left, right = cross(c, service, 'point')
    children = []
    for i, parent in enumerate((left, right)):
        c.post('/api/engineering/open/'+parent['scenario_id'], json={})
        service.state['network']['tolerance_mm'] = 35+i
        service.state['points'][i+1]['x'] += 10
        if i == 0:
            service.state['lines'] = [line for line in service.state['lines'] if line['id'] != deleted]
            for key in ('observed_edges', 'added_edges'):
                service.state['network'][key] = [lid for lid in service.state['network'].get(key, []) if lid != deleted]
        children.append(save(c, 'structural tip', parent))
    if reverse:
        children.reverse()
    plan = preview(c, *children)
    assert plan['conflicts'] == ['network']
    r = c.post('/api/engineering/merge', json=dict(plan, name='structural choice', resolutions={'network':choice}))
    assert r.status_code == 200, r.text
    assert c.post('/api/engineering/open/'+r.json()['scenario_id'], json={}).status_code == 200
    assert deleted not in [line['id'] for line in service.state['lines']]
    assert all(deleted not in service.state['network'].get(key, []) for key in ('observed_edges', 'added_edges'))
    assert service.state['network']['tolerance_mm'] == 35+(int(choice == 'source') ^ int(reverse))
