"""Tests for plan pause/resume service logic (Task 64)."""
from __future__ import annotations

from datetime import date, timedelta
from unittest.mock import patch

import pytest


class TestIsPlanPaused:
    """Tests for is_plan_paused service helper."""

    def test_returns_false_for_none_user(self):
        from app.daily_plan.service import is_plan_paused
        assert is_plan_paused(None) is False

    def test_returns_false_when_paused_until_none(self, test_user, db_session):
        from app.daily_plan.service import is_plan_paused
        test_user.plan_paused_until = None
        db_session.flush()
        assert is_plan_paused(test_user) is False

    def test_returns_true_when_paused_until_future(self, test_user, db_session):
        from app.daily_plan.service import is_plan_paused
        test_user.plan_paused_until = date.today() + timedelta(days=3)
        db_session.flush()
        assert is_plan_paused(test_user) is True

    def test_returns_false_when_paused_until_today(self, test_user, db_session):
        """paused_until == today means pause has expired (strictly >)."""
        from app.daily_plan.service import is_plan_paused
        test_user.plan_paused_until = date.today()
        db_session.flush()
        assert is_plan_paused(test_user) is False

    def test_returns_false_when_paused_until_past(self, test_user, db_session):
        from app.daily_plan.service import is_plan_paused
        test_user.plan_paused_until = date.today() - timedelta(days=1)
        db_session.flush()
        assert is_plan_paused(test_user) is False


class TestPauseStreakNeutrality:
    """Paused days must be streak-neutral via plan_pause StreakEvents."""

    def test_pause_creates_streak_events_per_day(self, authenticated_client, db_session):
        """POST /api/plan/pause creates one plan_pause StreakEvent per paused day."""
        import json
        from app.achievements.models import StreakEvent

        resp = authenticated_client.post(
            '/api/plan/pause',
            data=json.dumps({'days': 3}),
            content_type='application/json',
        )
        assert resp.status_code == 200

        with authenticated_client.application.app_context():
            from app import db as _db
            user_id = authenticated_client.application.test_user.id
            today = date.today()
            events = StreakEvent.query.filter(
                StreakEvent.user_id == user_id,
                StreakEvent.event_type == 'plan_pause',
                StreakEvent.event_date >= today,
            ).all()
            event_dates = {ev.event_date for ev in events}
            assert len(event_dates) == 3
            for offset in range(3):
                assert (today + timedelta(days=offset)) in event_dates

    def test_plan_pause_events_treated_as_active_in_streak(self, test_user, db_session):
        """plan_pause StreakEvents are included in streak's active-date set."""
        from app.achievements.models import StreakEvent
        from app import db

        # Add a plan_pause event for yesterday
        yesterday = date.today() - timedelta(days=1)
        db.session.add(StreakEvent(
            user_id=test_user.id,
            event_type='plan_pause',
            coins_delta=0,
            event_date=yesterday,
        ))
        db.session.flush()

        # has_repair_for_date includes plan_pause
        from app.achievements.streak_service import has_repair_for_date
        assert has_repair_for_date(test_user.id, yesterday) is True

    def test_resume_removes_future_streak_events(self, authenticated_client, db_session):
        """POST /api/plan/resume deletes future plan_pause StreakEvents."""
        import json
        from app.achievements.models import StreakEvent

        # First pause for 5 days
        authenticated_client.post(
            '/api/plan/pause',
            data=json.dumps({'days': 5}),
            content_type='application/json',
        )
        # Then resume
        resp = authenticated_client.post(
            '/api/plan/resume',
            data=json.dumps({}),
            content_type='application/json',
        )
        assert resp.status_code == 200

        with authenticated_client.application.app_context():
            user_id = authenticated_client.application.test_user.id
            today = date.today()
            # Today and future plan_pause events should be gone
            remaining = StreakEvent.query.filter(
                StreakEvent.user_id == user_id,
                StreakEvent.event_type == 'plan_pause',
                StreakEvent.event_date >= today,
            ).count()
            assert remaining == 0


class TestEarlyResume:
    """Early resume (before paused_until) must work correctly."""

    def test_early_resume_clears_paused_until(self, authenticated_client, db_session):
        """Resuming before paused_until clears the field immediately."""
        import json
        from app.auth.models import User

        authenticated_client.post(
            '/api/plan/pause',
            data=json.dumps({'days': 7}),
            content_type='application/json',
        )
        resp = authenticated_client.post(
            '/api/plan/resume',
            data=json.dumps({}),
            content_type='application/json',
        )
        assert resp.status_code == 200

        with authenticated_client.application.app_context():
            user_id = authenticated_client.application.test_user.id
            user = User.query.filter_by(id=user_id).first()
            assert user.plan_paused_until is None

    def test_resume_allows_plan_assembly(self, test_user, db_session):
        """After clearing plan_paused_until, get_daily_plan_unified returns non-paused mode."""
        from app.daily_plan.service import get_daily_plan_unified

        # Set up as paused then clear
        test_user.plan_paused_until = None
        db_session.flush()

        with patch('app.daily_plan.plan.get_daily_plan', return_value={
            'mode': 'unified', 'required': [], 'optional': [], 'setup': [],
            'day_secured': False,
        }):
            plan = get_daily_plan_unified(test_user.id)

        assert plan.get('mode') != 'paused'


class TestPauseValidation:
    """Pause endpoint validation edge cases."""

    def test_pause_rejects_bool(self, authenticated_client):
        """days=true (bool) rejected — bool is subclass of int in Python."""
        import json
        resp = authenticated_client.post(
            '/api/plan/pause',
            data=json.dumps({'days': True}),
            content_type='application/json',
        )
        assert resp.status_code == 400

    def test_pause_rejects_float(self, authenticated_client):
        """days=3.5 (float) rejected."""
        import json
        resp = authenticated_client.post(
            '/api/plan/pause',
            data=json.dumps({'days': 3.5}),
            content_type='application/json',
        )
        assert resp.status_code == 400

    def test_pause_rejects_missing_days(self, authenticated_client):
        """Missing days key → 400."""
        import json
        resp = authenticated_client.post(
            '/api/plan/pause',
            data=json.dumps({}),
            content_type='application/json',
        )
        assert resp.status_code == 400

    def test_pause_max_boundary_accepted(self, authenticated_client, db_session):
        """days=14 (max) is accepted."""
        import json
        resp = authenticated_client.post(
            '/api/plan/pause',
            data=json.dumps({'days': 14}),
            content_type='application/json',
        )
        assert resp.status_code == 200

    def test_pause_min_boundary_accepted(self, authenticated_client, db_session):
        """days=1 (min) is accepted."""
        import json
        resp = authenticated_client.post(
            '/api/plan/pause',
            data=json.dumps({'days': 1}),
            content_type='application/json',
        )
        assert resp.status_code == 200

    def test_expired_paused_until_does_not_block_plan(self, test_user, db_session):
        """plan_paused_until in the past → get_daily_plan_unified returns normal plan."""
        from app.daily_plan.service import get_daily_plan_unified

        test_user.plan_paused_until = date.today() - timedelta(days=2)
        db_session.flush()

        with patch('app.daily_plan.plan.get_daily_plan', return_value={
            'mode': 'unified', 'required': [], 'optional': [], 'setup': [],
            'day_secured': False,
        }):
            plan = get_daily_plan_unified(test_user.id)

        assert plan.get('mode') != 'paused'
        assert plan.get('_plan_meta', {}).get('effective_mode') != 'paused'
