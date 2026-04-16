"""Integration tests for /api/daily-plan endpoints.

Covers:
- GET /api/daily-plan: authenticated user gets 200 with plan data
- GET /api/daily-plan: unauthenticated request gets 401
- timezone param: invalid tz falls back to default (no 400)
- GET /api/daily-plan: cold-start user (no progress) returns a plan dict
"""
import pytest
from unittest.mock import patch, MagicMock


MOCK_PLAN = {
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
}


@pytest.mark.smoke
def test_daily_plan_authenticated(authenticated_client):
    """Authenticated user can retrieve daily plan."""
    with patch('app.daily_plan.service.get_daily_plan_unified', return_value=MOCK_PLAN):
        response = authenticated_client.get('/api/daily-plan')

    assert response.status_code == 200
    data = response.get_json()
    assert data['success'] is True


def test_daily_plan_unauthenticated(client):
    """Unauthenticated request to /api/daily-plan returns 401."""
    response = client.get('/api/daily-plan')
    assert response.status_code == 401
    data = response.get_json()
    assert data['success'] is False
    assert data['status_code'] == 401


def test_daily_plan_invalid_timezone_falls_back(authenticated_client):
    """Invalid tz param falls back to default timezone — returns 200, not 400."""
    with patch('app.daily_plan.service.get_daily_plan_unified', return_value=MOCK_PLAN) as mock_plan:
        response = authenticated_client.get('/api/daily-plan?tz=Invalid/Timezone')

    assert response.status_code == 200
    data = response.get_json()
    assert data['success'] is True


def test_daily_plan_valid_timezone(authenticated_client):
    """Valid tz param is accepted and passed to service."""
    with patch('app.daily_plan.service.get_daily_plan_unified', return_value=MOCK_PLAN) as mock_plan:
        response = authenticated_client.get('/api/daily-plan?tz=Europe/London')

    assert response.status_code == 200
    data = response.get_json()
    assert data['success'] is True


def test_daily_plan_cold_start_user(authenticated_client):
    """Cold-start user with no progress still gets a valid plan dict."""
    cold_start_plan = dict(MOCK_PLAN)
    cold_start_plan['onboarding'] = {'level': 'A0', 'suggestion': 'Start with basics'}

    with patch('app.daily_plan.service.get_daily_plan_unified', return_value=cold_start_plan):
        response = authenticated_client.get('/api/daily-plan')

    assert response.status_code == 200
    data = response.get_json()
    assert data['success'] is True
    assert data.get('onboarding') is not None


def test_daily_status_authenticated(authenticated_client, test_user):
    """Authenticated user can retrieve daily status."""
    mock_summary = {'lessons_count': 0, 'words_reviewed': 0}
    mock_streak = {
        'streak_status': {'streak': 0, 'has_activity_today': False},
        'required_steps': 3,
        'streak_repaired': False,
    }

    with patch('app.daily_plan.service.get_daily_plan_unified', return_value=MOCK_PLAN), \
         patch('app.telegram.queries.get_daily_summary', return_value=mock_summary), \
         patch('app.telegram.queries.get_yesterday_summary', return_value={}), \
         patch('app.achievements.streak_service.compute_plan_steps',
               return_value=(False, 3, 0, 3)), \
         patch('app.achievements.streak_service.process_streak_on_activity',
               return_value=mock_streak):
        response = authenticated_client.get('/api/daily-status')

    assert response.status_code == 200
    data = response.get_json()
    assert data['success'] is True


def test_daily_status_unauthenticated(client):
    """Unauthenticated request to /api/daily-status returns 401."""
    response = client.get('/api/daily-status')
    assert response.status_code == 401


def test_daily_summary_authenticated(authenticated_client):
    """Authenticated user can retrieve daily summary."""
    mock_summary = {
        'lessons_count': 2,
        'words_reviewed': 15,
        'grammar_exercises': 5,
    }
    with patch('app.telegram.queries.get_daily_summary', return_value=mock_summary):
        response = authenticated_client.get('/api/daily-summary')

    assert response.status_code == 200
    data = response.get_json()
    assert data['success'] is True
    assert data['lessons_count'] == 2


def test_daily_summary_unauthenticated(client):
    """Unauthenticated request to /api/daily-summary returns 401."""
    response = client.get('/api/daily-summary')
    assert response.status_code == 401


class TestParseDateParam:
    """Unit tests for parse_date_param utility."""

    def test_none_input_returns_no_error(self):
        from app.utils.validators import parse_date_param
        result, err = parse_date_param(None)
        assert result is None
        assert err is None

    def test_valid_date_string(self):
        from datetime import date
        from app.utils.validators import parse_date_param
        result, err = parse_date_param('2026-04-16')
        assert result == date(2026, 4, 16)
        assert err is None

    def test_malformed_date_returns_error(self):
        from app.utils.validators import parse_date_param
        result, err = parse_date_param('16-04-2026')
        assert result is None
        assert err is not None

    def test_partial_date_returns_error(self):
        from app.utils.validators import parse_date_param
        result, err = parse_date_param('2026-04')
        assert result is None
        assert err is not None

    def test_empty_string_returns_error(self):
        from app.utils.validators import parse_date_param
        result, err = parse_date_param('')
        assert result is None
        assert err is not None
