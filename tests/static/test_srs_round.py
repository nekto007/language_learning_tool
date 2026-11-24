"""Run SRS result and audio regressions against the browser scripts."""
from pathlib import Path
import shutil
import subprocess

import pytest


def test_srs_round() -> None:
    node = shutil.which('node')
    if node is None:
        pytest.skip('Node.js is not installed')
    result = subprocess.run([node, '--test', str(Path(__file__).with_suffix('.cjs'))],
                            cwd=Path(__file__).resolve().parents[2],
                            capture_output=True, text=True, timeout=30, check=False)
    assert result.returncode == 0, result.stdout + result.stderr
