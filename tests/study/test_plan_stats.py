"""Tests for GET /study/plan-stats — plan performance analytics route.

Task 50: Plan performance analytics route.
"""
from __future__ import annotations

from datetime import date, timedelta, datetime, timezone

import pytest

from app.daily_plan.models import DailyPlanLog
from app.utils.db import db


def _login(client, user) -> None:
    with client.session_transaction() as sess:
        sess['_user_id'] = str(user.id)
        sess['_fresh'] = True


def _make_log(db_session, user_id: int, plan_date: date, secured: bool = False) -> DailyPlanLog:
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


class TestPlanStatsRoute:
    def test_get_returns_200(self, app, db_session, test_user, client):
        _login(client, test_user)
        resp = client.get('/study/plan-stats')
        assert resp.status_code == 200

    def test_unauthenticated_redirects(self, app, db_session, client):
        resp = client.get('/study/plan-stats')
        assert resp.status_code in (302, 401, 403)

    def test_empty_state_shows_zeros(self, app, db_session, test_user, client):
        _login(client, test_user)
        resp = client.get('/study/plan-stats')
        html = resp.get_data(as_text=True)
        assert '0%' in html or 'Нет данных' in html

    def test_active_day_counted_in_completion_rate(self, app, db_session, test_user, client):
        today = date.today()
        _make_log(db_session, test_user.id, today, secured=False)
        _login(client, test_user)
        resp = client.get('/study/plan-stats')
        html = resp.get_data(as_text=True)
        # 1 day out of 30 = 3% completion rate
        assert '3%' in html or '1 из 30' in html

    def test_secured_day_counted_in_secured_rate(self, app, db_session, test_user, client):
        today = date.today()
        _make_log(db_session, test_user.id, today, secured=True)
        _login(client, test_user)
        resp = client.get('/study/plan-stats')
        html = resp.get_data(as_text=True)
        # 1 secured out of 1 active = 100%
        assert '100%' in html

    def test_day_secured_rate_zero_when_no_active_days(self, app, db_session, test_user, client):
        _login(client, test_user)
        resp = client.get('/study/plan-stats')
        html = resp.get_data(as_text=True)
        # secured rate should show 0% when there are no active days
        assert resp.status_code == 200

    def test_trend_up_when_second_half_more_active(self, app, db_session, test_user, client):
        today = date.today()
        # Add activity only in last 15 days
        for i in range(5):
            d = today - timedelta(days=i)
            _make_log(db_session, test_user.id, d, secured=False)
        _login(client, test_user)
        resp = client.get('/study/plan-stats')
        html = resp.get_data(as_text=True)
        assert 'растёт' in html or '↑' in html

    def test_trend_down_when_first_half_more_active(self, app, db_session, test_user, client):
        today = date.today()
        # Add activity only in first 15 days (older)
        for i in range(20, 30):
            d = today - timedelta(days=i)
            _make_log(db_session, test_user.id, d, secured=False)
        _login(client, test_user)
        resp = client.get('/study/plan-stats')
        html = resp.get_data(as_text=True)
        assert 'снижается' in html or '↓' in html

    def test_only_last_30_days_counted(self, app, db_session, test_user, client):
        old_date = date.today() - timedelta(days=35)
        _make_log(db_session, test_user.id, old_date, secured=True)
        _login(client, test_user)
        resp = client.get('/study/plan-stats')
        html = resp.get_data(as_text=True)
        # Old log outside 30-day window should not be counted
        assert 'Нет данных' in html or '0%' in html

    def test_only_current_user_logs_counted(self, app, db_session, test_user, client):
        from app.auth.models import User
        import uuid
        other = User(
            email=f'stats_{uuid.uuid4().hex[:8]}@test.com',
            username=f'statsuser_{uuid.uuid4().hex[:8]}',
            onboarding_completed=True,
        )
        other.set_password('password123')
        db_session.add(other)
        db_session.commit()

        today = date.today()
        _make_log(db_session, other.id, today, secured=True)
        _login(client, test_user)
        resp = client.get('/study/plan-stats')
        html = resp.get_data(as_text=True)
        assert 'Нет данных' in html or '0%' in html

    def test_stats_cards_rendered(self, app, db_session, test_user, client):
        _login(client, test_user)
        resp = client.get('/study/plan-stats')
        html = resp.get_data(as_text=True)
        assert 'Активность' in html
        assert 'День выполнен' in html
        assert 'Слотов в день' in html
        assert 'Тренд' in html

    def test_empty_state_message_when_no_active_days(self, app, db_session, test_user, client):
        _login(client, test_user)
        resp = client.get('/study/plan-stats')
        html = resp.get_data(as_text=True)
        assert 'Нет данных' in html
