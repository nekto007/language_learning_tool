"""Tests for the use_mission_plan feature flag on User model."""
import uuid

import pytest

from app.auth.models import User
from app.utils.db import db


def _make_user(db_session, **overrides):
    suffix = uuid.uuid4().hex[:8]
    defaults = dict(
        username=f"flag_user_{suffix}",
        email=f"flag_{suffix}@test.com",
        password_hash="hash",
        salt="salt",
    )
    defaults.update(overrides)
    user = User(**defaults)
    db_session.add(user)
    db_session.flush()
    return user


class TestUseMissionPlanFlag:
    def test_defaults_to_false(self, db_session):
        user = _make_user(db_session)
        assert user.use_mission_plan is False

    def test_can_be_set_to_true(self, db_session):
        user = _make_user(db_session, use_mission_plan=True)
        assert user.use_mission_plan is True

    def test_can_be_toggled(self, db_session):
        user = _make_user(db_session)
        assert user.use_mission_plan is False

        user.use_mission_plan = True
        db_session.flush()
        assert user.use_mission_plan is True

        user.use_mission_plan = False
        db_session.flush()
        assert user.use_mission_plan is False

    def test_persists_after_refresh(self, db_session):
        user = _make_user(db_session, use_mission_plan=True)
        db_session.flush()
        db_session.expire(user)
        assert user.use_mission_plan is True

    def test_independent_per_user(self, db_session):
        user_a = _make_user(db_session, use_mission_plan=True)
        user_b = _make_user(db_session, use_mission_plan=False)
        assert user_a.use_mission_plan is True
        assert user_b.use_mission_plan is False
