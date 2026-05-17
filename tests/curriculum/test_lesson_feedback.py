"""Tests for LessonFeedback model, save_lesson_feedback helper, and feedback API endpoint.

Task 90: Lesson user feedback collection.
"""
from __future__ import annotations

import uuid

from app.curriculum.models import (
    CEFRLevel, LessonFeedback, Lessons, Module, save_lesson_feedback,
)
from app.utils.db import db


def _unique_code() -> str:
    return uuid.uuid4().hex[:2].upper()


def _make_lesson(db_session) -> Lessons:
    level = CEFRLevel(code=_unique_code(), name="Level", description="d", order=1)
    db_session.add(level)
    db_session.commit()
    module = Module(
        level_id=level.id,
        number=1,
        title="Feedback Module",
        description="d",
        raw_content={"module": {"id": 1}},
    )
    db_session.add(module)
    db_session.commit()
    lesson = Lessons(
        module_id=module.id,
        number=1,
        title="Feedback Test Lesson",
        type="quiz",
        content={"items": []},
    )
    db_session.add(lesson)
    db_session.commit()
    return lesson


class TestLessonFeedbackModel:
    def test_feedback_saves_correctly(self, app, db_session, test_user):
        lesson = _make_lesson(db_session)
        fb = save_lesson_feedback(test_user.id, lesson.id, 5, None, db)
        db_session.commit()

        assert fb.id is not None
        assert fb.user_id == test_user.id
        assert fb.lesson_id == lesson.id
        assert fb.rating == 5
        assert fb.comment is None

    def test_feedback_with_comment(self, app, db_session, test_user):
        lesson = _make_lesson(db_session)
        fb = save_lesson_feedback(test_user.id, lesson.id, 1, "Too hard", db)
        db_session.commit()

        fetched = db_session.get(LessonFeedback, fb.id)
        assert fetched.comment == "Too hard"

    def test_created_at_set_automatically(self, app, db_session, test_user):
        lesson = _make_lesson(db_session)
        fb = save_lesson_feedback(test_user.id, lesson.id, 5, None, db)
        db_session.commit()

        assert fb.created_at is not None

    def test_duplicate_updates_not_creates(self, app, db_session, test_user):
        lesson = _make_lesson(db_session)
        fb1 = save_lesson_feedback(test_user.id, lesson.id, 5, None, db)
        db_session.commit()

        fb2 = save_lesson_feedback(test_user.id, lesson.id, 1, "Changed mind", db)
        db_session.commit()

        # Same row updated, not a new one
        assert fb1.id == fb2.id
        fetched = db_session.get(LessonFeedback, fb1.id)
        assert fetched.rating == 1
        assert fetched.comment == "Changed mind"

        # Only one row for this user+lesson
        count = db_session.query(LessonFeedback).filter_by(
            user_id=test_user.id, lesson_id=lesson.id
        ).count()
        assert count == 1

    def test_repr_contains_key_fields(self, app, db_session, test_user):
        lesson = _make_lesson(db_session)
        fb = save_lesson_feedback(test_user.id, lesson.id, 5, None, db)
        db_session.commit()

        r = repr(fb)
        assert str(test_user.id) in r
        assert str(lesson.id) in r
        assert "5" in r


class TestLessonFeedbackAPI:
    def _login(self, client, user):
        with client.session_transaction() as sess:
            sess['_user_id'] = str(user.id)
            sess['_fresh'] = True

    def test_feedback_thumbs_up_returns_200(self, app, client, db_session, test_user):
        lesson = _make_lesson(db_session)
        self._login(client, test_user)

        resp = client.post(
            f'/curriculum/api/lessons/{lesson.id}/feedback',
            json={'rating': 5},
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['success'] is True
        assert data['rating'] == 5

    def test_feedback_thumbs_down_returns_200(self, app, client, db_session, test_user):
        lesson = _make_lesson(db_session)
        self._login(client, test_user)

        resp = client.post(
            f'/curriculum/api/lessons/{lesson.id}/feedback',
            json={'rating': 1},
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['success'] is True
        assert data['rating'] == 1

    def test_feedback_saved_to_db(self, app, client, db_session, test_user):
        lesson = _make_lesson(db_session)
        self._login(client, test_user)

        client.post(f'/curriculum/api/lessons/{lesson.id}/feedback', json={'rating': 5})

        fb = db_session.query(LessonFeedback).filter_by(
            user_id=test_user.id, lesson_id=lesson.id
        ).first()
        assert fb is not None
        assert fb.rating == 5

    def test_duplicate_feedback_updates_rating(self, app, client, db_session, test_user):
        lesson = _make_lesson(db_session)
        self._login(client, test_user)

        client.post(f'/curriculum/api/lessons/{lesson.id}/feedback', json={'rating': 5})
        client.post(f'/curriculum/api/lessons/{lesson.id}/feedback', json={'rating': 1})

        count = db_session.query(LessonFeedback).filter_by(
            user_id=test_user.id, lesson_id=lesson.id
        ).count()
        assert count == 1

        fb = db_session.query(LessonFeedback).filter_by(
            user_id=test_user.id, lesson_id=lesson.id
        ).first()
        assert fb.rating == 1

    def test_invalid_rating_returns_400(self, app, client, db_session, test_user):
        lesson = _make_lesson(db_session)
        self._login(client, test_user)

        resp = client.post(
            f'/curriculum/api/lessons/{lesson.id}/feedback',
            json={'rating': 10},
        )
        assert resp.status_code == 400

    def test_missing_rating_returns_400(self, app, client, db_session, test_user):
        lesson = _make_lesson(db_session)
        self._login(client, test_user)

        resp = client.post(
            f'/curriculum/api/lessons/{lesson.id}/feedback',
            json={},
        )
        assert resp.status_code == 400

    def test_unauthenticated_returns_redirect(self, app, client, db_session):
        lesson = _make_lesson(db_session)

        resp = client.post(
            f'/curriculum/api/lessons/{lesson.id}/feedback',
            json={'rating': 5},
        )
        # Flask-Login redirects unauthenticated requests to login page
        assert resp.status_code in (302, 401)


class TestAdminContentQualityRatings:
    def test_admin_content_quality_includes_avg_rating(self, app, client, db_session, admin_user):
        lesson = _make_lesson(db_session)
        # Add a feedback row directly
        fb = LessonFeedback(user_id=admin_user.id, lesson_id=lesson.id, rating=5)
        db_session.add(fb)
        db_session.commit()

        with client.session_transaction() as sess:
            sess['_user_id'] = str(admin_user.id)
            sess['_fresh'] = True

        resp = client.get('/admin/content-quality')
        assert resp.status_code == 200
        # Avg rating appears in the rendered page
        assert b'avg_rating' in resp.data or b'5.0' in resp.data or 'Рейтинг'.encode() in resp.data
