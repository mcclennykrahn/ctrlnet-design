#!/usr/bin/env python3
"""Focused installed-wheel e2e in a fresh venv outside the checkout (network for dependencies)."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import tempfile
import time
import urllib.request
import venv


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('bundle', type=Path)
    args = parser.parse_args()
    bundle = args.bundle.resolve()
    metadata = json.loads((bundle / 'release.json').read_text())
    for name, digest in metadata['artifacts'].items():
        assert Path(name).name == name
        assert hashlib.sha256((bundle / name).read_bytes()).hexdigest() == digest, name
    wheel, = bundle.glob('*.whl')
    root = Path(__file__).resolve().parents[1]
    with tempfile.TemporaryDirectory(prefix='ctrlnet-install-') as tmp:
        work = Path(tmp)
        venv.EnvBuilder(with_pip=True).create(work / 'venv')
        bin_dir = work / 'venv' / 'bin'
        env = os.environ.copy()
        for key in list(env):
            if key.startswith(('PYTHON', 'CTRLNET')):
                env.pop(key)
        env['PYTHONNOUSERSITE'] = '1'
        def run(*cmd):
            return subprocess.run([str(x) for x in cmd], cwd=work, env=env, check=True)
        run(bin_dir / 'python', '-m', 'pip', 'install', f'{wheel}[webmap]')
        run(bin_dir / 'python', '-m', 'pip', 'check')
        run(bin_dir / 'python', '-c',
            'import ctrlnet,sys; from pathlib import Path; '
            'assert Path(ctrlnet.__file__).is_relative_to(Path(sys.prefix))')
        for entry in ('ctrlnet', 'ctrlnet-web', 'ctrlnet-package'):
            run(bin_dir / entry, '--help')
        project = work / 'project.sqlite'
        shutil.copy2(root / 'data/sample/demo_project.sqlite', project)
        run(bin_dir / 'ctrlnet', 'adjust', '--project', project, '--out', work / 'adjust.json')
        assert json.loads((work / 'adjust.json').read_text())
        with socket.socket() as sock:
            sock.bind(('127.0.0.1', 0))
            port = sock.getsockname()[1]
        with (work / 'server.log').open('w+') as log:
            server = subprocess.Popen([str(bin_dir / 'ctrlnet-web'), '--project', str(project),
                                       '--port', str(port)], cwd=work, env=env, stdout=log, stderr=log)
            try:
                base = f'http://127.0.0.1:{port}'
                for _ in range(150):
                    if server.poll() is not None:
                        log.seek(0)
                        raise RuntimeError(log.read())
                    try:
                        with urllib.request.urlopen(base + '/api/health', timeout=1) as response:
                            assert json.load(response)['status'] == 'ok'
                        break
                    except OSError:
                        time.sleep(.2)
                else:
                    raise RuntimeError('server readiness timed out')
                for path in ('/', '/static/leaflet/leaflet.js', '/static/leaflet/leaflet.css',
                             '/static/leaflet/images/marker-icon.png'):
                    with urllib.request.urlopen(base + path, timeout=5) as response:
                        assert response.status == 200 and response.read(), path
            finally:
                server.terminate()
                try:
                    server.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    server.kill()
                    server.wait()
    print('PASS: checksums, fresh wheel install, pip check, entry points, adjustment, HTTP health and bundled assets')


if __name__ == '__main__':
    main()
