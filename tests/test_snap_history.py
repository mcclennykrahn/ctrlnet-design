"""Post-v0.8 point/segment snapping and durable single-user editor history."""
import copy
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from ctrlnet.webmap.thesis_web import ThesisService, ThesisError, create_thesis_router, _inverse_xy


def setup_editor(path):
    s = ThesisService(path)
    s.import_coordinates('1；3800000，500000\n2；3800100，500000\n3；3800050，500050', 'snap')
    s.add_line('p1', 'p2')
    return s


def move_xy(s, pid, x, y, **kwargs):
    lat, lon = _inverse_xy(s.state, x, y)
    return s.move_point(pid, lon, lat, **kwargs)


def test_segment_point_tolerance_and_incident_exclusion(tmp_path):
    s = setup_editor(tmp_path/'s.sqlite')
    move_xy(s, 'p3', 3800050, 500002, snap_geometry_m=3)
    assert s.state['points'][2]['x'] == pytest.approx(3800050, abs=.001)
    assert s.state['points'][2]['y'] == 500000
    # A segment is finite: beyond its endpoint, nearest location is the endpoint.
    move_xy(s, 'p3', 3800101, 500001, snap_geometry_m=3)
    assert s.state['points'][2]['x'] == 3800100
    move_xy(s, 'p3', 3800050, 500004, snap_geometry_m=3)
    assert s.state['points'][2]['y'] == pytest.approx(500004, abs=.001)
    # Moving a segment endpoint must not snap back to its own incident segment.
    move_xy(s, 'p1', 3800020, 500001, snap_geometry_m=3)
    assert s.state['points'][0]['y'] == pytest.approx(500001, abs=.001)
    s.set_point_fixed('p3', True)
    with pytest.raises(ThesisError):
        move_xy(s, 'p3', 3800050, 500000, snap_geometry_m=3)


def test_add_snap_restart_undo_redo_and_failed_edit(tmp_path, monkeypatch):
    path = tmp_path/'s.sqlite'
    s = setup_editor(path)
    before = copy.deepcopy(s.state)
    lat, lon = _inverse_xy(s.state, 3800050, 500001)
    s.add_point(lon, lat, snap_geometry_m=2)
    snapped = copy.deepcopy(s.state)
    assert snapped['points'][-1]['y'] == 500000
    s = ThesisService(path)
    assert s.state == snapped
    s.restore_history('undo')
    assert s.state == before
    s = ThesisService(path)
    s.restore_history('redo')
    assert s.state == snapped
    with pytest.raises(ThesisError):
        s.add_point(lon, lat, snap_geometry_m=float('nan'))
    assert ThesisService(path).state == snapped
    # Disk failure rolls back both live state and history.
    def fail():
        raise OSError('simulated disk failure')
    monkeypatch.setattr(s, '_persist_draft', fail)
    with pytest.raises(OSError):
        s.delete_point('p4')
    assert s.state == snapped
    assert ThesisService(path).state == snapped


def test_history_branch_bound_and_api(tmp_path):
    path = tmp_path/'s.sqlite'
    s = setup_editor(path)
    for i in range(25):
        s.configure_network({'ellipse_scale': i+1})
    assert len(s._undo) == 20
    s.restore_history('undo')
    s.set_point_fixed('p3', True)
    assert not s._redo
    app = FastAPI()
    app.include_router(create_thesis_router(s))
    c = TestClient(app)
    assert c.post('/api/thesis/history/invalid').status_code == 400
    assert c.post('/api/thesis/history/undo').status_code == 200
    assert c.post('/api/thesis/history/redo').status_code == 200
    prior = copy.deepcopy(s.state)
    assert c.patch('/api/thesis/points/p3', json={'lon':117, 'lat':34, 'snap_geometry_m':-1}).status_code == 400
    assert s.state == prior
