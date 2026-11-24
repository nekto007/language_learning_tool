"""Keep cached legacy Grammar Lab pages usable with the current client."""
from pathlib import Path
import shutil
import subprocess

import pytest


def test_grammar_mixed_asset_compatibility() -> None:
    node = shutil.which('node')
    if node is None:
        pytest.skip('Node.js is not installed')
    result = subprocess.run([node, '--test', str(Path(__file__).with_suffix('.cjs'))],
                            cwd=Path(__file__).resolve().parents[2],
                            capture_output=True, text=True, timeout=30, check=False)
    assert result.returncode == 0, result.stdout + result.stderr
