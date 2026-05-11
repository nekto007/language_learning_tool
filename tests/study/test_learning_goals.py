"""Tests for Task 63: Learning goals settings page.

Covers:
- default values on User model
- POST /study/settings/goals saves values
- invalid inputs are clamped / rejected
- goals displayed in plan header
"""
from __future__ import annotations

import pytest

from app.auth.models import User
from app.utils.db import db


def _login(client, user) -> None:
    with client.session_transaction() as sess:
        sess['_user_id'] = str(user.id)
        sess['_fresh'] = True


class TestLearningGoalsModel:
    def test_default_daily_word_goal(self, test_user):
        assert test_user.daily_word_goal == 10

    def test_default_weekly_lesson_goal(self, test_user):
        assert test_user.weekly_lesson_goal == 5

    def test_set_daily_word_goal(self, db_session, test_user):
        test_user.daily_word_goal = 15
        db_session.commit()
        refreshed = db_session.get(User, test_user.id)
        assert refreshed.daily_word_goal == 15

    def test_set_weekly_lesson_goal(self, db_session, test_user):
        test_user.weekly_lesson_goal = 7
        db_session.commit()
        refreshed = db_session.get(User, test_user.id)
        assert refreshed.weekly_lesson_goal == 7


class TestLearningGoalsRoute:
    def test_post_saves_goals(self, app, db_session, test_user, client):
        _login(client, test_user)
        resp = client.post(
            '/study/settings/goals',
            data={'daily_word_goal': '15', 'weekly_lesson_goal': '7'},
            follow_redirects=True,
        )
        assert resp.status_code == 200
        refreshed = db_session.get(User, test_user.id)
        assert refreshed.daily_word_goal == 15
        assert refreshed.weekly_lesson_goal == 7

    def test_post_clamps_above_max(self, app, db_session, test_user, client):
        _login(client, test_user)
        resp = client.post(
            '/study/settings/goals',
            data={'daily_word_goal': '999', 'weekly_lesson_goal': '999'},
            follow_redirects=True,
        )
        assert resp.status_code == 200
        refreshed = db_session.get(User, test_user.id)
        assert refreshed.daily_word_goal == 50
        assert refreshed.weekly_lesson_goal == 30

    def test_post_clamps_below_min(self, app, db_session, test_user, client):
        _login(client, test_user)
        resp = client.post(
            '/study/settings/goals',
            data={'daily_word_goal': '0', 'weekly_lesson_goal': '0'},
            follow_redirects=True,
        )
        assert resp.status_code == 200
        refreshed = db_session.get(User, test_user.id)
        assert refreshed.daily_word_goal == 1
        assert refreshed.weekly_lesson_goal == 1

    def test_post_invalid_string_redirects(self, app, db_session, test_user, client):
        _login(client, test_user)
        resp = client.post(
            '/study/settings/goals',
            data={'daily_word_goal': 'abc', 'weekly_lesson_goal': 'xyz'},
            follow_redirects=True,
        )
        assert resp.status_code == 200

    def test_unauthenticated_redirects(self, client):
        resp = client.post(
            '/study/settings/goals',
            data={'daily_word_goal': '10', 'weekly_lesson_goal': '5'},
        )
        assert resp.status_code in (302, 401)

    def test_settings_page_shows_goal_form(self, app, db_session, test_user, client):
        _login(client, test_user)
        test_user.use_linear_plan = True
        db_session.commit()
        resp = client.get('/study/settings')
        assert resp.status_code == 200
        data = resp.data.decode('utf-8')
        assert 'daily_word_goal' in data
        assert 'weekly_lesson_goal' in data

    def test_settings_goal_form_hidden_without_linear_plan(self, app, db_session, test_user, client):
        _login(client, test_user)
        test_user.use_linear_plan = False
        db_session.commit()
        resp = client.get('/study/settings')
        assert resp.status_code == 200
        data = resp.data.decode('utf-8')
        assert 'settings_goals' not in data
