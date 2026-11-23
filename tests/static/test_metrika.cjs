// Run with node --test. No real analytics requests or browser accounts.
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const code = fs.readFileSync('app/static/js/metrika.js', 'utf8');

function boot(fetchImpl) {
    const scripts = [];
    const window = {
        location: {origin: 'https://llt-english.com'},
        fetch: fetchImpl || (async () => response()),
    };
    const document = {
        getElementById: () => ({nonce: 'test-nonce', textContent: JSON.stringify({
            id: 114597985, options: {webvisor: false, url: 'https://llt-english.com/'},
        })}),
        createElement: () => ({}),
        addEventListener: () => {},
        head: {appendChild: script => scripts.push(script)},
    };
    const context = vm.createContext({window, document, URL, Set, Date});
    vm.runInContext(code, context);
    return {window, scripts, context, calls: () => Array.from(window.ym.a || [], args => Array.from(args))};
}

function response(goals = '', extra = {}) {
    return {
        ok: true, url: 'https://llt-english.com/curriculum/submit',
        headers: {get: key => key === 'X-LLT-Learning-Goals' ? goals : null},
        ...extra,
    };
}

test('counter initializes once and loads asynchronously with CSP nonce', () => {
    const app = boot();
    vm.runInContext(code, app.context);
    assert.equal(app.calls().filter(c => c[1] === 'init').length, 1);
    assert.equal(app.scripts.length, 1);
    assert.equal(app.scripts[0].src, 'https://mc.yandex.ru/metrika/tag.js?id=114597985');
    assert.equal(app.scripts[0].async, true);
    assert.equal(app.scripts[0].nonce, 'test-nonce');
});

test('goals work before tag.js arrives, drop params, and ignore unlisted events', () => {
    const app = boot();
    app.window.lltMetrikaGoal('signup_completed', {email: 'secret@example.com'});
    app.window.lltMetrikaGoal('secret@example.com');
    const goals = app.calls().filter(c => c[1] === 'reachGoal');
    assert.deepEqual(goals, [[114597985, 'reachGoal', 'signup_completed']]);
});

test('grading preserves request arguments and original Response without reading its body', async () => {
    let received;
    const reply = response('learning_answered,lesson_completed');
    reply.json = () => { throw new Error('analytics must not read response body'); };
    const app = boot(async (...args) => { received = args; return reply; });
    const options = {method: 'POST', signal: {aborted: false}, body: 'private answers'};
    assert.equal(await app.window.fetch('/curriculum/submit', options), reply);
    assert.equal(received[1], options);
    assert.deepEqual(app.calls().filter(c => c[1] === 'reachGoal').map(c => c[2]),
        ['learning_answered', 'lesson_completed']);
    assert.ok(!JSON.stringify(app.calls()).includes('private answers'));
    await app.window.fetch('/curriculum/submit', options);
    assert.equal(app.calls().filter(c => c[2] === 'learning_answered').length, 1);
});

test('external and failed responses cannot trigger learning goals', async () => {
    for (const reply of [response('lesson_completed', {ok: false}),
        response('lesson_completed', {url: 'https://other.example/submit'})]) {
        const app = boot(async () => reply);
        await app.window.fetch('/anything');
        assert.equal(app.calls().filter(c => c[1] === 'reachGoal').length, 0);
    }
});

test('blocked analytics and rejected fetch do not change application behavior', async () => {
    const reply = response('lesson_completed');
    const app = boot(async () => reply);
    app.window.ym = () => { throw new Error('blocked analytics'); };
    assert.equal(await app.window.fetch('/curriculum/submit'), reply);
    const aborted = new Error('AbortError');
    const failing = boot(async () => { throw aborted; });
    await assert.rejects(failing.window.fetch('/curriculum/submit'), error => error === aborted);
});

test('no configuration means no counter and no fetch wrapping', () => {
    const original = async () => response();
    const window = {fetch: original};
    vm.runInNewContext(code, {window, document: {getElementById: () => null}});
    assert.equal(window.fetch, original);
    assert.equal(window.ym, undefined);
});
