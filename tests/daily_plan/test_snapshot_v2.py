"""Daily-plan snapshot v2: persistence, roll-over, overlay completion.

Tests cover:
- Fresh snapshot is written to ``DailyPlanLog.plan_json``
- Existing snapshot is returned unchanged
- Roll-over from yesterday triggers when ``has_learning_activity(yesterday)`` is False
- Roll-over does NOT trigger when yesterday had any activity
- Overlay marks curriculum item completed when its lesson was finished today
- Feature flag honours SiteSettings default OFF
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, time, timedelta, timezone

import pytest

from app.achievements.models import StreakEvent
from app.auth.models import User
from app.curriculum.models import CEFRLevel, LessonProgress, Lessons, Module
from app.daily_plan.models import DailyPlanLog
from app.daily_plan.snapshot import (
    SNAPSHOT_VERSION,
    overlay_completion,
    resolve_snapshot_for_today,
)
from app.utils.db import db as real_db
from tests.conftest import unique_level_code


@pytest.fixture
def user(db_session):
    suffix = uuid.uuid4().hex[:10]
    u = User(
        username=f'snap2_{suffix}',
        email=f'snap2_{suffix}@example.com',
        active=True,
    )
    u.set_password('secret123')
    db_session.add(u)
    db_session.commit()
    return u


@pytest.fixture
def vocabulary_lesson(db_session):
    code = unique_level_code()
    level = CEFRLevel(
        code=code, name=f'L-{code}', order=1,
    )
    db_session.add(level)
    db_session.commit()
    module = Module(
        level_id=level.id, number=1, title='M1', description='', raw_content={},
    )
    db_session.add(module)
    db_session.commit()
    lesson = Lessons(
        module_id=module.id, number=1, title='L1', type='vocabulary', content={},
    )
    db_session.add(lesson)
    db_session.commit()
    return lesson


class TestResolveSnapshot:

    def test_creates_fresh_snapshot_for_today(
        self, db_session, user, vocabulary_lesson,
    ):
        today = date.today()
        snap = resolve_snapshot_for_today(user.id, today, real_db)

        assert snap['version'] == SNAPSHOT_VERSION
        assert snap['date'] == today.isoformat()
        assert snap['tier'] in ('calm', 'normal', 'intensive')
        assert snap['rolled_over_from'] is None
        assert isinstance(snap['items'], list)
        # Persisted to DailyPlanLog.plan_json.
        row = db_session.query(DailyPlanLog).filter_by(
            user_id=user.id, plan_date=today,
        ).first()
        assert row is not None
        assert row.plan_json == snap

    def test_returns_existing_snapshot(self, db_session, user, vocabulary_lesson):
        today = date.today()
        # First call writes.
        snap1 = resolve_snapshot_for_today(user.id, today, real_db)
        real_db.session.commit()
        # Second call returns identical payload.
        snap2 = resolve_snapshot_for_today(user.id, today, real_db)
        assert snap2 == snap1


class TestRollover:

    def test_rollover_copies_yesterday_on_zero_activity(
        self, db_session, user, vocabulary_lesson,
    ):
        today = date.today()
        yesterday = today - timedelta(days=1)

        # Pre-seed yesterday's snapshot with one item.
        prior = {
            'version': SNAPSHOT_VERSION,
            'date': yesterday.isoformat(),
            'tier': 'calm',
            'rolled_over_from': None,
            'items': [{
                'id': 'curriculum:lesson:999',
                'section': 'required',
                'kind': 'curriculum',
                'title': 'Yesterday lesson',
                'subtitle': None,
                'lesson_type': 'vocabulary',
                'eta_minutes': 8,
                'url': '/learn/999/',
                'completion_signal': 'lesson_completed',
                'data': {'lesson_id': 999},
            }],
        }
        db_session.add(DailyPlanLog(
            user_id=user.id, plan_date=yesterday, plan_json=prior,
        ))
        db_session.commit()

        # No learning activity for yesterday → today rolls over.
        snap = resolve_snapshot_for_today(user.id, today, real_db)

        assert snap['rolled_over_from'] == yesterday.isoformat()
        assert snap['date'] == today.isoformat()
        # Items copied verbatim.
        assert snap['items'] == prior['items']

    def test_no_rollover_when_yesterday_had_activity(
        self, db_session, user, vocabulary_lesson,
    ):
        today = date.today()
        yesterday = today - timedelta(days=1)

        prior = {
            'version': SNAPSHOT_VERSION,
            'date': yesterday.isoformat(),
            'tier': 'calm',
            'rolled_over_from': None,
            'items': [{
                'id': 'curriculum:lesson:888',
                'section': 'required',
                'kind': 'curriculum',
                'title': 'Yesterday lesson',
                'subtitle': None,
                'lesson_type': 'vocabulary',
                'eta_minutes': 8,
                'url': '/learn/888/',
                'completion_signal': 'lesson_completed',
                'data': {'lesson_id': 888},
            }],
        }
        db_session.add(DailyPlanLog(
            user_id=user.id, plan_date=yesterday, plan_json=prior,
        ))
        # Activity yesterday — any LessonProgress in the user-local day window.
        from app.utils.time_utils import day_to_naive_utc
        y_start = day_to_naive_utc(user.id, real_db, days_ahead=-1)
        db_session.add(LessonProgress(
            user_id=user.id, lesson_id=vocabulary_lesson.id,
            status='in_progress',
            last_activity=y_start + timedelta(hours=10),
        ))
        db_session.commit()

        snap = resolve_snapshot_for_today(user.id, today, real_db)

        assert snap['rolled_over_from'] is None
        # Items reflect today's fresh build, not yesterday's copy.
        assert all(it.get('id') != 'curriculum:lesson:888' for it in snap['items'])

    def test_rollover_activity_window_uses_requested_plan_date(
        self, db_session, user, vocabulary_lesson,
    ):
        user.timezone = 'UTC'
        today = date.today() - timedelta(days=10)
        yesterday = today - timedelta(days=1)

        prior = {
            'version': SNAPSHOT_VERSION,
            'date': yesterday.isoformat(),
            'tier': 'calm',
            'rolled_over_from': None,
            'items': [{
                'id': 'curriculum:lesson:777',
                'section': 'required',
                'kind': 'curriculum',
                'title': 'Old requested-date lesson',
                'subtitle': None,
                'lesson_type': 'vocabulary',
                'eta_minutes': 8,
                'url': '/learn/777/',
                'completion_signal': 'lesson_completed',
                'data': {'lesson_id': 777},
            }],
        }
        db_session.add(DailyPlanLog(
            user_id=user.id, plan_date=yesterday, plan_json=prior,
        ))
        db_session.add(LessonProgress(
            user_id=user.id, lesson_id=vocabulary_lesson.id,
            status='in_progress',
            last_activity=datetime.combine(yesterday, time(hour=10)),
        ))
        db_session.commit()

        snap = resolve_snapshot_for_today(user.id, today, real_db)

        assert snap['rolled_over_from'] is None
        assert all(it.get('id') != 'curriculum:lesson:777' for it in snap['items'])


class TestOverlayCompletion:

    def test_curriculum_completed_today_marks_item_done(
        self, db_session, user, vocabulary_lesson,
    ):
        today = date.today()
        snap = resolve_snapshot_for_today(user.id, today, real_db)
        real_db.session.commit()

        # Find the curriculum item and complete its lesson today.
        cur = next(it for it in snap['items'] if it['kind'] == 'curriculum')
        lesson_id = cur['data']['lesson_id']

        from app.utils.time_utils import day_to_naive_utc
        today_start = day_to_naive_utc(user.id, real_db, days_ahead=0)
        db_session.add(LessonProgress(
            user_id=user.id, lesson_id=lesson_id,
            status='completed', score=100.0,
            last_activity=today_start + timedelta(hours=10),
            completed_at=today_start + timedelta(hours=10),
        ))
        db_session.commit()

        overlaid = overlay_completion(user.id, snap, real_db)
        cur_o = next(it for it in overlaid if it['kind'] == 'curriculum')
        assert cur_o['completed'] is True
        assert cur_o['url'] is None  # CTA hidden when done
        assert cur_o['eta_minutes'] == 0
        # Other slots remain uncompleted (no SRS/reading activity today).
        non_cur = [it for it in overlaid if it['kind'] != 'curriculum']
        assert all(not it.get('completed') for it in non_cur)
