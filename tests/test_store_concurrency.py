"""工程库并发、乐观锁、事务审计及旧库迁移。"""
import hashlib
import json
import multiprocessing
import sqlite3
from concurrent.futures import ThreadPoolExecutor, ProcessPoolExecutor

import pytest

from ctrlnet.store import (
    DATABASE_VERSION, VersionConflictError, _SCHEMA_SQL, add_observation,
    connect, create_scenario, get_or_compute_result, get_scenario, load_project,
    save_project, snapshot, update_observations,
)


def _append(args):
    path, i = args
    add_observation(path, 'base', {'id': f'd{i}', 'kind': 'distance',
                                'from': 'A', 'to': 'B', 'a_m': 0.002})


def _create(args):
    path, i = args
    create_scenario(path, f'方案{i}', scenario_id=f's{i}')


def _seed(path):
    save_project(path, {'id': 'p', 'name': '工程', 'points': [
        {'name': 'A', 'E': 0, 'N': 0, 'fixed': True},
        {'name': 'B', 'E': 10, 'N': 0, 'fixed': True}],
        'scenarios': [{'id': 'base', 'name': '基准'}]})


@pytest.mark.parametrize('processes', [False, True])
def test_parallel_writes(tmp_path, processes):
    path = tmp_path / 'parallel.sqlite'
    _seed(path)
    kwargs = {'mp_context': multiprocessing.get_context('spawn')} if processes else {}
    executor = ProcessPoolExecutor if processes else ThreadPoolExecutor
    with executor(max_workers=4, **kwargs) as pool:
        list(pool.map(_append, [(str(path), i) for i in range(16)]))
        list(pool.map(_create, [(str(path), i) for i in range(8)]))
    scenario = get_scenario(path, 'base')
    assert scenario['version'] == 17
    assert {o['id'] for o in scenario['observations']} == {f'd{i}' for i in range(16)}
    assert load_project(path)['n_scenarios'] == 9
    with connect(path) as conn:
        assert conn.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
        assert not conn.execute('PRAGMA foreign_key_check').fetchall()
        assert conn.execute('PRAGMA journal_mode').fetchone()[0] == 'wal'
        assert conn.execute('PRAGMA busy_timeout').fetchone()[0] == 30000


def test_stale_version_and_failed_write_leave_no_audit(tmp_path):
    path = tmp_path / 'conflict.sqlite'
    _seed(path)
    def attempt(i):
        try:
            return update_observations(path, 'base', [], expected_version=1)['version']
        except VersionConflictError:
            return 'conflict'
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(attempt, range(4)))
    assert results.count(2) == 1
    assert results.count('conflict') == 3
    with connect(path) as conn:
        before = conn.execute('SELECT count(*) FROM audit_log').fetchone()[0]
    with pytest.raises(VersionConflictError):
        add_observation(path, 'base', {}, expected_version=1)
    with pytest.raises(sqlite3.IntegrityError):
        save_project(
            path, {'id': 'p', 'name': 'bad', 'points': [],
                   'scenarios': [{'id': 'broken', 'parent_id': 'missing'}]}, overwrite=True)
    assert get_scenario(path, 'base')['version'] == 2
    with connect(path) as conn:
        assert conn.execute('SELECT count(*) FROM audit_log').fetchone()[0] == before


def test_audit_hashes_and_all_tables(tmp_path):
    path = tmp_path / 'audit.sqlite'
    _seed(path)
    add_observation(path, 'base', {'kind': 'distance', 'from': 'A', 'to': 'B'})
    snap = snapshot(path, 'base')
    get_or_compute_result(path, 'base', compute=lambda _: {'value': 1})
    get_or_compute_result(path, 'base', force=True, compute=lambda _: {'value': 2})
    with connect(path) as conn:
        rows = conn.execute('SELECT * FROM audit_log').fetchall()
        assert {r['object_type'] for r in rows} == {
            'projects', 'points', 'scenarios', 'observations', 'snapshots', 'results'}
        for r in rows:
            assert r['timestamp'] and r['object_id']
            assert (r['before_hash'] is None) == (r['operation'] == 'INSERT')
            assert r['after_hash'] is not None
            assert len(r['after_hash']) == 64
        row = conn.execute('SELECT * FROM snapshots WHERE id=?', (snap['id'],)).fetchone()
        expected = hashlib.sha256(json.dumps(tuple(row), ensure_ascii=False,
                                  separators=(',', ':'), sort_keys=True).encode()).hexdigest()
        assert conn.execute("SELECT after_hash FROM audit_log WHERE object_type='snapshots'").fetchone()[0] == expected
    count = len(rows)
    snapshot(path, 'base')
    get_or_compute_result(path, 'base')
    with connect(path) as conn:
        assert conn.execute('SELECT count(*) FROM audit_log').fetchone()[0] == count
    save_project(path, {'id': 'p', 'name': '替换', 'points': []}, overwrite=True)
    with connect(path) as conn:
        assert conn.execute("SELECT count(*) FROM audit_log WHERE operation='DELETE'").fetchone()[0] > 0


@pytest.mark.parametrize('missing_version', [False, True])
def test_legacy_migration_preserves_data(tmp_path, missing_version):
    path = tmp_path / 'legacy.sqlite'
    schema = _SCHEMA_SQL
    if missing_version:
        schema = schema.replace('    version         INTEGER NOT NULL DEFAULT 1,\n', '')
    with sqlite3.connect(path) as conn:
        conn.executescript(schema)
        conn.execute("INSERT INTO projects(id,name,created_at) VALUES('p','旧工程','2020')")
        conn.execute("INSERT INTO scenarios(id,project_id,name,created_at) VALUES('base','p','旧方案','2020')")
    assert load_project(path)['name'] == '旧工程'
    assert get_scenario(path, 'base')['version'] == 1
    update_observations(path, 'base', [], expected_version=1)
    for _ in range(2):
        with connect(path) as conn:
            assert conn.execute('PRAGMA user_version').fetchone()[0] == DATABASE_VERSION
            assert conn.execute('SELECT count(*) FROM audit_log').fetchone()[0] == 1
