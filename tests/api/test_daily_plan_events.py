"""Tests for Phase 1 tracking: daily plan event emission endpoints.

Covers:
- POST /api/daily-plan/events records client-side events
- Invalid event_type returns 400
- Non-JSON request returns 400
- Unauthenticated request returns 401
- emit_minimum_completed helper is idempotent
- minimum_completed auto-emitted on daily-status when day_secured=True
- minimum_completed NOT emitted when day_secured=False
"""
import pytest
from datetime import date, datetime, timezone
from unittest.mock import patch, MagicMock


MOCK_PLAN_SECURED = {
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
    'mission': {'type': 'progress', 'title': 'X', 'reason_code': 'r', 'reason_text': 't'},
    'day_secured': True,
}

MOCK_PLAN_UNSECURED = {**MOCK_PLAN_SECURED, 'day_secured': False}


# ---------------------------------------------------------------------------
# POST /api/daily-plan/events
# ---------------------------------------------------------------------------

def test_record_next_step_shown(authenticated_client, db_session):
    """next_step_shown event is stored and returns 200."""
    payload = {
        'event_type': 'next_step_shown',
        'step_kind': 'srs_review',
        'reason_text': 'You have 12 cards due',
    }
    response = authenticated_client.post(
        '/api/daily-plan/events',
        json=payload,
        content_type='application/json',
    )
    assert response.status_code == 200
    data = response.get_json()
    assert data['success'] is True
    assert data['event_type'] == 'next_step_shown'


def test_record_next_step_accepted(authenticated_client, db_session):
    payload = {'event_type': 'next_step_accepted', 'step_kind': 'grammar_practice'}
    response = authenticated_client.post('/api/daily-plan/events', json=payload)
    assert response.status_code == 200
    assert response.get_json()['event_type'] == 'next_step_accepted'


def test_record_next_step_dismissed(authenticated_client, db_session):
    payload = {'event_type': 'next_step_dismissed'}
    response = authenticated_client.post('/api/daily-plan/events', json=payload)
    assert response.status_code == 200
    assert response.get_json()['event_type'] == 'next_step_dismissed'


def test_record_session_ended_at_minimum(authenticated_client, db_session):
    payload = {'event_type': 'session_ended_at_minimum', 'plan_date': '2026-04-18'}
    response = authenticated_client.post('/api/daily-plan/events', json=payload)
    assert response.status_code == 200
    assert response.get_json()['event_type'] == 'session_ended_at_minimum'


def test_record_event_invalid_type(authenticated_client):
    """Unknown event_type returns 400."""
    response = authenticated_client.post(
        '/api/daily-plan/events',
        json={'event_type': 'minimum_completed'},  # server-only, not client-callable
    )
    assert response.status_code == 400
    data = response.get_json()
    assert data['success'] is False


def test_record_event_unknown_type(authenticated_client):
    """Completely unknown event_type returns 400."""
    response = authenticated_client.post(
        '/api/daily-plan/events',
        json={'event_type': 'bogus_event'},
    )
    assert response.status_code == 400


def test_record_event_non_json(authenticated_client):
    """Non-JSON body returns 400."""
    response = authenticated_client.post(
        '/api/daily-plan/events',
        data='event_type=next_step_shown',
        content_type='application/x-www-form-urlencoded',
    )
    assert response.status_code == 400


def test_record_event_unauthenticated(client):
    """Unauthenticated request returns 401."""
    response = client.post(
        '/api/daily-plan/events',
        json={'event_type': 'next_step_shown'},
    )
    assert response.status_code == 401


def test_record_event_with_invalid_plan_date(authenticated_client, db_session):
    """Invalid plan_date is silently ignored (treated as None)."""
    payload = {
        'event_type': 'next_step_dismissed',
        'plan_date': 'not-a-date',
    }
    response = authenticated_client.post('/api/daily-plan/events', json=payload)
    assert response.status_code == 200


def test_reason_text_truncated(authenticated_client, db_session, test_user):
    """reason_text longer than 500 chars is silently truncated."""
    payload = {
        'event_type': 'next_step_shown',
        'reason_text': 'x' * 600,
    }
    response = authenticated_client.post('/api/daily-plan/events', json=payload)
    assert response.status_code == 200

    from app.daily_plan.models import DailyPlanEvent
    ev = DailyPlanEvent.query.filter_by(
        user_id=test_user.id, event_type='next_step_shown',
    ).order_by(DailyPlanEvent.id.desc()).first()
    assert ev is not None
    assert len(ev.reason_text) == 500


# ---------------------------------------------------------------------------
# emit_minimum_completed helper
# ---------------------------------------------------------------------------

def test_emit_minimum_completed_idempotent(db_session, test_user):
    """emit_minimum_completed does not insert duplicate rows for same date."""
    from app.api.daily_plan import emit_minimum_completed
    from app.daily_plan.models import DailyPlanEvent
    from app.utils.db import db

    today = date(2026, 4, 18)
    emit_minimum_completed(test_user.id, 'progress', today)
    db.session.flush()
    emit_minimum_completed(test_user.id, 'progress', today)
    db.session.flush()

    count = DailyPlanEvent.query.filter_by(
        user_id=test_user.id,
        event_type='minimum_completed',
        plan_date=today,
    ).count()
    assert count == 1


def test_emit_minimum_completed_stores_mission_type(db_session, test_user):
    """emit_minimum_completed stores the mission_type field."""
    from app.api.daily_plan import emit_minimum_completed
    from app.daily_plan.models import DailyPlanEvent
    from app.utils.db import db

    today = date(2026, 4, 17)
    emit_minimum_completed(test_user.id, 'repair', today)
    db.session.flush()

    ev = DailyPlanEvent.query.filter_by(
        user_id=test_user.id,
        event_type='minimum_completed',
        plan_date=today,
    ).first()
    assert ev is not None
    assert ev.mission_type == 'repair'


# ---------------------------------------------------------------------------
# Auto-emission via /api/daily-status
# ---------------------------------------------------------------------------

def test_daily_status_emits_minimum_completed_when_secured(authenticated_client, db_session, test_user):
    """GET /api/daily-status auto-emits minimum_completed when day_secured=True."""
    from app.daily_plan.models import DailyPlanEvent

    mock_summary = {'lessons_count': 0, 'words_reviewed': 0}
    mock_streak = {
        'streak_status': {'streak': 0, 'has_activity_today': False},
        'required_steps': 3,
        'streak_repaired': False,
    }

    with patch('app.daily_plan.service.get_daily_plan_unified', return_value=MOCK_PLAN_SECURED), \
         patch('app.telegram.queries.get_daily_summary', return_value=mock_summary), \
         patch('app.telegram.queries.get_yesterday_summary', return_value={}), \
         patch('app.achievements.streak_service.compute_plan_steps',
               return_value=(True, 3, 3, 3)), \
         patch('app.achievements.streak_service.process_streak_on_activity',
               return_value=mock_streak):
        response = authenticated_client.get('/api/daily-status')

    assert response.status_code == 200
    assert response.get_json()['day_secured'] is True

    ev = DailyPlanEvent.query.filter_by(
        user_id=test_user.id,
        event_type='minimum_completed',
    ).first()
    assert ev is not None
    assert ev.mission_type == 'progress'


def test_daily_status_no_event_when_not_secured(authenticated_client, db_session, test_user):
    """GET /api/daily-status does NOT emit minimum_completed when day_secured=False."""
    from app.daily_plan.models import DailyPlanEvent

    mock_summary = {'lessons_count': 0, 'words_reviewed': 0}
    mock_streak = {
        'streak_status': {'streak': 0, 'has_activity_today': False},
        'required_steps': 3,
        'streak_repaired': False,
    }

    with patch('app.daily_plan.service.get_daily_plan_unified', return_value=MOCK_PLAN_UNSECURED), \
         patch('app.telegram.queries.get_daily_summary', return_value=mock_summary), \
         patch('app.telegram.queries.get_yesterday_summary', return_value={}), \
         patch('app.achievements.streak_service.compute_plan_steps',
               return_value=(False, 3, 1, 3)), \
         patch('app.achievements.streak_service.process_streak_on_activity',
               return_value=mock_streak):
        response = authenticated_client.get('/api/daily-status')

    assert response.status_code == 200
    assert response.get_json()['day_secured'] is False

    ev = DailyPlanEvent.query.filter_by(
        user_id=test_user.id,
        event_type='minimum_completed',
    ).first()
    assert ev is None


# ---------------------------------------------------------------------------
# Phase 3 rival strip events
# ---------------------------------------------------------------------------

def test_record_rival_strip_shown(authenticated_client, db_session):
    """rival_strip_shown event is accepted and stored."""
    response = authenticated_client.post(
        '/api/daily-plan/events',
        json={'event_type': 'rival_strip_shown'},
        content_type='application/json',
    )
    assert response.status_code == 200
    data = response.get_json()
    assert data['success'] is True
    assert data['event_type'] == 'rival_strip_shown'


def test_record_rival_strip_dismissed(authenticated_client, db_session):
    """rival_strip_dismissed event is accepted and stored."""
    response = authenticated_client.post(
        '/api/daily-plan/events',
        json={'event_type': 'rival_strip_dismissed'},
    )
    assert response.status_code == 200
    assert response.get_json()['event_type'] == 'rival_strip_dismissed'


def test_record_steps_taken_while_rival_visible(authenticated_client, db_session):
    """steps_taken_while_rival_visible event is accepted and stored."""
    response = authenticated_client.post(
        '/api/daily-plan/events',
        json={
            'event_type': 'steps_taken_while_rival_visible',
            'step_kind': 'learn',
        },
    )
    assert response.status_code == 200
    assert response.get_json()['event_type'] == 'steps_taken_while_rival_visible'


def test_rival_events_persisted_to_db(authenticated_client, db_session, test_user):
    """Rival strip events are written to the database with correct fields."""
    from app.daily_plan.models import DailyPlanEvent

    authenticated_client.post(
        '/api/daily-plan/events',
        json={'event_type': 'rival_strip_shown', 'plan_date': '2026-04-18'},
    )

    ev = DailyPlanEvent.query.filter_by(
        user_id=test_user.id,
        event_type='rival_strip_shown',
    ).first()
    assert ev is not None
    assert str(ev.plan_date) == '2026-04-18'


def test_rival_strip_shown_not_server_only(authenticated_client):
    """rival_strip_shown is in the client-callable set (not blocked like minimum_completed)."""
    response = authenticated_client.post(
        '/api/daily-plan/events',
        json={'event_type': 'rival_strip_shown'},
    )
    assert response.status_code == 200


def test_minimum_completed_still_blocked_from_client(authenticated_client):
    """minimum_completed remains server-only and cannot be sent by the client."""
    response = authenticated_client.post(
        '/api/daily-plan/events',
        json={'event_type': 'minimum_completed'},
    )
    assert response.status_code == 400
