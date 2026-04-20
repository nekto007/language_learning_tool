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


class TestReturnShape:
    def test_returns_all_expected_keys(self, app, db_session):
        _make_user(db_session)
        metrics = get_linear_plan_metrics(session=db_session)
        expected = {
            'cohort_size',
            'day_secured_rate',
            'average_slots_completed',
            'error_review_trigger_rate',
            'book_select_rate',
        }
        assert expected.issubset(metrics.keys())
