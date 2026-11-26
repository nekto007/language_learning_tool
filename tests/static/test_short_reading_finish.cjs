const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const source = fs.readFileSync(path.join(__dirname, '../../app/templates/books/reader_simple.html'), 'utf8');
const start = source.indexOf("const shortFinish = document.getElementById('short-reading-finish');");
const end = source.indexOf('// Offsets belong to the chapter text', start);

for (const [label, receipt, saved] of [
    ['fresh transition', {success: true, book_completed: true}, true],
    ['idempotent receipt', {success: true}, true],
    ['explicit failure', {success: false}, false],
    ['lost response', null, false],
]) {
    test(`explicit short finish handles ${label} without inventing a global completion`, async () => {
        let click;
        const calls = [];
        const events = [];
        const button = {disabled: false, textContent: '', addEventListener(type, callback) { click = callback; }};
        const status = {textContent: ''};
        vm.runInNewContext(source.slice(start, end), {
            shortPracticeComplete: true,
            CustomEvent: class { constructor(type) { this.type = type; } },
            document: {
                getElementById: id => id === 'short-reading-finish' ? button : status,
                dispatchEvent: event => events.push(event.type),
            },
            saveProgress: async (...args) => { calls.push(args); return receipt; },
        });
        await click();
        assert.deepEqual(calls, [[1, true]]);
        assert.equal(button.disabled, saved);
        assert.equal(events.includes('shortReadingFinishSaved'), saved);
        assert(!events.includes('bookCompleted'));
        assert.equal(status.textContent.includes('Результат сохранён'), saved);
    });
}
