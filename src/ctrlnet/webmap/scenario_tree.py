"""Conservative three-way merge of saved editor scenarios.

Topology is one indivisible unit; GNSS is another. No geometry splicing is
attempted. Both parents and the chosen common ancestor remain durable.
"""
import copy
from .. import store
from .project_bridge import editor_records, gnss_records


def _name(value):
    if not isinstance(value, str) or not 1 <= len(value.strip()) <= 120:
        raise ValueError('方案名称须为 1–120 字')
    return value.strip()


def rename(path, sid, name, version):
    name = _name(name)
    conn = store.connect(path)
    try:
        with store._write_transaction(conn):
            row = conn.execute('SELECT version FROM scenarios WHERE id=?', (sid,)).fetchone()
            if row is None:
                raise KeyError('方案不存在')
            if type(version) is not int or version != row['version']:
                raise store.VersionConflictError('方案已改变，请刷新')
            from ..lifecycle import require_draft
            require_draft(conn, sid)
            conn.execute('UPDATE scenarios SET name=?,version=version+1,updated_at=? WHERE id=?',
                         (name, store._utcnow(), sid))
        return {'scenario_id': sid, 'name': name, 'version': version + 1}
    finally:
        conn.close()


def _units(s):
    state = copy.deepcopy(s['metadata']['thesis_state'])
    gnss = [{k:o[k] for k in ('from', 'to', 'sigma_E', 'sigma_N', 'correlation')}
            for o in s['observations'] if o['kind'] == 'gnss']
    return {'topology': state, 'gnss': gnss}


def _same(key, a, b):
    if key != 'topology':
        return a == b
    from .thesis_web import _ensure_geometry, _refresh_derived
    def normalized(value):
        value = copy.deepcopy(value)
        for field in ('created_at', 'updated_at', 'saved_created_at', 'saved_updated_at'):
            value.pop(field, None)
        _ensure_geometry(value)
        _refresh_derived(value)
        return value
    return normalized(a) == normalized(b)


def _plan(conn, target, source):
    if target == source:
        raise ValueError('请选择两个不同方案')
    rows = {r['id']: store._fetch_scenario_dict(conn, r['id'])
            for r in conn.execute('SELECT id FROM scenarios')}
    if target not in rows or source not in rows:
        raise KeyError('方案不存在')
    t, s = rows[target], rows[source]
    if t['project_id'] != s['project_id']:
        raise ValueError('只能合并同一工程的方案')
    def ancestors(sid):
        found, pending = {}, [(sid, 0)]
        while pending:
            node, depth = pending.pop(0)
            if node in found:
                continue
            if node not in rows or rows[node]['project_id'] != t['project_id']:
                raise ValueError('方案谱系损坏')
            found[node] = depth
            row = rows[node]
            parents = row['metadata'].get('merge_parents') or [row['parent_id']]
            pending.extend((p, depth+1) for p in parents if p)
        return found
    ta, sa = ancestors(target), ancestors(source)
    common = set(ta) & set(sa)
    # Reject ambiguous merge bases instead of silently choosing in criss-cross DAGs.
    bases = [b for b in common if not any(b != c and b in ancestors(c) for c in common)]
    if len(bases) != 1:
        raise ValueError('需要唯一共同祖先；不支持无共同祖先或交叉合并')
    base = rows[bases[0]]
    units = [_units(r) for r in (base, t, s)]
    conflicts, merged = [], {}
    for key in units[0]:
        b, tv, sv = (u[key] for u in units)
        if _same(key, tv, sv) or _same(key, sv, b):
            merged[key] = tv
        elif _same(key, tv, b):
            merged[key] = sv
        else:
            conflicts.append(key)
    versions = {r['id']: r['version'] for r in (base, t, s)}
    return dict(target=target, source=source, base=base['id'], versions=versions,
                conflicts=conflicts), merged, units, t


def preview(path, target, source):
    conn = store.connect(path)
    try:
        conn.execute('BEGIN')
        return _plan(conn, target, source)[0]
    finally:
        conn.close()


def merge(path, payload):
    name = _name(payload.get('name'))
    conn = store.connect(path)
    try:
        with store._write_transaction(conn):
            plan, merged, units, target = _plan(conn, payload['target'], payload['source'])
            if payload.get('versions') != plan['versions']:
                raise store.VersionConflictError('预览已过期，请重新预览')
            resolutions = payload.get('resolutions', {})
            if not isinstance(resolutions, dict) or set(resolutions) != set(plan['conflicts']):
                raise ValueError('须明确解决全部冲突；不可提交多余选择')
            for key, choice in resolutions.items():
                if choice not in ('target', 'source'):
                    raise ValueError('冲突选择须为 target/source')
                merged[key] = units[1 if choice == 'target' else 2][key]
            state = copy.deepcopy(merged['topology'])
            points, observations = editor_records(state)
            observations += gnss_records(merged['gnss'], points)
            parent = conn.execute('SELECT id FROM snapshots WHERE scenario_id=? ORDER BY created_at DESC,rowid DESC LIMIT 1',
                                  (target['id'],)).fetchone()
            if parent is None:
                raise ValueError('目标方案没有快照')
            metadata = dict(thesis_state=state, merge_parents=[plan['target'], plan['source']],
                            merge_base=plan['base'], merge_versions=plan['versions'],
                            merge_resolutions=resolutions)
            result = store.save_editor_version(path,
                dict(id=target['project_id'], name=name, points=points),
                dict(name=name, observations=observations, metadata=metadata),
                parent_snapshot=parent['id'], _connection=conn)
            return dict(result, merge=plan)
    finally:
        conn.close()
