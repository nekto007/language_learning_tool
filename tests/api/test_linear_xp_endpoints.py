"""Integration tests for linear daily plan XP endpoints.

Covers the POST /api/daily-plan/error-review/complete endpoint added in
Task 14: it resolves submitted error ids, awards ``linear_error_review``
XP once per day, and reports any level-up / perfect-day bonus payload.
"""
from __future__ import annotations

import uuid

import pytest

from app.achievements.models import StreakEvent, UserStatistics
from app.curriculum.models import CEFRLevel, Lessons, Module
from app.daily_plan.linear.models import QuizErrorLog
from app.daily_plan.linear.xp import LINEAR_XP_EVENT_TYPE
from app.utils.db import db as real_db


def _linear_user_enable(db_session, test_user):
    test_user.use_linear_plan = True
    db_session.commit()
    stats = UserStatistics.query.filter_by(user_id=test_user.id).first()
    if stats is None:
        db_session.add(UserStatistics(
            user_id=test_user.id, total_xp=0, current_streak_days=0,
        ))
        db_session.commit()


def _ensure_module(db_session) -> Module:
    module = db_session.query(Module).order_by(Module.id.asc()).first()
    if module is not None:
        return module
    code = uuid.uuid4().hex[:2].upper()
    level = CEFRLevel(code=code, name='L', description='d', order=1)
    db_session.add(level)
    db_session.commit()
    module = Module(
        level_id=level.id,
        number=1,
        title='M',
        description='d',
        raw_content={'module': {'id': 1}},
    )
    db_session.add(module)
    db_session.commit()
    return module


def _make_lesson(db_session) -> Lessons:
    module = _ensure_module(db_session)
    next_number = db_session.query(Lessons).filter_by(module_id=module.id).count() + 1
    lesson = Lessons(
        module_id=module.id,
        number=next_number,
        title='Quiz',
        type='quiz',
        content={},
    )
    db_session.add(lesson)
    db_session.commit()
    return lesson


def _seed_errors(db_session, user_id: int, lesson_id: int, count: int):
    rows = []
    for i in range(count):
        entry = QuizErrorLog(
            user_id=user_id,
            lesson_id=lesson_id,
            question_payload={'idx': i},
        )
        db_session.add(entry)
        rows.append(entry)
    db_session.commit()
    return rows


class TestErrorReviewCompleteEndpoint:
    def test_resolves_errors_and_awards_xp(
        self, authenticated_client, db_session, test_user,
    ):
        _linear_user_enable(db_session, test_user)
        lesson = _make_lesson(db_session)
        errors = _seed_errors(db_session, test_user.id, lesson.id, 3)

        response = authenticated_client.post(
            '/api/daily-plan/error-review/complete',
            json={'error_ids': [e.id for e in errors]},
        )

        assert response.status_code == 200
        body = response.get_json()
        assert body['success'] is True
        assert body['resolved_count'] == 3
        assert body['xp']['awarded'] == 10

        # All 3 errors got a resolved_at timestamp.
        remaining_unresolved = (
            db_session.query(QuizErrorLog)
            .filter(
                QuizErrorLog.user_id == test_user.id,
                QuizErrorLog.resolved_at.is_(None),
            )
            .count()
        )
        assert remaining_unresolved == 0

        linear_events = (
            db_session.query(StreakEvent)
            .filter_by(user_id=test_user.id, event_type=LINEAR_XP_EVENT_TYPE)
            .all()
        )
        assert len(linear_events) == 1
        assert linear_events[0].details['source'] == 'linear_error_review'

    def test_second_call_same_day_does_not_double_award(
        self, authenticated_client, db_session, test_user,
    ):
        _linear_user_enable(db_session, test_user)
        lesson = _make_lesson(db_session)
        errors = _seed_errors(db_session, test_user.id, lesson.id, 2)

        first = authenticated_client.post(
            '/api/daily-plan/error-review/complete',
            json={'error_ids': [errors[0].id]},
        )
        assert first.status_code == 200
        assert first.get_json()['xp']['awarded'] == 10

        second = authenticated_client.post(
            '/api/daily-plan/error-review/complete',
            json={'error_ids': [errors[1].id]},
        )
        assert second.status_code == 200
        body = second.get_json()
        assert body['success'] is True
        assert body['resolved_count'] == 1
        assert 'xp' not in body  # already awarded earlier today

        stats = UserStatistics.query.filter_by(user_id=test_user.id).first()
        assert stats.total_xp == 10  # single award only

    def test_mission_user_resolves_but_earns_no_linear_xp(
        self, authenticated_client, db_session, test_user,
    ):
        # use_linear_plan stays False by default.
        lesson = _make_lesson(db_session)
        errors = _seed_errors(db_session, test_user.id, lesson.id, 2)

        response = authenticated_client.post(
            '/api/daily-plan/error-review/complete',
            json={'error_ids': [e.id for e in errors]},
        )

        assert response.status_code == 200
        body = response.get_json()
        assert body['resolved_count'] == 2
        assert 'xp' not in body

        linear_events = (
            db_session.query(StreakEvent)
            .filter_by(user_id=test_user.id, event_type=LINEAR_XP_EVENT_TYPE)
            .all()
        )
        assert linear_events == []

    def test_invalid_error_ids_rejected(self, authenticated_client, db_session, test_user):
        _linear_user_enable(db_session, test_user)
        response = authenticated_client.post(
            '/api/daily-plan/error-review/complete',
            json={'error_ids': 'not-a-list'},
        )
        assert response.status_code == 400

    def test_empty_body_still_awards_when_linear(
        self, authenticated_client, db_session, test_user,
    ):
        """Dashboard may POST with no ids if the user finished the pool
        via an earlier review — we still record the slot completion."""
        _linear_user_enable(db_session, test_user)
        response = authenticated_client.post(
            '/api/daily-plan/error-review/complete',
            json={},
        )
        assert response.status_code == 200
        body = response.get_json()
        assert body['success'] is True
        assert body['resolved_count'] == 0
        assert body['xp']['awarded'] == 10

    def test_foreign_error_ids_are_ignored(
        self, authenticated_client, db_session, test_user,
    ):
        _linear_user_enable(db_session, test_user)
        lesson = _make_lesson(db_session)

        # Create another user's error.
        from app.auth.models import User
        other = User(
            username=f'other_{uuid.uuid4().hex[:8]}',
            email=f'other_{uuid.uuid4().hex[:8]}@example.com',
            active=True,
        )
        other.set_password('secret123')
        db_session.add(other)
        db_session.commit()
        foreign = QuizErrorLog(
            user_id=other.id, lesson_id=lesson.id, question_payload={'x': 1},
        )
        db_session.add(foreign)
        db_session.commit()

        response = authenticated_client.post(
            '/api/daily-plan/error-review/complete',
            json={'error_ids': [foreign.id]},
        )
        assert response.status_code == 200
        assert response.get_json()['resolved_count'] == 0

        # Foreign error stays unresolved.
        reloaded = db_session.get(QuizErrorLog, foreign.id)
        assert reloaded.resolved_at is None
