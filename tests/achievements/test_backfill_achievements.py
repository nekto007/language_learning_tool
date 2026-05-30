"""Tests for backfill_achievements script (Task 11).

Covers:
- A user with stats that cross multiple thresholds gets every applicable
  achievement on a single run_backfill call.
- Running twice doesn't double-grant (idempotency).
- dry_run mode computes grants but the caller can roll them back.
- Users with no stats get a UserStatistics record created automatically.
"""
from __future__ import annotations

import uuid

import pytest

from app.achievements.models import UserStatistics
from app.achievements.seed import seed_achievements
from app.auth.models import User
from app.study.models import Achievement, UserAchievement
from app.utils.db import db
from scripts.backfill_achievements import run_backfill, BackfillReport


def _make_user(db_session):
    suffix = uuid.uuid4().hex[:8]
    user = User(
        username=f'bf_{suffix}',
        email=f'bf_{suffix}@test.com',
        active=True,
    )
    user.set_password('test123')
    db_session.add(user)
    db_session.flush()
    return user


def _ensure_seeds(db_session):
    seed_achievements()
    db_session.flush()


class TestRunBackfill:

    def test_user_with_streak_gets_streak_achievements(self, db_session):
        _ensure_seeds(db_session)
        user = _make_user(db_session)
        stats = UserStatistics(
            user_id=user.id,
            current_streak_days=7,
            longest_streak_days=7,
        )
        db_session.add(stats)
        db_session.flush()

        report = run_backfill(db_session, dry_run=False)

        earned_codes = set()
        uas = UserAchievement.query.filter_by(user_id=user.id).all()
        for ua in uas:
            a = Achievement.query.get(ua.achievement_id)
            if a:
                earned_codes.add(a.code)

        assert 'daily_streak_3' in earned_codes, "daily_streak_3 expected for streak=7"
        assert 'daily_streak_7' in earned_codes, "daily_streak_7 expected for streak=7"
        assert report.total_users > 0

    def test_user_with_lessons_gets_lesson_achievements(self, db_session):
        _ensure_seeds(db_session)
        user = _make_user(db_session)
        stats = UserStatistics(
            user_id=user.id,
            total_lessons_completed=10,
        )
        db_session.add(stats)
        db_session.flush()

        run_backfill(db_session, dry_run=False)

        earned_codes = set()
        uas = UserAchievement.query.filter_by(user_id=user.id).all()
        for ua in uas:
            a = Achievement.query.get(ua.achievement_id)
            if a:
                earned_codes.add(a.code)

        assert 'first_lesson' in earned_codes
        assert 'lessons_5' in earned_codes
        assert 'lessons_10' in earned_codes

    def test_idempotent_two_runs_no_double_grant(self, db_session):
        _ensure_seeds(db_session)
        user = _make_user(db_session)
        stats = UserStatistics(
            user_id=user.id,
            current_streak_days=7,
            longest_streak_days=7,
            total_lessons_completed=5,
        )
        db_session.add(stats)
        db_session.flush()

        report1 = run_backfill(db_session, dry_run=False)

        count_after_first = UserAchievement.query.filter_by(user_id=user.id).count()

        report2 = run_backfill(db_session, dry_run=False)

        count_after_second = UserAchievement.query.filter_by(user_id=user.id).count()

        assert count_after_first == count_after_second, (
            "Second run must not grant additional achievements"
        )

        # Second run's report should show nothing newly granted for this user
        second_user_results = [r for r in report2.results if r.user_id == user.id]
        assert second_user_results == [], "No new grants expected on second run"

    def test_user_without_stats_gets_stats_created(self, db_session):
        _ensure_seeds(db_session)
        user = _make_user(db_session)
        # Verify no stats exist yet
        assert UserStatistics.query.filter_by(user_id=user.id).first() is None

        run_backfill(db_session, dry_run=False)

        stats = UserStatistics.query.filter_by(user_id=user.id).first()
        assert stats is not None, "UserStatistics should be created during backfill"

    def test_dry_run_reports_what_would_be_granted(self, db_session):
        """dry_run=True must return a report indicating what would be granted.

        Note: because check_* functions commit via savepoints internally,
        dry_run cannot guarantee no DB writes in the test environment.
        The important contract is that the CLI caller can rollback the outer
        transaction after run_backfill(dry_run=True).  Here we verify only
        that the report accurately reflects expected grants.
        """
        _ensure_seeds(db_session)
        user = _make_user(db_session)
        stats = UserStatistics(
            user_id=user.id,
            current_streak_days=30,
            longest_streak_days=30,
        )
        db_session.add(stats)
        db_session.flush()

        report = run_backfill(db_session, dry_run=True)

        # Report must identify this user as having achievements to grant
        assert report.total_users >= 1
        user_result = next((r for r in report.results if r.user_id == user.id), None)
        assert user_result is not None, (
            "dry_run report must list user with qualifying stats"
        )
        assert user_result.newly_granted >= 1
        assert any('daily_streak' in c for c in user_result.codes), (
            "streak achievement codes expected in dry_run report"
        )

    def test_report_counts_affected_users(self, db_session):
        _ensure_seeds(db_session)
        user = _make_user(db_session)
        stats = UserStatistics(
            user_id=user.id,
            total_lessons_completed=1,
        )
        db_session.add(stats)
        db_session.flush()

        report = run_backfill(db_session, dry_run=False)

        assert isinstance(report, BackfillReport)
        assert report.total_users >= 1
        user_result = next((r for r in report.results if r.user_id == user.id), None)
        assert user_result is not None, "User with threshold-crossing stats must appear in report"
        assert user_result.newly_granted >= 1
        assert 'first_lesson' in user_result.codes
