"""Independent consensus guards for differing-content criss-cross bases."""
import copy
from test_v08 import bridge
from test_scenario_tree import save, preview
from test_equivalent_merge_bases import cross


def apply(c, a, b, resolutions=None):
    plan = preview(c, a, b)
    r = c.post('/api/engineering/merge', json=dict(plan, name='probe', resolutions=resolutions or {}))
    assert r.status_code == 200, r.text
    return r.json()


def test_three_best_bases_consensus(bridge):
    c, service = bridge
    root = save(c, 'root')
    siblings = []
    for i in range(3):
        c.post('/api/engineering/open/'+root['scenario_id'], json={})
        service.state['points'][0]['x'] += i
        siblings.append(save(c, str(i), root))
    a,b,d = siblings
    ab = apply(c,a,b)
    ba = apply(c,b,a)
    # Both intermediate branches explicitly resolve the competing edit to d.
    left = apply(c,ab,d,{'point:'+service.state['points'][0]['id']: 'source'})
    right = apply(c,ba,d,{'point:'+service.state['points'][0]['id']: 'source'})
    tips = []
    for i,parent in enumerate((left,right),1):
        c.post('/api/engineering/open/'+parent['scenario_id'], json={})
        service.state['points'][i]['x'] += 10
        tips.append(save(c,'tip',parent))
    plan = preview(c,*tips)
    assert len(plan['bases']) == 3
    assert set(plan['bases']) == {x['scenario_id'] for x in siblings}
    assert plan['conflicts'] == []
    assert len(plan['versions']) == 5
    apply(c,*tips)


def test_clean_but_disagreeing_candidates_rejected(bridge):
    c, service = bridge
    a,b,left,right = cross(c,service,'point')
    # Tips choose opposite bases at point 0: each ancestor permits a clean
    # merge, but the two choices produce opposite results. Must stay whole-unit.
    tips=[]
    for i,(parent,original) in enumerate(((left,a),(right,b)),1):
        c.post('/api/engineering/open/'+original['scenario_id'], json={})
        state=copy.deepcopy(service.state)
        c.post('/api/engineering/open/'+parent['scenario_id'], json={})
        service.state['points'][0]=state['points'][0]
        service.state['points'][i]['x']+=10
        tips.append(save(c,'tip',parent))
    plan=preview(c,*tips)
    assert plan['conflicts']==['topology']


def test_unknown_authored_disagreement_rejected(bridge):
    c, service = bridge
    a,b,left,right=cross(c,service,'unknown')
    tips=[]
    for i,parent in enumerate((left,right),1):
        c.post('/api/engineering/open/'+parent['scenario_id'], json={})
        service.state['points'][i]['x']+=3
        tips.append(save(c,'tip',parent))
    assert preview(c,*tips)['conflicts']==['topology']
