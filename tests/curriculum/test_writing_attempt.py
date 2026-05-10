"""Tests for UserWritingAttempt model and save_writing_attempt helper.

Task 20: UserWritingAttempt model.
"""
from __future__ import annotations

import uuid

from app.curriculum.models import (
    CEFRLevel, Lessons, Module, UserWritingAttempt, save_writing_attempt,
)
from app.utils.db import db


def _unique_code() -> str:
    return uuid.uuid4().hex[:2].upper()


def _make_writing_lesson(db_session) -> Lessons:
    level = CEFRLevel(code=_unique_code(), name="Level", description="d", order=1)
    db_session.add(level)
    db_session.commit()
    module = Module(
        level_id=level.id,
        number=1,
        title="Writing Module",
        description="d",
        raw_content={"module": {"id": 1}},
    )
    db_session.add(module)
    db_session.commit()
    lesson = Lessons(
        module_id=module.id,
        number=1,
        title="Writing Prompt Test",
        type="writing_prompt",
        content={"prompt": "Describe your day.", "min_words": 30},
    )
    db_session.add(lesson)
    db_session.commit()
    return lesson


class TestUserWritingAttemptModel:
    def test_model_saves_correctly(self, app, db_session, test_user):
        lesson = _make_writing_lesson(db_session)
        attempt = save_writing_attempt(
            test_user.id, lesson.id, "Hello world this is my writing.", True, db
        )
        assert attempt.id is not None
        assert attempt.user_id == test_user.id
        assert attempt.lesson_id == lesson.id
        assert attempt.response_text == "Hello world this is my writing."
        assert attempt.checklist_completed is True

    def test_word_count_computed_from_text(self, app, db_session, test_user):
        lesson = _make_writing_lesson(db_session)
        attempt = save_writing_attempt(
            test_user.id, lesson.id, "one two three four five", False, db
        )
        assert attempt.word_count == 5

    def test_empty_text_word_count_is_zero(self, app, db_session, test_user):
        lesson = _make_writing_lesson(db_session)
        attempt = save_writing_attempt(test_user.id, lesson.id, "", False, db)
        assert attempt.word_count == 0

    def test_whitespace_only_text_word_count_is_zero(self, app, db_session, test_user):
        lesson = _make_writing_lesson(db_session)
        attempt = save_writing_attempt(test_user.id, lesson.id, "   ", False, db)
        assert attempt.word_count == 0

    def test_multiple_attempts_per_lesson_allowed(self, app, db_session, test_user):
        lesson = _make_writing_lesson(db_session)
        attempt1 = save_writing_attempt(test_user.id, lesson.id, "First attempt text here.", True, db)
        attempt2 = save_writing_attempt(test_user.id, lesson.id, "Second attempt text here.", True, db)
        db.session.commit()
        rows = db.session.query(UserWritingAttempt).filter_by(
            user_id=test_user.id, lesson_id=lesson.id
        ).all()
        assert len(rows) == 2
        assert attempt1.id != attempt2.id

    def test_checklist_completed_false_stored(self, app, db_session, test_user):
        lesson = _make_writing_lesson(db_session)
        attempt = save_writing_attempt(
            test_user.id, lesson.id, "Some writing here for test.", False, db
        )
        assert attempt.checklist_completed is False

    def test_created_at_set_automatically(self, app, db_session, test_user):
        lesson = _make_writing_lesson(db_session)
        attempt = save_writing_attempt(
            test_user.id, lesson.id, "Time test writing attempt.", True, db
        )
        assert attempt.created_at is not None

    def test_repr_contains_key_fields(self, app, db_session, test_user):
        lesson = _make_writing_lesson(db_session)
        attempt = save_writing_attempt(
            test_user.id, lesson.id, "repr test writing words here.", True, db
        )
        r = repr(attempt)
        assert str(attempt.id) in r
        assert str(test_user.id) in r
