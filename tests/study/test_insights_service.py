"""Tests for get_writing_stats in insights_service.py.

Task 26: Writing accuracy analytics widget.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app.curriculum.models import CEFRLevel, Lessons, Module, UserWritingAttempt
from app.study.insights_service import get_writing_stats
from app.utils.db import db


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

def _unique_code() -> str:
    return uuid.uuid4().hex[:2].upper()


def _make_lesson(db_session) -> Lessons:
    code = _unique_code()
    level = CEFRLevel(code=code, name='Level', description='d', order=1)
    db_session.add(level)
    db_session.flush()
    module = Module(
        level_id=level.id,
        number=1,
        title='Module',
        description='d',
        raw_content={'module': {'id': 1}},
    )
    db_session.add(module)
    db_session.flush()
    lesson = Lessons(
        module_id=module.id,
        number=1,
        title='Writing Lesson',
        type='writing_prompt',
        content={'prompt': 'Describe your week.', 'min_words': 20},
    )
    db_session.add(lesson)
    db_session.flush()
    return lesson


def _make_attempt(
    db_session,
    user_id: int,
    lesson_id: int,
    text: str = 'hello world',
    days_ago: int = 0,
) -> UserWritingAttempt:
    created_at = datetime.now(timezone.utc) - timedelta(days=days_ago)
    attempt = UserWritingAttempt(
        user_id=user_id,
        lesson_id=lesson_id,
        response_text=text,
        word_count=len(text.split()),
        checklist_completed=True,
        created_at=created_at,
    )
    db_session.add(attempt)
    db_session.flush()
    return attempt


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestGetWritingStats:
    def test_zero_writing_returns_zeros(self, app, db_session, test_user):
        result = get_writing_stats(test_user.id)
        assert result['total_attempts'] == 0
        assert result['avg_word_count'] == 0.0
        assert result['consecutive_days'] == 0

    def test_total_attempts_counted(self, app, db_session, test_user):
        lesson = _make_lesson(db_session)
        _make_attempt(db_session, test_user.id, lesson.id, 'one two three')
        _make_attempt(db_session, test_user.id, lesson.id, 'four five six seven')
        result = get_writing_stats(test_user.id)
        assert result['total_attempts'] == 2

    def test_avg_word_count_correct(self, app, db_session, test_user):
        lesson = _make_lesson(db_session)
        # 3 words + 7 words = avg 5.0
        _make_attempt(db_session, test_user.id, lesson.id, 'one two three')
        _make_attempt(db_session, test_user.id, lesson.id, 'one two three four five six seven')
        result = get_writing_stats(test_user.id)
        assert result['avg_word_count'] == 5.0

    def test_consecutive_days_today(self, app, db_session, test_user):
        lesson = _make_lesson(db_session)
        _make_attempt(db_session, test_user.id, lesson.id, 'text today', days_ago=0)
        result = get_writing_stats(test_user.id)
        assert result['consecutive_days'] == 1

    def test_consecutive_days_streak_three(self, app, db_session, test_user):
        lesson = _make_lesson(db_session)
        for d in range(3):
            _make_attempt(db_session, test_user.id, lesson.id, 'daily writing', days_ago=d)
        result = get_writing_stats(test_user.id)
        assert result['consecutive_days'] == 3

    def test_gap_breaks_streak(self, app, db_session, test_user):
        lesson = _make_lesson(db_session)
        # Today and 3 days ago but not yesterday or 2 days ago
        _make_attempt(db_session, test_user.id, lesson.id, 'today', days_ago=0)
        _make_attempt(db_session, test_user.id, lesson.id, 'three days ago', days_ago=3)
        result = get_writing_stats(test_user.id)
        # Streak from today = 1 (gap at day 1)
        assert result['consecutive_days'] == 1

    def test_only_this_users_attempts_counted(self, app, db_session, test_user):
        from app.auth.models import User
        other = User(
            email=f'other_{uuid.uuid4().hex[:8]}@test.com',
            username=f'other_{uuid.uuid4().hex[:8]}',
            onboarding_completed=True,
        )
        other.set_password('pass')
        db_session.add(other)
        db_session.flush()

        lesson = _make_lesson(db_session)
        _make_attempt(db_session, other.id, lesson.id, 'other user text')
        result = get_writing_stats(test_user.id)
        assert result['total_attempts'] == 0
