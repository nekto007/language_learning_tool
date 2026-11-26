"""Run the reader's visual progress calculation with representative layout geometry."""
from pathlib import Path
import shutil
import subprocess

import pytest


def test_reader_progress_measures_scroll_distance_to_visible_last_line() -> None:
    node = shutil.which('node')
    if node is None:
        pytest.skip('Node.js is not installed')
    root = Path(__file__).resolve().parents[2]
    source = (root / 'app/templates/books/reader_simple.html').read_text(encoding='utf-8')
    visual = source[source.index('let lastLine;'):source.index('function locateLastLine')]
    harness = """
const assert = require('node:assert/strict');
const progress = {hidden: true};
const progressBar = {style: {}};
const progressText = {};
const document = {getElementById: () => progress};
const readerBody = {
    scrollTop: 0,
    getBoundingClientRect: () => ({top: 60, bottom: 660, height: 600}),
};
const chapterContent = {
    getBoundingClientRect: () => ({top: 260 - readerBody.scrollTop}),
};
"""
    scenario = """
let lastBottom = 1660;
lastLine = {getBoundingClientRect: () => ({
    top: lastBottom - readerBody.scrollTop - 24,
    bottom: lastBottom - readerBody.scrollTop,
})};
for (const [position, expected] of [
    [0, 0], [500, 50], [999, 99], [1000, 100],
    [1600, 100], [1620, 100], [1000, 100], [999, 99], [0, 0],
]) {
    readerBody.scrollTop = position;
    showVisibleProgress();
    assert.equal(progress.hidden, false);
    assert.equal(progressText.textContent, expected);
    assert.equal(progressBar.style.width, expected + '%');
}
lastBottom = 440;
showVisibleProgress();
assert.equal(progressText.textContent, 100);
lastLine = undefined;
showVisibleProgress();
assert.equal(progress.hidden, true);
"""
    result = subprocess.run([node, '-e', harness + visual + scenario], capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
