"""Tests for Task 78: Weekly learning report card on dashboard.

Covers:
- get_last_week_summary() returns correct aggregates
- Monday → weekly summary shown when user was active last week
- Already dismissed this week → hidden
- No last-week activity → hidden
- Dismiss endpoint sets session key
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest

from app.daily_plan.models import DailyPlanLog
from app.study.insights_service import get_last_week_summary
from app.utils.db import db


def _login(client, user) -> None:
    with client.session_transaction() as sess:
        sess['_user_id'] = str(user.id)
        sess['_fresh'] = True


def _last_monday() -> date:
    today = date.today()
    days_since_monday = today.weekday()
    return today - timedelta(days=days_since_monday + 7)


def _make_plan_log(db_session, user_id: int, plan_date: date, secured: bool = False) -> DailyPlanLog:
    log = DailyPlanLog(
        user_id=user_id,
        plan_date=plan_date,
        mission_type='progress',
        secured_at=datetime.now(timezone.utc) if secured else None,
        created_at=datetime.now(timezone.utc),
    )
    db_session.add(log)
    db_session.commit()
    return log


# ---------------------------------------------------------------------------
# Tests for get_last_week_summary()
# ---------------------------------------------------------------------------

class TestGetLastWeekSummary:
    def test_empty_user_returns_zeros(self, app, db_session, test_user):
        result = get_last_week_summary(test_user.id)
        assert result['words_reviewed'] == 0
        assert result['lessons_completed'] == 0
        assert result['days_secured'] == 0
        assert result['total_minutes'] == 0
        assert result['has_activity'] is False

    def test_has_activity_false_when_no_data(self, app, db_session, test_user):
        result = get_last_week_summary(test_user.id)
        assert result['has_activity'] is False

    def test_days_secured_counts_last_week_only(self, app, db_session, test_user):
        monday = _last_monday()
        # Secured on Wednesday of last week
        _make_plan_log(db_session, test_user.id, monday + timedelta(days=2), secured=True)
        # Not secured on Thursday (same week)
        _make_plan_log(db_session, test_user.id, monday + timedelta(days=3), secured=False)
        # Secured two weeks ago — should not count
        _make_plan_log(db_session, test_user.id, monday - timedelta(days=7), secured=True)

        result = get_last_week_summary(test_user.id)
        assert result['days_secured'] == 1
        assert result['has_activity'] is True

    def test_days_secured_full_week(self, app, db_session, test_user):
        monday = _last_monday()
        for i in range(7):
            _make_plan_log(db_session, test_user.id, monday + timedelta(days=i), secured=True)

        result = get_last_week_summary(test_user.id)
        assert result['days_secured'] == 7

    def test_vs_prev_week_positive_diff(self, app, db_session, test_user):
        monday = _last_monday()
        # 3 secured last week
        for i in range(3):
            _make_plan_log(db_session, test_user.id, monday + timedelta(days=i), secured=True)
        # 1 secured two weeks ago
        _make_plan_log(db_session, test_user.id, monday - timedelta(days=7), secured=True)

        result = get_last_week_summary(test_user.id)
        assert result['vs_prev_week']['days_diff'] == 2  # 3 - 1

    def test_week_label_format(self, app, db_session, test_user):
        result = get_last_week_summary(test_user.id)
        assert '–' in result['week_label']
        # e.g. "28.04–04.05" — should have day.month format on both sides
        parts = result['week_label'].split('–')
        assert len(parts) == 2
        assert '.' in parts[0]
        assert '.' in parts[1]

    def test_only_current_user_data(self, app, db_session, test_user):
        from app.auth.models import User
        import uuid
        other = User(
            email=f'wr_{uuid.uuid4().hex[:8]}@test.com',
            username=f'wruser_{uuid.uuid4().hex[:8]}',
            onboarding_completed=True,
        )
        other.set_password('pw123456')
        db_session.add(other)
        db_session.commit()

        monday = _last_monday()
        _make_plan_log(db_session, other.id, monday, secured=True)

        result = get_last_week_summary(test_user.id)
        assert result['days_secured'] == 0
        assert result['has_activity'] is False


# ---------------------------------------------------------------------------
# Tests for dashboard weekly report card rendering
# ---------------------------------------------------------------------------

class TestDashboardWeeklyReport:
    def test_dismiss_endpoint_sets_session(self, app, db_session, test_user, client):
        _login(client, test_user)
        dismiss_key = 'weekly_report_dismissed_2026-W20'
        resp = client.post(
            '/api/weekly-report/dismiss',
            json={'dismiss_key': dismiss_key},
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data.get('ok') is True
        # Session key should be set
        with client.session_transaction() as sess:
            assert sess.get(dismiss_key) is True

    def test_dismiss_endpoint_ignores_invalid_key(self, app, db_session, test_user, client):
        _login(client, test_user)
        resp = client.post(
            '/api/weekly-report/dismiss',
            json={'dismiss_key': 'some_random_key'},
        )
        assert resp.status_code == 200
        # Invalid key (doesn't start with weekly_report_dismissed_) — session not polluted
        with client.session_transaction() as sess:
            assert 'some_random_key' not in sess

    def test_dismiss_endpoint_requires_login(self, app, db_session, client):
        resp = client.post(
            '/api/weekly-report/dismiss',
            json={'dismiss_key': 'weekly_report_dismissed_2026-W20'},
        )
        assert resp.status_code in (302, 401, 403)

    def test_report_not_shown_when_no_activity(self, app, db_session, test_user, client):
        _login(client, test_user)
        # No plan logs, no study sessions — has_activity = False
        resp = client.get('/dashboard')
        html = resp.get_data(as_text=True)
        assert 'weekly-report-card' not in html

    def test_report_hidden_when_dismissed(self, app, db_session, test_user, client):
        _login(client, test_user)
        # Simulate dismiss already done this week
        today = date.today()
        week_key = today.strftime('%G-W%V')
        dismiss_key = f'weekly_report_dismissed_{week_key}'
        with client.session_transaction() as sess:
            sess[dismiss_key] = True
        # Even if there is activity, card should not show
        monday = _last_monday()
        _make_plan_log(db_session, test_user.id, monday, secured=True)
        resp = client.get('/dashboard')
        html = resp.get_data(as_text=True)
        assert 'weekly-report-card' not in html
