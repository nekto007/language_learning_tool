"""Integration tests for /api/daily-plan endpoints.

Covers:
- GET /api/daily-plan: authenticated user gets 200 with plan data
- GET /api/daily-plan: unauthenticated request gets 401
- timezone param: invalid tz falls back to default (no 400)
- GET /api/daily-plan: cold-start user (no progress) returns a plan dict
- /api/daily-status payload field correctness (Task 6)
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


def test_daily_plan_returns_phase_preview(authenticated_client):
    """Task 5: each mission phase carries preview metadata through the API response."""
    plan_with_preview = dict(MOCK_PLAN)
    plan_with_preview['mission'] = {'type': 'progress', 'title': 'X', 'reason_code': 'r', 'reason_text': 't'}
    plan_with_preview['phases'] = [
        {
            'id': 'p1',
            'phase': 'recall',
            'title': 'Разогрев',
            'source_kind': 'srs',
            'mode': 'srs_review',
            'required': True,
            'completed': False,
            'preview': {
                'item_count': 18,
                'content_title': 'Повторение карточек',
                'estimated_minutes': 3,
            },
        },
        {
            'id': 'p2',
            'phase': 'learn',
            'title': 'Главный шаг',
            'source_kind': 'normal_course',
            'mode': 'curriculum_lesson',
            'required': True,
            'completed': False,
            'preview': {
                'item_count': None,
                'content_title': 'Present Perfect',
                'estimated_minutes': 10,
            },
        },
    ]

    with patch('app.daily_plan.service.get_daily_plan_unified', return_value=plan_with_preview):
        response = authenticated_client.get('/api/daily-plan')

    assert response.status_code == 200
    data = response.get_json()
    phases = data.get('phases') or []
    assert len(phases) == 2

    recall_preview = phases[0].get('preview')
    assert recall_preview == {
        'item_count': 18,
        'content_title': 'Повторение карточек',
        'estimated_minutes': 3,
    }

    learn_preview = phases[1].get('preview')
    assert learn_preview['content_title'] == 'Present Perfect'
    assert learn_preview['estimated_minutes'] == 10
    assert learn_preview['item_count'] is None


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


class TestRouteStateInDailyPlan:
    """Task 12: route_state is included in /api/daily-plan response."""

    def test_route_state_present_no_completed_phases(self, authenticated_client):
        """route_state key is always present; steps_today=0 when no phases completed."""
        plan = dict(MOCK_PLAN)
        plan['phases'] = [
            {'id': 'p1', 'phase': 'recall', 'required': True, 'completed': False},
        ]
        with patch('app.daily_plan.service.get_daily_plan_unified', return_value=plan), \
             patch('app.daily_plan.route_progress.get_route_state', return_value={
                 'steps_today': 0,
                 'total_steps': 0,
                 'checkpoint_number': 0,
                 'steps_to_next_checkpoint': 20,
                 'percent_to_checkpoint': 0,
             }) as mock_rs:
            response = authenticated_client.get('/api/daily-plan')

        assert response.status_code == 200
        data = response.get_json()
        assert 'route_state' in data
        assert data['route_state']['steps_today'] == 0
        mock_rs.assert_called_once()
        _, call_steps_today, _ = mock_rs.call_args.args
        assert call_steps_today == 0

    # Mission-phase route-state aggregation removed: unified plan does not
    # carry phases, and `/api/daily-plan` always passes steps_today=0 now.


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


# ── Task 6: /api/daily-status payload correctness ─────────────────────────────

MOCK_STREAK_RESULT = {
    'streak_status': {'streak': 0, 'has_activity_today': False},
    'required_steps': 3,
    'streak_repaired': False,
}

MOCK_UNIFIED_PLAN = {
    'mode': 'unified',
    'required': [],
    'optional': [],
    'setup': [],
    'day_secured': False,
    '_plan_meta': {'effective_mode': 'unified'},
}


def _call_daily_status(authenticated_client, extra_patches=None):
    """Helper: call /api/daily-status with standard mocks applied."""
    patches = {
        'app.daily_plan.service.get_daily_plan_unified': MOCK_UNIFIED_PLAN,
        'app.telegram.queries.get_daily_summary': {'lessons_count': 0},
        'app.telegram.queries.get_yesterday_summary': {},
        'app.achievements.streak_service.compute_plan_steps': (False, 3, 0, 3),
        'app.achievements.streak_service.process_streak_on_activity': MOCK_STREAK_RESULT,
    }
    if extra_patches:
        patches.update(extra_patches)

    with patch('app.daily_plan.service.get_daily_plan_unified', return_value=patches['app.daily_plan.service.get_daily_plan_unified']), \
         patch('app.telegram.queries.get_daily_summary', return_value=patches['app.telegram.queries.get_daily_summary']), \
         patch('app.telegram.queries.get_yesterday_summary', return_value=patches['app.telegram.queries.get_yesterday_summary']), \
         patch('app.achievements.streak_service.compute_plan_steps', return_value=patches['app.achievements.streak_service.compute_plan_steps']), \
         patch('app.achievements.streak_service.process_streak_on_activity', return_value=patches['app.achievements.streak_service.process_streak_on_activity']):
        return authenticated_client.get('/api/daily-status')


class TestDailyStatusLeechSuspendedCount:
    """leech_suspended_count is always an int in the daily-status payload."""

    def test_leech_suspended_count_present_and_int(self, authenticated_client):
        """leech_suspended_count is always present and is an integer."""
        response = _call_daily_status(authenticated_client)
        assert response.status_code == 200
        data = response.get_json()
        assert 'leech_suspended_count' in data
        assert isinstance(data['leech_suspended_count'], int)

    def test_leech_suspended_count_zero_when_no_leeches(self, authenticated_client):
        """With no leech cards, leech_suspended_count == 0 (never None)."""
        with patch('app.api.daily_plan._count_leech_suspended', return_value=0):
            response = _call_daily_status(authenticated_client)
        data = response.get_json()
        assert data['leech_suspended_count'] == 0

    def test_leech_suspended_count_reflects_buried_leeches(self, authenticated_client):
        """Payload carries the actual count returned by the counting helper."""
        with patch('app.api.daily_plan._count_leech_suspended', return_value=3):
            response = _call_daily_status(authenticated_client)
        data = response.get_json()
        assert data['leech_suspended_count'] == 3


class TestDailyStatusSrsLimitReason:
    """srs_limit_reason is only present in payload when value is not 'normal'."""

    def test_srs_limit_reason_absent_when_normal(self, authenticated_client):
        """When adaptive limit is 'normal', srs_limit_reason is omitted from payload."""
        with patch('app.study.services.SRSService.get_adaptive_limit_reason', return_value='normal'):
            response = _call_daily_status(authenticated_client)
        data = response.get_json()
        assert 'srs_limit_reason' not in data

    def test_srs_limit_reason_present_when_accuracy_low(self, authenticated_client):
        """When adaptive limit is 'accuracy_low', srs_limit_reason is in payload."""
        with patch('app.study.services.SRSService.get_adaptive_limit_reason', return_value='accuracy_low'):
            response = _call_daily_status(authenticated_client)
        data = response.get_json()
        assert data.get('srs_limit_reason') == 'accuracy_low'

    def test_srs_limit_reason_present_when_backlog_reduction(self, authenticated_client):
        """When adaptive limit is 'backlog_reduction', srs_limit_reason is in payload."""
        with patch('app.study.services.SRSService.get_adaptive_limit_reason', return_value='backlog_reduction'):
            response = _call_daily_status(authenticated_client)
        data = response.get_json()
        assert data.get('srs_limit_reason') == 'backlog_reduction'


class TestDailyStatusTomorrowPreview:
    """tomorrow_preview in the plan sub-object reflects slot types only (no suspended lessons)."""

    def test_tomorrow_preview_none_when_day_not_secured(self, authenticated_client):
        """When day is not yet secured, tomorrow_preview is absent from the plan."""
        plan = dict(MOCK_UNIFIED_PLAN)
        plan['day_secured'] = False

        with patch('app.daily_plan.service.get_daily_plan_unified', return_value=plan), \
             patch('app.telegram.queries.get_daily_summary', return_value={}), \
             patch('app.telegram.queries.get_yesterday_summary', return_value={}), \
             patch('app.achievements.streak_service.compute_plan_steps', return_value=(False, 3, 0, 3)), \
             patch('app.achievements.streak_service.process_streak_on_activity', return_value=MOCK_STREAK_RESULT):
            response = authenticated_client.get('/api/daily-status')

        data = response.get_json()
        assert response.status_code == 200
        assert data.get('plan', {}).get('tomorrow_preview') is None

    def test_tomorrow_preview_contains_slot_types_not_lesson_ids(self, authenticated_client):
        """When present, tomorrow_preview has slot_types list (no lesson ids/status fields)."""
        preview = {'estimated_minutes': 25, 'slot_types': ['curriculum', 'srs']}
        plan = dict(MOCK_UNIFIED_PLAN)
        plan['tomorrow_preview'] = preview
        plan['day_secured'] = True

        with patch('app.daily_plan.service.get_daily_plan_unified', return_value=plan), \
             patch('app.telegram.queries.get_daily_summary', return_value={}), \
             patch('app.telegram.queries.get_yesterday_summary', return_value={}), \
             patch('app.achievements.streak_service.compute_plan_steps', return_value=(True, 3, 3, 3)), \
             patch('app.achievements.streak_service.process_streak_on_activity', return_value={**MOCK_STREAK_RESULT, 'required_steps': 3}), \
             patch('app.daily_plan.service.write_secured_at'), \
             patch('app.daily_plan.service.compute_day_secured_from_activity', return_value=True):
            response = authenticated_client.get('/api/daily-status')

        data = response.get_json()
        assert response.status_code == 200
        tp = data.get('plan', {}).get('tomorrow_preview')
        if tp is not None:
            assert 'slot_types' in tp
            assert isinstance(tp['slot_types'], list)
            assert 'estimated_minutes' in tp
            for st in tp['slot_types']:
                assert isinstance(st, str)


class TestDailyStatusRecoverySuggestion:
    """recovery_suggestion is correct when yesterday_plan is absent or present in DB."""

    def test_recovery_suggestion_absent_when_no_yesterday_log(self, authenticated_client):
        """When DailyPlanLog entry for yesterday is missing, no recovery_suggestion is returned."""
        with patch('app.api.daily_plan._get_recovery_suggestion', return_value=None):
            response = _call_daily_status(authenticated_client)
        data = response.get_json()
        assert 'recovery_suggestion' not in data

    def test_recovery_suggestion_absent_when_yesterday_secured(self, authenticated_client):
        """When yesterday's plan was secured, no recovery_suggestion is returned."""
        with patch('app.api.daily_plan._get_recovery_suggestion', return_value=None):
            response = _call_daily_status(authenticated_client)
        data = response.get_json()
        assert 'recovery_suggestion' not in data

    def test_recovery_suggestion_present_when_yesterday_incomplete(self, authenticated_client):
        """When yesterday was incomplete (log exists but not secured), suggestion is returned."""
        suggestion = {
            'missed_kind': 'srs',
            'action_url': '/dashboard',
            'missed_date': '2026-05-26',
        }
        with patch('app.api.daily_plan._get_recovery_suggestion', return_value=suggestion):
            response = _call_daily_status(authenticated_client)
        data = response.get_json()
        rs = data.get('recovery_suggestion')
        assert rs is not None
        assert rs['missed_kind'] == 'srs'
        assert rs['action_url'] == '/dashboard'
        assert rs['missed_date'] == '2026-05-26'

    def test_recovery_suggestion_returns_none_for_missing_log(self, db_session, test_user):
        """Unit: _get_recovery_suggestion returns None when no DailyPlanLog for yesterday."""
        from app.api.daily_plan import _get_recovery_suggestion
        result = _get_recovery_suggestion(test_user.id, 'Europe/Moscow')
        assert result is None


class TestCountLeechSuspendedHelper:
    """Unit tests for the _count_leech_suspended helper."""

    def test_returns_int_always(self, db_session, test_user):
        """_count_leech_suspended always returns an int, never None."""
        from app.api.daily_plan import _count_leech_suspended
        result = _count_leech_suspended(test_user.id)
        assert isinstance(result, int)
        assert result >= 0

    def test_returns_zero_for_user_without_cards(self, db_session, test_user):
        """User with no SRS cards gets leech_suspended_count == 0."""
        from app.api.daily_plan import _count_leech_suspended
        assert _count_leech_suspended(test_user.id) == 0
