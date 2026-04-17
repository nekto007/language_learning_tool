"""Integration tests for /api/daily-race endpoint (Task 22).

Covers:
- GET /api/daily-race returns 200 with standings for an authenticated user
- Unauthenticated requests get 401
- Response includes `participants` list with `rank` + `is_me`
- Points reflect the caller's plan+completion when phases exist
"""
from __future__ import annotations

from unittest.mock import patch


def _plan_with_phases() -> dict:
    return {
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
        'mission': {'type': 'progress', 'title': 'Mission', 'reason_code': 'r', 'reason_text': 't'},
        'phases': [
            {
                'id': 'p1', 'phase': 'recall', 'required': True,
                'mode': 'srs_review', 'title': 'Recall',
                'source_kind': 'srs', 'completed': False,
            },
            {
                'id': 'p2', 'phase': 'learn', 'required': True,
                'mode': 'curriculum_lesson', 'title': 'Learn',
                'source_kind': 'normal_course', 'completed': False,
            },
        ],
    }


def test_daily_race_unauthenticated(client):
    response = client.get('/api/daily-race')
    assert response.status_code == 401


def test_daily_race_authenticated_returns_standings(authenticated_client):
    plan = _plan_with_phases()
    summary = {
        'lessons_count': 0,
        'words_reviewed': 0,
        'srs_words_reviewed': 0,
        'grammar_exercises': 0,
        'books_read': [],
        'book_course_lessons_today': 0,
    }
    with patch('app.daily_plan.service.get_daily_plan_unified', return_value=plan), \
         patch('app.telegram.queries.get_daily_summary', return_value=summary):
        response = authenticated_client.get('/api/daily-race')

    assert response.status_code == 200
    data = response.get_json()
    assert data['success'] is True
    race = data['race']
    assert 'race_id' in race
    assert 'race_date' in race
    participants = race['participants']
    assert isinstance(participants, list)
    assert len(participants) >= 3  # human + ghost fillers
    me_entries = [p for p in participants if p.get('is_me')]
    assert len(me_entries) == 1
    assert me_entries[0]['rank'] == race['my_rank']


def test_daily_race_points_reflect_completion(authenticated_client, db_session):
    """When a phase is completed, participant points reflect phase values."""
    from datetime import datetime
    import pytz
    from app.achievements.daily_race import update_race_points_from_plan, get_or_create_race
    from config.settings import DEFAULT_TIMEZONE

    plan = _plan_with_phases()
    summary = {
        'lessons_count': 1,
        'words_reviewed': 0,
        'srs_words_reviewed': 0,
        'grammar_exercises': 0,
        'books_read': [],
        'book_course_lessons_today': 0,
    }

    from app.achievements.streak_service import compute_plan_steps
    plan_completion, _, _, _ = compute_plan_steps(plan, summary)
    # Sanity check: learn phase is marked done (lessons_count = 1).
    assert plan_completion['p2'] is True

    user_id = authenticated_client.application.test_user.id
    tz_obj = pytz.timezone(DEFAULT_TIMEZONE)
    today = datetime.now(tz_obj).date()

    # Enroll the user and apply the update directly to ensure our helper
    # stores the right point total regardless of route commit semantics.
    get_or_create_race(user_id, today)
    update_race_points_from_plan(
        user_id, today, plan['phases'], plan_completion,
    )
    db_session.flush()

    with patch('app.daily_plan.service.get_daily_plan_unified', return_value=plan), \
         patch('app.telegram.queries.get_daily_summary', return_value=summary):
        response = authenticated_client.get('/api/daily-race')

    assert response.status_code == 200
    data = response.get_json()
    race = data['race']
    me = next(p for p in race['participants'] if p['is_me'])
    # learn phase = 22 points per MISSION_PHASE_POINTS
    assert me['points'] == 22
