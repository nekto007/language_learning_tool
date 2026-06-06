"""Regression tests for daily-plan robustness fixes #18, #19, #20, #21."""
from __future__ import annotations

import uuid
from datetime import date, datetime, timezone

from app.utils.db import db as app_db


# ── #20: had_recent_failures must not treat passed IS NULL as a failure ────────

def _attempt(db_session, user_id, lesson_id, *, passed, n, minutes_ago=0):
    from datetime import timedelta

    from app.curriculum.models import LessonAttempt
    when = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(minutes=minutes_ago)
    a = LessonAttempt(
        user_id=user_id, lesson_id=lesson_id, attempt_number=n,
        started_at=when, completed_at=when, passed=passed,
    )
    db_session.add(a)
    db_session.commit()
    return a


class TestHadRecentFailures:
    def test_all_failed_is_true(self, db_session, test_user, test_lesson_quiz):
        from app.daily_plan.items.error_review import (
            RECENT_FAILURE_WINDOW, had_recent_failures,
        )
        for i in range(RECENT_FAILURE_WINDOW):
            _attempt(db_session, test_user.id, test_lesson_quiz.id,
                     passed=False, n=i + 1, minutes_ago=RECENT_FAILURE_WINDOW - i)
        assert had_recent_failures(test_user.id, app_db) is True

    def test_null_passed_not_counted_as_failure(self, db_session, test_user, test_lesson_quiz):
        from app.daily_plan.items.error_review import (
            RECENT_FAILURE_WINDOW, had_recent_failures,
        )
        # All attempts incomplete (passed IS NULL) → not failures → no escalation.
        for i in range(RECENT_FAILURE_WINDOW + 1):
            _attempt(db_session, test_user.id, test_lesson_quiz.id,
                     passed=None, n=i + 1, minutes_ago=10 - i)
        assert had_recent_failures(test_user.id, app_db) is False

    def test_null_in_window_does_not_inflate_failures(self, db_session, test_user, test_lesson_quiz):
        # 2 real fails + 1 NULL: graded rows < window → not "all failed".
        _attempt(db_session, test_user.id, test_lesson_quiz.id, passed=False, n=1, minutes_ago=3)
        _attempt(db_session, test_user.id, test_lesson_quiz.id, passed=False, n=2, minutes_ago=2)
        _attempt(db_session, test_user.id, test_lesson_quiz.id, passed=None, n=3, minutes_ago=1)
        from app.daily_plan.items.error_review import had_recent_failures
        assert had_recent_failures(test_user.id, app_db) is False


# ── #18: reading item is None for a book with no chapters ─────────────────────

class TestReadingItemChapterless:
    def test_none_for_book_without_chapters(self, db_session, test_user):
        from app.books.models import Book
        from app.daily_plan.items.reading import build_reading_item
        from app.daily_plan.linear.models import UserReadingPreference

        book = Book(title='Empty', author='A', level='A1', chapters_cnt=0)
        db_session.add(book)
        db_session.flush()
        db_session.add(UserReadingPreference(user_id=test_user.id, book_id=book.id))
        db_session.commit()

        assert build_reading_item(test_user.id, app_db) is None


# ── #19: write_secured_at is idempotent and never duplicates the row ──────────

class TestWriteSecuredAt:
    def test_idempotent_no_duplicate_row(self, db_session, test_user):
        from app.daily_plan.models import DailyPlanLog
        from app.daily_plan.service import write_secured_at

        plan_date = date(2026, 6, 6)
        write_secured_at(test_user.id, plan_date)
        db_session.commit()

        row = DailyPlanLog.query.filter_by(
            user_id=test_user.id, plan_date=plan_date,
        ).first()
        assert row is not None
        assert row.secured_at is not None
        first_ts = row.secured_at

        # Second call: must not duplicate the row nor reset secured_at.
        write_secured_at(test_user.id, plan_date)
        db_session.commit()

        rows = DailyPlanLog.query.filter_by(
            user_id=test_user.id, plan_date=plan_date,
        ).all()
        assert len(rows) == 1
        assert rows[0].secured_at == first_ts


# ── #21: get_topic_sibling_exercises uses positional case() (SA 2.0 ready) ────

class TestSiblingExercisesCase:
    def test_query_executes_without_error(self, db_session):
        from app.daily_plan.linear.errors import get_topic_sibling_exercises
        from app.grammar_lab.models import GrammarExercise, GrammarTopic

        suffix = uuid.uuid4().hex[:8]
        topic = GrammarTopic(
            slug=f'sib-{suffix}', title='Sib', title_ru='Сиб', level='B1',
            order=1, content={'introduction': 'x', 'sections': []},
            estimated_time=10, difficulty=2,
        )
        db_session.add(topic)
        db_session.flush()
        content_by_type = {
            'multiple_choice': {'question': 'q', 'options': ['a', 'b'], 'correct_answer': 'a'},
            'fill_blank': {'sentence': '___', 'correct_answer': 'a'},
            'reorder': {'correct_answer': 'a b'},
        }
        for i, ex_type in enumerate(content_by_type):
            db_session.add(GrammarExercise(
                topic_id=topic.id, exercise_type=ex_type,
                content=content_by_type[ex_type],
                difficulty=1, order=i,
            ))
        db_session.commit()

        # The positional case() must build & run; multiple_choice ranks first.
        rows = get_topic_sibling_exercises(topic.id, set(), app_db, count=2)
        assert isinstance(rows, list)
        assert len(rows) == 2
        assert rows[0].exercise_type == 'multiple_choice'
