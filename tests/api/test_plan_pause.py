"""Tests for plan pause/resume functionality (Task 48)."""
from __future__ import annotations

import json
from datetime import date, timedelta
from unittest.mock import patch, MagicMock

import pytest


def _paused_plan(paused_until: str) -> dict:
    return {
        'mode': 'paused',
        'paused_until': paused_until,
        'day_secured': False,
        '_plan_meta': {
            'mission_plan_enabled': False,
            'effective_mode': 'paused',
            'fallback_reason': None,
        },
    }


def _linear_plan() -> dict:
    return {
        'mode': 'linear',
        'baseline_slots': [],
        'slots': [],
        'chain_meta': {'baseline_count': 0, 'has_more_available': False, 'exhausted_sources': []},
        'continuation': {'available': False, 'next_lessons': []},
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


class TestPlanPauseEndpoint:
    """Tests for POST /api/plan/pause."""

    def test_pause_valid_days(self, authenticated_client, db_session):
        """Pause with valid days → 200, paused_until set correctly."""
        resp = authenticated_client.post(
            '/api/plan/pause',
            data=json.dumps({'days': 3}),
            content_type='application/json',
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['status'] == 'ok'
        expected_until = (date.today() + timedelta(days=3)).isoformat()
        assert data['paused_until'] == expected_until

    def test_pause_invalid_days_zero(self, authenticated_client):
        """days=0 → 400 bad request."""
        resp = authenticated_client.post(
            '/api/plan/pause',
            data=json.dumps({'days': 0}),
            content_type='application/json',
        )
        assert resp.status_code == 400

    def test_pause_invalid_days_too_large(self, authenticated_client):
        """days=15 → 400 bad request."""
        resp = authenticated_client.post(
            '/api/plan/pause',
            data=json.dumps({'days': 15}),
            content_type='application/json',
        )
        assert resp.status_code == 400

    def test_pause_invalid_days_string(self, authenticated_client):
        """days='abc' → 400 bad request."""
        resp = authenticated_client.post(
            '/api/plan/pause',
            data=json.dumps({'days': 'abc'}),
            content_type='application/json',
        )
        assert resp.status_code == 400

    def test_pause_sets_plan_paused_until(self, authenticated_client, db_session):
        """Pause endpoint actually sets user.plan_paused_until in DB."""
        from app.auth.models import User

        resp = authenticated_client.post(
            '/api/plan/pause',
            data=json.dumps({'days': 5}),
            content_type='application/json',
        )
        assert resp.status_code == 200

        with authenticated_client.application.app_context():
            user = User.query.first()
            assert user is not None
            assert user.plan_paused_until == date.today() + timedelta(days=5)

    def test_pause_unauthenticated(self, client):
        """Unauthenticated request → redirected or 401."""
        resp = client.post(
            '/api/plan/pause',
            data=json.dumps({'days': 3}),
            content_type='application/json',
        )
        assert resp.status_code in (401, 302)


class TestPlanResumeEndpoint:
    """Tests for POST /api/plan/resume."""

    def test_resume_clears_paused_until(self, authenticated_client, db_session):
        """Resume clears plan_paused_until."""
        from app.auth.models import User

        # First pause
        authenticated_client.post(
            '/api/plan/pause',
            data=json.dumps({'days': 5}),
            content_type='application/json',
        )

        resp = authenticated_client.post(
            '/api/plan/resume',
            data=json.dumps({}),
            content_type='application/json',
        )
        assert resp.status_code == 200
        assert resp.get_json()['status'] == 'ok'

        with authenticated_client.application.app_context():
            user = User.query.first()
            assert user.plan_paused_until is None

    def test_resume_when_not_paused(self, authenticated_client, db_session):
        """Resume when not paused → 200 ok (idempotent)."""
        resp = authenticated_client.post(
            '/api/plan/resume',
            data=json.dumps({}),
            content_type='application/json',
        )
        assert resp.status_code == 200


class TestPlanPausedMode:
    """Tests for plan behavior during pause."""

    def _status_patches(self, plan):
        return [
            patch('app.daily_plan.service.get_daily_plan_unified', return_value=plan),
            patch('app.telegram.queries.get_daily_summary', return_value=_empty_summary()),
            patch('app.telegram.queries.get_yesterday_summary', return_value=_empty_summary()),
            patch('app.study.services.SRSService.get_adaptive_limit_reason', return_value='normal'),
        ]

    def test_daily_status_paused_returns_paused_flag(self, authenticated_client, db_session):
        """When plan is paused, /api/daily-status includes plan_paused=True and paused_until."""
        paused_until = (date.today() + timedelta(days=2)).isoformat()
        plan = _paused_plan(paused_until)
        patches = self._status_patches(plan)
        with patches[0], patches[1], patches[2], patches[3]:
            with patch('app.api.daily_plan._compute_listening_goal', return_value={
                'listening_goal_minutes': 10,
                'listening_minutes_today': 0,
                'listening_goal_reached': False,
            }):
                resp = authenticated_client.get('/api/daily-status')

        assert resp.status_code == 200
        data = resp.get_json()
        assert data.get('plan_paused') is True
        assert data.get('paused_until') == paused_until

    def test_daily_status_not_paused_no_flag(self, authenticated_client, db_session):
        """When plan is not paused, plan_paused not in payload."""
        plan = _linear_plan()
        patches = self._status_patches(plan)
        with patches[0], patches[1], patches[2], patches[3]:
            with patch('app.api.daily_plan._compute_listening_goal', return_value={
                'listening_goal_minutes': 10,
                'listening_minutes_today': 0,
                'listening_goal_reached': False,
            }):
                resp = authenticated_client.get('/api/daily-status')

        assert resp.status_code == 200
        data = resp.get_json()
        assert data.get('plan_paused') is None

    def test_daily_plan_returns_paused_mode(self, authenticated_client, db_session):
        """When plan is paused, /api/daily-plan returns mode=paused."""
        paused_until = (date.today() + timedelta(days=1)).isoformat()
        plan = _paused_plan(paused_until)
        with patch('app.daily_plan.service.get_daily_plan_unified', return_value=plan):
            with patch('app.telegram.queries.get_daily_summary', return_value=_empty_summary()):
                resp = authenticated_client.get('/api/daily-plan')

        assert resp.status_code == 200
        data = resp.get_json()
        assert data.get('mode') == 'paused'
        assert data.get('paused_until') == paused_until


class TestPauseStreakNeutrality:
    """Tests that paused days do not break streak."""

    def test_get_daily_plan_unified_paused_when_flag_set(self, test_user, db_session):
        """get_daily_plan_unified returns paused payload when user.plan_paused_until >= today."""
        from app.daily_plan.service import get_daily_plan_unified

        test_user.plan_paused_until = date.today() + timedelta(days=3)
        db_session.flush()

        plan = get_daily_plan_unified(test_user.id)
        assert plan.get('mode') == 'paused'
        assert plan.get('_plan_meta', {}).get('effective_mode') == 'paused'
        assert plan.get('paused_until') == (date.today() + timedelta(days=3)).isoformat()

    def test_get_daily_plan_unified_not_paused_when_expired(self, test_user, db_session):
        """get_daily_plan_unified does NOT return paused when plan_paused_until is in the past."""
        from app.daily_plan.service import get_daily_plan_unified

        # Set paused_until to yesterday
        test_user.plan_paused_until = date.today() - timedelta(days=1)
        db_session.flush()

        with patch('app.daily_plan.service._get_linear_plan_safe', return_value=None), \
             patch('app.daily_plan.service.get_mission_plan', return_value=None), \
             patch('app.telegram.queries.get_daily_plan_v2', return_value={'mode': 'legacy'}):
            plan = get_daily_plan_unified(test_user.id)

        assert plan.get('mode') != 'paused'

    def test_get_daily_plan_unified_not_paused_when_null(self, test_user, db_session):
        """get_daily_plan_unified does NOT return paused when plan_paused_until is None."""
        from app.daily_plan.service import get_daily_plan_unified

        test_user.plan_paused_until = None
        db_session.flush()

        with patch('app.daily_plan.service._get_linear_plan_safe', return_value=None), \
             patch('app.daily_plan.service.get_mission_plan', return_value=None), \
             patch('app.telegram.queries.get_daily_plan_v2', return_value={'mode': 'legacy'}):
            plan = get_daily_plan_unified(test_user.id)

        assert plan.get('mode') != 'paused'
