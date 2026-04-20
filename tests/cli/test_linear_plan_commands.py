"""CLI tests for the linear-plan-enable / linear-plan-disable Flask commands."""
from __future__ import annotations

import uuid

import pytest

from app.auth.models import User
from app.utils.db import db


@pytest.fixture
def cli_user(db_session):
    username = f'linearcli_{uuid.uuid4().hex[:8]}'
    user = User(
        username=username,
        email=f'{username}@example.com',
        active=True,
        onboarding_completed=True,
        use_linear_plan=False,
    )
    user.set_password('testpass123')
    db_session.add(user)
    db_session.commit()
    return user


class TestLinearPlanEnableCommand:
    def test_enable_flips_flag_to_true(self, app, db_session, cli_user):
        runner = app.test_cli_runner()

        result = runner.invoke(args=['linear-plan-enable', str(cli_user.id)])

        assert result.exit_code == 0
        assert f'use_linear_plan enabled for user_id={cli_user.id}' in result.output

        refreshed = db.session.get(User, cli_user.id)
        assert refreshed.use_linear_plan is True

    def test_enable_is_idempotent(self, app, db_session, cli_user):
        cli_user.use_linear_plan = True
        db_session.commit()
        runner = app.test_cli_runner()

        result = runner.invoke(args=['linear-plan-enable', str(cli_user.id)])

        assert result.exit_code == 0
        assert 'already enabled' in result.output

        refreshed = db.session.get(User, cli_user.id)
        assert refreshed.use_linear_plan is True

    def test_enable_missing_user_exits_nonzero(self, app, db_session):
        runner = app.test_cli_runner()

        result = runner.invoke(args=['linear-plan-enable', '9999999'])

        assert result.exit_code != 0
        assert 'not found' in result.output

    def test_enable_rejects_non_integer_id(self, app):
        runner = app.test_cli_runner()

        result = runner.invoke(args=['linear-plan-enable', 'not-an-int'])

        assert result.exit_code != 0


class TestLinearPlanDisableCommand:
    def test_disable_flips_flag_to_false(self, app, db_session, cli_user):
        cli_user.use_linear_plan = True
        db_session.commit()
        runner = app.test_cli_runner()

        result = runner.invoke(args=['linear-plan-disable', str(cli_user.id)])

        assert result.exit_code == 0
        assert f'use_linear_plan disabled for user_id={cli_user.id}' in result.output

        refreshed = db.session.get(User, cli_user.id)
        assert refreshed.use_linear_plan is False

    def test_disable_is_idempotent(self, app, db_session, cli_user):
        runner = app.test_cli_runner()

        result = runner.invoke(args=['linear-plan-disable', str(cli_user.id)])

        assert result.exit_code == 0
        assert 'already disabled' in result.output

        refreshed = db.session.get(User, cli_user.id)
        assert refreshed.use_linear_plan is False

    def test_disable_missing_user_exits_nonzero(self, app, db_session):
        runner = app.test_cli_runner()

        result = runner.invoke(args=['linear-plan-disable', '9999999'])

        assert result.exit_code != 0
        assert 'not found' in result.output


class TestToggleRoundTrip:
    def test_enable_then_disable(self, app, db_session, cli_user):
        runner = app.test_cli_runner()

        enable_result = runner.invoke(args=['linear-plan-enable', str(cli_user.id)])
        assert enable_result.exit_code == 0
        assert db.session.get(User, cli_user.id).use_linear_plan is True

        disable_result = runner.invoke(args=['linear-plan-disable', str(cli_user.id)])
        assert disable_result.exit_code == 0
        assert db.session.get(User, cli_user.id).use_linear_plan is False
