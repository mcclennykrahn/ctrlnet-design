"""Workflow transitions, stale requests, mutation guards and immutable inputs."""
import pytest
from test_v08 import bridge
from test_scenario_tree import save
from ctrlnet import store, lifecycle


def test_lifecycle_roundtrip_and_guards(bridge):
    c, service = bridge
    root = save(c, 'workflow')
    sid, version = root['scenario_id'], root['version']
    snap = store.get_snapshot(service.repository.path, root['snapshot_id'])
    for target in ('review', 'approved', 'archived', 'draft', 'review', 'draft'):
        before = c.get('/api/engineering/projects').json()
        for bad in (dict(target=target, version=version, note=''),
                    dict(target='invalid', version=version, note='reason')):
            assert c.post('/api/engineering/lifecycle/'+sid, json=bad).status_code == 400
            assert c.get('/api/engineering/projects').json() == before
        result = c.post('/api/engineering/lifecycle/'+sid,
                        json=dict(target=target, version=version, note='<reason>'))
        assert result.status_code == 200, result.text
        assert c.post('/api/engineering/lifecycle/'+sid,
                      json=dict(target=target, version=version, note='stale')).status_code == 409
        version += 1
        scenario = store.get_scenario(service.repository.path, sid)
        assert scenario['version'] == version
        assert lifecycle.describe(scenario['metadata'])['state'] == target
        if target != 'draft':
            assert c.post('/api/engineering/rename/'+sid,json=dict(name='blocked',version=version)).status_code == 400
            with pytest.raises(ValueError, match='draft'):
                store.update_observations(service.repository.path,sid,[],expected_version=version)
            child = save(c, 'independent draft', root)
            assert lifecycle.describe(store.get_scenario(service.repository.path,child['scenario_id'])['metadata']) == dict(state='draft',allowed=['review','archived'],history=[])
        assert store.get_snapshot(service.repository.path,root['snapshot_id']) == snap
    history = lifecycle.describe(store.get_scenario(service.repository.path,sid)['metadata'])['history']
    assert len(history) == 6
    assert all(h['note'] == '<reason>' for h in history)


@pytest.mark.parametrize('source', list(lifecycle.TRANSITIONS))
@pytest.mark.parametrize('target', list(lifecycle.TRANSITIONS))
def test_transition_matrix(bridge,source,target):
    c, service = bridge
    saved = save(c,'matrix')
    sid = saved['scenario_id']
    version = saved['version']
    for step in dict(draft=[], review=['review'],approved=['review','approved'],archived=['archived'])[source]:
        lifecycle.transition(service.repository.path,sid,step,version,'setup')
        version += 1
    before = store.get_scenario(service.repository.path,sid)
    if target in lifecycle.TRANSITIONS[source]:
        assert lifecycle.transition(service.repository.path,sid,target,version,'decision')['state'] == target
    else:
        with pytest.raises(ValueError):
            lifecycle.transition(service.repository.path,sid,target,version,'decision')
        assert store.get_scenario(service.repository.path,sid) == before


def test_stale_evidence_and_overwrite_rejected(bridge):
    c, service = bridge
    saved = save(c,'evidence')
    path, sid = service.repository.path, saved['scenario_id']
    scenario = store.get_scenario(path,sid)
    changed = scenario['observations'][:-1]
    updated = store.update_observations(path,sid,changed,expected_version=scenario['version'])
    with pytest.raises(ValueError,match='current snapshot'):
        lifecycle.transition(path,sid,'review',updated['version'],'review')
    store.snapshot(path,sid)
    result = lifecycle.transition(path,sid,'review',updated['version'],'review')
    assert result['history'][-1]['evidence']['snapshot_id']
    lifecycle.transition(path,sid,'draft',result['version'],'return')
    project = store.load_project(path,saved['project_id'])
    before = store.get_scenario(path,sid)
    with pytest.raises(ValueError,match='lifecycle history'):
        store.save_project(path,project,overwrite=True)
    assert store.get_scenario(path,sid) == before
