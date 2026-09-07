"""Run the actual reader session state machine with delayed HTTP responses."""
# ruff: noqa: RUF001 -- assertions intentionally match the Russian UI labels
from pathlib import Path
import shutil
import subprocess

import pytest


SOURCE = Path('app/templates/books/reader_simple.html').read_text(encoding='utf-8')
SOURCE = SOURCE[SOURCE.index('(function () {', SOURCE.index('// Reading session —')):]
SOURCE = SOURCE[:SOURCE.index('// Word translation')]
SOURCE = SOURCE.replace("{{ csrf_token() }}", 'test-csrf')
SOURCE = SOURCE.replace('{{ current_chapter.id }}', '81')
SOURCE = SOURCE.rsplit('})();', 1)[0] + """
globalThis.reader = {
    open: _openSession, close: _closeSession, start: _start, pause: _pause,
    render: _renderTimer, extend: _extendCheckpoint, heartbeat: _scheduleHeartbeat,
    seed(seconds, checkpoint = 300) {
        state = 'active'; activeSecondsToday = seconds; nextCheckpoint = checkpoint;
        didSeedFromServer = true; activeTickAnchor = Date.now();
    },
    get clock() { return { seconds: activeSecondsToday, anchor: activeTickAnchor,
        checkpoint: nextCheckpoint, paused: checkpointPause, state, sessionId }; }
};
})();
"""

HARNESS = """
const assert = require('node:assert/strict');
let now = 100000;
Date.now = () => now;
const requests = [];
const intervals = [];
global.setInterval = (fn, ms) => { intervals.push({fn, ms}); return intervals.length; };
global.clearInterval = () => {};
global.setTimeout = () => 1;
global.clearTimeout = () => {};
const makeElement = () => ({ hidden: true, textContent: '', children: [],
    classList: {toggle() {}}, setAttribute() {}, addEventListener() {},
    appendChild(child) { this.children.push(child); },
    set innerHTML(value) { this.children = []; }
});
const title = makeElement(), cta = makeElement();
const elements = Object.fromEntries(['reading-timer-bar', 'reading-timer-elapsed',
    'reading-timer-target', 'reading-pause-btn'].map(id => [id, makeElement()]));
elements['reading-completion-banner'] = {
    hidden: true, querySelector: selector => selector.endsWith('__title') ? title : cta
};
global.document = {hidden: false, addEventListener() {}, createElement: makeElement,
    getElementById: id => elements[id] || null};
global.window = {addEventListener() {}};
global.readerBody = {scrollTop: 0, scrollHeight: 100, clientHeight: 50};
global.fetch = (url, options) => new Promise(resolve => requests.push({url, resolve}));
async function reply(data, ok = true) {
    const request = requests.shift();
    assert.ok(request, 'expected an outstanding request');
    request.resolve({ok, json: async () => data});
    for (let i = 0; i < 12; i++) await Promise.resolve();
    return request.url;
}
const startData = seconds => ({session_id: 1098, book_seconds_today: seconds,
    today_target_seconds: 300, study_date: '2026-09-08'});
"""


@pytest.mark.parametrize('scenario', [
    # Initial HTTP latency must not be included in the displayed reading time.
    """
    reader.start(); now += 5000;
    assert.equal(reader.clock.anchor, null);
    await reply(startData(291));
    reader.render();
    assert.equal(elements['reading-timer-elapsed'].textContent, '04:51');
    assert.equal(reader.clock.anchor, now);
    """,
    # The reported incident: local 300 / server 291 reconciles without reload,
    # stays on the original target, and completes after nine more seconds.
    """
    reader.seed(300); reader.open(); await reply(startData(291));
    assert.equal(reader.clock.seconds, 291);
    assert.equal(reader.clock.checkpoint, 300);
    assert.equal(reader.clock.paused, false);
    now += 9000; reader.render();
    assert.equal(reader.clock.paused, true);
    assert.equal(requests[0].url, '/api/books/reading-session/end');
    await reply({banner_state: 'daily_target', daily_target_met: true,
        next_slot_url: '/lesson/next', dashboard_url: '/dashboard'});
    assert.equal(title.textContent, '🎉 Дневная норма по чтению выполнена');
    assert.deepEqual(cta.children.map(child => child.textContent),
        ['Следующий урок плана', 'На дашборд', 'Ещё 5 минут']);
    """,
    # Actual heartbeat callback: neither /end latency nor /start latency counts.
    """
    reader.seed(200); reader.open(); await reply(startData(200));
    reader.heartbeat(); now += 60000;
    intervals.find(timer => timer.ms === 60000).fn();
    assert.equal(reader.clock.seconds, 260);
    assert.equal(reader.clock.anchor, null);
    now += 5000; reader.render();
    assert.equal(elements['reading-timer-elapsed'].textContent, '04:20');
    await reply({banner_state: 'none'});
    assert.equal(requests[0].url, '/api/books/reading-session/start');
    now += 5000; reader.render();
    assert.equal(elements['reading-timer-elapsed'].textContent, '04:20');
    await reply(startData(261));
    assert.equal(reader.clock.seconds, 261);
    assert.equal(reader.clock.anchor, now);
    """,
    # Reconciliation must not replace an explicitly extended checkpoint.
    """
    reader.seed(350, 600); reader.open(); await reply(startData(341));
    assert.equal(reader.clock.checkpoint, 600);
    assert.equal(reader.clock.seconds, 341);
    """,
    # Pausing while /start is in flight must close the late-created session.
    """
    reader.start(); reader.pause(); now += 4000;
    await reply(startData(291));
    assert.equal(reader.clock.state, 'paused');
    assert.equal(reader.clock.anchor, null);
    assert.equal(requests[0].url, '/api/books/reading-session/end');
    await reply({banner_state: 'none'});
    assert.equal(reader.clock.sessionId, null);
    """,
    # No confirmed session: do not advance the local timer on failed /start.
    """
    reader.start(); await reply(null, false); now += 60000; reader.render();
    assert.equal(reader.clock.anchor, null);
    assert.equal(reader.clock.paused, false);
    assert.equal(reader.clock.state, 'paused');
    assert.equal(elements['reading-timer-elapsed'].textContent, '00:00');
    reader.start(); await reply(startData(291));
    assert.equal(reader.clock.state, 'active');
    assert.equal(reader.clock.seconds, 291);
    """,
    # A new study day resets both the server total and the checkpoint.
    """
    reader.seed(350, 600); reader.open(); await reply(startData(350));
    reader.close(); await reply({banner_state: 'none'});
    reader.open(); await reply({...startData(0), study_date: '2026-09-09'});
    assert.equal(reader.clock.seconds, 0);
    assert.equal(reader.clock.checkpoint, 300);
    """,
])
def test_reader_clock_matches_server_sessions(scenario):
    node = shutil.which('node')
    if not node:
        pytest.skip('Node.js is required for reader state-machine tests')
    script = HARNESS + '\n' + SOURCE + '\n' + (
        '(async () => {\n' + scenario + '\n})().catch(error => { '
        'console.error(error); process.exitCode = 1; });'
    )
    result = subprocess.run([node, '-e', script], capture_output=True, text=True, timeout=15)
    assert result.returncode == 0, result.stdout + result.stderr
