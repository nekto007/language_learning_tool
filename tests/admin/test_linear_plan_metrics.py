"""Tests for the linear daily plan admin metrics aggregation."""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app.admin.services.linear_plan_metrics import get_linear_plan_metrics
from app.auth.models import User
from app.curriculum.models import LessonProgress
from app.daily_plan.linear.models import QuizErrorLog, UserReadingPreference
from app.daily_plan.models import DailyPlanLog
from app.study.models import StudySession


def _make_user(db_session, *, linear: bool = True, onboarded: bool = True) -> User:
    suffix = uuid.uuid4().hex[:8]
    user = User(
        username=f"lp_{suffix}",
        email=f"lp_{suffix}@example.com",
        active=True,
        onboarding_completed=onboarded,
        use_linear_plan=linear,
    )
    user.set_password("pw")
    db_session.add(user)
    db_session.commit()
    return user


def _make_book(db_session):
    """Create a minimal Book row for preference/reading-progress tests."""
    from app.books.models import Book

    book = Book(
        title=f"Book_{uuid.uuid4().hex[:6]}",
        author='Tester',
        level='B1',
        chapters_cnt=1,
        words_total=100,
        unique_words=80,
    )
    db_session.add(book)
    db_session.commit()
    return book


class TestCohortIsolation:
    def test_empty_cohort_returns_zero_metrics(self, app, db_session):
        metrics = get_linear_plan_metrics(session=db_session)
        assert metrics['cohort_size'] == 0
        assert metrics['day_secured_rate'] == 0.0
        assert metrics['average_slots_completed'] == 0.0
        assert metrics['error_review_trigger_rate'] == 0.0
        assert metrics['book_select_rate'] == 0.0

    def test_non_linear_users_excluded(self, app, db_session):
        _make_user(db_session, linear=False)
        _make_user(db_session, linear=False)
        metrics = get_linear_plan_metrics(session=db_session)
        assert metrics['cohort_size'] == 0

    def test_cohort_counts_only_linear_users(self, app, db_session):
        _make_user(db_session, linear=True)
        _make_user(db_session, linear=True)
        _make_user(db_session, linear=False)
        metrics = get_linear_plan_metrics(session=db_session)
        assert metrics['cohort_size'] == 2


class TestDaySecuredRate:
    def test_secured_today_counts_toward_rate(self, app, db_session):
        user = _make_user(db_session)
        today = datetime.now(timezone.utc).date()
        db_session.add(
            DailyPlanLog(
                user_id=user.id,
                plan_date=today,
                secured_at=datetime.now(timezone.utc),
            )
        )
        db_session.commit()

        metrics = get_linear_plan_metrics(session=db_session, today=today)
        assert metrics['day_secured_rate'] == 100.0

    def test_unsecured_log_excluded(self, app, db_session):
        user = _make_user(db_session)
        today = datetime.now(timezone.utc).date()
        db_session.add(DailyPlanLog(user_id=user.id, plan_date=today, secured_at=None))
        db_session.commit()

        metrics = get_linear_plan_metrics(session=db_session, today=today)
        assert metrics['day_secured_rate'] == 0.0

    def test_partial_secured_rate(self, app, db_session):
        u1 = _make_user(db_session)
        u2 = _make_user(db_session)
        today = datetime.now(timezone.utc).date()
        db_session.add(
            DailyPlanLog(
                user_id=u1.id,
                plan_date=today,
                secured_at=datetime.now(timezone.utc),
            )
        )
        db_session.commit()
        metrics = get_linear_plan_metrics(session=db_session, today=today)
        assert metrics['day_secured_rate'] == 50.0


class TestBookSelectRate:
    def test_single_selection_fills_rate(self, app, db_session):
        user = _make_user(db_session)
        book = _make_book(db_session)
        db_session.add(UserReadingPreference(user_id=user.id, book_id=book.id))
        db_session.commit()
        metrics = get_linear_plan_metrics(session=db_session)
        assert metrics['book_select_rate'] == 100.0

    def test_no_selection_is_zero(self, app, db_session):
        _make_user(db_session)
        metrics = get_linear_plan_metrics(session=db_session)
        assert metrics['book_select_rate'] == 0.0


class TestErrorReviewTriggerRate:
    def test_below_threshold_does_not_trigger(self, app, db_session, test_lesson_quiz):
        user = _make_user(db_session)
        for _ in range(4):
            db_session.add(
                QuizErrorLog(
                    user_id=user.id,
                    lesson_id=test_lesson_quiz.id,
                    question_payload={'q': 'x'},
                )
            )
        db_session.commit()
        metrics = get_linear_plan_metrics(session=db_session)
        assert metrics['error_review_trigger_rate'] == 0.0

    def test_above_threshold_without_recent_resolve_triggers(self, app, db_session, test_lesson_quiz):
        user = _make_user(db_session)
        for _ in range(5):
            db_session.add(
                QuizErrorLog(
                    user_id=user.id,
                    lesson_id=test_lesson_quiz.id,
                    question_payload={'q': 'x'},
                )
            )
        db_session.commit()
        metrics = get_linear_plan_metrics(session=db_session)
        assert metrics['error_review_trigger_rate'] == 100.0

    def test_high_backlog_overrides_default_cooldown(self, app, db_session, test_lesson_quiz):
        """At ≥15 unresolved, cooldown drops to 1 day (vs default 3d)."""
        user = _make_user(db_session)
        for _ in range(15):
            db_session.add(
                QuizErrorLog(
                    user_id=user.id,
                    lesson_id=test_lesson_quiz.id,
                    question_payload={'q': 'x'},
                )
            )
        # Resolved 2 days ago — past 1d high-backlog cooldown but inside default 3d.
        db_session.add(
            QuizErrorLog(
                user_id=user.id,
                lesson_id=test_lesson_quiz.id,
                question_payload={'q': 'r'},
                resolved_at=datetime.now(timezone.utc) - timedelta(days=2),
            )
        )
        db_session.commit()
        metrics = get_linear_plan_metrics(session=db_session)
        assert metrics['error_review_trigger_rate'] == 100.0

    def test_recent_resolve_suppresses_trigger(self, app, db_session, test_lesson_quiz):
        user = _make_user(db_session)
        for _ in range(5):
            db_session.add(
                QuizErrorLog(
                    user_id=user.id,
                    lesson_id=test_lesson_quiz.id,
                    question_payload={'q': 'x'},
                )
            )
        db_session.add(
            QuizErrorLog(
                user_id=user.id,
                lesson_id=test_lesson_quiz.id,
                question_payload={'q': 'resolved'},
                resolved_at=datetime.now(timezone.utc),
            )
        )
        db_session.commit()
        metrics = get_linear_plan_metrics(session=db_session)
        assert metrics['error_review_trigger_rate'] == 0.0


class TestAverageSlotsCompleted:
    def test_no_activity_is_zero(self, app, db_session):
        _make_user(db_session)
        metrics = get_linear_plan_metrics(session=db_session)
        assert metrics['average_slots_completed'] == 0.0

    def test_curriculum_completion_counts_as_one_slot(self, app, db_session, test_lesson_vocabulary):
        user = _make_user(db_session)
        today = datetime.now(timezone.utc).date()
        now = datetime.now(timezone.utc)
        db_session.add(
            LessonProgress(
                user_id=user.id,
                lesson_id=test_lesson_vocabulary.id,
                status='completed',
                completed_at=now,
            )
        )
        db_session.commit()
        metrics = get_linear_plan_metrics(session=db_session, today=today)
        assert metrics['average_slots_completed'] == 1.0

    def test_multiple_slots_accumulate(self, app, db_session, test_lesson_vocabulary):
        user = _make_user(db_session)
        today = datetime.now(timezone.utc).date()
        now = datetime.now(timezone.utc)
        db_session.add(
            LessonProgress(
                user_id=user.id,
                lesson_id=test_lesson_vocabulary.id,
                status='completed',
                completed_at=now,
            )
        )
        db_session.add(StudySession(user_id=user.id, start_time=now))
        db_session.commit()
        metrics = get_linear_plan_metrics(session=db_session, today=today)
        assert metrics['average_slots_completed'] == 2.0

    def test_yesterday_activity_does_not_count(self, app, db_session):
        user = _make_user(db_session)
        today = datetime.now(timezone.utc).date()
        yesterday = datetime.now(timezone.utc) - timedelta(days=1)
        db_session.add(StudySession(user_id=user.id, start_time=yesterday))
        db_session.commit()
        metrics = get_linear_plan_metrics(session=db_session, today=today)
        assert metrics['average_slots_completed'] == 0.0


class TestReadingGateCompletionRate:
    def _add_reading_xp_event(self, db_session, user_id, when):
        from app.achievements.models import StreakEvent

        db_session.add(
            StreakEvent(
                user_id=user_id,
                event_type='xp_linear',
                event_date=when,
                coins_delta=0,
                details={'source': 'linear_book_reading', 'xp': 15},
            )
        )

    def test_empty_cohort_is_zero(self, app, db_session):
        metrics = get_linear_plan_metrics(session=db_session)
        assert metrics['reading_gate_completion_rate'] == 0.0

    def test_no_xp_event_today_is_zero(self, app, db_session):
        _make_user(db_session)
        metrics = get_linear_plan_metrics(session=db_session)
        assert metrics['reading_gate_completion_rate'] == 0.0

    def test_single_user_with_event_fills_rate(self, app, db_session):
        user = _make_user(db_session)
        today = datetime.now(timezone.utc).date()
        self._add_reading_xp_event(db_session, user.id, today)
        db_session.commit()
        metrics = get_linear_plan_metrics(session=db_session, today=today)
        assert metrics['reading_gate_completion_rate'] == 100.0

    def test_partial_completion_rate(self, app, db_session):
        u1 = _make_user(db_session)
        _make_user(db_session)
        today = datetime.now(timezone.utc).date()
        self._add_reading_xp_event(db_session, u1.id, today)
        db_session.commit()
        metrics = get_linear_plan_metrics(session=db_session, today=today)
        assert metrics['reading_gate_completion_rate'] == 50.0

    def test_yesterday_event_does_not_count(self, app, db_session):
        user = _make_user(db_session)
        today = datetime.now(timezone.utc).date()
        yesterday = today - timedelta(days=1)
        self._add_reading_xp_event(db_session, user.id, yesterday)
        db_session.commit()
        metrics = get_linear_plan_metrics(session=db_session, today=today)
        assert metrics['reading_gate_completion_rate'] == 0.0

    def test_other_xp_source_does_not_count(self, app, db_session):
        from app.achievements.models import StreakEvent

        user = _make_user(db_session)
        today = datetime.now(timezone.utc).date()
        db_session.add(
            StreakEvent(
                user_id=user.id,
                event_type='xp_linear',
                event_date=today,
                coins_delta=0,
                details={'source': 'linear_srs_global', 'xp': 8},
            )
        )
        db_session.commit()
        metrics = get_linear_plan_metrics(session=db_session, today=today)
        assert metrics['reading_gate_completion_rate'] == 0.0


class TestErrorReviewCompletionRate:
    def _seed_unresolved(self, db_session, user, lesson, *, count=5, days_ago=1):
        """Seed backlog rows dated `days_ago` in the past.

        Rows must predate today to be counted as start-of-day backlog —
        a row created and resolved on the same day is not carryover.
        """
        backdated = datetime.now(timezone.utc) - timedelta(days=days_ago)
        for _ in range(count):
            db_session.add(
                QuizErrorLog(
                    user_id=user.id,
                    lesson_id=lesson.id,
                    question_payload={'q': 'x'},
                    answered_wrong_at=backdated,
                    created_at=backdated,
                )
            )
        db_session.commit()

    def test_zero_qualified_returns_zero(self, app, db_session):
        _make_user(db_session)
        metrics = get_linear_plan_metrics(session=db_session)
        assert metrics['error_review_completion_rate'] == 0.0

    def test_below_threshold_not_qualified(self, app, db_session, test_lesson_quiz):
        user = _make_user(db_session)
        # 3 unresolved + 1 resolved today = start-of-day 4, below threshold.
        self._seed_unresolved(db_session, user, test_lesson_quiz, count=3)
        db_session.add(
            QuizErrorLog(
                user_id=user.id,
                lesson_id=test_lesson_quiz.id,
                question_payload={'q': 'r'},
                resolved_at=datetime.now(timezone.utc),
            )
        )
        db_session.commit()
        metrics = get_linear_plan_metrics(session=db_session)
        assert metrics['error_review_completion_rate'] == 0.0

    def test_resolved_user_stays_in_denominator(self, app, db_session, test_lesson_quiz):
        """User who started day at 5 unresolved, resolved one, must remain qualified.

        Otherwise the metric drops them from both numerator and denominator
        and underreports the completions it tries to measure.
        """
        user = _make_user(db_session)
        self._seed_unresolved(db_session, user, test_lesson_quiz, count=5)
        # Resolve one of the backlog rows today.
        backlog_row = (
            db_session.query(QuizErrorLog)
            .filter(QuizErrorLog.user_id == user.id)
            .first()
        )
        backlog_row.resolved_at = datetime.now(timezone.utc)
        db_session.commit()
        today = datetime.now(timezone.utc).date()
        metrics = get_linear_plan_metrics(session=db_session, today=today)
        assert metrics['error_review_completion_rate'] == 100.0

    def test_all_qualified_resolved_today(self, app, db_session, test_lesson_quiz):
        user = _make_user(db_session)
        self._seed_unresolved(db_session, user, test_lesson_quiz, count=5)
        today = datetime.now(timezone.utc).date()
        # Resolve one of the backlog rows today.
        row = (
            db_session.query(QuizErrorLog)
            .filter(QuizErrorLog.user_id == user.id)
            .first()
        )
        row.resolved_at = datetime.now(timezone.utc)
        db_session.commit()
        metrics = get_linear_plan_metrics(session=db_session, today=today)
        assert metrics['error_review_completion_rate'] == 100.0

    def test_mixed_qualified_users(self, app, db_session, test_lesson_quiz):
        u1 = _make_user(db_session)
        u2 = _make_user(db_session)
        self._seed_unresolved(db_session, u1, test_lesson_quiz, count=5)
        self._seed_unresolved(db_session, u2, test_lesson_quiz, count=5)
        today = datetime.now(timezone.utc).date()
        # Only u1 resolves a backlog row today.
        u1_row = (
            db_session.query(QuizErrorLog)
            .filter(QuizErrorLog.user_id == u1.id)
            .first()
        )
        u1_row.resolved_at = datetime.now(timezone.utc)
        db_session.commit()
        metrics = get_linear_plan_metrics(session=db_session, today=today)
        assert metrics['error_review_completion_rate'] == 50.0

    def test_resolved_yesterday_does_not_count(self, app, db_session, test_lesson_quiz):
        user = _make_user(db_session)
        self._seed_unresolved(db_session, user, test_lesson_quiz, count=5)
        today = datetime.now(timezone.utc).date()
        db_session.add(
            QuizErrorLog(
                user_id=user.id,
                lesson_id=test_lesson_quiz.id,
                question_payload={'q': 'r'},
                resolved_at=datetime.now(timezone.utc) - timedelta(days=1),
            )
        )
        db_session.commit()
        metrics = get_linear_plan_metrics(session=db_session, today=today)
        assert metrics['error_review_completion_rate'] == 0.0


class TestReturnShape:
    def test_returns_all_expected_keys(self, app, db_session):
        _make_user(db_session)
        metrics = get_linear_plan_metrics(session=db_session)
        expected = {
            'cohort_size',
            'day_secured_rate',
            'average_slots_completed',
            'error_review_trigger_rate',
            'error_review_completion_rate',
            'book_select_rate',
            'reading_gate_completion_rate',
            'focus_distribution',
            'focus_average_slots',
        }
        assert expected.issubset(metrics.keys())


class TestFocusDistribution:
    def _set_focus(self, db_session, user, focus):
        user.onboarding_focus = focus
        db_session.commit()

    def test_empty_cohort_returns_zero_buckets(self, app, db_session):
        metrics = get_linear_plan_metrics(session=db_session)
        assert metrics['focus_distribution'] == {
            'grammar': 0, 'vocabulary': 0, 'reading': 0, 'all': 0, 'none': 0,
        }
        assert metrics['focus_average_slots'] == {
            'grammar': 0.0, 'vocabulary': 0.0, 'reading': 0.0, 'all': 0.0, 'none': 0.0,
        }

    def test_buckets_split_across_focuses(self, app, db_session):
        u_grammar = _make_user(db_session)
        u_vocab = _make_user(db_session)
        u_reading = _make_user(db_session)
        u_all = _make_user(db_session)
        u_none = _make_user(db_session)
        self._set_focus(db_session, u_grammar, 'grammar')
        self._set_focus(db_session, u_vocab, 'vocabulary,reading')
        self._set_focus(db_session, u_reading, 'reading')
        self._set_focus(db_session, u_all, 'all')
        # u_none has no focus set
        metrics = get_linear_plan_metrics(session=db_session)
        dist = metrics['focus_distribution']
        assert dist['grammar'] == 1
        assert dist['vocabulary'] == 1
        assert dist['reading'] == 1
        assert dist['all'] == 1
        assert dist['none'] == 1

    def test_unknown_focus_value_buckets_into_none(self, app, db_session):
        u = _make_user(db_session)
        self._set_focus(db_session, u, 'something_weird')
        metrics = get_linear_plan_metrics(session=db_session)
        assert metrics['focus_distribution']['none'] == 1

    def test_average_slots_per_focus(self, app, db_session, test_lesson_vocabulary):
        u_grammar1 = _make_user(db_session)
        u_grammar2 = _make_user(db_session)
        u_reading = _make_user(db_session)
        self._set_focus(db_session, u_grammar1, 'grammar')
        self._set_focus(db_session, u_grammar2, 'grammar')
        self._set_focus(db_session, u_reading, 'reading')

        today = datetime.now(timezone.utc).date()
        now = datetime.now(timezone.utc)
        # Only u_grammar1 completes a curriculum lesson today.
        db_session.add(
            LessonProgress(
                user_id=u_grammar1.id,
                lesson_id=test_lesson_vocabulary.id,
                status='completed',
                completed_at=now,
            )
        )
        db_session.commit()

        metrics = get_linear_plan_metrics(session=db_session, today=today)
        # grammar bucket: 1 slot across 2 users = 0.5 avg
        assert metrics['focus_average_slots']['grammar'] == 0.5
        # reading bucket: 0 slots / 1 user = 0.0
        assert metrics['focus_average_slots']['reading'] == 0.0
        # empty buckets stay 0.0
        assert metrics['focus_average_slots']['vocabulary'] == 0.0
