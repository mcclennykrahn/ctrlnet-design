#!/usr/bin/env python3
"""Build an untagged candidate bundle; never publish or overwrite artifacts."""
import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True, help='new or empty output directory')
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    out = args.out.resolve()
    if out.exists() and (not out.is_dir() or any(out.iterdir())):
        parser.error('output must be a new or empty directory')
    out.mkdir(parents=True, exist_ok=True)
    # Default build isolation; build creates the wheel from the sdist.
    subprocess.run([sys.executable, '-m', 'build', '--outdir', str(out), str(root)], check=True)
    artifacts = sorted(p for p in out.iterdir() if p.suffix == '.whl' or p.name.endswith('.tar.gz'))
    if len(artifacts) != 2 or sum(p.suffix == '.whl' for p in artifacts) != 1:
        raise RuntimeError('expected exactly one wheel and one sdist')
    sums = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in artifacts}
    (out / 'SHA256SUMS').write_text(''.join(f'{sha}  {name}\n' for name, sha in sums.items()))
    revision = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=root, text=True).strip()
    dirty = bool(subprocess.check_output(['git', 'status', '--porcelain'], cwd=root, text=True))
    (out / 'release.json').write_text(json.dumps({
        'kind': 'untagged-candidate', 'source_commit': revision, 'worktree_dirty': dirty,
        'artifacts': sums, 'validation': 'not performed by build; run test_release_install.py',
    }, indent=2) + '\n')
    print(out)


if __name__ == '__main__':
    main()
