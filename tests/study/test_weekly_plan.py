"""Tests for the weekly plan overview route GET /study/weekly.

Task 44: Weekly plan overview page.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

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


class TestWeeklyPlanRoute:
    def test_get_returns_200(self, app, db_session, test_user, client):
        _login(client, test_user)
        resp = client.get('/study/weekly')
        assert resp.status_code == 200

    def test_unauthenticated_redirects(self, app, db_session, client):
        resp = client.get('/study/weekly')
        assert resp.status_code in (302, 401, 403)

    def test_seven_days_rendered(self, app, db_session, test_user, client):
        _login(client, test_user)
        resp = client.get('/study/weekly')
        html = resp.get_data(as_text=True)
        # Should contain 7 day cells in the grid
        assert html.count('weekly-plan__day') >= 7

    def test_today_shown_as_current(self, app, db_session, test_user, client):
        _login(client, test_user)
        resp = client.get('/study/weekly')
        html = resp.get_data(as_text=True)
        assert 'weekly-plan__day--current' in html

    def test_past_day_shows_daily_plan_log_data(self, app, db_session, test_user, client):
        today = date.today()
        yesterday = today - timedelta(days=1)
        _make_log(db_session, test_user.id, yesterday, secured=True)
        _login(client, test_user)
        resp = client.get('/study/weekly')
        html = resp.get_data(as_text=True)
        # Secured past day should render data-secured="true"
        assert 'data-secured="true"' in html

    def test_past_unsecured_day_has_activity_label(self, app, db_session, test_user, client):
        today = date.today()
        yesterday = today - timedelta(days=1)
        _make_log(db_session, test_user.id, yesterday, secured=False)
        _login(client, test_user)
        resp = client.get('/study/weekly')
        html = resp.get_data(as_text=True)
        assert 'Начат' in html

    def test_future_days_show_projected_slots(self, app, db_session, test_user, client):
        _login(client, test_user)
        resp = client.get('/study/weekly')
        html = resp.get_data(as_text=True)
        assert 'weekly-plan__day--future' in html
        assert 'Прогноз' in html

    def test_future_days_have_slot_icons(self, app, db_session, test_user, client):
        _login(client, test_user)
        resp = client.get('/study/weekly')
        html = resp.get_data(as_text=True)
        assert 'weekly-plan__slot-icon--curriculum' in html
        assert 'weekly-plan__slot-icon--srs' in html

    def test_today_shows_estimated_time(self, app, db_session, test_user, client):
        _login(client, test_user)
        resp = client.get('/study/weekly')
        html = resp.get_data(as_text=True)
        assert 'мин' in html

    def test_only_current_user_logs_shown(self, app, db_session, test_user, client):
        from app.auth.models import User
        import uuid
        other = User(
            email=f'wk_{uuid.uuid4().hex[:8]}@test.com',
            username=f'wkuser_{uuid.uuid4().hex[:8]}',
            onboarding_completed=True,
        )
        other.set_password('password123')
        db_session.add(other)
        db_session.commit()

        today = date.today()
        yesterday = today - timedelta(days=1)
        _make_log(db_session, other.id, yesterday, secured=True)
        _login(client, test_user)
        resp = client.get('/study/weekly')
        html = resp.get_data(as_text=True)
        # Other user's secured day should not count — test_user has no logs so no data-secured="true"
        assert 'data-secured="true"' not in html

    def test_today_cta_link_present(self, app, db_session, test_user, client):
        _login(client, test_user)
        resp = client.get('/study/weekly')
        html = resp.get_data(as_text=True)
        assert 'weekly-plan__cta' in html

    def test_weekly_link_on_study_index(self, app, db_session, test_user, client):
        _login(client, test_user)
        resp = client.get('/study/')
        html = resp.get_data(as_text=True)
        assert 'weekly_plan' in html or '/study/weekly' in html
