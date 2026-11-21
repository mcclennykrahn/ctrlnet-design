"""Simultaneous independent title/network choices need all-base consensus."""
import pytest
from test_v08 import bridge
from test_consensus_title_choice import tips
from test_scenario_tree import save, preview
from ctrlnet import store
from ctrlnet.webmap import scenario_tree as tree
from test_equivalent_merge_bases import cross


def dual_tips(c, service, guard=None):
    a, b, children = tips(c, service, guard)
    result = []
    for i, child in enumerate(children):
        c.post('/api/engineering/open/'+child['scenario_id'], json={})
        service.state['network']['tolerance_mm'] = 35+i
        result.append(save(c, 'dual tip', child))
    return a, b, result


@pytest.mark.parametrize('reverse', [False, True])
@pytest.mark.parametrize('title', ['target', 'source'])
@pytest.mark.parametrize('network', ['target', 'source'])
def test_independent_dual_choices(bridge, reverse, title, network):
    c, service = bridge
    a, b, children = dual_tips(c, service)
    if reverse:
        children.reverse()
    rows = [store.get_scenario(service.repository.path, x['scenario_id']) for x in (a,b,*children)]
    plan = preview(c, *children)
    assert plan['conflicts'] == ['title', 'network']
    assert plan['differing_base_units'] == ['topology']
    resolutions = dict(title=title, network=network)
    r = c.post('/api/engineering/merge', json=dict(plan, name='dual choice', resolutions=resolutions))
    assert r.status_code == 200, r.text
    saved = store.get_scenario(service.repository.path, r.json()['scenario_id'])
    assert saved['metadata']['merge_versions'] == plan['versions']
    assert saved['metadata']['merge_bases'] == plan['bases']
    assert saved['metadata']['merge_resolutions'] == resolutions
    assert c.post('/api/engineering/open/'+saved['id'], json={}).status_code == 200
    assert service.state['name'] == rows[2 if title == 'target' else 3]['metadata']['thesis_state']['name']
    assert service.state['network'] == rows[2 if network == 'target' else 3]['metadata']['thesis_state']['network']
    for index in (1,2):
        assert service.state['points'][index]['x'] == rows[0]['metadata']['thesis_state']['points'][index]['x']+10
    for key in ('point','line','angle'):
        assert service.state['seq'][key] == max(row['metadata']['thesis_state']['seq'][key] for row in rows)
    assert rows == [store.get_scenario(service.repository.path, x['scenario_id']) for x in (a,b,*children)]


@pytest.mark.parametrize('guard', ['point', 'unknown', 'invalid'])
def test_other_conflicts_stay_whole_topology(bridge, guard):
    c, service = bridge
    _, _, children = dual_tips(c, service, guard)
    assert preview(c, *children)['conflicts'] == ['topology']


@pytest.mark.parametrize('resolutions', [{}, {'title':'source'}, {'network':'target'},
    {'title':'bad','network':'target'}, {'title':'target','network':'source','topology':'target'}])
def test_invalid_choices_are_atomic(bridge, resolutions):
    c, service = bridge
    _, _, children = dual_tips(c, service)
    plan = preview(c, *children)
    before = c.get('/api/engineering/projects').json()
    assert c.post('/api/engineering/merge', json=dict(plan, name='invalid', resolutions=resolutions)).status_code == 400
    assert c.get('/api/engineering/projects').json() == before


@pytest.mark.parametrize('index', [0,1])
def test_every_base_version_guarded(bridge, index):
    c, service = bridge
    _, _, children = dual_tips(c, service)
    plan = preview(c, *children)
    sid = plan['bases'][index]
    c.post('/api/engineering/rename/'+sid, json=dict(name='changed', version=plan['versions'][sid]))
    before = c.get('/api/engineering/projects').json()
    assert c.post('/api/engineering/merge', json=dict(plan, name='stale', resolutions=dict(title='source',network='target'))).status_code == 409
    assert c.get('/api/engineering/projects').json() == before


@pytest.mark.parametrize('reverse', [False, True])
@pytest.mark.parametrize('title', ['target', 'source'])
@pytest.mark.parametrize('network', ['target', 'source'])
def test_selected_deletion_preserves_both_independent_choices(bridge, reverse, title, network):
    c, service = bridge
    deleted = service.state['lines'][0]['id']
    service.state['network']['observed_edges'] = [deleted]
    _, _, left, right = cross(c, service, 'point')
    children=[]
    for i,parent in enumerate((left,right)):
        c.post('/api/engineering/open/'+parent['scenario_id'], json={})
        service.state['name'] = 'title '+str(i)
        service.state['network']['tolerance_mm'] = 35+i
        service.state['points'][i+1]['x'] += 10
        if i == 0:
            service.state['lines']=[x for x in service.state['lines'] if x['id'] != deleted]
            for key in ('observed_edges','added_edges'):
                service.state['network'][key]=[x for x in service.state['network'].get(key,[]) if x != deleted]
        children.append(save(c,'structural tip',parent))
    if reverse:
        children.reverse()
    plan=preview(c,*children)
    assert plan['conflicts']==['title','network']
    r=c.post('/api/engineering/merge',json=dict(plan,name='review structural',resolutions=dict(title=title,network=network)))
    assert r.status_code==200, r.text
    assert c.post('/api/engineering/open/'+r.json()['scenario_id'],json={}).status_code==200
    assert deleted not in [x['id'] for x in service.state['lines']]
    assert all(deleted not in service.state['network'].get(k,[]) for k in ('observed_edges','added_edges'))
    assert service.state['network']['tolerance_mm']==35+(int(network=='source') ^ int(reverse))
    assert service.state['name']=='title '+str(int(title=='source') ^ int(reverse))

@pytest.mark.parametrize('bad_outcome', [('target','target'),('target','source'),('source','target'),('source','source')])
def test_each_outcome_checked(bridge, monkeypatch, bad_outcome):
    c, service = bridge
    _,_,children=dual_tips(c,service)
    real=tree._merge_point_coordinates
    def poisoned(base,target,source,point_conflicts=None,choices=None):
        result=real(base,target,source,point_conflicts,choices)
        # One ancestor disagrees only for one chosen combination; initial
        # unresolved candidates remain equal. A partial check would miss it.
        if result and choices and (choices.get('title'),choices.get('network'))==bad_outcome and base['points'][0]['x']==target['points'][0]['x']:
            result['points'][1]['x']+=123
        return result
    monkeypatch.setattr(tree,'_merge_point_coordinates',poisoned)
    assert preview(c,*children)['conflicts']==['topology']


def test_mismatched_conflicts(bridge,monkeypatch):
    c,service=bridge
    _,_,children=dual_tips(c,service)
    real=tree._merge_point_coordinates
    def mismatched(base,target,source,point_conflicts=None,choices=None):
        result=real(base,target,source,point_conflicts,choices)
        if result and base['points'][0]['x']==target['points'][0]['x']:
            point_conflicts.remove('network')
        return result
    monkeypatch.setattr(tree,'_merge_point_coordinates',mismatched)
    assert preview(c,*children)['conflicts']==['topology']
