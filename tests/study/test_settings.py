"""Tests that onboarding_focus is reflected by _get_user_focus in the plan."""
from __future__ import annotations

import pytest

from app.auth.models import User
from app.utils.db import db


def _login(client, user) -> None:
    with client.session_transaction() as sess:
        sess['_user_id'] = str(user.id)
        sess['_fresh'] = True


class TestFocusReflectedInPlan:
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
