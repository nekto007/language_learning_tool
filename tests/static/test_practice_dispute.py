"""Run the ordinary-quiz dispute UI contract without a database or running backend."""
from pathlib import Path
import shutil
import subprocess

import pytest


def test_practice_dispute_ui_in_node() -> None:
    node = shutil.which('node')
    if node is None:
        pytest.skip('Node.js is not installed')
    root = Path(__file__).resolve().parents[2]
    result = subprocess.run(
        [node, '--test', str(Path(__file__).with_suffix('.cjs'))],
        cwd=root, capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr
