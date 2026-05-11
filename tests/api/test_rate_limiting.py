"""Tests for API rate limiting on pronunciation and writing endpoints (Task 99)."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from unittest.mock import patch

import pytest

from app.curriculum.models import CEFRLevel, Lessons, LessonProgress, Module

SUBMIT_URL = '/curriculum/api/lesson/{}/submit'


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _unique_code() -> str:
    return uuid.uuid4().hex[:2].upper()


def _make_lesson(db_session, lesson_type: str, content: dict) -> Lessons:
    level = CEFRLevel(code=_unique_code(), name='Level', description='d', order=1)
    db_session.add(level)
    db_session.commit()
    module = Module(
        level_id=level.id,
        number=1,
        title='Test Module',
        description='d',
        raw_content={'module': {'id': 1}},
    )
    db_session.add(module)
    db_session.commit()
    lesson = Lessons(
        module_id=module.id,
        number=1,
        title='Test Lesson',
        type=lesson_type,
        content=content,
    )
    db_session.add(lesson)
    db_session.commit()
    return lesson


def _ensure_progress(db_session, user_id: int, lesson_id: int) -> LessonProgress:
    progress = LessonProgress.query.filter_by(user_id=user_id, lesson_id=lesson_id).first()
    if not progress:
        progress = LessonProgress(
            user_id=user_id,
            lesson_id=lesson_id,
            status='in_progress',
        )
        db_session.add(progress)
        db_session.commit()
    return progress


def _login(client, user) -> None:
    with client.session_transaction() as sess:
        sess['_user_id'] = str(user.id)
        sess['_fresh'] = True


# ---------------------------------------------------------------------------
# Pronunciation rate limiting
# ---------------------------------------------------------------------------

class TestPronunciationRateLimit:
    """Rate limit: max 200 pronunciation attempts per user per day."""

    def test_within_limit_allowed(self, client, db_session, test_user):
        lesson = _make_lesson(
            db_session,
            'pronunciation',
            {'items': [{'word': 'hello'}]},
        )
        _ensure_progress(db_session, test_user.id, lesson.id)
        _login(client, test_user)

        mock_path = 'app.curriculum.routes.lessons._count_pronunciation_attempts_today'
        with patch(mock_path, return_value=199):
            resp = client.post(
                SUBMIT_URL.format(lesson.id),
                json={'target_word': 'hello', 'recognized_text': 'hello'},
            )
        # Should NOT be rate-limited (199 < 200)
        assert resp.status_code != 429

    def test_at_limit_blocked(self, client, db_session, test_user):
        lesson = _make_lesson(
            db_session,
            'pronunciation',
            {'items': [{'word': 'hello'}]},
        )
        _ensure_progress(db_session, test_user.id, lesson.id)
        _login(client, test_user)

        mock_path = 'app.curriculum.routes.lessons._count_pronunciation_attempts_today'
        with patch(mock_path, return_value=200):
            resp = client.post(
                SUBMIT_URL.format(lesson.id),
                json={'target_word': 'hello', 'recognized_text': 'hello'},
            )
        assert resp.status_code == 429
        data = resp.get_json()
        assert data['error'] == 'rate_limit_exceeded'

    def test_over_limit_blocked(self, client, db_session, test_user):
        lesson = _make_lesson(
            db_session,
            'pronunciation',
            {'items': [{'word': 'world'}]},
        )
        _ensure_progress(db_session, test_user.id, lesson.id)
        _login(client, test_user)

        mock_path = 'app.curriculum.routes.lessons._count_pronunciation_attempts_today'
        with patch(mock_path, return_value=201):
            resp = client.post(
                SUBMIT_URL.format(lesson.id),
                json={'target_word': 'world', 'recognized_text': 'world'},
            )
        assert resp.status_code == 429

    def test_different_users_independent(self, client, db_session, test_user):
        """One user being rate-limited does not block another user."""
        other_user_id = test_user.id + 9999

        lesson = _make_lesson(
            db_session,
            'pronunciation',
            {'items': [{'word': 'test'}]},
        )
        _ensure_progress(db_session, test_user.id, lesson.id)
        _login(client, test_user)

        def _side_effect(uid):
            # other_user_id is over limit, current test_user is not
            return 250 if uid == other_user_id else 0

        mock_path = 'app.curriculum.routes.lessons._count_pronunciation_attempts_today'
        with patch(mock_path, side_effect=_side_effect):
            resp = client.post(
                SUBMIT_URL.format(lesson.id),
                json={'target_word': 'test', 'recognized_text': 'test'},
            )
        assert resp.status_code != 429


# ---------------------------------------------------------------------------
# Writing rate limiting
# ---------------------------------------------------------------------------

class TestWritingRateLimit:
    """Rate limit: max 70 writing attempts per user per day."""

    def test_within_limit_allowed(self, client, db_session, test_user):
        lesson = _make_lesson(
            db_session,
            'writing_prompt',
            {'prompt': 'Write about your day.', 'min_words': 1},
        )
        _ensure_progress(db_session, test_user.id, lesson.id)
        _login(client, test_user)

        mock_path = 'app.curriculum.routes.lessons._count_writing_attempts_today'
        with patch(mock_path, return_value=69):
            resp = client.post(
                SUBMIT_URL.format(lesson.id),
                json={'response_text': 'today was good', 'checklist_completed': False},
            )
        assert resp.status_code != 429

    def test_at_limit_blocked(self, client, db_session, test_user):
        lesson = _make_lesson(
            db_session,
            'writing_prompt',
            {'prompt': 'Write about your day.', 'min_words': 1},
        )
        _ensure_progress(db_session, test_user.id, lesson.id)
        _login(client, test_user)

        mock_path = 'app.curriculum.routes.lessons._count_writing_attempts_today'
        with patch(mock_path, return_value=70):
            resp = client.post(
                SUBMIT_URL.format(lesson.id),
                json={'response_text': 'today was good', 'checklist_completed': False},
            )
        assert resp.status_code == 429
        data = resp.get_json()
        assert data['error'] == 'rate_limit_exceeded'

    def test_over_limit_blocked(self, client, db_session, test_user):
        lesson = _make_lesson(
            db_session,
            'writing_prompt',
            {'prompt': 'Write about your day.', 'min_words': 1},
        )
        _ensure_progress(db_session, test_user.id, lesson.id)
        _login(client, test_user)

        mock_path = 'app.curriculum.routes.lessons._count_writing_attempts_today'
        with patch(mock_path, return_value=71):
            resp = client.post(
                SUBMIT_URL.format(lesson.id),
                json={'response_text': 'today was good', 'checklist_completed': False},
            )
        assert resp.status_code == 429

    def test_different_users_independent(self, client, db_session, test_user):
        """One user being rate-limited does not block another user."""
        other_user_id = test_user.id + 9999

        lesson = _make_lesson(
            db_session,
            'writing_prompt',
            {'prompt': 'Write something.', 'min_words': 1},
        )
        _ensure_progress(db_session, test_user.id, lesson.id)
        _login(client, test_user)

        def _side_effect(uid):
            return 100 if uid == other_user_id else 0

        mock_path = 'app.curriculum.routes.lessons._count_writing_attempts_today'
        with patch(mock_path, side_effect=_side_effect):
            resp = client.post(
                SUBMIT_URL.format(lesson.id),
                json={'response_text': 'today was good', 'checklist_completed': False},
            )
        assert resp.status_code != 429


# ---------------------------------------------------------------------------
# Count helpers unit tests
# ---------------------------------------------------------------------------

class TestCountHelpers:
    """Unit tests for the daily-count helper functions."""

    def test_count_pronunciation_returns_zero_for_new_user(self, db_session, test_user):
        from app.curriculum.routes.lessons import _count_pronunciation_attempts_today
        count = _count_pronunciation_attempts_today(test_user.id)
        assert count == 0

    def test_count_writing_returns_zero_for_new_user(self, db_session, test_user):
        from app.curriculum.routes.lessons import _count_writing_attempts_today
        count = _count_writing_attempts_today(test_user.id)
        assert count == 0

    def test_count_pronunciation_counts_todays_rows(self, db_session, test_user):
        from app.curriculum.models import PronunciationAttempt
        from app.curriculum.routes.lessons import _count_pronunciation_attempts_today

        attempt = PronunciationAttempt(
            user_id=test_user.id,
            word='hello',
            recognized_text='hello',
            matched=True,
            created_at=datetime.now(timezone.utc).replace(tzinfo=None),
        )
        db_session.add(attempt)
        db_session.commit()

        count = _count_pronunciation_attempts_today(test_user.id)
        assert count == 1

    def test_count_writing_counts_todays_rows(self, db_session, test_user, test_module):
        from app.curriculum.models import Lessons, UserWritingAttempt
        from app.curriculum.routes.lessons import _count_writing_attempts_today

        lesson = Lessons(
            module_id=test_module.id,
            number=55,
            title='Writing',
            type='writing_prompt',
            content={'prompt': 'Write.', 'min_words': 1},
        )
        db_session.add(lesson)
        db_session.commit()

        attempt = UserWritingAttempt(
            user_id=test_user.id,
            lesson_id=lesson.id,
            response_text='hello world',
            word_count=2,
            checklist_completed=False,
            created_at=datetime.now(timezone.utc).replace(tzinfo=None),
        )
        db_session.add(attempt)
        db_session.commit()

        count = _count_writing_attempts_today(test_user.id)
        assert count == 1
