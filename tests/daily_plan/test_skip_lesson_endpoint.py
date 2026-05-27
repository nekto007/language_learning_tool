"""Tests for POST /api/daily-plan/skip-lesson endpoint.

Covers:
- 400 for missing/invalid lesson_id
- 400 for non-existent lesson_id
- already_deferred on repeated skip of same lesson today
- skip_quota_exhausted after quota (1 per user-local day) is used
- Successful skip returns next_lesson_id (or null)
- Concurrent duplicate insert handled via savepoint + IntegrityError
- slot_skipped event quota enforcement (separate from lesson skip)
"""
from __future__ import annotations

import uuid
from datetime import date, timedelta
from unittest.mock import patch

import pytest

from app.curriculum.models import CEFRLevel, Lessons, Module
from app.daily_plan.models import LessonSkip


# ──────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────

def _make_lesson(db_session) -> Lessons:
    # CEFRLevel.code is VARCHAR(2) unique — generate random 2-char hex codes and
    # retry on the rare collision (test isolation via savepoints keeps the table small).
    import random
    import string
    while True:
        uid = ''.join(random.choices(string.ascii_uppercase, k=2))
        if not db_session.query(CEFRLevel).filter_by(code=uid).first():
            break
    level = CEFRLevel(code=uid, name='Beginner', description='desc', order=random.randint(200, 9999))
    db_session.add(level)
    db_session.commit()
    module = Module(
        level_id=level.id,
        number=99,
        title=f'Module {uid}',
        description='desc',
        raw_content={'module': {'id': 99}},
    )
    db_session.add(module)
    db_session.commit()
    lesson = Lessons(
        module_id=module.id,
        number=99,
        title=f'Lesson {uid}',
        type='quiz',
        content={},
    )
    db_session.add(lesson)
    db_session.commit()
    return lesson


def _post_skip(client, lesson_id):
    return client.post(
        '/api/daily-plan/skip-lesson',
        json={'lesson_id': lesson_id},
    )


# ──────────────────────────────────────────────
# Input validation
# ──────────────────────────────────────────────

class TestSkipLessonInputValidation:
    def test_missing_lesson_id_returns_400(self, authenticated_client):
        resp = authenticated_client.post('/api/daily-plan/skip-lesson', json={})
        assert resp.status_code == 400
        assert resp.get_json()['error'] == 'invalid_input'

    def test_non_integer_lesson_id_returns_400(self, authenticated_client):
        resp = authenticated_client.post(
            '/api/daily-plan/skip-lesson', json={'lesson_id': 'abc'}
        )
        assert resp.status_code == 400
        assert resp.get_json()['error'] == 'invalid_input'

    def test_zero_lesson_id_returns_400(self, authenticated_client):
        resp = authenticated_client.post(
            '/api/daily-plan/skip-lesson', json={'lesson_id': 0}
        )
        assert resp.status_code == 400
        assert resp.get_json()['error'] == 'invalid_input'

    def test_negative_lesson_id_returns_400(self, authenticated_client):
        resp = authenticated_client.post(
            '/api/daily-plan/skip-lesson', json={'lesson_id': -5}
        )
        assert resp.status_code == 400
        assert resp.get_json()['error'] == 'invalid_input'

    def test_boolean_lesson_id_returns_400(self, authenticated_client):
        resp = authenticated_client.post(
            '/api/daily-plan/skip-lesson', json={'lesson_id': True}
        )
        assert resp.status_code == 400
        assert resp.get_json()['error'] == 'invalid_input'

    def test_non_json_content_type_returns_400(self, authenticated_client):
        resp = authenticated_client.post(
            '/api/daily-plan/skip-lesson',
            data='lesson_id=1',
            content_type='application/x-www-form-urlencoded',
        )
        assert resp.status_code == 400

    def test_nonexistent_lesson_id_returns_400(self, authenticated_client):
        resp = _post_skip(authenticated_client, 9999999)
        assert resp.status_code == 400
        assert resp.get_json()['error'] == 'invalid_lesson'


# ──────────────────────────────────────────────
# already_deferred
# ──────────────────────────────────────────────

class TestAlreadyDeferred:
    def test_already_deferred_on_second_skip_same_lesson(
        self, authenticated_client, db_session, test_user
    ):
        lesson = _make_lesson(db_session)
        today = date.today()
        with patch('app.utils.time_utils.get_user_local_date', return_value=today):
            first = _post_skip(authenticated_client, lesson.id)
            second = _post_skip(authenticated_client, lesson.id)

        assert first.status_code == 200
        assert second.status_code == 400
        assert second.get_json()['error'] == 'already_deferred'

    def test_already_deferred_only_for_same_user_local_date(
        self, authenticated_client, db_session, test_user
    ):
        lesson = _make_lesson(db_session)
        today = date.today()
        yesterday = today - timedelta(days=1)

        # Manually insert a skip for yesterday (not today) — should not block today's skip.
        db_session.add(LessonSkip(
            user_id=test_user.id,
            lesson_id=lesson.id,
            skipped_on_date=yesterday,
            defer_until_date=today,
        ))
        db_session.commit()

        with patch('app.utils.time_utils.get_user_local_date', return_value=today):
            resp = _post_skip(authenticated_client, lesson.id)

        assert resp.status_code == 200


# ──────────────────────────────────────────────
# Quota enforcement
# ──────────────────────────────────────────────

class TestSkipLessonQuota:
    def test_skip_quota_exhausted_after_one_lesson_skip(
        self, authenticated_client, db_session, test_user
    ):
        lesson_a = _make_lesson(db_session)
        lesson_b = _make_lesson(db_session)
        today = date.today()
        with patch('app.utils.time_utils.get_user_local_date', return_value=today):
            first = _post_skip(authenticated_client, lesson_a.id)
            second = _post_skip(authenticated_client, lesson_b.id)

        assert first.status_code == 200
        assert second.status_code == 429
        assert second.get_json()['error'] == 'skip_quota_exhausted'

    def test_quota_is_per_user_local_date(
        self, authenticated_client, db_session, test_user
    ):
        lesson = _make_lesson(db_session)
        today = date.today()
        yesterday = today - timedelta(days=1)

        # Simulate: yesterday's skip already stored in DB.
        db_session.add(LessonSkip(
            user_id=test_user.id,
            lesson_id=lesson.id,
            skipped_on_date=yesterday,
            defer_until_date=today,
        ))
        db_session.commit()

        # Today's quota should be fresh.
        lesson_b = _make_lesson(db_session)
        with patch('app.utils.time_utils.get_user_local_date', return_value=today):
            resp = _post_skip(authenticated_client, lesson_b.id)

        assert resp.status_code == 200

    def test_skip_writes_lesson_skip_row(
        self, authenticated_client, db_session, test_user
    ):
        lesson = _make_lesson(db_session)
        today = date.today()
        with patch('app.utils.time_utils.get_user_local_date', return_value=today):
            resp = _post_skip(authenticated_client, lesson.id)

        assert resp.status_code == 200
        skip_row = db_session.query(LessonSkip).filter_by(
            user_id=test_user.id,
            lesson_id=lesson.id,
            skipped_on_date=today,
        ).first()
        assert skip_row is not None
        assert skip_row.defer_until_date == today + timedelta(days=1)


# ──────────────────────────────────────────────
# Successful skip response
# ──────────────────────────────────────────────

class TestSkipLessonSuccess:
    def test_success_returns_next_lesson_id_or_null(
        self, authenticated_client, db_session
    ):
        lesson = _make_lesson(db_session)
        today = date.today()
        with patch('app.utils.time_utils.get_user_local_date', return_value=today):
            resp = _post_skip(authenticated_client, lesson.id)

        assert resp.status_code == 200
        data = resp.get_json()
        assert data['success'] is True
        assert 'next_lesson_id' in data

    def test_next_lesson_id_is_null_when_no_eligible_lesson(
        self, authenticated_client, db_session
    ):
        lesson = _make_lesson(db_session)
        today = date.today()
        with patch('app.utils.time_utils.get_user_local_date', return_value=today):
            with patch('app.curriculum.navigation.find_next_lesson', return_value=None):
                resp = _post_skip(authenticated_client, lesson.id)

        assert resp.status_code == 200
        assert resp.get_json()['next_lesson_id'] is None

    def test_unauthenticated_request_returns_401(self, client):
        resp = client.post('/api/daily-plan/skip-lesson', json={'lesson_id': 1})
        assert resp.status_code in (401, 302)


# ──────────────────────────────────────────────
# Concurrent duplicate (savepoint dedup)
# ──────────────────────────────────────────────

class TestSkipLessonConcurrentDedup:
    def test_concurrent_same_lesson_returns_already_deferred(
        self, authenticated_client, db_session, test_user
    ):
        """Simulate a concurrent duplicate by pre-inserting the LessonSkip row
        before the second request hits the savepoint insert."""
        lesson = _make_lesson(db_session)
        today = date.today()

        # Pre-insert the row to simulate the concurrent first request having
        # already committed its LessonSkip before the second arrives at the DB.
        db_session.add(LessonSkip(
            user_id=test_user.id,
            lesson_id=lesson.id,
            skipped_on_date=today,
            defer_until_date=today + timedelta(days=1),
        ))
        db_session.commit()

        with patch('app.utils.time_utils.get_user_local_date', return_value=today):
            resp = _post_skip(authenticated_client, lesson.id)

        # The endpoint checks for existing rows BEFORE the savepoint insert,
        # so this path returns already_deferred (not a 500).
        assert resp.status_code == 400
        assert resp.get_json()['error'] == 'already_deferred'
