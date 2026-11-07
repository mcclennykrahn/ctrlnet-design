"""Conservative three-way merge of saved editor scenarios.

Disjoint existing-point edits, measured line overrides and network settings
merge automatically; competing existing-point edits offer whole-point choices.
Competing network settings offer whole-object choices; measured override
conflicts offer whole-line choices when structure is unchanged.
Combined field merges match points/lines/angles by ID and retain target list order.
Existing-line and existing-angle names merge by ID with whole-object conflict choices.
Other topology conflicts retain whole-topology choices.
Both parents remain durable.
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


def _merge_point_coordinates(base, target, source, point_conflicts=None, choices=None):
    """Merge existing-point fields and measured line overrides by authored field.

    A point's x/y/lon/lat tuple is indivisible. Derived geometry and timestamps
    are ignored. Each measured override flag/value pair and the entire network
    settings object are indivisible. Competing point edits select a whole point;
    competing network edits select the whole settings object. Competing measured
    overrides select a whole line, with unkept geometry recomputed afterward.
    """
    from .thesis_web import _ensure_geometry, _refresh_derived
    coordinates = ('x', 'y', 'lon', 'lat')
    groups = (coordinates, ('name',), ('fixed',))

    def skeleton(state):
        value = copy.deepcopy(state)
        for field in ('created_at', 'updated_at', 'saved_created_at', 'saved_updated_at'):
            value.pop(field, None)
        value.pop('network', None)
        ids = [p.get('id') for p in value.get('points', [])]
        if any(not isinstance(i, str) or not i for i in ids) or len(set(ids)) != len(ids):
            return None
        for point in value.get('points', []):
            for field in (*coordinates, 'name', 'fixed'):
                point.pop(field, None)
        line_ids = [line.get('id') for line in value.get('lines', [])]
        if any(not isinstance(i, str) or not i for i in line_ids) or len(set(line_ids)) != len(line_ids):
            return None
        for line in value.get('lines', []):
            line.pop('name', None)
            for field in ('length', 'azimuth'):
                line.pop(field, None)
                line.pop('_keep_' + field, None)
        angle_ids = [angle.get('id') for angle in value.get('angles', [])]
        if any(not isinstance(i, str) or not i for i in angle_ids) or len(set(angle_ids)) != len(angle_ids):
            return None
        # Sort comparison copies only: IDs define identity, while the
        # result retains the target branch's presentation order.
        for collection in ('points', 'lines', 'angles'):
            value[collection].sort(key=lambda item: item['id'])
        for angle in value.get('angles', []):
            angle.pop('value', None)
            angle.pop('name', None)
        return value

    shapes = [skeleton(s) for s in (base, target, source)]
    if shapes[0] is None or not shapes[0] == shapes[1] == shapes[2]:
        return None
    result = copy.deepcopy(target)
    # Keep observation selections, grade and display settings together. Their
    # internal dependencies are not safe to resolve field by field.
    b, t, s = (("network" in state, state.get("network"))
               for state in (base, target, source))
    if t == s or s == b:
        chosen = target
    elif t == b:
        chosen = source
    else:
        if point_conflicts is None:
            return None
        point_conflicts.append('network')
        chosen = source if (choices or {}).get('network') == 'source' else target
    if 'network' in chosen:
        result['network'] = copy.deepcopy(chosen['network'])
    else:
        result.pop('network', None)
    def aligned(collection):
        indexes = [{item['id']: item for item in state[collection]}
                   for state in (base, target, source)]
        for out in result[collection]:
            yield tuple(index[out['id']] for index in indexes) + (out,)

    for bp, tp, sp, out in aligned('points'):
        conflicted = False
        for fields in groups:
            # Presence is authored too: absent and explicit null are distinct.
            b, t, s = (tuple((k in p, p.get(k)) for k in fields) for p in (bp, tp, sp))
            if t == s or s == b:
                chosen = tp
            elif t == b:
                chosen = sp
            else:
                if point_conflicts is None:
                    return None
                conflicted = True
                break
            for field in fields:
                if field in chosen:
                    out[field] = chosen[field]
                else:
                    out.pop(field, None)
        if conflicted:
            key = 'point:' + bp['id']
            point_conflicts.append(key)
            chosen = sp if (choices or {}).get(key) == 'source' else tp
            out.clear()
            out.update(copy.deepcopy(chosen))
    for bl, tl, sl, out in aligned('lines'):
        for field in ('name', 'length', 'azimuth'):
            flag = '_keep_' + field
            def authored(line):
                # Unkept values are computed, so geometry changes are not edits.
                if field == 'name':
                    return (field in line, line.get(field))
                return ((flag in line, line.get(flag)),
                        (field in line, line.get(field)) if line.get(flag) else None)
            b, t, s = (authored(line) for line in (bl, tl, sl))
            if t == s or s == b:
                chosen = tl
            elif t == b:
                chosen = sl
            else:
                if point_conflicts is None:
                    return None
                key = 'line:' + bl['id']
                point_conflicts.append(key)
                chosen = sl if (choices or {}).get(key) == 'source' else tl
                out.clear()
                out.update(copy.deepcopy(chosen))
                break
            for key in ((field,) if field == 'name' else (flag, field)):
                if key in chosen:
                    out[key] = chosen[key]
                else:
                    out.pop(key, None)
    for ba, ta, sa, out in aligned('angles'):
        b, t, s = (("name" in angle, angle.get("name")) for angle in (ba, ta, sa))
        if t == s or s == b:
            chosen = ta
        elif t == b:
            chosen = sa
        else:
            if point_conflicts is None:
                return None
            key = 'angle:' + ba['id']
            point_conflicts.append(key)
            chosen = sa if (choices or {}).get(key) == 'source' else ta
        # References and all other authored fields are equal by skeleton check.
        out.clear()
        out.update(copy.deepcopy(chosen))
    _ensure_geometry(result)
    _refresh_derived(result)
    return result


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
            point_conflicts = []
            combined = _merge_point_coordinates(b, tv, sv, point_conflicts) if key == 'topology' else None
            if combined is None:
                conflicts.append(key)
            else:
                merged[key] = combined
                conflicts.extend(point_conflicts)
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
                if key != 'network' and not key.startswith(('point:', 'line:', 'angle:')):
                    merged[key] = units[1 if choice == 'target' else 2][key]
            if 'network' in resolutions or any(key.startswith(('point:', 'line:', 'angle:')) for key in resolutions):
                merged['topology'] = _merge_point_coordinates(
                    *(u['topology'] for u in units), point_conflicts=[], choices=resolutions)
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
