"""Integration tests for GET /api/daily-plan/next-slot.

The endpoint powers the plan-aware completion-screen CTA: after a user
finishes a baseline slot, the frontend asks the API which slot to surface
next. Covers:

- ``use_linear_plan=False`` → 404 (gating stale plan-context URLs from
  Telegram links etc).
- ``current=curriculum`` with three incomplete slots → returns ``srs``
  (skips the current kind even if still incomplete).
- ``current`` omitted → returns the first baseline slot.
- Reading slot kind → serialises as ``book`` in the response (matches the
  query-param format surfaced in URLs and sessionStorage).
- All baseline slots done → ``next=null``, ``day_secured=true``; the
  first call writes ``DailyPlanLog.secured_at`` and returns
  ``secured_just_now=true``; the second call on the same day returns
  ``secured_just_now=false``.
- ``secured_at`` already written (by /api/daily-status) before this call
  → ``secured_just_now=false`` on the very first next-slot call.
"""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import patch

import pytest

from app.daily_plan.models import DailyPlanEvent, DailyPlanLog


def _linear_plan(
    *,
    curriculum_done: bool = False,
    srs_done: bool = False,
    reading_done: bool = False,
    include_error_review: bool = False,
    error_review_done: bool = False,
) -> dict:
    """Build a canonical linear-plan payload for these tests."""
    baseline_slots = [
        {
            'kind': 'curriculum',
            'title': 'B1 · M5 · L3 (card)',
            'lesson_type': 'card',
            'eta_minutes': 8,
            'url': '/learn/101/?source=linear_plan_card&from=linear_plan&slot=curriculum',
            'completed': curriculum_done,
            'data': {},
        },
        {
            'kind': 'srs',
            'title': 'Карточки на повторение',
            'lesson_type': None,
            'eta_minutes': 5,
            'url': '/study?source=linear_plan&from=linear_plan&slot=srs',
            'completed': srs_done,
            'data': {},
        },
        {
            'kind': 'reading',
            'title': 'The Great Gatsby',
            'lesson_type': None,
            'eta_minutes': 10,
            'url': '/read/7?from=linear_plan&slot=book',
            'completed': reading_done,
            'data': {},
        },
    ]
    if include_error_review:
        baseline_slots.append({
            'kind': 'error_review',
            'title': 'Разбор ошибок',
            'lesson_type': None,
            'eta_minutes': 6,
            'url': '/curriculum_lessons/error_review?from=linear_plan&slot=error_review',
            'completed': error_review_done,
            'data': {},
        })
    return {
        'mode': 'linear',
        'position': None,
        'progress': {'level': 'B1', 'percent': 20, 'lessons_remaining_in_level': 60},
        'baseline_slots': baseline_slots,
        'continuation': {'available': False, 'next_lessons': []},
        'day_secured': False,
    }


def _empty_summary() -> dict:
    return {
        'lessons_count': 0,
        'lesson_types': [],
        'words_reviewed': 0,
        'srs_words_reviewed': 0,
        'srs_new_reviewed': 0,
        'srs_review_reviewed': 0,
        'grammar_exercises': 0,
        'grammar_correct': 0,
        'books_read': [],
        'book_course_lessons_today': 0,
    }


def _all_done_summary() -> dict:
    return {
        **_empty_summary(),
        'lessons_count': 1,
        'srs_review_reviewed': 5,
        'srs_words_reviewed': 5,
        'words_reviewed': 5,
        'books_read': ['Book A'],
    }


@pytest.fixture
def linear_user(db_session, test_user):
    """Flip the linear-plan flag on for the authenticated test user."""
    test_user.use_linear_plan = True
    db_session.commit()
    return test_user


# ── Gating ────────────────────────────────────────────────────────────


class TestNextSlotGating:
    def test_returns_404_when_linear_plan_disabled(self, authenticated_client, test_user):
        # test_user.use_linear_plan defaults to False — no flip here.
        response = authenticated_client.get('/api/daily-plan/next-slot')

        assert response.status_code == 404
        data = response.get_json()
        assert data['success'] is False
        assert data.get('error') == 'linear_plan_disabled'

    def test_returns_401_for_anonymous(self, client):
        response = client.get('/api/daily-plan/next-slot')
        assert response.status_code == 401


# ── Picking the next slot ─────────────────────────────────────────────


class TestNextSlotSelection:
    def test_current_curriculum_all_incomplete_returns_srs(
        self, authenticated_client, linear_user,
    ):
        plan = _linear_plan()
        with patch(
            'app.daily_plan.linear.plan.get_linear_plan', return_value=plan,
        ), patch(
            'app.telegram.queries.get_daily_summary', return_value=_empty_summary(),
        ):
            response = authenticated_client.get(
                '/api/daily-plan/next-slot?current=curriculum'
            )

        assert response.status_code == 200
        data = response.get_json()
        assert data['success'] is True
        assert data['day_secured'] is False
        assert data['secured_just_now'] is False
        assert data['next']['kind'] == 'srs'
        assert data['next']['url'].startswith('/study')
        assert data['next']['title'] == 'Карточки на повторение'

    def test_no_current_param_returns_first_slot(
        self, authenticated_client, linear_user,
    ):
        plan = _linear_plan()
        with patch(
            'app.daily_plan.linear.plan.get_linear_plan', return_value=plan,
        ), patch(
            'app.telegram.queries.get_daily_summary', return_value=_empty_summary(),
        ):
            response = authenticated_client.get('/api/daily-plan/next-slot')

        assert response.status_code == 200
        data = response.get_json()
        assert data['next']['kind'] == 'curriculum'

    def test_reading_slot_serialised_as_book(
        self, authenticated_client, linear_user,
    ):
        plan = _linear_plan(curriculum_done=True, srs_done=True)
        with patch(
            'app.daily_plan.linear.plan.get_linear_plan', return_value=plan,
        ), patch(
            'app.telegram.queries.get_daily_summary', return_value=_empty_summary(),
        ):
            response = authenticated_client.get('/api/daily-plan/next-slot?current=srs')

        assert response.status_code == 200
        data = response.get_json()
        # Internal slot.kind='reading' → exposed as query-param form 'book'.
        assert data['next']['kind'] == 'book'
        assert data['next']['title'] == 'The Great Gatsby'

    def test_current_book_maps_to_reading_and_is_skipped(
        self, authenticated_client, linear_user,
    ):
        plan = _linear_plan(curriculum_done=True, srs_done=True)
        # Reading slot incomplete, but caller says they are currently
        # finishing it → the endpoint should return the next incomplete
        # slot excluding reading. No more slots remain beyond reading in
        # the base payload, so ``next`` is null while ``day_secured`` is
        # still False (reading is not counted as done).
        with patch(
            'app.daily_plan.linear.plan.get_linear_plan', return_value=plan,
        ), patch(
            'app.telegram.queries.get_daily_summary', return_value=_empty_summary(),
        ):
            response = authenticated_client.get('/api/daily-plan/next-slot?current=book')

        assert response.status_code == 200
        data = response.get_json()
        assert data['next'] is None
        assert data['day_secured'] is False

    def test_error_review_slot_picked_when_present(
        self, authenticated_client, linear_user,
    ):
        plan = _linear_plan(
            curriculum_done=True, srs_done=True, reading_done=True,
            include_error_review=True, error_review_done=False,
        )
        summary = _all_done_summary()
        with patch(
            'app.daily_plan.linear.plan.get_linear_plan', return_value=plan,
        ), patch(
            'app.telegram.queries.get_daily_summary', return_value=summary,
        ):
            response = authenticated_client.get('/api/daily-plan/next-slot?current=book')

        assert response.status_code == 200
        data = response.get_json()
        assert data['next']['kind'] == 'error_review'
        assert data['day_secured'] is False

    def test_unknown_current_param_ignored(
        self, authenticated_client, linear_user,
    ):
        # A stale/unknown ``current`` value should not silently hide the
        # first slot — we just fall through and return the first
        # incomplete slot (curriculum here).
        plan = _linear_plan()
        with patch(
            'app.daily_plan.linear.plan.get_linear_plan', return_value=plan,
        ), patch(
            'app.telegram.queries.get_daily_summary', return_value=_empty_summary(),
        ):
            response = authenticated_client.get(
                '/api/daily-plan/next-slot?current=totally_bogus'
            )

        assert response.status_code == 200
        assert response.get_json()['next']['kind'] == 'curriculum'


# ── Day-secured transitions ──────────────────────────────────────────


class TestNextSlotDaySecured:
    def test_all_done_first_call_writes_secured_at(
        self, authenticated_client, linear_user, db_session,
    ):
        plan = _linear_plan(curriculum_done=True, srs_done=True, reading_done=True)
        with patch(
            'app.daily_plan.linear.plan.get_linear_plan', return_value=plan,
        ), patch(
            'app.telegram.queries.get_daily_summary', return_value=_all_done_summary(),
        ):
            response = authenticated_client.get(
                '/api/daily-plan/next-slot?current=book'
            )

        assert response.status_code == 200
        data = response.get_json()
        assert data['next'] is None
        assert data['day_secured'] is True
        assert data['secured_just_now'] is True

        log = DailyPlanLog.query.filter_by(user_id=linear_user.id).first()
        assert log is not None
        assert log.secured_at is not None
        assert log.mission_type is None

        ev = DailyPlanEvent.query.filter_by(
            user_id=linear_user.id, event_type='minimum_completed',
        ).first()
        assert ev is not None
        assert ev.mission_type is None

    def test_second_call_same_day_returns_secured_just_now_false(
        self, authenticated_client, linear_user, db_session,
    ):
        plan = _linear_plan(curriculum_done=True, srs_done=True, reading_done=True)
        with patch(
            'app.daily_plan.linear.plan.get_linear_plan', return_value=plan,
        ), patch(
            'app.telegram.queries.get_daily_summary', return_value=_all_done_summary(),
        ):
            first = authenticated_client.get('/api/daily-plan/next-slot')
            second = authenticated_client.get('/api/daily-plan/next-slot')

        assert first.status_code == 200
        assert first.get_json()['secured_just_now'] is True

        assert second.status_code == 200
        second_data = second.get_json()
        assert second_data['day_secured'] is True
        assert second_data['secured_just_now'] is False
        assert second_data['next'] is None

        # Only one DailyPlanLog row exists — write_secured_at is idempotent.
        logs = DailyPlanLog.query.filter_by(user_id=linear_user.id).all()
        assert len(logs) == 1

    def test_secured_at_already_written_returns_just_now_false(
        self, authenticated_client, linear_user, db_session,
    ):
        # Simulate /api/daily-status having written secured_at earlier in
        # the day. The next-slot call must not claim it just secured the
        # day — otherwise the UI would flash the "day saved" overlay twice.
        import pytz
        from app.daily_plan.models import DailyPlanLog
        from config.settings import DEFAULT_TIMEZONE

        tz_obj = pytz.timezone(DEFAULT_TIMEZONE)
        today = datetime.now(tz_obj).date()
        existing = DailyPlanLog(
            user_id=linear_user.id,
            plan_date=today,
            mission_type=None,
            secured_at=datetime.now(timezone.utc),
        )
        db_session.add(existing)
        db_session.commit()

        plan = _linear_plan(curriculum_done=True, srs_done=True, reading_done=True)
        with patch(
            'app.daily_plan.linear.plan.get_linear_plan', return_value=plan,
        ), patch(
            'app.telegram.queries.get_daily_summary', return_value=_all_done_summary(),
        ):
            response = authenticated_client.get('/api/daily-plan/next-slot')

        assert response.status_code == 200
        data = response.get_json()
        assert data['day_secured'] is True
        assert data['secured_just_now'] is False

    def test_not_secured_does_not_write_log(
        self, authenticated_client, linear_user, db_session,
    ):
        plan = _linear_plan()
        with patch(
            'app.daily_plan.linear.plan.get_linear_plan', return_value=plan,
        ), patch(
            'app.telegram.queries.get_daily_summary', return_value=_empty_summary(),
        ):
            response = authenticated_client.get('/api/daily-plan/next-slot')

        assert response.status_code == 200
        assert response.get_json()['day_secured'] is False

        log = DailyPlanLog.query.filter_by(user_id=linear_user.id).first()
        assert log is None
