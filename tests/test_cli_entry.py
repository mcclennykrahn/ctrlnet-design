"""Smoke the actual installed console script from outside the source tree."""
import os
from pathlib import Path
import subprocess
import sys

import pytest


@pytest.mark.parametrize("command", [None, "adjust", "report", "package", "serve", "tiles"])
def test_installed_help(command, tmp_path):
    executable = Path(sys.executable).parent / "ctrlnet"
    env = dict(os.environ)
    env.pop("PYTHONPATH", None)
    result = subprocess.run(
        [str(executable), *([command] if command else []), "--help"],
        cwd=tmp_path, env=env, text=True, capture_output=True, timeout=30,
    )
    assert result.returncode == 0, result.stderr
    assert "usage:" in result.stdout
