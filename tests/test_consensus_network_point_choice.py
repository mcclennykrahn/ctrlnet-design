"""Network plus one whole-point choice requires all four outcomes to agree."""
import pytest
from test_v08 import bridge
from test_consensus_point_choice import point_tips as original_point_tips
from test_scenario_tree import save, preview
from ctrlnet import store
from ctrlnet.webmap import scenario_tree as tree

def point_tips(c, service):
    a, b, children = original_point_tips(c, service)
    tips = []
    for i, parent in enumerate(children):
        assert c.post("/api/engineering/open/"+parent["scenario_id"], json={}).status_code == 200
        service.state["network"]["observed_angles"] = [angle["id"] for angle in service.state["angles"][:i+1]]
        tips.append(save(c, "network tip", parent))
    return a, b, tips



@pytest.mark.parametrize('network', ['target', 'source'])
@pytest.mark.parametrize('reverse', [False, True])
@pytest.mark.parametrize('choice', ['target', 'source'])
def test_joint_choice_reopen(bridge, reverse, choice, network):
    c, service = bridge
    a, b, children = point_tips(c, service)
    if reverse:
        children.reverse()
    rows = [store.get_scenario(service.repository.path, x['scenario_id']) for x in (a,b,*children)]
    states = [r['metadata']['thesis_state'] for r in rows]
    key = 'point:'+states[2]['points'][3]['id']
    plan = preview(c, *children)
    assert plan['conflicts'] == ['network', key]
    assert plan['differing_base_units'] == ['topology']
    assert set(plan['bases']) == {a['scenario_id'], b['scenario_id']}
    before = c.get('/api/engineering/projects').json()
    for resolutions in ({}, {key:'bad'}, {key:choice, 'topology':choice}):
        assert c.post('/api/engineering/merge', json=dict(plan,name='bad',resolutions=resolutions)).status_code == 400
        assert c.get('/api/engineering/projects').json() == before
    r = c.post('/api/engineering/merge', json=dict(plan,name='point consensus',resolutions={'network':network,key:choice}))
    assert r.status_code == 200, r.text
    saved = store.get_scenario(service.repository.path, r.json()['scenario_id'])
    assert saved['metadata']['merge_versions'] == plan['versions']
    assert saved['metadata']['merge_bases'] == plan['bases']
    assert saved['metadata']['merge_resolutions'] == {'network':network,key:choice}
    assert c.post('/api/engineering/open/'+saved['id'],json={}).status_code == 200
    state = service.state
    assert state['network'] == states[2 if network == 'target' else 3]['network']
    assert state['points'][3] == states[2 if choice == 'target' else 3]['points'][3]
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
    _, _, children = point_tips(c,service)
    key = 'point:'+service.state['points'][3]['id']
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
    _, _, children = point_tips(c,service)
    plan = preview(c,*children)
    key = plan['conflicts'][1]
    sid = plan['bases'][index]
    c.post('/api/engineering/rename/'+sid,json=dict(name='changed',version=plan['versions'][sid]))
    before = c.get('/api/engineering/projects').json()
    assert c.post('/api/engineering/merge',json=dict(plan,name='stale',resolutions={'network':'target',key:'source'})).status_code == 409
    assert c.get('/api/engineering/projects').json() == before


@pytest.mark.parametrize('extra', ['point', 'line', 'angle', 'title', 'unknown'])
def test_other_mixed_conflicts_conservative(bridge, extra):
    c, service = bridge
    _, _, children = point_tips(c,service)
    descendants = []
    for i, parent in enumerate(children):
        assert c.post('/api/engineering/open/'+parent['scenario_id'],json={}).status_code == 200
        if extra == 'angle':
            service.state['angles'][1]['name'] = 901+i
        elif extra == 'point':
            service.state['points'][0]['y'] += 2+i
        elif extra == 'line':
            service.state['lines'][0]['name'] = 901+i
        elif extra == 'title':
            service.state['name'] = 'title '+str(i)
        elif i:
            service.state['future_authored'] = True
        descendants.append(save(c,'extra conflict',parent))
    assert preview(c,*descendants)['conflicts'] == ['topology']
