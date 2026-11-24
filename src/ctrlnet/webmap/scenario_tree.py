"""Conservative three-way merge of saved editor scenarios.

Disjoint existing-point edits, measured line overrides and network settings
merge automatically; competing existing-point edits offer whole-point choices.
Competing network settings offer whole-object choices; measured override
conflicts offer whole-line choices for existing lines.
Combined field merges match points/lines/angles by ID and retain target list order.
Known allocator counters merge by maximum even without structural changes.
Existing-line and existing-angle names merge by ID with whole-object conflict choices.
Existing-line endpoint changes merge as whole authored lines, so measurements
never transfer automatically between different endpoint pairs.
Existing-angle reference changes merge as whole authored angles.
Isolated point additions and unchanged isolated point deletions merge by ID.
Unchanged line and angle deletions clear unchanged selections and merge
with allocator preservation.
Line additions between surviving existing or compatible new points merge by ID;
selections use whole-network merge rules.
Angle additions between common existing points merge by ID; selections use
whole-network merge rules.
Other topology conflicts retain whole-topology choices.
One-sided editor project-title edits combine with supported topology edits;
competing titles offer independent target/source title choices.
Both parents remain durable.
Differing-content best bases require whole-unit choices unless the tips agree
or every best base produces an equivalent conflict-free topology merge;
an otherwise clean consensus can retain an independent competing-title choice
when every best base reports only that same title conflict. Title and network
conflicts can coexist when all four outcomes agree across every best base.
A lone whole-point, whole-line or whole-angle choice is also retained when
both outcomes agree across every best base. A title plus one whole-angle choice
is retained only when all four outcomes agree; other mixed or multiple field
conflicts retain whole-topology choices.
Units with equivalent authored bases retain ordinary three-way behavior,
including bases differing only in stable-ID list presentation order,
reconciling valid known allocator counters across every base.
"""
import copy
from itertools import product
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


def _same_base(key, a, b):
    """Presentation order does not distinguish stable-ID authored ancestors.

    Normalize comparison copies only; the merge still uses the target's order.
    Unknown fields and malformed/duplicate IDs must not disappear in comparison.
    """
    if key != 'topology':
        return _same(key, a, b)
    values = copy.deepcopy([a, b])
    for value in values:
        for collection in ('points', 'lines', 'angles'):
            items = value.get(collection)
            if not isinstance(items, list) or any(not isinstance(item, dict) for item in items):
                return False
            ids = [item.get('id') for item in items]
            if any(not isinstance(i, str) or not i for i in ids) or len(set(ids)) != len(ids):
                return False
            items.sort(key=lambda item: item['id'])
    return _same(key, *values)


def _merge_point_coordinates(base, target, source, point_conflicts=None, choices=None):
    """Merge existing-point fields and measured line overrides by authored field.

    A point's x/y/lon/lat tuple is indivisible. Derived geometry and timestamps
    are ignored. Each measured override flag/value pair and the entire network
    settings object are indivisible. Competing point edits select a whole point;
    competing network edits select the whole settings object. Competing measured
    overrides select a whole line, with unkept geometry recomputed afterward.
    Changed endpoint pairs make the entire authored line indivisible.
    """
    from .thesis_web import _ensure_geometry, _refresh_derived
    coordinates = ('x', 'y', 'lon', 'lat')
    groups = (coordinates, ('name',), ('fixed',))

    def skeleton(state):
        value = copy.deepcopy(state)
        for field in ('created_at', 'updated_at', 'saved_created_at', 'saved_updated_at'):
            value.pop(field, None)
        value.pop('network', None)
        value.pop('name', None)
        # Known counters record consumed IDs, independently of authored topology.
        seq = value.get('seq')
        if not isinstance(seq, dict) or any(
                type(seq.get(key)) is not int or seq[key] < 0
                for key in ('point', 'line', 'angle')):
            return None
        for key in ('point', 'line', 'angle'):
            seq.pop(key)
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
            # Only references to distinct existing point IDs are in scope.
            if (line.get('from') not in ids or line.get('to') not in ids
                    or line['from'] == line['to']):
                return None
            line.pop('from', None)
            line.pop('to', None)
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
            refs = [angle.get(field) for field in ('station', 'backsight', 'foresight')]
            if any(ref not in ids for ref in refs) or len(set(refs)) != 3:
                return None
            for field in ('station', 'backsight', 'foresight'):
                angle.pop(field, None)
            angle.pop('value', None)
            angle.pop('name', None)
        return value

    # Ignore derived geometry, but retain every authored measurement detail.
    states = (base, target, source)
    line_indexes = []
    for state in states:
        ids = [line.get('id') for line in state['lines']]
        if any(not isinstance(i, str) or not i for i in ids) or len(set(ids)) != len(ids):
            return None
        line_indexes.append({line['id']: line for line in state['lines']})
    added_lines = (set(line_indexes[1]) | set(line_indexes[2])) - set(line_indexes[0])
    if added_lines:
        # Check before stripping so recursion cannot hide new references.
        point_ids = [{p['id'] for p in state['points']} for state in states]
        # Base endpoints must survive both branches. Recursion validates new
        # points and their collisions after the added lines are stripped.
        common_points = (set.intersection(*point_ids)
                         | ((point_ids[1] | point_ids[2]) - point_ids[0]))
        # Selection merges with the whole network object below. Accepted
        # additions are restored for every network choice, keeping IDs valid.
        additions = {}
        for state, index in zip(states[1:], line_indexes[1:]):
            local_points = {p['id'] for p in state['points']}
            for lid in added_lines & set(index):
                line = index[lid]
                if (set(line) - {'id', 'name', 'from', 'to', 'length', 'azimuth',
                                 '_keep_length', '_keep_azimuth'}
                        or line.get('from') not in common_points
                        or line.get('to') not in common_points
                        or line.get('from') not in local_points
                        or line.get('to') not in local_points
                        or line['from'] == line['to']):
                    return None
                authored = copy.deepcopy(line)
                for field in ('length', 'azimuth'):
                    if not line.get('_keep_' + field):
                        authored.pop(field, None)
                if lid in additions and additions[lid] != authored:
                    return None
                additions[lid] = authored
        # Every offered whole-line choice must remain compatible with additions.
        # Checking only the default result can advertise a resolution that later
        # produces duplicate names or undirected endpoint pairs.
        survivors = set.intersection(*(set(index) for index in line_indexes))
        added_names = {str(line.get('name')) for line in additions.values()}
        added_pairs = {frozenset((line['from'], line['to']))
                       for line in additions.values()}
        if any(str(index[lid].get('name')) in added_names
               or frozenset((index[lid]['from'], index[lid]['to'])) in added_pairs
               for index in line_indexes[1:] for lid in survivors):
            return None
        stripped = copy.deepcopy(states)
        for state in stripped:
            state['lines'] = [line for line in state['lines'] if line['id'] not in added_lines]
            state['seq']['line'] = base['seq']['line']
        combined = _merge_point_coordinates(*stripped, point_conflicts=point_conflicts, choices=choices)
        if combined is None:
            return None
        by_id = {line['id']: line for line in combined['lines']}
        by_id.update(copy.deepcopy(additions))
        order = [line['id'] for line in target['lines'] if line['id'] in by_id]
        order += [line['id'] for line in source['lines']
                  if line['id'] in by_id and line['id'] not in line_indexes[1]]
        combined['lines'] = [by_id[lid] for lid in order]
        names = [str(line.get('name')) for line in combined['lines']]
        if len(set(names)) != len(names):
            return None
        pairs = [frozenset((line['from'], line['to'])) for line in combined['lines']]
        if len(set(pairs)) != len(pairs):
            return None
        combined['seq']['line'] = max(state['seq']['line'] for state in states)
        _ensure_geometry(combined)
        _refresh_derived(combined)
        return combined

    removed_lines = set(line_indexes[0]) - (set(line_indexes[1]) & set(line_indexes[2]))
    if removed_lines:
        # Inspect original references before stripping lines: otherwise a
        # referenced point can appear isolated to the recursive deletion guard.
        removed_points = {p['id'] for p in base['points']} - (
            {p['id'] for p in target['points']} & {p['id'] for p in source['points']})
        if any(line.get(key) in removed_points for state in states
               for line in state['lines'] for key in ('from', 'to')):
            return None
        # A retaining branch must preserve the base selection for each deleted
        # line. A deleting branch must clear it. Strip those references from all
        # three networks before merging unrelated settings, so neither network
        # resolution can resurrect a dangling selection.
        selection_keys = ('observed_edges', 'added_edges')
        for lid in removed_lines:
            for state, index in zip((target, source), line_indexes[1:]):
                for key in selection_keys:
                    selected = lid in state.get('network', {}).get(key, [])
                    expected = lid in base.get('network', {}).get(key, []) if lid in index else False
                    if selected != expected:
                        return None
        def authored_deleted_line(line):
            value = copy.deepcopy(line)
            for field in ('length', 'azimuth'):
                if not line.get('_keep_' + field):
                    value.pop(field, None)
            return value
        for lid in removed_lines:
            original = line_indexes[0][lid]
            if set(original) - {'id', 'name', 'from', 'to', 'length', 'azimuth',
                                '_keep_length', '_keep_azimuth'}:
                return None
            if any(lid in index and authored_deleted_line(index[lid]) !=
                   authored_deleted_line(original) for index in line_indexes[1:]):
                return None
        stripped = copy.deepcopy(states)
        for state in stripped:
            state['lines'] = [line for line in state['lines'] if line['id'] not in removed_lines]
            for key in selection_keys:
                if key in state.get('network', {}):
                    state['network'][key] = [lid for lid in state['network'][key]
                                             if lid not in removed_lines]
            state['seq']['line'] = base['seq']['line']
        combined = _merge_point_coordinates(*stripped, point_conflicts=point_conflicts, choices=choices)
        if combined is not None:
            network = combined.get('network', {})
            if any(lid in removed_lines for key in ('observed_edges', 'added_edges')
                   for lid in network.get(key, [])):
                return None
            combined['seq']['line'] = max(state['seq']['line'] for state in states)
        return combined

    states = (base, target, source)
    angle_indexes = []
    for state in states:
        ids = [angle.get('id') for angle in state['angles']]
        if any(not isinstance(i, str) or not i for i in ids) or len(set(ids)) != len(ids):
            return None
        angle_indexes.append({angle['id']: angle for angle in state['angles']})
    added_angles = (set(angle_indexes[1]) | set(angle_indexes[2])) - set(angle_indexes[0])
    if added_angles:
        point_ids = [{p['id'] for p in state['points']} for state in states]
        # Existing references must survive both branches; recursion validates
        # new points for authored compatibility and name collisions.
        common_points = (set.intersection(*point_ids)
                         | ((point_ids[1] | point_ids[2]) - point_ids[0]))
        # Keep selections in the indivisible network object, as for lines.
        # All accepted additions are restored for either network choice.
        additions = {}
        refs = ('station', 'backsight', 'foresight')
        for state, index in zip(states[1:], angle_indexes[1:]):
            local_points = {p['id'] for p in state['points']}
            for aid in added_angles & set(index):
                angle = index[aid]
                triple = tuple(angle.get(key) for key in refs)
                if (set(angle) - {'id', 'name', 'station', 'backsight', 'foresight', 'value'}
                        or any(pid not in common_points or pid not in local_points for pid in triple)
                        or len(set(triple)) != 3):
                    return None
                authored = {k: v for k, v in angle.items() if k != 'value'}
                if aid in additions and additions[aid] != authored:
                    return None
                additions[aid] = authored
        # Preview must remain safe for every whole-angle choice it offers.
        # Checking only the default merged result can hide a collision in the
        # other branch, causing the resolution pass to return no topology.
        survivors = set.intersection(*(set(index) for index in angle_indexes))
        added_names = {str(a.get('name')) for a in additions.values()}
        added_triples = {tuple(a[key] for key in refs) for a in additions.values()}
        if any(str(index[aid].get('name')) in added_names
               or tuple(index[aid].get(key) for key in refs) in added_triples
               for index in angle_indexes[1:] for aid in survivors):
            return None
        stripped = copy.deepcopy(states)
        for state in stripped:
            state['angles'] = [a for a in state['angles'] if a['id'] not in added_angles]
            state['seq']['angle'] = base['seq']['angle']
        combined = _merge_point_coordinates(*stripped, point_conflicts=point_conflicts, choices=choices)
        if combined is None:
            return None
        by_id = {a['id']: a for a in combined['angles']}
        by_id.update(copy.deepcopy(additions))
        order = [a['id'] for a in target['angles'] if a['id'] in by_id]
        order += [a['id'] for a in source['angles']
                  if a['id'] in by_id and a['id'] not in angle_indexes[1]]
        combined['angles'] = [by_id[aid] for aid in order]
        names = [str(a.get('name')) for a in combined['angles']]
        triples = [tuple(a[key] for key in refs) for a in combined['angles']]
        if len(set(names)) != len(names) or len(set(triples)) != len(triples):
            return None
        combined['seq']['angle'] = max(state['seq']['angle'] for state in states)
        _ensure_geometry(combined)
        _refresh_derived(combined)
        return combined

    removed_angles = set(angle_indexes[0]) - (set(angle_indexes[1]) & set(angle_indexes[2]))
    if removed_angles:
        # Stripping angles must not hide a referenced-point deletion from the
        # existing isolated-point guard below.
        removed_points = {p['id'] for p in base['points']} - (
            {p['id'] for p in target['points']} & {p['id'] for p in source['points']})
        if any(angle.get(key) in removed_points for state in states
               for angle in state['angles'] for key in ('station', 'backsight', 'foresight')):
            return None
        # Retaining branches must preserve base membership; deleting branches
        # must clear it. Remove these IDs before whole-network choices so no
        # resolution can resurrect a dangling angle selection.
        selection_keys = ('observed_angles', 'added_angles')
        for aid in removed_angles:
            for state, index in zip((target, source), angle_indexes[1:]):
                for key in selection_keys:
                    selected = aid in state.get('network', {}).get(key, [])
                    expected = aid in base.get('network', {}).get(key, []) if aid in index else False
                    if selected != expected:
                        return None
        def authored_deleted_angle(angle):
            value = copy.deepcopy(angle)
            value.pop('value', None)
            return value
        for aid in removed_angles:
            original = angle_indexes[0][aid]
            if set(original) - {'id', 'name', 'station', 'backsight', 'foresight', 'value'}:
                return None
            if any(aid in index and authored_deleted_angle(index[aid]) !=
                   authored_deleted_angle(original) for index in angle_indexes[1:]):
                return None
        stripped = copy.deepcopy(states)
        for state in stripped:
            state['angles'] = [angle for angle in state['angles'] if angle['id'] not in removed_angles]
            for key in selection_keys:
                if key in state.get('network', {}):
                    state['network'][key] = [aid for aid in state['network'][key]
                                             if aid not in removed_angles]
            state['seq']['angle'] = base['seq']['angle']
        combined = _merge_point_coordinates(*stripped, point_conflicts=point_conflicts, choices=choices)
        if combined is not None:
            network = combined.get('network', {})
            if any(aid in removed_angles for key in ('observed_angles', 'added_angles')
                   for aid in network.get(key, [])):
                return None
            combined['seq']['angle'] = max(state['seq']['angle'] for state in states)
        return combined

    # Isolated additions/deletions: stripping them must leave a supported merge.
    # Referenced deletions remain conservative; additions are checked recursively.
    base_ids = {p['id'] for p in base['points']}
    branch_ids = [{p['id'] for p in state['points']} for state in (target, source)]
    removed = base_ids - set.intersection(*branch_ids)
    if removed:
        # Deletions are safe only for isolated, otherwise unchanged points.
        states = (base, target, source)
        indexes = []
        for state in states:
            ids = [p.get('id') for p in state['points']]
            if (any(not isinstance(i, str) or not i for i in ids)
                    or len(set(ids)) != len(ids)):
                return None
            indexes.append({p['id']: p for p in state['points']})
            if any(line.get(k) in removed for line in state['lines'] for k in ('from', 'to')):
                return None
            if any(angle.get(k) in removed for angle in state['angles']
                   for k in ('station', 'backsight', 'foresight')):
                return None
        for pid in removed:
            original = indexes[0][pid]
            if set(original) - {'id', 'name', 'x', 'y', 'lon', 'lat', 'fixed'}:
                return None
            if any(pid in index and index[pid] != original for index in indexes[1:]):
                return None
        stripped = copy.deepcopy(states)
        for state in stripped:
            state['points'] = [p for p in state['points'] if p['id'] not in removed]
            state['seq']['point'] = base['seq']['point']
        combined = _merge_point_coordinates(*stripped, point_conflicts=point_conflicts, choices=choices)
        if combined is not None:
            combined['seq']['point'] = max(state['seq']['point'] for state in states)
        return combined
    if any({p['id'] for p in state['points']} != base_ids for state in (target, source)):
        states = (base, target, source)
        indexes = []
        for state in states:
            ids = [p.get('id') for p in state['points']]
            if (any(not isinstance(i, str) or not i for i in ids)
                    or len(set(ids)) != len(ids) or not base_ids <= set(ids)):
                return None
            indexes.append({p['id']: p for p in state['points']})
        additions = {}
        for index in indexes[1:]:
            for pid, point in index.items():
                if pid in base_ids:
                    continue
                if set(point) - {'id', 'name', 'x', 'y', 'lon', 'lat', 'fixed'}:
                    return None
                if pid in additions and additions[pid] != point:
                    return None
                additions[pid] = point
        stripped = copy.deepcopy(states)
        for state in stripped:
            state['points'] = [p for p in state['points'] if p['id'] in base_ids]
            state['seq']['point'] = base['seq']['point']
        combined = _merge_point_coordinates(*stripped, point_conflicts=point_conflicts, choices=choices)
        if combined is None:
            return None
        by_id = {p['id']: p for p in combined['points']}
        by_id.update(copy.deepcopy(additions))
        order = [p['id'] for p in target['points']]
        order += [p['id'] for p in source['points'] if p['id'] not in indexes[1]]
        combined['points'] = [by_id[pid] for pid in order]
        names = [str(p.get('name')) for p in combined['points']]
        if len(set(names)) != len(names):
            return None
        # Keep both allocators' high-water marks to avoid future ID reuse.
        combined['seq']['point'] = max(state['seq']['point'] for state in states)
        _ensure_geometry(combined)
        _refresh_derived(combined)
        return combined

    shapes = [skeleton(s) for s in (base, target, source)]
    if shapes[0] is None or not shapes[0] == shapes[1] == shapes[2]:
        return None
    result = copy.deepcopy(target)
    for key in ('point', 'line', 'angle'):
        result['seq'][key] = max(state['seq'][key] for state in (base, target, source))
    # The editor title is independent of geometry and observation selections.
    # Preserve presence as well as value. Title choices keep geometry edits intact;
    # callers without a conflict collector still require a clean merge.
    b, t, s = (("name" in state, state.get("name"))
               for state in (base, target, source))
    if t == s or s == b:
        chosen_title = target
    elif t == b:
        chosen_title = source
    else:
        if point_conflicts is None:
            return None
        point_conflicts.append('title')
        chosen_title = source if (choices or {}).get('title') == 'source' else target
    if 'name' in chosen_title:
        result['name'] = copy.deepcopy(chosen_title['name'])
    else:
        result.pop('name', None)
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
        endpoints = [(line['from'], line['to']) for line in (bl, tl, sl)]
        if not endpoints[0] == endpoints[1] == endpoints[2]:
            # An observation belongs to its endpoint pair. Treat the whole line
            # as indivisible whenever endpoints change, including measurements
            # and names, rather than grafting old measurements onto a new edge.
            def authored_line(line):
                value = copy.deepcopy(line)
                for field in ('length', 'azimuth'):
                    if not line.get('_keep_' + field):
                        value.pop(field, None)
                return value
            b, t, s = map(authored_line, (bl, tl, sl))
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
            continue
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
        def authored_angle(angle):
            # Derived values do not count as edits. Names and references travel
            # together so an authored name cannot migrate to a different ray.
            value = copy.deepcopy(angle)
            value.pop('value', None)
            return value
        b, t, s = map(authored_angle, (ba, ta, sa))
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
        # Whole-angle selection keeps reference triples and names together.
        out.clear()
        out.update(copy.deepcopy(chosen))
    _ensure_geometry(result)
    _refresh_derived(result)
    return result


def _plan(conn, target, source, choices=None):
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
    # Never use an arbitrary representative to resolve differing ancestor units.
    # Such units require agreement of tips or clean results from every base.
    bases = sorted(b for b in common if not any(b != c and b in ancestors(c) for c in common))
    if not bases:
        raise ValueError('需要共同祖先')
    base = rows[bases[0]]
    base_units = _units(base)
    # Known consumed-ID counters do not make authored ancestors disagree.
    # Use their shared high-water marks in the representative merge state,
    # including the later field-choice pass, without modifying saved ancestors.
    ancestor_units = [_units(rows[bid]) for bid in bases]
    counters = ('point', 'line', 'angle')
    valid_counters = all(
        isinstance(u['topology'].get('seq'), dict) and all(
            type(u['topology']['seq'].get(k)) is int
            and u['topology']['seq'][k] >= 0 for k in counters)
        for u in ancestor_units)
    if valid_counters:
        high_water = {k: max(u['topology']['seq'][k] for u in ancestor_units)
                      for k in counters}
        base_units['topology']['seq'].update(high_water)
        for u in ancestor_units:
            u['topology']['seq'].update(high_water)
    ambiguous_units = set()
    reordered_topology_bases = False
    for other in ancestor_units[1:]:
        if (_same_base('topology', base_units['topology'], other['topology'])
                and not _same('topology', base_units['topology'], other['topology'])):
            reordered_topology_bases = True
        ambiguous_units.update(key for key, value in base_units.items()
                               if not _same_base(key, value, other[key]))
    units = [base_units, _units(t), _units(s)]
    conflicts, merged = [], {}
    for key in units[0]:
        b, tv, sv = (u[key] for u in units)
        # Preserve the existing convergence path even when order-only bases
        # become equivalent: structural convergence need not replay edits.
        tip_values = copy.deepcopy([tv, sv])
        if key == 'topology':
            for value in tip_values:
                if isinstance(value.get('seq'), dict):
                    for counter in ('point', 'line', 'angle'):
                        value['seq'].pop(counter, None)
        if key in ambiguous_units or (key == 'topology' and reordered_topology_bases
                                      and _same(key, *tip_values)):
            if _same_base(key, *tip_values):
                if key == 'topology':
                    # Stable-ID list order does not undo authored convergence.
                    # Retain the target presentation without replaying edits.
                    # Converged authored tips can have reset counters (for
                    # example after JSON import). Preserve consumed IDs from
                    # every best base without replaying ancestor edits.
                    states = [*(_units(rows[bid])[key] for bid in bases), tv, sv]
                    counters = ('point', 'line', 'angle')
                    if any(not isinstance(state.get('seq'), dict) or any(
                            type(state['seq'].get(counter)) is not int
                            or state['seq'][counter] < 0 for counter in counters)
                           for state in states):
                        conflicts.append(key)
                        continue
                    merged[key] = copy.deepcopy(tv)
                    merged[key]['seq'].update({
                        counter: max(state['seq'][counter] for state in states)
                        for counter in counters})
                else:
                    merged[key] = tv
            else:
                # Every base must permit the same geometry, with either no
                # conflicts or the same bounded title/network or lone item choice.
                candidates = []
                candidate_conflicts = []
                if key == 'topology':
                    for bid in bases:
                        fields = []
                        candidate = _merge_point_coordinates(
                            _units(rows[bid])[key], tv, sv, point_conflicts=fields, choices=choices)
                        if candidate is None or not (
                                fields in ([], ['title'], ['network'], ['title', 'network'])
                                or (len(fields) == 1 and fields[0].startswith(('point:', 'line:', 'angle:')))
                                or (len(fields) == 2 and fields[0] == 'title'
                                    and fields[1].startswith('angle:'))):
                            break
                        candidates.append(candidate)
                        candidate_conflicts.append(fields)
                if candidates and len(candidates) == len(bases):
                    # Each clean candidate already preserves its base and both
                    # tips. Reconcile consumed IDs across *all* best bases
                    # before comparing authored results; a larger counter is
                    # bookkeeping, not a competing ancestor edit.
                    high_water = {counter: max(c['seq'][counter] for c in candidates)
                                  for counter in ('point', 'line', 'angle')}
                    for candidate in candidates:
                        candidate['seq'].update(high_water)
                if (len(candidates) == len(bases)
                        and all(fields == candidate_conflicts[0] for fields in candidate_conflicts)
                        and all(
                            _same(key, candidates[0], candidate) for candidate in candidates[1:])):
                    # Check every supported choice outcome. Selection
                    # filtering can depend on structural edits, so agreement for
                    # one choice cannot establish agreement for another.
                    choice_fields = candidate_conflicts[0]
                    outcomes_agree = True
                    for outcomes in product(('target', 'source'), repeat=len(choice_fields)):
                        resolved_choices = dict(zip(choice_fields, outcomes))
                        alternate = []
                        for bid in bases:
                            fields = []
                            value = _merge_point_coordinates(
                                _units(rows[bid])[key], tv, sv,
                                point_conflicts=fields, choices=resolved_choices)
                            if value is None or fields != choice_fields:
                                break
                            value['seq'].update(high_water)
                            alternate.append(value)
                        if len(alternate) != len(bases) or any(
                                not _same(key, alternate[0], value)
                                for value in alternate[1:]):
                            outcomes_agree = False
                            break
                    if not outcomes_agree:
                        conflicts.append(key)
                        continue
                    merged[key] = candidates[0]
                    conflicts.extend(candidate_conflicts[0])
                else:
                    conflicts.append(key)
        elif (_same(key, tv, sv) or (
                not (key == 'topology' and reordered_topology_bases)
                and (_same(key, sv, b) or _same(key, tv, b)))):
            chosen = sv if not (_same(key, tv, sv) or _same(key, sv, b)) else tv
            if key == 'topology':
                # Trivial content merges can reset consumed IDs through import
                # or converged deletions. Preserve all ancestor high-water marks.
                states = [*(_units(rows[bid])[key] for bid in bases), tv, sv]
                counters = ('point', 'line', 'angle')
                if any(not isinstance(state.get('seq'), dict) or any(
                        type(state['seq'].get(counter)) is not int
                        or state['seq'][counter] < 0 for counter in counters)
                       for state in states):
                    conflicts.append(key)
                    continue
                chosen = copy.deepcopy(chosen)
                chosen['seq'].update({
                    counter: max(state['seq'][counter] for state in states)
                    for counter in counters})
            merged[key] = chosen
        else:
            point_conflicts = []
            combined = _merge_point_coordinates(b, tv, sv, point_conflicts) if key == 'topology' else None
            if combined is None:
                conflicts.append(key)
            else:
                merged[key] = combined
                conflicts.extend(point_conflicts)
    versions = {r['id']: r['version'] for r in [*(rows[bid] for bid in bases), t, s]}
    return dict(target=target, source=source, base=base['id'], bases=bases,
                differing_base_units=sorted(ambiguous_units), versions=versions,
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
                if key not in ('network', 'title') and not key.startswith(('point:', 'line:', 'angle:')):
                    merged[key] = units[1 if choice == 'target' else 2][key]
            if 'topology' in plan['differing_base_units'] and (
                    'network' in resolutions or any(k.startswith(('point:', 'line:', 'angle:')) for k in resolutions)):
                _, resolved, _, _ = _plan(conn, payload['target'], payload['source'], resolutions)
                merged['topology'] = resolved['topology']
            elif 'topology' in plan['differing_base_units'] and 'title' in resolutions:
                # The geometry was verified against every base. Replaying the
                # representative ancestor here would discard that consensus.
                chosen = units[1 if resolutions['title'] == 'target' else 2]['topology']
                if 'name' in chosen:
                    merged['topology']['name'] = copy.deepcopy(chosen['name'])
                else:
                    merged['topology'].pop('name', None)
            elif {'network', 'title'} & resolutions.keys() or any(key.startswith(('point:', 'line:', 'angle:')) for key in resolutions):
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
                            merge_base=plan['base'], merge_bases=plan['bases'], merge_versions=plan['versions'],
                            merge_resolutions=resolutions)
            result = store.save_editor_version(path,
                dict(id=target['project_id'], name=name, points=points),
                dict(name=name, observations=observations, metadata=metadata),
                parent_snapshot=parent['id'], _connection=conn)
            return dict(result, merge=plan)
    finally:
        conn.close()
