"""Tests for cohort_service: conversion funnel and cohort retention."""
import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app.auth.models import User
from app.daily_plan.models import DailyPlanLog
from app.utils.db import db


def _make_user(db_session, *, registered_days_ago: int = 1, onboarding_done: bool = False) -> User:
    name = f'u_{uuid.uuid4().hex[:8]}'
    user = User(username=name, email=f'{name}@test.com', active=True)
    user.set_password('pass')
    user.onboarding_completed = onboarding_done
    # Back-date created_at
    user.created_at = datetime.now(timezone.utc) - timedelta(days=registered_days_ago)
    db_session.add(user)
    db_session.flush()
    return user


def _make_plan_log(db_session, user_id: int, *, days_after_reg: float = 0.1) -> DailyPlanLog:
    log = DailyPlanLog(
        user_id=user_id,
        plan_date=(datetime.now(timezone.utc) - timedelta(days=1)).date(),
    )
    db_session.add(log)
    db_session.flush()
    return log


def _make_secured_plan_log(db_session, user_id: int) -> DailyPlanLog:
    log = DailyPlanLog(
        user_id=user_id,
        plan_date=(datetime.now(timezone.utc) - timedelta(days=1)).date(),
        secured_at=datetime.now(timezone.utc) - timedelta(hours=2),
    )
    db_session.add(log)
    db_session.flush()
    return log


class TestGetFunnelData:
    """Verify get_funnel_data shapes and counts."""

    @pytest.mark.smoke
    def test_empty_db_returns_zeros(self, app, db_session):
        """With no users, all funnel counts are 0."""
        from app.admin.services.cohort_service import get_funnel_data

        result = get_funnel_data(db_session, days=30)
        assert result.days == 30
        assert len(result.steps) == 6
        for step in result.steps:
            assert step.count == 0

    def test_registered_step_counts_only_recent(self, app, db_session):
        """Only users registered within `days` window are counted."""
        from app.admin.services.cohort_service import get_funnel_data

        recent_user = _make_user(db_session, registered_days_ago=5)
        old_user = _make_user(db_session, registered_days_ago=60)
        db_session.commit()

        result = get_funnel_data(db_session, days=30)
        registered_step = result.steps[0]
        # recent user should be counted, old user should not
        assert registered_step.count >= 1

        result_7d = get_funnel_data(db_session, days=3)
        assert result_7d.steps[0].count == 0  # recent user registered 5 days ago, outside 3-day window

    def test_onboarding_step_counts_completed(self, app, db_session):
        """Users with onboarding_completed=True are counted in the onboarding step."""
        from app.admin.services.cohort_service import get_funnel_data

        u1 = _make_user(db_session, registered_days_ago=2, onboarding_done=True)
        u2 = _make_user(db_session, registered_days_ago=2, onboarding_done=False)
        db_session.commit()

        result = get_funnel_data(db_session, days=30)
        onboarding_step = result.steps[1]
        # At least u1 should be counted
        assert onboarding_step.count >= 1

    def test_first_plan_step_counts_plan_users(self, app, db_session):
        """Users with any DailyPlanLog appear in first_plan_built step."""
        from app.admin.services.cohort_service import get_funnel_data

        u1 = _make_user(db_session, registered_days_ago=5, onboarding_done=True)
        u2 = _make_user(db_session, registered_days_ago=5, onboarding_done=True)
        _make_plan_log(db_session, u1.id)
        # u2 has no plan
        db_session.commit()

        result = get_funnel_data(db_session, days=30)
        first_plan_step = result.steps[2]
        assert first_plan_step.count >= 1

    def test_day_secured_step_counts_secured_plans(self, app, db_session):
        """Users with secured_at plan appear in day_secured step."""
        from app.admin.services.cohort_service import get_funnel_data

        u1 = _make_user(db_session, registered_days_ago=5, onboarding_done=True)
        u2 = _make_user(db_session, registered_days_ago=5, onboarding_done=True)
        _make_plan_log(db_session, u1.id)  # not secured
        _make_secured_plan_log(db_session, u2.id)  # secured
        db_session.commit()

        result = get_funnel_data(db_session, days=30)
        day_secured_step = result.steps[3]
        assert day_secured_step.count >= 1

    def test_funnel_step_counts_are_monotonic_non_increasing(self, app, db_session):
        """Each funnel step has count <= previous step (true subset semantics)."""
        from app.admin.services.cohort_service import get_funnel_data

        # User who built a plan but never completed onboarding should NOT
        # advance past the onboarding step in the funnel.
        u = _make_user(db_session, registered_days_ago=5, onboarding_done=False)
        _make_plan_log(db_session, u.id)
        db_session.commit()

        result = get_funnel_data(db_session, days=30)
        counts = [s.count for s in result.steps]
        for i in range(1, len(counts)):
            assert counts[i] <= counts[i - 1], (
                f'Step {i} ({counts[i]}) exceeds previous step ({counts[i-1]}); '
                'funnel should be monotonic non-increasing.'
            )

    def test_conversion_from_top_always_present(self, app, db_session):
        """All steps have conversion_from_top populated."""
        from app.admin.services.cohort_service import get_funnel_data

        _make_user(db_session, registered_days_ago=2)
        db_session.commit()

        result = get_funnel_data(db_session, days=30)
        for step in result.steps:
            assert step.conversion_from_top is not None
            assert 0.0 <= step.conversion_from_top <= 100.0

    def test_first_step_has_no_conversion_from_prev(self, app, db_session):
        """The first step (registered) has no conversion_from_prev."""
        from app.admin.services.cohort_service import get_funnel_data

        result = get_funnel_data(db_session, days=30)
        assert result.steps[0].conversion_from_prev is None

    def test_subsequent_steps_have_conversion_from_prev(self, app, db_session):
        """Steps 2+ have conversion_from_prev."""
        from app.admin.services.cohort_service import get_funnel_data

        _make_user(db_session, registered_days_ago=2, onboarding_done=True)
        db_session.commit()

        result = get_funnel_data(db_session, days=30)
        for step in result.steps[1:]:
            assert step.conversion_from_prev is not None

    def test_admin_users_excluded(self, app, db_session):
        """Admin users are not counted in the funnel."""
        from app.admin.services.cohort_service import get_funnel_data

        admin = _make_user(db_session, registered_days_ago=2)
        admin.is_admin = True
        db_session.commit()

        result = get_funnel_data(db_session, days=30)
        # Admin user should not be counted
        assert result.steps[0].count == 0

    def test_zero_users_monotonic_and_safe(self, app, db_session):
        """With zero users, all counts are 0 and conversions are safe (no div-by-zero)."""
        from app.admin.services.cohort_service import get_funnel_data

        result = get_funnel_data(db_session, days=30)
        counts = [s.count for s in result.steps]
        assert counts == [0, 0, 0, 0, 0, 0]
        # First step has no prev; all conv_top must be 0 (no users at top)
        assert result.steps[0].conversion_from_prev is None
        for step in result.steps:
            assert step.conversion_from_top == 0.0

    def test_single_user_full_path_monotonic(self, app, db_session):
        """A single user who registered, onboarded, built a plan, and secured a day
        produces a strictly non-increasing funnel (each ≤ previous).
        """
        from app.admin.services.cohort_service import get_funnel_data

        u = _make_user(db_session, registered_days_ago=2, onboarding_done=True)
        _make_secured_plan_log(db_session, u.id)
        db_session.commit()

        result = get_funnel_data(db_session, days=30)
        counts = [s.count for s in result.steps]
        # Step counts: registered, onboarding, first_plan, day_secured, ret7, ret30
        # First four should be 1, retention windows depend on activity timing but
        # must stay ≤ day_secured.
        assert counts[0] == 1
        assert counts[1] == 1
        assert counts[2] == 1
        assert counts[3] == 1
        for i in range(1, len(counts)):
            assert counts[i] <= counts[i - 1], (
                f'Step {i} ({counts[i]}) exceeds previous step ({counts[i-1]})'
            )

    def test_mixed_cohort_monotonic(self, app, db_session):
        """Several users at various funnel depths still produce monotonic counts."""
        from app.admin.services.cohort_service import get_funnel_data

        # u1: registered only
        _make_user(db_session, registered_days_ago=2, onboarding_done=False)
        # u2: onboarded
        _make_user(db_session, registered_days_ago=2, onboarding_done=True)
        # u3: onboarded + plan
        u3 = _make_user(db_session, registered_days_ago=3, onboarding_done=True)
        _make_plan_log(db_session, u3.id)
        # u4: onboarded + secured
        u4 = _make_user(db_session, registered_days_ago=4, onboarding_done=True)
        _make_secured_plan_log(db_session, u4.id)
        db_session.commit()

        result = get_funnel_data(db_session, days=30)
        counts = [s.count for s in result.steps]
        for i in range(1, len(counts)):
            assert counts[i] <= counts[i - 1], (
                f'Step {i} ({counts[i]}) exceeds previous step ({counts[i-1]}); counts={counts}'
            )


class TestGetCohortRetention:
    """Verify get_cohort_retention returns correct structure."""

    @pytest.mark.smoke
    def test_returns_correct_number_of_weeks(self, app, db_session):
        """Returns exactly `weeks` CohortWeek entries."""
        from app.admin.services.cohort_service import get_cohort_retention

        result = get_cohort_retention(db_session, weeks=4)
        assert len(result) == 4

    def test_empty_cohort_weeks_have_none_pcts(self, app, db_session):
        """Weeks with no users have cohort_size=0 and None percentages."""
        from app.admin.services.cohort_service import get_cohort_retention

        result = get_cohort_retention(db_session, weeks=4)
        for cohort in result:
            if cohort.cohort_size == 0:
                assert cohort.day1_pct is None
                assert cohort.day7_pct is None
                assert cohort.day30_pct is None

    def test_week_with_user_has_cohort_size(self, app, db_session):
        """A week with a registered user has cohort_size >= 1."""
        from app.admin.services.cohort_service import get_cohort_retention

        _make_user(db_session, registered_days_ago=3)
        db_session.commit()

        result = get_cohort_retention(db_session, weeks=4)
        sizes = [c.cohort_size for c in result]
        assert max(sizes) >= 1

    def test_week_labels_are_strings(self, app, db_session):
        """All week_label fields are non-empty strings."""
        from app.admin.services.cohort_service import get_cohort_retention

        result = get_cohort_retention(db_session, weeks=4)
        for cohort in result:
            assert isinstance(cohort.week_label, str)
            assert len(cohort.week_label) > 0

    def test_week_start_is_iso_date(self, app, db_session):
        """All week_start fields are ISO date strings (YYYY-MM-DD)."""
        from app.admin.services.cohort_service import get_cohort_retention

        result = get_cohort_retention(db_session, weeks=4)
        for cohort in result:
            assert len(cohort.week_start) == 10
            assert cohort.week_start[4] == '-'
            assert cohort.week_start[7] == '-'

    def test_day1_pct_with_plan_activity(self, app, db_session):
        """User who builds a plan within 48h of registration is counted in day1."""
        from app.admin.services.cohort_service import get_cohort_retention
        from datetime import date

        user = _make_user(db_session, registered_days_ago=5)
        # Create a plan log with created_at 2 hours after registration
        log = DailyPlanLog(
            user_id=user.id,
            plan_date=date.today(),
        )
        # Manually set created_at to be 2 hours after user registration
        log.created_at = user.created_at + timedelta(hours=2)
        db_session.add(log)
        db_session.commit()

        result = get_cohort_retention(db_session, weeks=4)
        # Find the cohort week that contains this user
        matching = [c for c in result if c.cohort_size > 0]
        assert len(matching) >= 1
        # day1_pct should be > 0 since user had plan activity within 48h
        assert matching[0].day1_pct is not None
        assert matching[0].day1_pct > 0


class TestActivityFunnelRoute:
    """Verify the /admin/activity/funnel route renders correctly."""

    @pytest.mark.smoke
    def test_funnel_route_returns_200(self, app, client, admin_user):
        """Admin can access the funnel page."""
        resp = client.get('/admin/activity/funnel')
        assert resp.status_code == 200

    def test_funnel_route_with_days_param(self, app, client, admin_user):
        """Funnel route accepts valid days query param."""
        resp = client.get('/admin/activity/funnel?days=7&weeks=4')
        assert resp.status_code == 200

    def test_funnel_route_invalid_days_falls_back(self, app, client, admin_user):
        """Invalid days value falls back to 30."""
        resp = client.get('/admin/activity/funnel?days=999')
        assert resp.status_code == 200

    def test_funnel_route_contains_chart_canvas(self, app, client, admin_user):
        """Response contains the Chart.js canvas element."""
        resp = client.get('/admin/activity/funnel')
        html = resp.data.decode('utf-8')
        assert 'funnelChart' in html

    def test_funnel_route_contains_cohort_table(self, app, client, admin_user):
        """Response contains the cohort retention table."""
        resp = client.get('/admin/activity/funnel')
        html = resp.data.decode('utf-8')
        assert 'Когортное удержание' in html

    def test_funnel_route_invalid_weeks_falls_back(self, app, client, admin_user):
        """Invalid weeks value (not in whitelist) falls back to 8."""
        resp = client.get('/admin/activity/funnel?weeks=3')
        assert resp.status_code == 200

    def test_funnel_route_negative_days_falls_back(self, app, client, admin_user):
        """Negative days value falls back to 30 (whitelist rejects it)."""
        resp = client.get('/admin/activity/funnel?days=-1')
        assert resp.status_code == 200

    def test_funnel_route_zero_days_falls_back(self, app, client, admin_user):
        """days=0 is not in whitelist, falls back to 30."""
        resp = client.get('/admin/activity/funnel?days=0')
        assert resp.status_code == 200

    def test_funnel_route_all_valid_days_accepted(self, app, client, admin_user):
        """All whitelisted days values are accepted without error."""
        for d in (7, 14, 30, 60, 90):
            resp = client.get(f'/admin/activity/funnel?days={d}')
            assert resp.status_code == 200, f'days={d} should be valid'

    def test_funnel_route_all_valid_weeks_accepted(self, app, client, admin_user):
        """All whitelisted weeks values are accepted without error."""
        for w in (4, 8, 12, 16):
            resp = client.get(f'/admin/activity/funnel?weeks={w}')
            assert resp.status_code == 200, f'weeks={w} should be valid'


class TestNaiveDatetimeHandling:
    """Verify cohort service uses naive UTC datetimes consistently."""

    def test_get_funnel_data_does_not_raise_with_tz_naive_db(self, app, db_session):
        """get_funnel_data succeeds without tz-aware/naive mismatch errors."""
        from app.admin.services.cohort_service import get_funnel_data

        u = _make_user(db_session, registered_days_ago=2, onboarding_done=True)
        db_session.commit()

        # Should not raise DatatypeMismatch or similar tz-mix errors
        result = get_funnel_data(db_session, days=30)
        assert result is not None
        assert all(step.count >= 0 for step in result.steps)

    def test_get_cohort_retention_does_not_raise(self, app, db_session):
        """get_cohort_retention completes without tz-aware datetime errors."""
        from app.admin.services.cohort_service import get_cohort_retention

        _make_user(db_session, registered_days_ago=3)
        db_session.commit()

        result = get_cohort_retention(db_session, weeks=4)
        assert len(result) == 4
        for week in result:
            # pct values, when present, must be in [0, 100]
            if week.day1_pct is not None:
                assert 0.0 <= week.day1_pct <= 100.0
            if week.day7_pct is not None:
                assert 0.0 <= week.day7_pct <= 100.0
            if week.day30_pct is not None:
                assert 0.0 <= week.day30_pct <= 100.0

    def test_funnel_generated_at_is_aware(self, app, db_session):
        """FunnelData.generated_at is timezone-aware (UTC) for display purposes."""
        from app.admin.services.cohort_service import get_funnel_data

        result = get_funnel_data(db_session, days=30)
        assert result.generated_at.tzinfo is not None

    def test_zero_cohort_retention_returns_none_pcts(self, app, db_session):
        """When cohort has 0 users, all percentage fields are None."""
        from app.admin.services.cohort_service import get_cohort_retention

        result = get_cohort_retention(db_session, weeks=4)
        # No users were created, so all cohorts have size 0
        for week in result:
            assert week.cohort_size == 0
            assert week.day1_pct is None
            assert week.day7_pct is None
            assert week.day30_pct is None

    def test_funnel_with_zero_registered_no_division_error(self, app, db_session):
        """Funnel with 0 registered users produces 0.0 conversion_from_top (no ZeroDivisionError)."""
        from app.admin.services.cohort_service import get_funnel_data

        result = get_funnel_data(db_session, days=30)
        for step in result.steps:
            assert step.conversion_from_top == 0.0
