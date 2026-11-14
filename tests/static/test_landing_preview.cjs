const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const source = fs.readFileSync(path.join(__dirname, '../../app/static/js/landing/preview.js'), 'utf8');

function page(clipboard, options = {}) {
    const elements = {};
    const events = [];
    const requests = [];
    for (const id of ['landing-preview', 'preview-feedback', 'preview-reset',
        'landing-share-copy', 'landing-share-url', 'landing-share-status', 'preview-register']) {
        elements[id] = {
            hidden: id === 'preview-feedback' || id === 'preview-reset',
            dataset: {}, textContent: '', handlers: {},
            addEventListener(event, callback) { this.handlers[event] = callback; },
            focus() { this.focused = true; },
            select() { this.selected = true; },
        };
    }
    const answers = (options.answers || ['am', 'is', 'are']).map(value => ({
        name: 'preview-answer', value, checked: false,
        focus() { this.focused = true; },
    }));
    elements['landing-preview'].querySelectorAll = () => answers;
    elements['landing-preview'].dataset = {
        previewId: options.previewId || 'intro_am', correct: options.correct || 'am',
        explanation: options.explanation || 'С I используем am: I am Anna. — «Я Анна».',
        eventUrl: '/landing/events',
        recordedEvents: options.recordedEvents || '',
    };
    elements['landing-share-url'].value = 'https://llt-english.com/?utm_source=friend&utm_medium=share&utm_campaign=first_learners';
    vm.runInNewContext(source, {
        document: {getElementById: id => elements[id], querySelector: () => ({content: 'test-csrf'})},
        navigator: {clipboard},
        window: {gtag: (...args) => { if (options.failTracking) throw new Error('blocked'); events.push(args); }},
        fetch: (url, init) => {
            requests.push({url, ...init});
            return options.failTracking ? Promise.reject(new Error('offline')) : Promise.resolve({status: 204});
        },
    });
    return {elements, answers, events, requests};
}

test('an incorrect demo answer explains the correction and can be retried', () => {
    const {elements: e, answers} = page();
    answers[1].checked = true;
    e['landing-preview'].handlers.change({target: answers[1]});
    assert.equal(e['preview-feedback'].hidden, false);
    assert.equal(e['preview-feedback'].dataset.result, 'review');
    assert.match(e['preview-feedback'].textContent, /I am Anna/);
    e['preview-reset'].handlers.click();
    assert.ok(answers.every(answer => !answer.checked));
    assert.equal(e['preview-feedback'].hidden, true);
    assert.equal(e['preview-feedback'].textContent, '');
    assert.equal(answers[0].focused, true);
    e['landing-preview'].handlers.change({target: answers[0]});
    assert.equal(e['preview-feedback'].dataset.result, 'correct');
    assert.match(e['preview-feedback'].textContent, /Правильно/);
});

test('the selected variant controls grading and explanation without changing on retry', () => {
    const {elements: e, answers} = page(undefined, {
        previewId: 'plural_books', answers: ['book', 'books', 'bookes'], correct: 'books',
        explanation: 'Во множественном числе: two books — две книги.',
    });
    e['landing-preview'].handlers.change({target: answers[1]});
    assert.equal(e['preview-feedback'].dataset.result, 'correct');
    assert.match(e['preview-feedback'].textContent, /two books/);
    e['preview-reset'].handlers.click();
    e['landing-preview'].handlers.change({target: answers[0]});
    assert.equal(e['preview-feedback'].dataset.result, 'review');
    assert.match(e['preview-feedback'].textContent, /books/);
    assert.equal(e['landing-preview'].dataset.previewId, 'plural_books');
});

test('first interaction, first answer and CTA are counted once despite retries', () => {
    const {elements: e, answers, events, requests} = page();
    e['landing-preview'].handlers.focusin({target: answers[1]});
    e['landing-preview'].handlers.change({target: answers[1]});
    e['preview-reset'].handlers.click();
    e['landing-preview'].handlers.change({target: answers[0]});
    e['preview-register'].handlers.click();
    e['preview-register'].handlers.click();
    assert.equal(events.length, 3);
    assert.equal(requests.length, 3);
    const payloads = requests.map(req => JSON.parse(req.body));
    assert.deepEqual(payloads.map(p => p.event), ['preview_started', 'preview_answered', 'registration_clicked']);
    assert.equal(payloads[1].correct, false);  // Later correction does not rewrite first attempt.
    assert.ok(payloads.every(p => p.preview_id === 'intro_am'));
    assert.ok(requests.every(req => req.keepalive && req.credentials === 'same-origin'));
    assert.ok(requests.every(req => req.headers['X-CSRFToken'] === 'test-csrf'));
    assert.ok(payloads.every(p => !('answer' in p) && !('email' in p)));
});

test('a reload does not resend stages already recorded for this session', () => {
    const {elements: e, answers, requests, events} = page(undefined, {
        recordedEvents: 'preview_started,preview_answered',
    });
    e['landing-preview'].handlers.change({target: answers[0]});
    assert.equal(e['preview-feedback'].dataset.result, 'correct');
    assert.equal(requests.length, 0);
    assert.equal(events.length, 0);
    e['preview-register'].handlers.click();
    assert.equal(JSON.parse(requests[0].body).event, 'registration_clicked');
});

test('unavailable analytics cannot block practice, retry or the registration link', async () => {
    const {elements: e, answers} = page(undefined, {failTracking: true});
    e['landing-preview'].handlers.change({target: answers[0]});
    assert.equal(e['preview-feedback'].dataset.result, 'correct');
    e['preview-reset'].handlers.click();
    assert.equal(e['preview-feedback'].hidden, true);
    e['preview-register'].handlers.click();
    await Promise.resolve();
});

test('sharing copies the attributed link', async () => {
    let copied;
    const {elements: e} = page({writeText: async value => { copied = value; }});
    await e['landing-share-copy'].handlers.click();
    assert.equal(copied, e['landing-share-url'].value);
    assert.equal(new URL(copied).searchParams.get('utm_source'), 'friend');
    assert.match(e['landing-share-status'].textContent, /скопирована/);
});

for (const clipboard of [undefined, {writeText: async () => { throw new Error('denied'); }}]) {
    test(`clipboard ${clipboard ? 'denied' : 'unavailable'} leaves the link selected for manual copying`, async () => {
        const {elements: e} = page(clipboard);
        await e['landing-share-copy'].handlers.click();
        assert.equal(e['landing-share-url'].selected, true);
        assert.equal(e['landing-share-url'].focused, true);
        assert.match(e['landing-share-status'].textContent, /выделенную ссылку/);
    });
}
