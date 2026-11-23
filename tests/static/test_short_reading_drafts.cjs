const {test} = require('node:test');
const assert = require('node:assert/strict');

// Older supported Node releases expose WebCrypto only through node:crypto.
if (!globalThis.crypto?.subtle) {
    Object.defineProperty(globalThis, 'crypto', {
        value: require('node:crypto').webcrypto,
        configurable: true,
    });
}
const {Practice, DraftStore, contentDigest} = require('../../app/static/js/books/short_reading.js');

const questions = () => [0, 1, 2].map(index => ({
    id: 'q' + index,
    explanation: 'Current explanation ' + index,
    options: [{id: 'a'}, {id: 'b'}, {id: 'c'}],
    correct_option: 'b',
}));
const identity = {account: '1', book: '2', chapter: '3'};
const revision = 'a'.repeat(64);
const memory = () => {
    const values = new Map();
    return {
        getItem: key => values.get(key) ?? null,
        setItem: (key, value) => values.set(key, value),
    };
};

test('unchecked selection survives without becoming feedback', () => {
    const practice = new Practice(questions());
    practice.choose('a');
    const restored = new Practice(questions());
    assert(restored.restore(practice.snapshot()));
    assert.equal(restored.selection, 'a');
    assert.equal(restored.feedback, null);
});

test('wrong feedback uses current content, never a stored verdict', () => {
    const practice = new Practice(questions());
    practice.choose('b');
    practice.check();
    practice.continue();
    practice.choose('a');
    practice.check();
    const saved = {...practice.snapshot(), feedback: {correct: true, explanation: 'STALE'}};
    const restored = new Practice(questions());
    assert(restored.restore(saved));
    assert.equal(restored.index, 1);
    assert.deepEqual(restored.feedback, {correct: false, explanation: 'Current explanation 1'});
    restored.continue();
    assert.equal(restored.index, 1);
    assert.equal(restored.selection, null);
});

test('checked final correct answer still requires explicit continue', () => {
    const practice = new Practice(questions());
    for (let index = 0; index < 2; index++) {
        practice.choose('b');
        practice.check();
        practice.continue();
    }
    practice.choose('b');
    practice.check();
    const restored = new Practice(questions());
    assert(restored.restore(practice.snapshot()));
    assert.equal(restored.completed, false);
    assert.equal(restored.feedback.correct, true);
    restored.continue();
    assert.equal(restored.completed, true);
    const complete = new Practice(questions());
    assert(complete.restore(restored.snapshot()));
    assert(complete.completed);
});

test('forged index, completion, invalid options and history are rejected atomically', () => {
    const invalidChanges = [
        {index: 2}, {completed: true}, {selection: 'invalid'}, {checked: true},
        {answers: ['a']}, {answers: ['b'], index: 0}, {index: -1}, {index: 1.5},
        {answers: ['b', 'b', 'b'], completed: false},
    ];
    for (const change of invalidChanges) {
        const practice = new Practice(questions());
        assert.equal(practice.restore({...practice.snapshot(), ...change}), false, JSON.stringify(change));
        assert.deepEqual(practice.snapshot(), new Practice(questions()).snapshot());
    }
});

test('owner, book, chapter and revision remain bound when a record is copied to another key', () => {
    const storage = memory();
    const practice = new Practice(questions());
    practice.choose('a');
    const source = new DraftStore(storage, identity, revision);
    source.save(practice);
    const otherScopes = [
        [{...identity, account: '9'}, revision],
        [{...identity, book: '9'}, revision],
        [{...identity, chapter: '9'}, revision],
        [identity, 'b'.repeat(64)],
    ];
    for (const [scope, digest] of otherScopes) {
        const target = new DraftStore(storage, scope, digest);
        storage.setItem(target.key, storage.getItem(source.key));
        assert.equal(target.load(new Practice(questions())), false);
    }
});

test('snapshot contains own input and checked state, no feedback or correctness ledger', () => {
    const storage = memory();
    const store = new DraftStore(storage, identity, revision);
    const practice = new Practice(questions());
    practice.choose('a');
    practice.check();
    assert(store.save(practice));
    const raw = storage.getItem(store.key);
    assert(!raw.includes('explanation'));
    assert(!raw.includes('correct'));
    const restored = new Practice(questions());
    assert(store.load(restored));
    assert.equal(restored.feedback.correct, false);
});

test('denied and quota storage preserve live answers and report unavailable', () => {
    for (const name of ['SecurityError', 'QuotaExceededError']) {
        const storage = {
            getItem() { throw Object.assign(new Error(), {name}); },
            setItem() { throw Object.assign(new Error(), {name}); },
        };
        const practice = new Practice(questions());
        const store = new DraftStore(storage, identity, revision);
        store.load(practice);
        practice.choose('a');
        practice.check();
        assert.equal(store.save(practice), false);
        assert(store.unavailable);
        assert.equal(practice.selection, 'a');
        assert.equal(practice.feedback.correct, false);
    }
});

test('a write after a read error does not promise recoverability until a fresh successful read', () => {
    const storage = memory();
    const read = storage.getItem;
    storage.getItem = () => { throw new Error('read denied'); };
    const practice = new Practice(questions());
    const store = new DraftStore(storage, identity, revision);
    assert.equal(store.load(practice), false);
    practice.choose('a');
    assert.equal(store.save(practice), false);
    assert(store.unavailable);
    assert(read(store.key), 'The write happened, but reading remains unverified');
    storage.getItem = read;
    const freshStore = new DraftStore(storage, identity, revision);
    const restored = new Practice(questions());
    assert(freshStore.load(restored));
    assert.equal(freshStore.unavailable, false);
    assert.equal(restored.selection, 'a');
});

test('malformed JSON is ignored without mislabelling healthy storage as unavailable', () => {
    const storage = memory();
    const store = new DraftStore(storage, identity, revision);
    storage.setItem(store.key, '{bad');
    assert.equal(store.load(new Practice(questions())), false);
    assert.equal(store.unavailable, false);
});

test('SHA256 binds both reading data and current text', async () => {
    const digest = await contentDigest({text: 'A', questions: questions()});
    assert.match(digest, /^[a-f0-9]{64}$/);
    assert.notEqual(digest, await contentDigest({text: 'B', questions: questions()}));
    const changed = questions();
    changed[0].correct_option = 'a';
    assert.notEqual(digest, await contentDigest({text: 'A', questions: changed}));
});
