"""Tests for ListeningAttempt model and log_listening_attempt helper.

Task 8: Listening attempt tracking model.
"""
from __future__ import annotations

import uuid

import pytest

from app.curriculum.models import CEFRLevel, Lessons, ListeningAttempt, Module
from app.curriculum.listening_service import log_listening_attempt


def _unique_code() -> str:
    return uuid.uuid4().hex[:2].upper()


def _make_listening_lesson(db_session, lesson_type: str = 'dictation') -> Lessons:
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
        title='Listening Test',
        type=lesson_type,
        content={
            'audio_url': '/static/audio/test.mp3',
            'transcript': 'Hello world',
        },
    )
    db_session.add(lesson)
    db_session.commit()
    return lesson


# ---------------------------------------------------------------------------
# Model tests
# ---------------------------------------------------------------------------

class TestListeningAttemptModel:
    def test_model_persists_correctly(self, db_session, app, test_user):
        with app.app_context():
            lesson = _make_listening_lesson(db_session)
            attempt = ListeningAttempt(
                user_id=test_user.id,
                lesson_id=lesson.id,
                score=85.0,
                replay_count=2,
            )
            db_session.add(attempt)
            db_session.commit()

            fetched = db_session.query(ListeningAttempt).filter_by(id=attempt.id).one()
            assert fetched.user_id == test_user.id
            assert fetched.lesson_id == lesson.id
            assert fetched.score == 85.0
            assert fetched.replay_count == 2
            assert fetched.created_at is not None

    def test_duplicate_lesson_attempts_allowed(self, db_session, app, test_user):
        with app.app_context():
            lesson = _make_listening_lesson(db_session)
            for score in (60.0, 80.0, 100.0):
                attempt = ListeningAttempt(
                    user_id=test_user.id,
                    lesson_id=lesson.id,
                    score=score,
                    replay_count=0,
                )
                db_session.add(attempt)
            db_session.commit()

            rows = db_session.query(ListeningAttempt).filter_by(
                user_id=test_user.id, lesson_id=lesson.id
            ).all()
            assert len(rows) == 3

    def test_repr_contains_key_info(self, db_session, app, test_user):
        with app.app_context():
            lesson = _make_listening_lesson(db_session)
            attempt = ListeningAttempt(
                user_id=test_user.id,
                lesson_id=lesson.id,
                score=50.0,
                replay_count=1,
            )
            db_session.add(attempt)
            db_session.commit()
            r = repr(attempt)
            assert str(test_user.id) in r
            assert '50.0' in r


# ---------------------------------------------------------------------------
# Service helper tests
# ---------------------------------------------------------------------------

class TestLogListeningAttempt:
    def test_creates_row(self, db_session, app, test_user):
        from app.utils.db import db as _db

        with app.app_context():
            lesson = _make_listening_lesson(db_session, 'dictation')
            attempt = log_listening_attempt(
                user_id=test_user.id,
                lesson_id=lesson.id,
                score=90.0,
                replay_count=3,
                db=_db,
            )
            db_session.commit()

            assert attempt.id is not None
            assert attempt.score == 90.0
            assert attempt.replay_count == 3

    def test_score_stored_as_float(self, db_session, app, test_user):
        from app.utils.db import db as _db

        with app.app_context():
            lesson = _make_listening_lesson(db_session, 'audio_fill_blank')
            attempt = log_listening_attempt(
                user_id=test_user.id,
                lesson_id=lesson.id,
                score=75,
                replay_count=0,
                db=_db,
            )
            db_session.commit()
            assert isinstance(attempt.score, float)

    def test_multiple_calls_create_multiple_rows(self, db_session, app, test_user):
        from app.utils.db import db as _db

        with app.app_context():
            lesson = _make_listening_lesson(db_session)
            for score in (50.0, 70.0):
                log_listening_attempt(test_user.id, lesson.id, score, 0, _db)
            db_session.commit()

            count = db_session.query(ListeningAttempt).filter_by(
                user_id=test_user.id, lesson_id=lesson.id
            ).count()
            assert count == 2
