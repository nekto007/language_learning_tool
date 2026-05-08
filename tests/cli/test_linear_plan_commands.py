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


class TestLinearPlanStatusCommand:
    def test_status_missing_user_exits_nonzero(self, app, db_session):
        runner = app.test_cli_runner()

        result = runner.invoke(args=['linear-plan-status', '9999999'])

        assert result.exit_code != 0
        assert 'not found' in result.output

    def test_status_prints_summary_for_disabled_user(self, app, db_session, cli_user):
        runner = app.test_cli_runner()

        result = runner.invoke(args=['linear-plan-status', str(cli_user.id)])

        assert result.exit_code == 0
        assert f'user_id={cli_user.id}' in result.output
        assert 'use_linear_plan=False' in result.output
        assert 'unresolved_errors=' in result.output
        assert 'reading_preference:' in result.output
        assert 'recent_linear_xp' in result.output

    def test_status_includes_unresolved_and_recent_xp(self, app, db_session, cli_user):
        from datetime import date, datetime, timezone

        from app.achievements.models import StreakEvent
        from app.curriculum.models import CEFRLevel, Lessons, Module
        from app.daily_plan.linear.models import QuizErrorLog
        from app.daily_plan.linear.xp import LINEAR_XP_EVENT_TYPE

        cli_user.use_linear_plan = True

        suffix = uuid.uuid4().hex[:6].upper()
        level = CEFRLevel(code=suffix[:2], name='L', description='d', order=1)
        db_session.add(level)
        db_session.flush()
        module = Module(
            level_id=level.id, number=1, title='M', description='d',
            raw_content={'module': {'id': 1}},
        )
        db_session.add(module)
        db_session.flush()
        lesson = Lessons(module_id=module.id, number=1, title='L', type='quiz', content={})
        db_session.add(lesson)
        db_session.flush()

        for _ in range(3):
            db_session.add(QuizErrorLog(
                user_id=cli_user.id,
                lesson_id=lesson.id,
                question_payload={'question_index': uuid.uuid4().hex},
                answered_wrong_at=datetime.now(timezone.utc),
            ))

        db_session.add(StreakEvent(
            user_id=cli_user.id,
            event_type=LINEAR_XP_EVENT_TYPE,
            event_date=date.today(),
            coins_delta=0,
            details={'source': 'linear_curriculum_card', 'xp': 20},
        ))
        db_session.commit()

        runner = app.test_cli_runner()
        result = runner.invoke(args=['linear-plan-status', str(cli_user.id)])

        assert result.exit_code == 0
        assert 'use_linear_plan=True' in result.output
        assert 'unresolved_errors=3' in result.output
        assert 'linear_curriculum_card' in result.output
        assert 'xp=20' in result.output


class TestToggleRoundTrip:
    def test_enable_then_disable(self, app, db_session, cli_user):
        runner = app.test_cli_runner()

        enable_result = runner.invoke(args=['linear-plan-enable', str(cli_user.id)])
        assert enable_result.exit_code == 0
        assert db.session.get(User, cli_user.id).use_linear_plan is True

        disable_result = runner.invoke(args=['linear-plan-disable', str(cli_user.id)])
        assert disable_result.exit_code == 0
        assert db.session.get(User, cli_user.id).use_linear_plan is False
