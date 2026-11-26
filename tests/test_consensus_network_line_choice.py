"""Network plus one whole-line choice requires all four outcomes to agree."""
import pytest
from test_v08 import bridge
from test_consensus_line_choice import line_tips
from test_scenario_tree import preview
from ctrlnet import store
from ctrlnet.webmap import scenario_tree as tree


@pytest.mark.parametrize('field', ['name', 'length'])
@pytest.mark.parametrize('network', ['target', 'source'])
@pytest.mark.parametrize('reverse', [False, True])
@pytest.mark.parametrize('choice', ['target', 'source'])
def test_joint_choice_reopen(bridge, reverse, choice, field, network):
    c, service = bridge
    a, b, children = line_tips(c, service, 'network', field=field)
    if reverse:
        children.reverse()
    rows = [store.get_scenario(service.repository.path, x['scenario_id']) for x in (a,b,*children)]
    states = [r['metadata']['thesis_state'] for r in rows]
    key = 'line:'+states[2]['lines'][0]['id']
    plan = preview(c, *children)
    assert plan['conflicts'] == ['network', key]
    assert plan['differing_base_units'] == ['topology']
    assert set(plan['bases']) == {a['scenario_id'], b['scenario_id']}
    before = c.get('/api/engineering/projects').json()
    for resolutions in ({}, {key:'bad'}, {key:choice, 'topology':choice}):
        assert c.post('/api/engineering/merge', json=dict(plan,name='bad',resolutions=resolutions)).status_code == 400
        assert c.get('/api/engineering/projects').json() == before
    r = c.post('/api/engineering/merge', json=dict(plan,name='line consensus',resolutions={'network':network,key:choice}))
    assert r.status_code == 200, r.text
    saved = store.get_scenario(service.repository.path, r.json()['scenario_id'])
    assert saved['metadata']['merge_versions'] == plan['versions']
    assert saved['metadata']['merge_bases'] == plan['bases']
    assert saved['metadata']['merge_resolutions'] == {'network':network,key:choice}
    assert c.post('/api/engineering/open/'+saved['id'],json={}).status_code == 200
    state = service.state
    assert state['network'] == states[2 if network == 'target' else 3]['network']
    line = state['lines'][0]
    expected = states[2 if choice == 'target' else 3]['lines'][0]
    assert line == expected
    for i in (1,2):
        assert state['points'][i]['y'] == states[0]['points'][i]['y']+10
    assert [p['id'] for p in state['points']] == [p['id'] for p in states[2]['points']]
    for k in ('point','line','angle'):
        assert state['seq'][k] == max(s['seq'][k] for s in states)
    assert rows == [store.get_scenario(service.repository.path, x['scenario_id']) for x in (a,b,*children)]


@pytest.mark.parametrize('choice',['target','source'])
@pytest.mark.parametrize('network',['target','source'])
def test_all_four_outcomes_checked(bridge, monkeypatch, choice, network):
    c, service = bridge
    _, _, children = line_tips(c,service,'network')
    key = 'line:'+service.state['lines'][0]['id']
    real = tree._merge_point_coordinates
    def poisoned(base,target,source,point_conflicts=None,choices=None):
        result = real(base,target,source,point_conflicts,choices)
        if result and choices and choices.get(key) == choice and choices.get('network') == network and base['points'][0]['x'] == target['points'][0]['x']:
            result['points'][1]['y'] += 123
        return result
    monkeypatch.setattr(tree,'_merge_point_coordinates',poisoned)
    assert preview(c,*children)['conflicts'] == ['topology']


@pytest.mark.parametrize('index',[0,1])
def test_every_base_version_guarded(bridge,index):
    c, service = bridge
    _, _, children = line_tips(c,service,'network')
    plan = preview(c,*children)
    key = plan['conflicts'][1]
    sid = plan['bases'][index]
    c.post('/api/engineering/rename/'+sid,json=dict(name='changed',version=plan['versions'][sid]))
    before = c.get('/api/engineering/projects').json()
    assert c.post('/api/engineering/merge',json=dict(plan,name='stale',resolutions={'network':'target',key:'source'})).status_code == 409
    assert c.get('/api/engineering/projects').json() == before


@pytest.mark.parametrize('extra', ['line', 'point', 'angle', 'title', 'unknown'])
def test_other_mixed_conflicts_conservative(bridge, extra):
    from test_scenario_tree import save
    c, service = bridge
    _, _, children = line_tips(c,service,'network')
    descendants = []
    for i, parent in enumerate(children):
        assert c.post('/api/engineering/open/'+parent['scenario_id'],json={}).status_code == 200
        if extra == 'line':
            service.state['lines'][1]['name'] = 901+i
        elif extra == 'point':
            service.state['points'][0]['y'] += 2+i
        elif extra == 'angle':
            service.state['angles'][0]['name'] = 901+i
        elif extra == 'title':
            service.state['name'] = 'title '+str(i)
        elif i:
            service.state['future_authored'] = True
        descendants.append(save(c,'extra conflict',parent))
    assert preview(c,*descendants)['conflicts'] == ['topology']



@pytest.mark.parametrize('reverse', [False, True])
@pytest.mark.parametrize('collision_branch', [0, 1])
def test_duplicate_alternate_endpoint_outcome_rejected(bridge, reverse, collision_branch):
    from test_scenario_tree import save
    c, service = bridge
    _, _, tips = line_tips(c, service, 'network')
    children = []
    for i, parent in enumerate(tips):
        assert c.post('/api/engineering/open/'+parent['scenario_id'], json={}).status_code == 200
        pairs = {frozenset((line['from'], line['to'])) for line in service.state['lines']}
        available = [(a['id'], b['id']) for a in service.state['points']
                     for b in service.state['points'] if a['id'] < b['id']
                     and frozenset((a['id'], b['id'])) not in pairs]
        first, second = service.state['lines'][:2]
        first.update(zip(('from', 'to'), available[i]))
        if i == collision_branch:
            second.update(zip(('from', 'to'), available[1-i]))
        # Each tip is valid; combining the other line choice with the one-sided
        # second-line edit creates a duplicate pair in just one outcome.
        tip_pairs = [frozenset((line['from'], line['to'])) for line in service.state['lines']]
        assert len(set(tip_pairs)) == len(tip_pairs)
        children.append(save(c, 'alternate endpoint collision', parent))
    if reverse:
        children.reverse()
    plan = preview(c, *children)
    assert plan['conflicts'] == ['topology']
    before = c.get('/api/engineering/projects').json()
    key = 'line:'+service.state['lines'][0]['id']
    # Even choosing the safe branch must not expose partially safe field choices.
    for choice in ('target', 'source'):
        response = c.post('/api/engineering/merge', json=dict(
            plan, name='unsafe', resolutions={'network':'target', key:choice}))
        assert response.status_code == 400
        assert c.get('/api/engineering/projects').json() == before
