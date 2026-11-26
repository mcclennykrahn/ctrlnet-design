"""One whole-angle choice requires agreement for both outcomes at every base."""
import pytest
from test_v08 import bridge
from test_scenario_tree import save, preview
from test_equivalent_merge_bases import cross
from ctrlnet import store
from ctrlnet.webmap import scenario_tree as tree


def angle_tips(c, service, guard=None, field="name"):
    a, b, left, right = cross(c, service, 'point')
    children = []
    for i, parent in enumerate((left, right)):
        c.post('/api/engineering/open/'+parent['scenario_id'], json={})
        if field == 'name':
            service.state['angles'][0]['name'] = 801+i
        else:
            angle = service.state['angles'][0]
            angle['station'], angle['backsight'] = angle['backsight'], angle['station']
            if i:
                angle['backsight'], angle['foresight'] = angle['foresight'], angle['backsight']
        service.state['points'][i+1]['y'] += 10
        service.state['seq']['point'] += 20+i
        if guard == 'title':
            service.state['name'] = 'title '+str(i)
        elif guard == 'multiple':
            service.state['points'][0]['y'] += i+1
        elif guard == 'angles':
            service.state['angles'][1]['name'] = 901+i
        elif guard == 'line':
            service.state['lines'][0]['name'] = 901+i
        elif guard == 'network':
            service.state['network']['observed_angles'] = [a['id'] for a in service.state['angles'][:i+1]]
        elif guard == 'unknown' and i:
            service.state['future_authored'] = True
        children.append(save(c, 'angle tip', parent))
    return a, b, children


@pytest.mark.parametrize('field', ['name', 'references'])
@pytest.mark.parametrize('reverse', [False, True])
@pytest.mark.parametrize('choice', ['target', 'source'])
def test_angle_choice_reopen(bridge, reverse, choice, field):
    c, service = bridge
    a, b, children = angle_tips(c, service, field=field)
    if reverse:
        children.reverse()
    rows = [store.get_scenario(service.repository.path, x['scenario_id']) for x in (a,b,*children)]
    states = [r['metadata']['thesis_state'] for r in rows]
    key = 'angle:'+states[2]['angles'][0]['id']
    plan = preview(c, *children)
    assert plan['conflicts'] == [key]
    assert plan['differing_base_units'] == ['topology']
    assert set(plan['bases']) == {a['scenario_id'], b['scenario_id']}
    before = c.get('/api/engineering/projects').json()
    for resolutions in ({}, {key:'bad'}, {key:choice, 'topology':choice}):
        assert c.post('/api/engineering/merge', json=dict(plan,name='bad',resolutions=resolutions)).status_code == 400
        assert c.get('/api/engineering/projects').json() == before
    r = c.post('/api/engineering/merge', json=dict(plan,name='angle consensus',resolutions={key:choice}))
    assert r.status_code == 200, r.text
    saved = store.get_scenario(service.repository.path, r.json()['scenario_id'])
    assert saved['metadata']['merge_versions'] == plan['versions']
    assert saved['metadata']['merge_bases'] == plan['bases']
    assert saved['metadata']['merge_resolutions'] == {key:choice}
    assert c.post('/api/engineering/open/'+saved['id'],json={}).status_code == 200
    state = service.state
    angle = state['angles'][0]
    expected = states[2 if choice == 'target' else 3]['angles'][0]
    assert {k:v for k,v in angle.items() if k != 'value'} == {k:v for k,v in expected.items() if k != 'value'}
    from ctrlnet.webmap.thesis_web import _angle_value
    assert angle['value'] == pytest.approx(_angle_value(state, angle))
    for i in (1,2):
        assert state['points'][i]['y'] == states[0]['points'][i]['y']+10
    assert [p['id'] for p in state['points']] == [p['id'] for p in states[2]['points']]
    for k in ('point','line','angle'):
        assert state['seq'][k] == max(s['seq'][k] for s in states)
    assert rows == [store.get_scenario(service.repository.path, x['scenario_id']) for x in (a,b,*children)]


@pytest.mark.parametrize('guard',['multiple','angles','line','unknown'])
def test_other_conflicts_conservative(bridge, guard):
    c, service = bridge
    _, _, children = angle_tips(c, service, guard)
    assert preview(c,*children)['conflicts'] == ['topology']


@pytest.mark.parametrize('choice',['target','source'])
def test_both_outcomes_checked(bridge, monkeypatch, choice):
    c, service = bridge
    _, _, children = angle_tips(c,service)
    key = 'angle:'+service.state['angles'][0]['id']
    real = tree._merge_point_coordinates
    def poisoned(base,target,source,point_conflicts=None,choices=None):
        result = real(base,target,source,point_conflicts,choices)
        if result and choices and choices.get(key) == choice and base['points'][0]['x'] == target['points'][0]['x']:
            result['points'][1]['y'] += 123
        return result
    monkeypatch.setattr(tree,'_merge_point_coordinates',poisoned)
    assert preview(c,*children)['conflicts'] == ['topology']


@pytest.mark.parametrize('index',[0,1])
def test_every_base_version_guarded(bridge,index):
    c, service = bridge
    _, _, children = angle_tips(c,service)
    plan = preview(c,*children)
    key = plan['conflicts'][0]
    sid = plan['bases'][index]
    c.post('/api/engineering/rename/'+sid,json=dict(name='changed',version=plan['versions'][sid]))
    before = c.get('/api/engineering/projects').json()
    assert c.post('/api/engineering/merge',json=dict(plan,name='stale',resolutions={key:'source'})).status_code == 409
    assert c.get('/api/engineering/projects').json() == before
