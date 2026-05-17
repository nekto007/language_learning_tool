"""Tests for the plan completion heatmap calendar route GET /study/calendar.

Task 43: Plan completion heatmap calendar.
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


class TestPlanCalendarRoute:
    def test_get_returns_200(self, app, db_session, test_user, client):
        _login(client, test_user)
        resp = client.get('/study/calendar')
        assert resp.status_code == 200

    def test_unauthenticated_redirects(self, app, db_session, client):
        resp = client.get('/study/calendar')
        assert resp.status_code in (302, 401, 403)

    def test_empty_state_shows_zero_secured(self, app, db_session, test_user, client):
        _login(client, test_user)
        resp = client.get('/study/calendar')
        html = resp.get_data(as_text=True)
        assert '0 дней выполнен план' in html

    def test_secured_day_shows_in_stats(self, app, db_session, test_user, client):
        today = date.today()
        _make_log(db_session, test_user.id, today, secured=True)
        _login(client, test_user)
        resp = client.get('/study/calendar')
        html = resp.get_data(as_text=True)
        assert '1 дней выполнен план' in html

    def test_secured_day_has_level2_cell(self, app, db_session, test_user, client):
        today = date.today()
        _make_log(db_session, test_user.id, today, secured=True)
        _login(client, test_user)
        resp = client.get('/study/calendar')
        html = resp.get_data(as_text=True)
        assert 'plan-calendar__cell--level-2' in html

    def test_active_but_not_secured_day_has_level1_cell(self, app, db_session, test_user, client):
        today = date.today()
        _make_log(db_session, test_user.id, today, secured=False)
        _login(client, test_user)
        resp = client.get('/study/calendar')
        html = resp.get_data(as_text=True)
        assert 'plan-calendar__cell--level-1' in html

    def test_empty_day_has_level0_cell(self, app, db_session, test_user, client):
        _login(client, test_user)
        resp = client.get('/study/calendar')
        html = resp.get_data(as_text=True)
        assert 'plan-calendar__cell--level-0' in html

    def test_total_active_count_includes_unsecured(self, app, db_session, test_user, client):
        today = date.today()
        yesterday = today - timedelta(days=1)
        _make_log(db_session, test_user.id, today, secured=True)
        _make_log(db_session, test_user.id, yesterday, secured=False)
        _login(client, test_user)
        resp = client.get('/study/calendar')
        html = resp.get_data(as_text=True)
        assert '2 активных дней' in html

    def test_days_outside_90_day_window_excluded(self, app, db_session, test_user, client):
        old_date = date.today() - timedelta(days=100)
        _make_log(db_session, test_user.id, old_date, secured=True)
        _login(client, test_user)
        resp = client.get('/study/calendar')
        html = resp.get_data(as_text=True)
        # Old secured day should not appear in stats
        assert '0 дней выполнен план' in html

    def test_data_date_attribute_present_for_active_days(self, app, db_session, test_user, client):
        today = date.today()
        _make_log(db_session, test_user.id, today, secured=True)
        _login(client, test_user)
        resp = client.get('/study/calendar')
        html = resp.get_data(as_text=True)
        assert f'data-date="{today.strftime("%Y-%m-%d")}"' in html

    def test_only_current_user_logs_counted(self, app, db_session, test_user, client):
        from app.auth.models import User
        import uuid
        other = User(
            email=f'cal_{uuid.uuid4().hex[:8]}@test.com',
            username=f'caluser_{uuid.uuid4().hex[:8]}',
            onboarding_completed=True,
        )
        other.set_password('password123')
        db_session.add(other)
        db_session.commit()

        today = date.today()
        _make_log(db_session, other.id, today, secured=True)
        _login(client, test_user)
        resp = client.get('/study/calendar')
        html = resp.get_data(as_text=True)
        assert '0 дней выполнен план' in html

    def test_calendar_grid_rendered(self, app, db_session, test_user, client):
        _login(client, test_user)
        resp = client.get('/study/calendar')
        html = resp.get_data(as_text=True)
        assert 'plan-calendar__grid' in html

    def test_secured_day_tooltip_text(self, app, db_session, test_user, client):
        today = date.today()
        _make_log(db_session, test_user.id, today, secured=True)
        _login(client, test_user)
        resp = client.get('/study/calendar')
        html = resp.get_data(as_text=True)
        assert 'план выполнен' in html
