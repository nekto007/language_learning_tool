const { test } = require('node:test');
const assert = require('node:assert/strict');
const { readFileSync } = require('node:fs');
const vm = require('node:vm');

function setupAudio(card) {
    const document = { hidden: false };
    const proto = vm.runInNewContext(
        readFileSync('app/static/js/flashcard-session.js', 'utf8') + '\nFlashcardSession.prototype', { document }
    );
    const session = Object.create(proto);
    const played = [];
    session.els = {
        frontAudioBtn: {}, backAudioBtn: {},
        wordAudio: {
            play() { played.push(this.src); return Promise.resolve(); }, pause() {},
            getAttribute() { return this.src; }, removeAttribute() { delete this.src; },
        },
    };
    session.config = { showAudio: true };
    session.currentCardIndex = 0;
    session.cards = [card];
    return { session, played, document };
}

test('English recording plays on the front once, reverse waits for reveal, missing audio stays silent', () => {
    const first = { direction: 'eng-rus', audio_url: '/word-a.mp3' };
    const { session, played } = setupAudio(first);
    session._setCardAudio(first);
    session.flipCard();
    assert.deepEqual(played, ['/word-a.mp3']);
    const reverse = { direction: 'rus-eng', audio_url: '/word-b.mp3' };
    session.cards = [reverse];
    session._setCardAudio(reverse);
    assert.ok(session.els.frontAudioBtn.hidden);
    assert.equal(played.length, 1);
    session.flipCard();
    session._playWordAudio(true);
    assert.deepEqual(played.slice(1), ['/word-b.mp3', '/word-b.mp3']);
    for (const url of [null, '', '  ']) {
        session._setCardAudio({ direction: 'eng-rus', audio_url: url });
        session.flipCard();
        assert.ok(session.els.backAudioBtn.hidden);
    }
    assert.equal(played.length, 3);
});

test('blocked first autoplay can recover inside the reveal gesture; disabled or hidden sessions stay quiet', async () => {
    const card = { direction: 'eng-rus', audio_url: '/word.mp3' };
    const { session, document, played } = setupAudio(card);
    const player = session.els.wordAudio;
    const play = player.play;
    player.play = () => Promise.reject({ name: 'NotAllowedError' });
    session._setCardAudio(card);
    await Promise.resolve();
    player.play = play;
    session.flipCard();
    assert.deepEqual(played, ['/word.mp3']);
    document.hidden = true;
    session._setCardAudio(card);
    document.hidden = false;
    session.config.showAudio = false;
    session._setCardAudio(card);
    session.flipCard();
    assert.ok(session.els.frontAudioBtn.hidden);
    assert.deepEqual(played, ['/word.mp3']);
});

test('finishing the last SRS step leaves results visible with a clickable plan exit', async () => {
    const node = () => ({ setAttribute() {}, style: {} });
    const dashboard = node(), next = node();
    const window = { location: { href: '/study/cards', search: '?from=linear_plan&slot=srs', pathname: '/study/cards' } };
    vm.runInNewContext(readFileSync('app/static/js/linear-plan-context.js', 'utf8'), {
        window, document: { addEventListener() {} }, URLSearchParams,
        fetch: async () => ({ ok: true, json: async () => ({ day_secured: true, next: null }) }),
    });
    const container = { ...node(), querySelector: s => s.includes('dashboard') ? dashboard : s.includes('next-slot') ? next : null };
    assert.equal(await window.linearPlanContext.applySrsPlanAwareCompletion(container), 'plan');
    assert.equal(window.location.href, '/study/cards');
    assert.equal(dashboard.href, '/dashboard?day_secured=1');
    assert.equal(next.style.display, 'none');
});
