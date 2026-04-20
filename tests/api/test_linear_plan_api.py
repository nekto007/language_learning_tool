"""Integration tests for linear mode in /api/daily-plan and /api/daily-status.

Covers Task 11 acceptance:
- /api/daily-plan returns the linear payload shape when ``_plan_meta.effective_mode == 'linear'``
  (mode / position / progress / baseline_slots / continuation / day_secured)
- /api/daily-status recomputes ``day_secured`` from baseline-slot activity
- When all baseline slots are completed the endpoint writes a DailyPlanLog
  row with ``mission_type=NULL`` and auto-emits ``minimum_completed``
- The error_review slot gates day_secured when triggered
- Mission (phases) flow is preserved — backward compat
"""
from __future__ import annotations

from datetime import date
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
    """Build a representative linear-plan payload for API tests."""
    baseline_slots = [
        {
            'kind': 'curriculum',
            'title': 'B1 · M5 · L3 (card)',
            'lesson_type': 'card',
            'eta_minutes': 8,
            'url': '/curriculum_lessons/101?from=linear_plan',
            'completed': curriculum_done,
        },
        {
            'kind': 'srs',
            'title': 'Карточки на повторение',
            'eta_minutes': 5,
            'url': '/study?source=linear_plan',
            'completed': srs_done,
        },
        {
            'kind': 'reading',
            'title': 'Чтение книги',
            'eta_minutes': 10,
            'url': '/books/7/read',
            'completed': reading_done,
        },
    ]
    if include_error_review:
        baseline_slots.append({
            'kind': 'error_review',
            'title': 'Разбор ошибок',
            'eta_minutes': 6,
            'url': '/curriculum_lessons/error_review?source=linear_plan',
            'completed': error_review_done,
        })

    return {
        'mode': 'linear',
        'position': {
            'lesson_id': 101,
            'lesson_type': 'card',
            'lesson_number': 3,
            'module_id': 50,
            'module_number': 5,
            'level_code': 'B1',
        },
        'progress': {
            'level': 'B1',
            'percent': 20,
            'lessons_remaining_in_level': 60,
        },
        'baseline_slots': baseline_slots,
        'continuation': {
            'available': False,
            'next_lessons': [],
        },
        # Assembler always returns False — the API recomputes it.
        'day_secured': False,
        '_plan_meta': {
            'mission_plan_enabled': False,
            'effective_mode': 'linear',
            'fallback_reason': None,
        },
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


# ── /api/daily-plan ───────────────────────────────────────────────────


class TestDailyPlanApiLinearShape:
    def test_linear_payload_exposes_linear_fields(self, authenticated_client):
        plan = _linear_plan()
        with patch(
            'app.daily_plan.service.get_daily_plan_unified', return_value=plan,
        ):
            response = authenticated_client.get('/api/daily-plan')

        assert response.status_code == 200
        data = response.get_json()
        assert data['success'] is True
        assert data['mode'] == 'linear'
        assert data['position']['level_code'] == 'B1'
        assert data['progress']['level'] == 'B1'
        assert {s['kind'] for s in data['baseline_slots']} == {
            'curriculum', 'srs', 'reading',
        }
        assert data['continuation']['available'] is False
        assert data['day_secured'] is False
        # route_state is still included but reports no steps for linear.
        assert 'route_state' in data

    def test_linear_day_secured_false_when_no_activity(self, authenticated_client):
        plan = _linear_plan()
        with patch(
            'app.daily_plan.service.get_daily_plan_unified', return_value=plan,
        ), patch(
            'app.telegram.queries.get_daily_summary', return_value=_empty_summary(),
        ):
            response = authenticated_client.get('/api/daily-plan')

        assert response.status_code == 200
        assert response.get_json()['day_secured'] is False

    def test_linear_day_secured_true_when_slots_completed(self, authenticated_client):
        plan = _linear_plan(curriculum_done=True, srs_done=True, reading_done=True)
        with patch(
            'app.daily_plan.service.get_daily_plan_unified', return_value=plan,
        ), patch(
            'app.telegram.queries.get_daily_summary', return_value=_empty_summary(),
        ):
            response = authenticated_client.get('/api/daily-plan')

        assert response.status_code == 200
        data = response.get_json()
        assert data['day_secured'] is True

    def test_linear_day_secured_true_via_summary_signals(self, authenticated_client):
        # Reading has no summary fallback (see streak_service), so the
        # plan's reading slot must report completed=True for this scenario.
        plan = _linear_plan(reading_done=True)
        summary = {
            **_empty_summary(),
            'lessons_count': 1,
            'words_reviewed': 10,
            'srs_words_reviewed': 10,
            'srs_review_reviewed': 10,
            'books_read': ['Book A'],
        }
        with patch(
            'app.daily_plan.service.get_daily_plan_unified', return_value=plan,
        ), patch(
            'app.telegram.queries.get_daily_summary', return_value=summary,
        ):
            response = authenticated_client.get('/api/daily-plan')

        assert response.status_code == 200
        assert response.get_json()['day_secured'] is True

    def test_error_review_slot_blocks_day_secured(self, authenticated_client):
        plan = _linear_plan(
            curriculum_done=True,
            srs_done=True,
            reading_done=True,
            include_error_review=True,
            error_review_done=False,
        )
        # Summary mirrors the completed slots so they stay True, but
        # error_review has no summary signal → remains incomplete.
        summary = {
            **_empty_summary(),
            'lessons_count': 1,
            'words_reviewed': 5,
            'srs_words_reviewed': 5,
            'srs_review_reviewed': 5,
            'books_read': ['Book A'],
        }
        with patch(
            'app.daily_plan.service.get_daily_plan_unified', return_value=plan,
        ), patch(
            'app.telegram.queries.get_daily_summary', return_value=summary,
        ):
            response = authenticated_client.get('/api/daily-plan')

        assert response.status_code == 200
        data = response.get_json()
        assert {s['kind'] for s in data['baseline_slots']} == {
            'curriculum', 'srs', 'reading', 'error_review',
        }
        assert data['day_secured'] is False

    def test_error_review_slot_completed_secures_day(self, authenticated_client):
        plan = _linear_plan(
            curriculum_done=True,
            srs_done=True,
            reading_done=True,
            include_error_review=True,
            error_review_done=True,
        )
        summary = {
            **_empty_summary(),
            'lessons_count': 1,
            'words_reviewed': 5,
            'srs_words_reviewed': 5,
            'srs_review_reviewed': 5,
            'books_read': ['Book A'],
        }
        with patch(
            'app.daily_plan.service.get_daily_plan_unified', return_value=plan,
        ), patch(
            'app.telegram.queries.get_daily_summary', return_value=summary,
        ):
            response = authenticated_client.get('/api/daily-plan')

        assert response.status_code == 200
        assert response.get_json()['day_secured'] is True


# ── Backward compatibility for mission / legacy ──────────────────────


class TestDailyPlanApiBackwardCompat:
    def test_mission_payload_shape_preserved(self, authenticated_client):
        """Mission plans keep the old ``phases``/``mission`` shape."""
        mission_plan = {
            'next_lesson': None,
            'grammar_topic': None,
            'words_due': 0,
            'has_any_words': False,
            'book_to_read': None,
            'suggested_books': [],
            'book_course_lesson': None,
            'book_course_done_today': False,
            'onboarding': None,
            'bonus': [],
            'mission': {
                'type': 'progress',
                'title': 'X',
                'reason_code': 'r',
                'reason_text': 't',
            },
            'phases': [
                {
                    'id': 'p1',
                    'phase': 'recall',
                    'title': 'Разогрев',
                    'mode': 'srs_review',
                    'required': True,
                    'completed': False,
                },
            ],
            '_plan_meta': {
                'mission_plan_enabled': True,
                'effective_mode': 'mission',
                'fallback_reason': None,
            },
        }
        with patch(
            'app.daily_plan.service.get_daily_plan_unified', return_value=mission_plan,
        ), patch(
            'app.telegram.queries.get_daily_summary', return_value=_empty_summary(),
        ):
            response = authenticated_client.get('/api/daily-plan')

        assert response.status_code == 200
        data = response.get_json()
        # Mission shape remains untouched — no linear-only keys leak in.
        assert data.get('mode') is None or data.get('mode') != 'linear'
        assert data.get('baseline_slots') is None
        assert data.get('phases') is not None
        assert data.get('mission', {}).get('type') == 'progress'

    def test_legacy_payload_shape_preserved(self, authenticated_client):
        """Legacy flat payload is returned as-is."""
        legacy_plan = {
            'next_lesson': None,
            'grammar_topic': None,
            'words_due': 0,
            'has_any_words': False,
            'book_to_read': None,
            'suggested_books': [],
            'book_course_lesson': None,
            'book_course_done_today': False,
            'onboarding': None,
            'bonus': [],
            'mission': None,
            '_plan_meta': {
                'mission_plan_enabled': False,
                'effective_mode': 'legacy',
                'fallback_reason': None,
            },
        }
        with patch(
            'app.daily_plan.service.get_daily_plan_unified', return_value=legacy_plan,
        ):
            response = authenticated_client.get('/api/daily-plan')

        assert response.status_code == 200
        data = response.get_json()
        assert data.get('mode') is None
        assert data.get('baseline_slots') is None
        assert 'next_lesson' in data


# ── /api/daily-status ─────────────────────────────────────────────────


class TestDailyStatusApiLinear:
    def test_linear_status_returns_day_secured_false(self, authenticated_client):
        plan = _linear_plan()
        with patch(
            'app.daily_plan.service.get_daily_plan_unified', return_value=plan,
        ), patch(
            'app.telegram.queries.get_daily_summary', return_value=_empty_summary(),
        ), patch(
            'app.telegram.queries.get_yesterday_summary', return_value={},
        ), patch(
            'app.achievements.streak_service.process_streak_on_activity',
            return_value={
                'streak_status': {'streak': 0, 'has_activity_today': False},
                'required_steps': 3,
                'streak_repaired': False,
            },
        ):
            response = authenticated_client.get('/api/daily-status')

        assert response.status_code == 200
        data = response.get_json()
        assert data['success'] is True
        assert data['day_secured'] is False
        assert data['plan']['mode'] == 'linear'

    def test_linear_status_day_secured_true_and_writes_log(
        self, authenticated_client, db_session, test_user,
    ):
        plan = _linear_plan(curriculum_done=True, srs_done=True, reading_done=True)
        summary = {
            **_empty_summary(),
            'lessons_count': 1,
            'words_reviewed': 8,
            'srs_words_reviewed': 8,
            'srs_review_reviewed': 8,
            'books_read': ['Book A'],
        }
        with patch(
            'app.daily_plan.service.get_daily_plan_unified', return_value=plan,
        ), patch(
            'app.telegram.queries.get_daily_summary', return_value=summary,
        ), patch(
            'app.telegram.queries.get_yesterday_summary', return_value={},
        ), patch(
            'app.achievements.streak_service.process_streak_on_activity',
            return_value={
                'streak_status': {'streak': 0, 'has_activity_today': True},
                'required_steps': 3,
                'streak_repaired': False,
            },
        ):
            response = authenticated_client.get('/api/daily-status')

        assert response.status_code == 200
        data = response.get_json()
        assert data['day_secured'] is True
        assert data['plan_completion'] == {
            'curriculum': True,
            'srs': True,
            'reading': True,
        }

        # DailyPlanLog is written with mission_type=NULL for linear.
        log = DailyPlanLog.query.filter_by(user_id=test_user.id).first()
        assert log is not None
        assert log.mission_type is None
        assert log.secured_at is not None

        # minimum_completed is emitted with mission_type=None.
        ev = DailyPlanEvent.query.filter_by(
            user_id=test_user.id, event_type='minimum_completed',
        ).first()
        assert ev is not None
        assert ev.mission_type is None

    def test_linear_status_error_review_gates_day_secured(self, authenticated_client):
        plan = _linear_plan(
            curriculum_done=True,
            srs_done=True,
            reading_done=True,
            include_error_review=True,
            error_review_done=False,
        )
        summary = {
            **_empty_summary(),
            'lessons_count': 1,
            'words_reviewed': 5,
            'srs_words_reviewed': 5,
            'srs_review_reviewed': 5,
            'books_read': ['Book A'],
        }
        with patch(
            'app.daily_plan.service.get_daily_plan_unified', return_value=plan,
        ), patch(
            'app.telegram.queries.get_daily_summary', return_value=summary,
        ), patch(
            'app.telegram.queries.get_yesterday_summary', return_value={},
        ), patch(
            'app.achievements.streak_service.process_streak_on_activity',
            return_value={
                'streak_status': {'streak': 0, 'has_activity_today': True},
                'required_steps': 4,
                'streak_repaired': False,
            },
        ):
            response = authenticated_client.get('/api/daily-status')

        assert response.status_code == 200
        data = response.get_json()
        assert data['day_secured'] is False
        assert data['plan_completion']['error_review'] is False


class TestDailyStatusApiMissionBackwardCompat:
    def test_mission_status_shape_preserved(self, authenticated_client):
        mission_plan = {
            'next_lesson': None,
            'grammar_topic': None,
            'words_due': 0,
            'has_any_words': False,
            'book_to_read': None,
            'suggested_books': [],
            'book_course_lesson': None,
            'book_course_done_today': False,
            'onboarding': None,
            'bonus': [],
            'mission': {
                'type': 'progress',
                'title': 'X',
                'reason_code': 'r',
                'reason_text': 't',
            },
            'phases': [
                {
                    'id': 'p1',
                    'phase': 'recall',
                    'title': 'Разогрев',
                    'mode': 'srs_review',
                    'required': True,
                    'completed': False,
                },
            ],
            'day_secured': False,
            '_plan_meta': {
                'mission_plan_enabled': True,
                'effective_mode': 'mission',
                'fallback_reason': None,
            },
        }
        with patch(
            'app.daily_plan.service.get_daily_plan_unified', return_value=mission_plan,
        ), patch(
            'app.telegram.queries.get_daily_summary', return_value=_empty_summary(),
        ), patch(
            'app.telegram.queries.get_yesterday_summary', return_value={},
        ), patch(
            'app.achievements.streak_service.process_streak_on_activity',
            return_value={
                'streak_status': {'streak': 0, 'has_activity_today': False},
                'required_steps': 1,
                'streak_repaired': False,
            },
        ):
            response = authenticated_client.get('/api/daily-status')

        assert response.status_code == 200
        data = response.get_json()
        assert data['success'] is True
        assert data['day_secured'] is False
        assert data['plan'].get('mode') is None or data['plan'].get('mode') != 'linear'
        assert data['plan'].get('phases') is not None
        assert data['plan'].get('baseline_slots') is None
