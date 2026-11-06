"""在临时工程库演示并发写、版本冲突、审计；只保留 JSON 摘要。"""
import json
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from ctrlnet.store import (
    VersionConflictError, add_observation, connect, get_scenario, save_project,
    update_observations,
)

ROOT = Path(__file__).resolve().parents[1]


def main():
    with tempfile.TemporaryDirectory(dir=ROOT / 'outputs') as temp:
        path = Path(temp) / 'demo.sqlite'
        save_project(path, {'id': 'demo', 'name': '并发审计演示', 'points': [],
                            'scenarios': [{'id': 'base', 'name': '基准'}]})
        def append(i):
            add_observation(path, 'base', {'id': f'o{i}', 'kind': 'distance',
                                         'from': 'A', 'to': 'B'})
        with ThreadPoolExecutor(max_workers=4) as pool:
            list(pool.map(append, range(20)))
        scenario = get_scenario(path, 'base')
        conflict = False
        try:
            update_observations(path, 'base', [], expected_version=1)
        except VersionConflictError:
            conflict = True
        conn = connect(path)
        try:
            summary = {
                'writers': 4, 'observations': scenario['n_observations'],
                'version': scenario['version'], 'stale_version_rejected': conflict,
                'journal_mode': conn.execute('PRAGMA journal_mode').fetchone()[0],
                'integrity_check': conn.execute('PRAGMA integrity_check').fetchone()[0],
                'audit_counts': [dict(r) for r in conn.execute(
                    'SELECT object_type,operation,count(*) AS count FROM audit_log '
                    'GROUP BY object_type,operation ORDER BY object_type,operation')],
            }
        finally:
            conn.close()
        assert summary['observations'] == 20 and summary['version'] == 21
        assert conflict and summary['integrity_check'] == 'ok'
    output = ROOT / 'outputs' / 'store_concurrency_demo.json'
    output.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + '\n')
    print(output)


if __name__ == '__main__':
    main()
