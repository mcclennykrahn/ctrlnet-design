"""Single-user saved-scenario workflow; approval is a recorded user decision."""
import json
from . import store

TRANSITIONS = {
    'draft': ('review', 'archived'),
    'review': ('draft', 'approved', 'archived'),
    'approved': ('draft', 'archived'),
    'archived': ('draft',),
}


def describe(metadata):
    state = metadata.get('lifecycle_state', 'draft')
    if state not in TRANSITIONS:
        raise ValueError('Unknown lifecycle state')
    return dict(state=state, allowed=list(TRANSITIONS[state]),
                history=metadata.get('lifecycle_history', []))


def require_draft(conn, sid):
    row = conn.execute('SELECT metadata_json FROM scenarios WHERE id=?', (sid,)).fetchone()
    if row is None:
        raise KeyError(sid)
    if describe(json.loads(row['metadata_json']))['state'] != 'draft':
        raise ValueError('Return scenario to draft before modifying it')


def transition(path, sid, target, version, note):
    if not isinstance(note, str) or not 1 <= len(note.strip()) <= 500:
        raise ValueError('Transition note must contain 1–500 characters')
    conn = store.connect(path)
    try:
        with store._write_transaction(conn):
            scenario = store._fetch_scenario_dict(conn, sid)
            if scenario is None:
                raise KeyError(sid)
            if type(version) is not int or version != scenario['version']:
                raise store.VersionConflictError('Scenario changed; refresh before transitioning')
            metadata = scenario['metadata']
            current = describe(metadata)
            if not isinstance(target, str) or target not in current['allowed']:
                raise ValueError('Illegal lifecycle transition')
            evidence = None
            if target in ('review', 'approved'):
                project = store._project_row_to_dict(conn.execute(
                    'SELECT * FROM projects WHERE id=?', (scenario['project_id'],)).fetchone())
                project['points'] = store._fetch_points(conn, scenario['project_id'])
                for row in conn.execute('SELECT id,input_hash,payload_json FROM snapshots WHERE scenario_id=? ORDER BY rowid DESC', (sid,)):
                    saved = json.loads(row['payload_json'])
                    current_input = store._snapshot_payload(project, scenario, saved['engine']['options'])
                    # Names and workflow revision counters are not numerical inputs.
                    for payload in (saved, current_input):
                        payload.pop('snapshot_id', None)
                        payload['network'].pop('version', None)
                        payload['network'].pop('name', None)
                        payload['project'].pop('name', None)
                    if store.canonical_json(saved) == store.canonical_json(current_input):
                        evidence = dict(snapshot_id=row['id'], input_hash=row['input_hash'])
                        break
                if evidence is None:
                    raise ValueError('Save a current snapshot before submitting for review')
            now = store._utcnow()
            metadata['lifecycle_state'] = target
            metadata['lifecycle_history'] = current['history'] + [dict(
                source=current['state'], target=target, note=note.strip(),
                at=now, version=version + 1, evidence=evidence)]
            conn.execute('UPDATE scenarios SET metadata_json=?,version=version+1,updated_at=? WHERE id=?',
                         (store._json_dump(metadata), now, sid))
            return dict(scenario_id=sid, version=version + 1, **describe(metadata))
    finally:
        conn.close()
