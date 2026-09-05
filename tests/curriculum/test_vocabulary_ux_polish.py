"""Lesson audit, item 9: vocabulary deck UX (no knowledge gate by owner decision).

1. Completion is the learner's explicit click on the last card; the deck no
   longer completes itself 500 ms after the 20th card appears and hides.
2. Card position is snapshotted mid-lesson and the deck resumes from it; a
   snapshot never downgrades a completed lesson.
3. Cyrillic transliteration by level: always on A0-A2, only without IPA on B1,
   never on B2+. Word-clip auto-play defaults on for A1-A2 only.
"""

from __future__ import annotations

import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest
from flask import url_for

from app.curriculum.models import CEFRLevel, LessonProgress, Lessons, Module
from app.curriculum.routes.vocabulary_lessons import (
    _autoplay_default,
    _transliteration_mode,
    _vocabulary_display_context,
    _vocabulary_resume_state,
)
from app.words.models import CollectionWords

TEMPLATE = Path('app/templates/curriculum/lessons/vocabulary.html')


def _login(client, user) -> None:
    with client.session_transaction() as sess:
        sess['_user_id'] = str(user.id)
        sess['_fresh'] = True


def _level(db_session, code: str) -> CEFRLevel:
    level = db_session.query(CEFRLevel).filter_by(code=code).first()
    if level is None:
        level = CEFRLevel(code=code, name=f'Level {code}', description='d', order=1)
        db_session.add(level)
        db_session.commit()
    return level


def _word_item(english: str, translit: str) -> dict:
    return {
        'english': english, 'russian': 'перевод', 'pronunciation': translit,
        'example': f'I say {english}.', 'example_translation': 'Я говорю.',
        'audio': f'[sound:{english}.mp3]',
    }


def _lesson(db_session, level_code: str, items: list[dict]) -> Lessons:
    level = _level(db_session, level_code)
    module = Module(level_id=level.id, number=96, title='Item 9 module', description='d',
                    raw_content={'module': {'id': 1}})
    db_session.add(module)
    db_session.commit()
    lesson = Lessons(module_id=module.id, number=1, title='Vocabulary item 9', type='vocabulary',
                     content={'vocabulary': items})
    db_session.add(lesson)
    db_session.commit()
    return lesson


def _db_word(db_session, english: str, ipa: str | None) -> CollectionWords:
    word = CollectionWords(english_word=english, russian_word='перевод', ipa_transcription=ipa)
    db_session.add(word)
    db_session.commit()
    return word


def _unique(prefix: str) -> str:
    return f'{prefix}{uuid.uuid4().hex[:8]}'


def _get(app, client, lesson) -> str:
    with app.test_request_context():
        url = url_for('curriculum_lessons.vocabulary_lesson', lesson_id=lesson.id)
    resp = client.get(url)
    assert resp.status_code == 200
    return resp.get_data(as_text=True)


def _progress_url(app, lesson) -> str:
    with app.test_request_context():
        return url_for('curriculum_lessons.update_lesson_progress', lesson_id=lesson.id)


# ---------------------------------------------------------------------------
# Level policy helpers
# ---------------------------------------------------------------------------

class TestLevelPolicy:
    @pytest.mark.parametrize('code, mode', [('A0', 'always'), ('A1', 'always'), ('a2', 'always'), ('', 'always'),
                                            ('B1', 'fallback'), ('B2', 'never'), ('C1', 'never'), ('C2', 'never')])
    def test_transliteration_mode(self, code, mode):
        assert _transliteration_mode(code) == mode

    @pytest.mark.parametrize('code, on', [('A1', True), ('a2', True), ('B1', False), ('C1', False), ('', False)])
    def test_autoplay_default(self, code, on):
        assert _autoplay_default(code) is on

    def test_display_context_without_module(self):
        lesson = type('Lesson', (), {'module': None})()
        ctx = _vocabulary_display_context(lesson, None, [1, 2, 3])
        assert ctx == {'transliteration_mode': 'always', 'autoplay_default': False, 'resume_state': None}


class TestResumeState:
    @staticmethod
    def _progress(status, data):
        # The helper only reads .status / .data; a stand-in keeps this unit test
        # independent of ORM mapper configuration order.
        return SimpleNamespace(status=status, data=data)

    def test_none_and_completed_do_not_resume(self):
        assert _vocabulary_resume_state(None, 20) is None
        assert _vocabulary_resume_state(self._progress('completed', {'presented': [0, 1], 'card_index': 1}), 20) is None

    def test_junk_is_dropped(self):
        assert _vocabulary_resume_state(self._progress('in_progress', None), 20) is None
        assert _vocabulary_resume_state(self._progress('in_progress', {'presented': 'abc'}), 20) is None
        assert _vocabulary_resume_state(self._progress('in_progress', {'presented': [True, -1, 20, 'x']}), 20) is None

    def test_valid_indices_kept_and_index_falls_back(self):
        state = _vocabulary_resume_state(
            self._progress('in_progress', {'presented': [3, 0, 1, 1, 25, False], 'card_index': 'nope'}), 20)
        assert state == {'index': 3, 'presented': [0, 1, 3]}
        state = _vocabulary_resume_state(self._progress('in_progress', {'presented': [0, 1, 2], 'card_index': 1}), 20)
        assert state == {'index': 1, 'presented': [0, 1, 2]}


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------

class TestRender:
    def test_a1_shows_transliteration_and_autoplay_on(self, app, db_session, test_user, client):
        lesson = _lesson(db_session, 'A1', [_word_item(_unique('appl'), 'транслит-а1')])
        _login(client, test_user)
        html = _get(app, client, lesson)
        assert 'транслит-а1' in html
        assert 'id="btn-autoplay"' in html and 'aria-pressed="true"' in html
        assert 'autoplayDefault: true' in html

    def test_b1_transliteration_only_without_ipa(self, app, db_session, test_user, client):
        with_ipa = _unique('with')
        without = _unique('without')
        _db_word(db_session, with_ipa, 'ˈwɪð')
        _db_word(db_session, without, None)
        lesson = _lesson(db_session, 'B1', [_word_item(with_ipa, 'транслит-есть-ipa'), _word_item(without, 'транслит-нет-ipa')])
        _login(client, test_user)
        html = _get(app, client, lesson)
        assert '/ˈwɪð/' in html
        assert 'транслит-есть-ipa' not in html
        assert 'транслит-нет-ipa' in html
        assert 'aria-pressed="false"' in html and 'autoplayDefault: false' in html

    def test_c1_never_shows_transliteration(self, app, db_session, test_user, client):
        word = _unique('rubic')
        _db_word(db_session, word, None)
        lesson = _lesson(db_session, 'C1', [_word_item(word, 'крос зэ рубикэн')])
        _login(client, test_user)
        html = _get(app, client, lesson)
        assert 'крос зэ рубикэн' not in html

    def test_explicit_finish_and_banner_outside_deck(self, app, db_session, test_user, client):
        lesson = _lesson(db_session, 'A1', [_word_item(_unique('w'), 'т') for _ in range(3)])
        _login(client, test_user)
        html = _get(app, client, lesson)
        assert 'data-label-finish="Завершить"' in html
        assert 'id="btn-next-label"' in html
        # the banner is a sibling of the deck, hidden until the click
        deck_end = html.index('id="cards-navigation"')
        assert html.index('id="no-cards-message"') > deck_end
        assert 'id="no-cards-message" hidden' in html
        assert 'resume: null' in html

    def test_template_has_no_auto_completion(self):
        src = TEMPLATE.read_text(encoding='utf-8')
        assert 'setTimeout(completeLesson' not in src
        assert 'allViewed' not in src
        assert 'flipped_count: cardsState.flippedCards.size' in src
        assert "status: 'in_progress'" in src and 'keepalive: !!keepalive' in src
        assert "err.name === 'NotAllowedError'" in src


# ---------------------------------------------------------------------------
# Snapshot round trip through the progress endpoint
# ---------------------------------------------------------------------------

class TestSnapshotRoundTrip:
    def test_snapshot_saves_and_resumes(self, app, db_session, test_user, client):
        lesson = _lesson(db_session, 'A2', [_word_item(_unique('w'), 'т') for _ in range(5)])
        _login(client, test_user)
        resp = client.post(_progress_url(app, lesson), json={
            'status': 'in_progress', 'data': {'card_index': 2, 'presented': [0, 1, 2], 'total_cards': 5}})
        assert resp.status_code == 200, resp.get_data(as_text=True)
        progress = db_session.query(LessonProgress).filter_by(user_id=test_user.id, lesson_id=lesson.id).one()
        assert progress.status == 'in_progress'
        assert progress.data['presented'] == [0, 1, 2]
        html = _get(app, client, lesson)
        assert 'resume: {"index": 2, "presented": [0, 1, 2]}' in html

    def test_snapshot_cannot_downgrade_completed(self, app, db_session, test_user, client):
        lesson = _lesson(db_session, 'A2', [_word_item(_unique('w'), 'т') for _ in range(2)])
        _login(client, test_user)
        url = _progress_url(app, lesson)
        done = client.post(url, json={'status': 'completed', 'score': 100,
                                      'data': {'cards_viewed': 2, 'total_cards': 2, 'flipped_count': 1}})
        assert done.status_code == 200
        late = client.post(url, json={'status': 'in_progress', 'data': {'card_index': 0, 'presented': [0]}})
        assert late.status_code == 200
        progress = db_session.query(LessonProgress).filter_by(user_id=test_user.id, lesson_id=lesson.id).one()
        assert progress.status == 'completed'
        assert progress.data == {'cards_viewed': 2, 'total_cards': 2, 'flipped_count': 1}
        assert progress.completed_at is not None
        # a completed deck opens without resume state
        assert 'resume: null' in _get(app, client, lesson)

    def test_other_types_keep_their_snapshot_semantics(self, app, db_session, test_user, client):
        """The no-downgrade backstop is scoped to decks; other lesson types are untouched."""
        level = _level(db_session, 'A2')
        module = Module(level_id=level.id, number=95, title='m', description='d', raw_content={'module': {'id': 1}})
        db_session.add(module)
        db_session.commit()
        lesson = Lessons(module_id=module.id, number=2, title='theory', type='grammar',
                         content={'title': 't', 'theory': 'x'})
        db_session.add(lesson)
        db_session.commit()
        _login(client, test_user)
        url = _progress_url(app, lesson)
        assert client.post(url, json={'status': 'completed'}).status_code == 200
        assert client.post(url, json={'status': 'in_progress', 'data': {'k': 1}}).status_code == 200
        progress = db_session.query(LessonProgress).filter_by(user_id=test_user.id, lesson_id=lesson.id).one()
        assert progress.status == 'in_progress'
