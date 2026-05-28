"""Tests for PronunciationAttempt model and log_pronunciation_attempt helper.

Task 56: Pronunciation attempt tracking.
"""
from __future__ import annotations

import uuid

import pytest

from app.curriculum.models import CEFRLevel, Lessons, Module, PronunciationAttempt
from app.curriculum.listening_service import log_pronunciation_attempt
from tests.conftest import unique_level_code


def _make_pronunciation_lesson(db_session) -> Lessons:
    level = CEFRLevel(code=unique_level_code(), name='Level', description='d', order=1)
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
        title='Pronunciation Test',
        type='pronunciation',
        content={
            'items': [
                {'word': 'apple', 'pronunciation_hint': '/ˈæpəl/'},
            ]
        },
    )
    db_session.add(lesson)
    db_session.commit()
    return lesson


# ---------------------------------------------------------------------------
# Model tests
# ---------------------------------------------------------------------------

class TestPronunciationAttemptModel:
    def test_model_saves_correctly(self, db_session, app, test_user):
        with app.app_context():
            attempt = PronunciationAttempt(
                user_id=test_user.id,
                word='apple',
                recognized_text='apple',
                matched=True,
            )
            db_session.add(attempt)
            db_session.commit()

            fetched = db_session.query(PronunciationAttempt).filter_by(id=attempt.id).one()
            assert fetched.user_id == test_user.id
            assert fetched.word == 'apple'
            assert fetched.recognized_text == 'apple'
            assert fetched.matched is True
            assert fetched.created_at is not None

    def test_matched_computed_correctly_true(self, db_session, app, test_user):
        with app.app_context():
            attempt = PronunciationAttempt(
                user_id=test_user.id,
                word='hello',
                recognized_text='hello',
                matched=True,
            )
            db_session.add(attempt)
            db_session.commit()
            assert attempt.matched is True

    def test_matched_computed_correctly_false(self, db_session, app, test_user):
        with app.app_context():
            attempt = PronunciationAttempt(
                user_id=test_user.id,
                word='hello',
                recognized_text='world',
                matched=False,
            )
            db_session.add(attempt)
            db_session.commit()
            assert attempt.matched is False

    def test_multiple_attempts_per_word_allowed(self, db_session, app, test_user):
        with app.app_context():
            for recognized, matched in [('aple', False), ('apple', True), ('appel', False)]:
                attempt = PronunciationAttempt(
                    user_id=test_user.id,
                    word='apple',
                    recognized_text=recognized,
                    matched=matched,
                )
                db_session.add(attempt)
            db_session.commit()

            rows = db_session.query(PronunciationAttempt).filter_by(
                user_id=test_user.id, word='apple'
            ).all()
            assert len(rows) == 3

    def test_repr_contains_key_info(self, db_session, app, test_user):
        with app.app_context():
            attempt = PronunciationAttempt(
                user_id=test_user.id,
                word='banana',
                recognized_text='',
                matched=False,
            )
            db_session.add(attempt)
            db_session.commit()
            r = repr(attempt)
            assert 'banana' in r
            assert str(test_user.id) in r


# ---------------------------------------------------------------------------
# Helper function tests
# ---------------------------------------------------------------------------

class TestLogPronunciationAttempt:
    def test_creates_row(self, db_session, app, test_user):
        from app.utils.db import db as _db

        with app.app_context():
            attempt = log_pronunciation_attempt(
                user_id=test_user.id,
                word='orange',
                recognized='orange',
                matched=True,
                db=_db,
            )
            db_session.commit()

            assert attempt.id is not None
            assert attempt.word == 'orange'
            assert attempt.recognized_text == 'orange'
            assert attempt.matched is True

    def test_self_assessed_logs_matched_false(self, db_session, app, test_user):
        from app.utils.db import db as _db

        with app.app_context():
            attempt = log_pronunciation_attempt(
                user_id=test_user.id,
                word='grape',
                recognized='',
                matched=False,
                db=_db,
            )
            db_session.commit()

            assert attempt.matched is False
            assert attempt.recognized_text == ''

    def test_multiple_calls_create_multiple_rows(self, db_session, app, test_user):
        from app.utils.db import db as _db

        with app.app_context():
            for recognized, matched in [('aple', False), ('apple', True)]:
                log_pronunciation_attempt(
                    user_id=test_user.id,
                    word='apple',
                    recognized=recognized,
                    matched=matched,
                    db=_db,
                )
            db_session.commit()

            count = db_session.query(PronunciationAttempt).filter_by(
                user_id=test_user.id, word='apple'
            ).count()
            assert count == 2
