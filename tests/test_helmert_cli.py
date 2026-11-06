import json
import subprocess
import sys

import numpy as np
import pytest

from ctrlnet.cli import main


def test_estimate_apply_inverse_end_to_end(tmp_path):
    src = [[0, 0, 0], [1000, 0, 0], [0, 1000, 0], [0, 0, 1000]]
    # Independent analytic fixture: translation + scale + rotation around Z.
    dst = [[1 + 1.000002*x - 0.000003*y, 2 + 0.000003*x + 1.000002*y, 3 + 1.000002*z] for x, y, z in src]
    def run(operation, payload):
        path = tmp_path / 'input.json'
        path.write_text(json.dumps(payload))
        process = subprocess.run([sys.executable, '-m', 'ctrlnet.cli', 'helmert', operation, str(path)], capture_output=True, text=True)
        assert process.returncode == 0, process.stderr
        return json.loads(process.stdout)
    result = run('estimate', {'src': src, 'dst': dst})
    np.testing.assert_allclose(result['params'], [1, 2, 3, 0, 0, 3e-6, 2], atol=1e-8)
    assert result['parameter_units'] == ['m', 'm', 'm', 'rad', 'rad', 'rad', 'ppm']
    transformed = run('forward', {'points': src, 'params': result['params']})
    np.testing.assert_allclose(transformed['points'], dst, atol=1e-9)
    restored = run('inverse', {'points': transformed['points'], 'params': result['params']})
    np.testing.assert_allclose(restored['points'], src, atol=1e-9)


@pytest.mark.parametrize('payload', [[], {}, {'src': [[0, 0, 0]]*3, 'dst': [[0, 0, 0]]*3}, {'src': [[float('nan'), 0, 0]], 'dst': [[0, 0, 0]]}])
def test_invalid_input_does_not_replace_output(tmp_path, payload):
    path = tmp_path / 'input.json'
    path.write_text(json.dumps(payload))
    output = tmp_path / 'output.json'
    output.write_text('preserved')
    with pytest.raises(SystemExit) as exc:
        main(['helmert', 'estimate', str(path), '--out', str(output)])
    assert exc.value.code == 2
    assert output.read_text() == 'preserved'
