"""Tests for Task 65: Focus area override without re-onboarding."""
from __future__ import annotations

import pytest

from app.auth.models import User
from app.utils.db import db


def _login(client, user) -> None:
    with client.session_transaction() as sess:
        sess['_user_id'] = str(user.id)
        sess['_fresh'] = True


class TestFocusAreaRoute:
    def test_valid_focus_grammar(self, app, db_session, test_user, client):
        _login(client, test_user)
        resp = client.post(
            '/study/settings/focus',
            data={'onboarding_focus': 'grammar'},
            follow_redirects=True,
        )
        assert resp.status_code == 200
        refreshed = db_session.get(User, test_user.id)
        assert refreshed.onboarding_focus == 'grammar'

    def test_valid_focus_vocabulary(self, app, db_session, test_user, client):
        _login(client, test_user)
        resp = client.post(
            '/study/settings/focus',
            data={'onboarding_focus': 'vocabulary'},
            follow_redirects=True,
        )
        assert resp.status_code == 200
        refreshed = db_session.get(User, test_user.id)
        assert refreshed.onboarding_focus == 'vocabulary'

    def test_valid_focus_reading(self, app, db_session, test_user, client):
        _login(client, test_user)
        resp = client.post(
            '/study/settings/focus',
            data={'onboarding_focus': 'reading'},
            follow_redirects=True,
        )
        assert resp.status_code == 200
        refreshed = db_session.get(User, test_user.id)
        assert refreshed.onboarding_focus == 'reading'

    def test_valid_focus_speaking(self, app, db_session, test_user, client):
        _login(client, test_user)
        resp = client.post(
            '/study/settings/focus',
            data={'onboarding_focus': 'speaking'},
            follow_redirects=True,
        )
        assert resp.status_code == 200
        refreshed = db_session.get(User, test_user.id)
        assert refreshed.onboarding_focus == 'speaking'

    def test_focus_all_clears_field(self, app, db_session, test_user, client):
        _login(client, test_user)
        test_user.onboarding_focus = 'grammar'
        db_session.commit()
        resp = client.post(
            '/study/settings/focus',
            data={'onboarding_focus': 'all'},
            follow_redirects=True,
        )
        assert resp.status_code == 200
        refreshed = db_session.get(User, test_user.id)
        assert refreshed.onboarding_focus is None

    def test_invalid_focus_rejected(self, app, db_session, test_user, client):
        _login(client, test_user)
        original_focus = test_user.onboarding_focus
        resp = client.post(
            '/study/settings/focus',
            data={'onboarding_focus': 'invalid_value'},
            follow_redirects=True,
        )
        assert resp.status_code == 200
        refreshed = db_session.get(User, test_user.id)
        assert refreshed.onboarding_focus == original_focus

    def test_unauthenticated_redirects(self, client):
        resp = client.post(
            '/study/settings/focus',
            data={'onboarding_focus': 'grammar'},
        )
        assert resp.status_code in (302, 401)

    def test_settings_page_shows_focus_form(self, app, db_session, test_user, client):
        _login(client, test_user)
        test_user.use_linear_plan = True
        db_session.commit()
        resp = client.get('/study/settings')
        assert resp.status_code == 200
        data = resp.data.decode('utf-8')
        assert 'onboarding_focus' in data
        assert 'Акцент обучения' in data

    def test_settings_focus_form_hidden_without_linear_plan(self, app, db_session, test_user, client):
        _login(client, test_user)
        test_user.use_linear_plan = False
        db_session.commit()
        resp = client.get('/study/settings')
        assert resp.status_code == 200
        data = resp.data.decode('utf-8')
        assert 'settings_focus' not in data

    def test_focus_change_reflected_in_plan(self, app, db_session, test_user, client):
        from app.daily_plan.linear.plan import _get_user_focus
        _login(client, test_user)
        test_user.onboarding_focus = 'reading'
        db_session.commit()
        focus = _get_user_focus(test_user.id, db)
        assert focus == 'reading'

    def test_speaking_focus_reflected_in_plan(self, app, db_session, test_user, client):
        from app.daily_plan.linear.plan import _get_user_focus
        test_user.onboarding_focus = 'speaking'
        db_session.commit()
        focus = _get_user_focus(test_user.id, db)
        assert focus == 'speaking'

    def test_all_focus_returns_none_in_plan(self, app, db_session, test_user, client):
        from app.daily_plan.linear.plan import _get_user_focus
        test_user.onboarding_focus = None
        db_session.commit()
        focus = _get_user_focus(test_user.id, db)
        assert focus is None
