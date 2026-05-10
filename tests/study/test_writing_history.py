"""Tests for the writing history route GET /study/writing.

Task 21: Writing history page.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest

from app.curriculum.models import CEFRLevel, Lessons, Module, UserWritingAttempt
from app.utils.db import db


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _unique_code() -> str:
    return uuid.uuid4().hex[:2].upper()


def _make_lesson(db_session, lesson_type: str = 'writing_prompt') -> Lessons:
    level = CEFRLevel(code=_unique_code(), name='Level', description='d', order=1)
    db_session.add(level)
    db_session.commit()
    module = Module(
        level_id=level.id,
        number=1,
        title='Writing Module',
        description='d',
        raw_content={'module': {'id': 1}},
    )
    db_session.add(module)
    db_session.commit()

    if lesson_type == 'writing_prompt':
        content = {'prompt': 'Describe your day.', 'min_words': 30}
    elif lesson_type == 'translation':
        content = {'russian': 'Я иду домой', 'english': 'I am going home'}
    elif lesson_type == 'sentence_correction':
        content = {
            'incorrect_sentence': 'He go to school yesterday.',
            'correct_sentence': 'He went to school yesterday.',
            'error_type': 'tense',
            'explanation': 'Past tense required.',
        }
    else:
        content = {}

    lesson = Lessons(
        module_id=module.id,
        number=1,
        title=f'{lesson_type.title()} Lesson',
        type=lesson_type,
        content=content,
    )
    db_session.add(lesson)
    db_session.commit()
    return lesson


def _make_attempt(db_session, user_id: int, lesson_id: int, text: str = 'some text here', checklist: bool = True) -> UserWritingAttempt:
    attempt = UserWritingAttempt(
        user_id=user_id,
        lesson_id=lesson_id,
        response_text=text,
        word_count=len(text.split()),
        checklist_completed=checklist,
        created_at=datetime.now(timezone.utc),
    )
    db_session.add(attempt)
    db_session.commit()
    return attempt


def _login(client, user) -> None:
    with client.session_transaction() as sess:
        sess['_user_id'] = str(user.id)
        sess['_fresh'] = True


# ---------------------------------------------------------------------------
# Route tests
# ---------------------------------------------------------------------------

class TestWritingHistoryRoute:
    def test_get_returns_200(self, app, db_session, test_user, client):
        _login(client, test_user)
        resp = client.get('/study/writing')
        assert resp.status_code == 200

    def test_empty_state_shows_no_records_message(self, app, db_session, test_user, client):
        _login(client, test_user)
        resp = client.get('/study/writing')
        html = resp.get_data(as_text=True)
        assert 'Пока нет записей' in html

    def test_attempt_shown_in_list(self, app, db_session, test_user, client):
        lesson = _make_lesson(db_session, 'writing_prompt')
        _make_attempt(db_session, test_user.id, lesson.id, 'My writing response text here.')
        _login(client, test_user)
        resp = client.get('/study/writing')
        html = resp.get_data(as_text=True)
        assert 'My writing response text here.' in html

    def test_response_preview_truncated_at_100_chars(self, app, db_session, test_user, client):
        lesson = _make_lesson(db_session, 'writing_prompt')
        long_text = 'a' * 150
        _make_attempt(db_session, test_user.id, lesson.id, long_text)
        _login(client, test_user)
        resp = client.get('/study/writing')
        html = resp.get_data(as_text=True)
        assert 'a' * 100 in html
        assert 'a' * 150 not in html

    def test_prompt_from_writing_prompt_shown(self, app, db_session, test_user, client):
        lesson = _make_lesson(db_session, 'writing_prompt')
        _make_attempt(db_session, test_user.id, lesson.id)
        _login(client, test_user)
        resp = client.get('/study/writing')
        html = resp.get_data(as_text=True)
        assert 'Describe your day.' in html

    def test_russian_sentence_shown_for_translation(self, app, db_session, test_user, client):
        lesson = _make_lesson(db_session, 'translation')
        _make_attempt(db_session, test_user.id, lesson.id)
        _login(client, test_user)
        resp = client.get('/study/writing')
        html = resp.get_data(as_text=True)
        assert 'Я иду домой' in html

    def test_incorrect_sentence_shown_for_correction(self, app, db_session, test_user, client):
        lesson = _make_lesson(db_session, 'sentence_correction')
        _make_attempt(db_session, test_user.id, lesson.id)
        _login(client, test_user)
        resp = client.get('/study/writing')
        html = resp.get_data(as_text=True)
        assert 'He go to school yesterday.' in html

    def test_unauthenticated_redirects(self, app, db_session, client):
        resp = client.get('/study/writing')
        assert resp.status_code in (302, 401, 403)

    def test_type_filter_writing_prompt(self, app, db_session, test_user, client):
        wp_lesson = _make_lesson(db_session, 'writing_prompt')
        tr_lesson = _make_lesson(db_session, 'translation')
        _make_attempt(db_session, test_user.id, wp_lesson.id, 'Writing prompt response')
        _make_attempt(db_session, test_user.id, tr_lesson.id, 'Translation response')
        _login(client, test_user)
        resp = client.get('/study/writing?type=writing_prompt')
        html = resp.get_data(as_text=True)
        assert 'Writing prompt response' in html
        assert 'Translation response' not in html

    def test_type_filter_translation(self, app, db_session, test_user, client):
        wp_lesson = _make_lesson(db_session, 'writing_prompt')
        tr_lesson = _make_lesson(db_session, 'translation')
        _make_attempt(db_session, test_user.id, wp_lesson.id, 'Writing prompt response')
        _make_attempt(db_session, test_user.id, tr_lesson.id, 'Translation response')
        _login(client, test_user)
        resp = client.get('/study/writing?type=translation')
        html = resp.get_data(as_text=True)
        assert 'Translation response' in html
        assert 'Writing prompt response' not in html

    def test_invalid_type_filter_shows_all(self, app, db_session, test_user, client):
        lesson = _make_lesson(db_session, 'writing_prompt')
        _make_attempt(db_session, test_user.id, lesson.id, 'Valid response text')
        _login(client, test_user)
        resp = client.get('/study/writing?type=invalid_type')
        html = resp.get_data(as_text=True)
        assert 'Valid response text' in html

    def test_only_current_user_attempts_shown(self, app, db_session, test_user, client):
        from app.auth.models import User
        other_user = User(
            email=f'other_{uuid.uuid4().hex[:8]}@test.com',
            username=f'other_{uuid.uuid4().hex[:8]}',
            onboarding_completed=True,
        )
        other_user.set_password('password123')
        db_session.add(other_user)
        db_session.commit()

        lesson = _make_lesson(db_session, 'writing_prompt')
        _make_attempt(db_session, other_user.id, lesson.id, 'Other user secret response')
        _make_attempt(db_session, test_user.id, lesson.id, 'My own response')
        _login(client, test_user)
        resp = client.get('/study/writing')
        html = resp.get_data(as_text=True)
        assert 'My own response' in html
        assert 'Other user secret response' not in html

    def test_pagination_page_2(self, app, db_session, test_user, client):
        lesson = _make_lesson(db_session, 'writing_prompt')
        for i in range(25):
            _make_attempt(db_session, test_user.id, lesson.id, f'Response number {i:03d} for pagination test')
        _login(client, test_user)
        resp1 = client.get('/study/writing?page=1')
        resp2 = client.get('/study/writing?page=2')
        html1 = resp1.get_data(as_text=True)
        html2 = resp2.get_data(as_text=True)
        assert resp1.status_code == 200
        assert resp2.status_code == 200
        # Pages should have different content
        assert html1 != html2

    def test_pagination_controls_shown_when_multiple_pages(self, app, db_session, test_user, client):
        lesson = _make_lesson(db_session, 'writing_prompt')
        for i in range(25):
            _make_attempt(db_session, test_user.id, lesson.id, f'Response page test {i:03d}')
        _login(client, test_user)
        resp = client.get('/study/writing')
        html = resp.get_data(as_text=True)
        assert 'page=2' in html

    def test_no_pagination_when_few_items(self, app, db_session, test_user, client):
        lesson = _make_lesson(db_session, 'writing_prompt')
        _make_attempt(db_session, test_user.id, lesson.id, 'Just one attempt here.')
        _login(client, test_user)
        resp = client.get('/study/writing')
        html = resp.get_data(as_text=True)
        # No page navigation links when only 1 page (check for page=2 link)
        assert 'page=2' not in html

    def test_word_count_displayed(self, app, db_session, test_user, client):
        lesson = _make_lesson(db_session, 'writing_prompt')
        _make_attempt(db_session, test_user.id, lesson.id, 'one two three four five')
        _login(client, test_user)
        resp = client.get('/study/writing')
        html = resp.get_data(as_text=True)
        assert '5 сл.' in html

    def test_filter_links_present_in_template(self, app, db_session, test_user, client):
        _login(client, test_user)
        resp = client.get('/study/writing')
        html = resp.get_data(as_text=True)
        assert 'type=writing_prompt' in html
        assert 'type=translation' in html
        assert 'type=sentence_correction' in html
