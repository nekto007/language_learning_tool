"""Exercise the real Grammar Lab JS with controlled transport and no database."""
from pathlib import Path
import shutil
import subprocess

import pytest


@pytest.mark.parametrize('suite', ['test_grammar_lab_dispute.cjs', 'test_grammar_mixed_resume.cjs'])
def test_grammar_lab_ui_in_node(suite: str) -> None:
    node = shutil.which('node')
    if node is None:
        pytest.skip('Node.js is not installed')
    root = Path(__file__).resolve().parents[2]
    result = subprocess.run(
        [node, '--test', str(Path(__file__).with_name(suite))],
        cwd=root, capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr
