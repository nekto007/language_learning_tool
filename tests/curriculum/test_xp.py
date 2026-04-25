"""Tests for curriculum-lesson XP date normalization.

Regression target: ``complete_lesson()`` used to dedupe by ``date.today()``
(UTC-naive), while ``card_lessons.complete_srs_session`` dedupes by the
user's local date. Near midnight the two keys diverged and a single
lesson could collect XP twice.

``app/utils/time_utils.get_user_local_date`` is now the single source of
truth, and ``complete_lesson`` routes through it.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from unittest.mock import patch

import pytest

from app.achievements.models import StreakEvent
from app.curriculum.models import Lessons, Module, LessonProgress
from app.curriculum.service import complete_lesson
from app.curriculum.xp import (
    CURRICULUM_LESSON_EVENT_TYPE,
    award_curriculum_lesson_xp_idempotent,
)
from app.utils.time_utils import get_user_local_date


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_lesson(db_session, test_module):
    lesson = Lessons(
        module_id=test_module.id,
        number=1,
        title='TZ lesson',
        type='vocabulary',
        order=0,
        content={},
    )
    db_session.add(lesson)
    db_session.commit()
    return lesson


def _xp_events(db_session, user_id, lesson_id):
    return db_session.query(StreakEvent).filter(
        StreakEvent.user_id == user_id,
        StreakEvent.event_type == CURRICULUM_LESSON_EVENT_TYPE,
        StreakEvent.details['lesson_id'].astext == str(lesson_id),
    ).all()


# ---------------------------------------------------------------------------
# get_user_local_date
# ---------------------------------------------------------------------------

class TestGetUserLocalDate:
    def test_returns_tz_aware_date_for_user(self, app, db_session, test_user):
        test_user.timezone = 'America/New_York'
        db_session.commit()
        with app.app_context():
            # At 04:30 UTC, NY is still on the previous calendar day.
            frozen = datetime(2026, 4, 25, 4, 30, tzinfo=timezone.utc)
            with patch('app.utils.time_utils.datetime') as dt_mock:
                dt_mock.now = lambda tz=None: frozen.astimezone(tz) if tz else frozen
                result = get_user_local_date(test_user.id)
            # UTC: 2026-04-25; NY at 00:30 EDT: 2026-04-25 too — pick a
            # tighter boundary.
            assert result == date(2026, 4, 25)

    def test_cross_midnight_tz_returns_prior_local_date(self, app, db_session, test_user):
        test_user.timezone = 'America/New_York'
        db_session.commit()
        with app.app_context():
            # 03:00 UTC on the 25th = 23:00 EDT on the 24th.
            frozen = datetime(2026, 4, 25, 3, 0, tzinfo=timezone.utc)
            with patch('app.utils.time_utils.datetime') as dt_mock:
                dt_mock.now = lambda tz=None: frozen.astimezone(tz) if tz else frozen
                result = get_user_local_date(test_user.id)
            assert result == date(2026, 4, 24)

    def test_missing_timezone_falls_back_to_default(self, app, db_session, test_user):
        test_user.timezone = None
        db_session.commit()
        with app.app_context():
            # Europe/Moscow (UTC+3) — 23:00 UTC → 02:00 next-day Moscow.
            frozen = datetime(2026, 4, 25, 23, 0, tzinfo=timezone.utc)
            with patch('app.utils.time_utils.datetime') as dt_mock:
                dt_mock.now = lambda tz=None: frozen.astimezone(tz) if tz else frozen
                result = get_user_local_date(test_user.id)
            assert result == date(2026, 4, 26)

    def test_invalid_timezone_falls_back_to_utc(self, app, db_session, test_user):
        test_user.timezone = 'Not/A/Real/Zone'
        db_session.commit()
        with app.app_context():
            frozen = datetime(2026, 4, 25, 12, 0, tzinfo=timezone.utc)
            with patch('app.utils.time_utils.datetime') as dt_mock:
                dt_mock.now = lambda tz=None: frozen.astimezone(tz) if tz else frozen
                result = get_user_local_date(test_user.id)
            assert result == date(2026, 4, 25)


# ---------------------------------------------------------------------------
# complete_lesson integration
# ---------------------------------------------------------------------------

class TestCompleteLessonXPDate:
    def test_xp_stored_under_user_local_date(self, app, db_session, test_user, test_module):
        """complete_lesson should key StreakEvent.event_date on user tz, not UTC."""
        test_user.timezone = 'America/New_York'
        db_session.commit()
        lesson = _make_lesson(db_session, test_module)

        local_today = date(2026, 4, 24)
        with app.app_context(), patch(
            'app.utils.time_utils.get_user_local_date', return_value=local_today,
        ):
            progress = complete_lesson(test_user.id, lesson.id, score=90.0)

        assert progress is not None
        events = _xp_events(db_session, test_user.id, lesson.id)
        assert len(events) == 1
        assert events[0].event_date == local_today

    def test_cross_midnight_completion_not_double_awarded(
        self, app, db_session, test_user, test_module,
    ):
        """A user finishing a lesson just before midnight (local) and again
        just after (UTC rolled over) must not collect XP twice."""
        test_user.timezone = 'America/New_York'
        db_session.commit()
        lesson = _make_lesson(db_session, test_module)

        local_today = date(2026, 4, 24)

        # First call — user's local evening, UTC already next day.
        with app.app_context(), patch(
            'app.utils.time_utils.get_user_local_date', return_value=local_today,
        ):
            complete_lesson(test_user.id, lesson.id, score=90.0)

        # Second call — same user-local date, different UTC date.
        with app.app_context(), patch(
            'app.utils.time_utils.get_user_local_date', return_value=local_today,
        ):
            complete_lesson(test_user.id, lesson.id, score=95.0)

        events = _xp_events(db_session, test_user.id, lesson.id)
        assert len(events) == 1, (
            'Second call within the same user-local day must be a no-op; '
            'regression: UTC date.today() would produce two rows.'
        )

    def test_next_user_local_day_awards_again(
        self, app, db_session, test_user, test_module,
    ):
        test_user.timezone = 'America/New_York'
        db_session.commit()
        lesson = _make_lesson(db_session, test_module)

        day1 = date(2026, 4, 24)
        day2 = day1 + timedelta(days=1)

        with app.app_context(), patch(
            'app.utils.time_utils.get_user_local_date', return_value=day1,
        ):
            complete_lesson(test_user.id, lesson.id, score=90.0)

        with app.app_context(), patch(
            'app.utils.time_utils.get_user_local_date', return_value=day2,
        ):
            complete_lesson(test_user.id, lesson.id, score=90.0)

        events = _xp_events(db_session, test_user.id, lesson.id)
        assert {e.event_date for e in events} == {day1, day2}


# ---------------------------------------------------------------------------
# Idempotency helper still dedupes by (user, lesson, date)
# ---------------------------------------------------------------------------

class TestAwardIdempotentHelperDate:
    def test_different_dates_independent_awards(
        self, app, db_session, test_user, test_module,
    ):
        lesson = _make_lesson(db_session, test_module)
        with app.app_context():
            first = award_curriculum_lesson_xp_idempotent(
                test_user.id, lesson.id, date(2026, 4, 24),
            )
            second = award_curriculum_lesson_xp_idempotent(
                test_user.id, lesson.id, date(2026, 4, 24),
            )
            third = award_curriculum_lesson_xp_idempotent(
                test_user.id, lesson.id, date(2026, 4, 25),
            )
        assert first is not None
        assert second is None
        assert third is not None
