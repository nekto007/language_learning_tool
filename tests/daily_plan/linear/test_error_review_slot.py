"""Tests for ``build_error_review_slot`` cooldown/last-resolved metadata.

Covers Task 4 of the Linear Daily Plan 20 Improvements plan: the slot
exposes ``last_resolved_at``, ``hours_since_resolved``, and
``cooldown_remaining_hours`` so the dashboard can hint at how recently
the user reviewed errors and (for high-backlog overrides) how much
standard cooldown is still nominally pending.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from app.auth.models import User
from app.curriculum.models import CEFRLevel, Lessons, Module
from app.daily_plan.linear.models import QuizErrorLog
from app.daily_plan.linear.slots.error_review_slot import build_error_review_slot
from app.utils.db import db as real_db


def _unique_code() -> str:
    return uuid.uuid4().hex[:2].upper()


def _make_user(db_session) -> User:
    suffix = uuid.uuid4().hex[:10]
    user = User(
        username=f'errslot_{suffix}',
        email=f'errslot_{suffix}@example.com',
        active=True,
    )
    user.set_password('secret123')
    db_session.add(user)
    db_session.commit()
    return user


def _make_lesson(db_session) -> Lessons:
    level = CEFRLevel(code=_unique_code(), name='L', description='desc', order=1)
    db_session.add(level)
    db_session.commit()
    module = Module(
        level_id=level.id,
        number=1,
        title='M1',
        description='d',
        raw_content={'module': {'id': 1}},
    )
    db_session.add(module)
    db_session.commit()
    lesson = Lessons(
        module_id=module.id,
        number=1,
        title='Lq',
        type='quiz',
        content={},
    )
    db_session.add(lesson)
    db_session.commit()
    return lesson


def _seed_errors(db_session, user, lesson, count, resolved_at=None):
    rows = []
    for i in range(count):
        entry = QuizErrorLog(
            user_id=user.id,
            lesson_id=lesson.id,
            question_payload={'seed': i},
            resolved_at=resolved_at,
        )
        db_session.add(entry)
        rows.append(entry)
    db_session.commit()
    return rows


class TestErrorReviewSlotCooldownMeta:
    def test_never_resolved_emits_none_metadata(self, db_session):
        user = _make_user(db_session)
        lesson = _make_lesson(db_session)
        _seed_errors(db_session, user, lesson, count=6)

        slot = build_error_review_slot(user.id, real_db)

        assert slot is not None
        assert slot.data['last_resolved_at'] is None
        assert slot.data['hours_since_resolved'] is None
        assert slot.data['cooldown_remaining_hours'] == 0

    def test_high_backlog_override_reports_remaining_cooldown(self, db_session):
        user = _make_user(db_session)
        lesson = _make_lesson(db_session)
        _seed_errors(db_session, user, lesson, count=15)
        # Resolved 1.5d ago — past 1d high-backlog cooldown but not past
        # the standard 3d cooldown, so the slot still surfaces while the
        # standard cooldown_remaining_hours stays positive.
        _seed_errors(
            db_session, user, lesson, count=1,
            resolved_at=datetime.now(timezone.utc) - timedelta(days=1, hours=12),
        )

        slot = build_error_review_slot(user.id, real_db)

        assert slot is not None
        assert slot.data['last_resolved_at'] is not None
        assert slot.data['hours_since_resolved'] == 36
        # 3d - 36h = 36h remaining, ceil → 36.
        assert slot.data['cooldown_remaining_hours'] == 36

    def test_resolved_long_ago_zeros_cooldown_remaining(self, db_session):
        user = _make_user(db_session)
        lesson = _make_lesson(db_session)
        _seed_errors(db_session, user, lesson, count=6)
        _seed_errors(
            db_session, user, lesson, count=1,
            resolved_at=datetime.now(timezone.utc) - timedelta(days=5),
        )

        slot = build_error_review_slot(user.id, real_db)

        assert slot is not None
        assert slot.data['last_resolved_at'] is not None
        assert slot.data['hours_since_resolved'] >= 24 * 5 - 1
        assert slot.data['cooldown_remaining_hours'] == 0
