const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const source = fs.readFileSync(path.join(__dirname, '../../app/static/js/landing/preview.js'), 'utf8');

function page(clipboard) {
    const elements = {};
    for (const id of ['landing-preview', 'preview-feedback', 'preview-reset',
        'landing-share-copy', 'landing-share-url', 'landing-share-status']) {
        elements[id] = {
            hidden: id === 'preview-feedback' || id === 'preview-reset',
            dataset: {}, textContent: '', handlers: {},
            addEventListener(event, callback) { this.handlers[event] = callback; },
            focus() { this.focused = true; },
            select() { this.selected = true; },
        };
    }
    const answers = ['am', 'is', 'are'].map(value => ({
        name: 'preview-answer', value, checked: false,
        focus() { this.focused = true; },
    }));
    elements['landing-preview'].querySelectorAll = () => answers;
    elements['landing-share-url'].value = 'https://llt-english.com/?utm_source=friend&utm_medium=share&utm_campaign=first_learners';
    vm.runInNewContext(source, {
        document: {getElementById: id => elements[id]}, navigator: {clipboard},
    });
    return {elements, answers};
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
