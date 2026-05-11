"""Tests for insights_service.py.

Task 26: Writing accuracy analytics widget.
Task 39: Vocabulary growth chart on dashboard.
Task 57: Pronunciation weakness detection.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app.curriculum.models import CEFRLevel, Lessons, Module, UserWritingAttempt, PronunciationAttempt
from app.study.insights_service import get_writing_stats, get_vocabulary_growth, get_pronunciation_weaknesses
from app.study.models import UserCardDirection, UserWord
from app.words.models import CollectionWords
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


# ---------------------------------------------------------------------------
# Helpers for vocabulary growth tests
# ---------------------------------------------------------------------------

def _make_collection_word(db_session) -> CollectionWords:
    word = CollectionWords(
        english_word=f'testword_{uuid.uuid4().hex[:8]}',
        russian_word='тест',
        level='A1',
    )
    db_session.add(word)
    db_session.flush()
    return word


def _make_user_word(db_session, user_id: int, days_ago: int = 0) -> UserWord:
    word = _make_collection_word(db_session)
    uw = UserWord(user_id=user_id, word_id=word.id)
    uw.created_at = datetime.now(timezone.utc) - timedelta(days=days_ago)
    db_session.add(uw)
    db_session.flush()
    return uw


def _make_card_direction(db_session, user_word_id: int, state: str = 'new') -> UserCardDirection:
    card = UserCardDirection(user_word_id=user_word_id, direction='eng-rus')
    card.state = state
    db_session.add(card)
    db_session.flush()
    return card


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestGetVocabularyGrowth:
    def test_empty_user_returns_zeros(self, app, db_session, test_user):
        result = get_vocabulary_growth(test_user.id, days=7)
        assert result['total_active'] == 0
        assert result['words_this_week'] == 0
        assert len(result['dates']) == 7
        assert len(result['counts']) == 7
        assert all(c == 0 for c in result['counts'])

    def test_dates_length_matches_days(self, app, db_session, test_user):
        result = get_vocabulary_growth(test_user.id, days=14)
        assert len(result['dates']) == 14
        assert len(result['counts']) == 14

    def test_word_added_today_counted(self, app, db_session, test_user):
        _make_user_word(db_session, test_user.id, days_ago=0)
        result = get_vocabulary_growth(test_user.id, days=7)
        # Today is the last element
        assert result['counts'][-1] == 1
        assert result['words_this_week'] == 1

    def test_word_added_three_days_ago_counted(self, app, db_session, test_user):
        _make_user_word(db_session, test_user.id, days_ago=3)
        result = get_vocabulary_growth(test_user.id, days=7)
        assert result['counts'][-4] == 1

    def test_total_active_counts_reviewed_cards(self, app, db_session, test_user):
        uw1 = _make_user_word(db_session, test_user.id, days_ago=0)
        uw2 = _make_user_word(db_session, test_user.id, days_ago=0)
        _make_card_direction(db_session, uw1.id, state='review')
        _make_card_direction(db_session, uw2.id, state='new')
        result = get_vocabulary_growth(test_user.id, days=7)
        assert result['total_active'] == 1

    def test_total_active_excludes_new_state(self, app, db_session, test_user):
        uw = _make_user_word(db_session, test_user.id, days_ago=0)
        _make_card_direction(db_session, uw.id, state='new')
        result = get_vocabulary_growth(test_user.id, days=7)
        assert result['total_active'] == 0

    def test_words_this_week_sums_last_7(self, app, db_session, test_user):
        for d in range(3):
            _make_user_word(db_session, test_user.id, days_ago=d)
        # 1 word added 35 days ago — outside the 7-day window
        _make_user_word(db_session, test_user.id, days_ago=35)
        result = get_vocabulary_growth(test_user.id, days=30)
        # words_this_week = sum of last 7 counts: 3 words in last 7 days
        assert result['words_this_week'] == 3

    def test_other_users_words_excluded(self, app, db_session, test_user):
        from app.auth.models import User
        other = User(
            email=f'other_{uuid.uuid4().hex[:8]}@test.com',
            username=f'other_{uuid.uuid4().hex[:8]}',
            onboarding_completed=True,
        )
        other.set_password('pass')
        db_session.add(other)
        db_session.flush()
        _make_user_word(db_session, other.id, days_ago=0)
        result = get_vocabulary_growth(test_user.id, days=7)
        assert result['words_this_week'] == 0
        assert result['total_active'] == 0


# ---------------------------------------------------------------------------
# Helpers for pronunciation weakness tests
# ---------------------------------------------------------------------------

def _make_pronunciation_attempt(
    db_session,
    user_id: int,
    word: str,
    matched: bool,
) -> PronunciationAttempt:
    attempt = PronunciationAttempt(
        user_id=user_id,
        word=word,
        recognized_text=word if matched else 'wrong',
        matched=matched,
    )
    db_session.add(attempt)
    db_session.flush()
    return attempt


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestGetPronunciationWeaknesses:
    def test_no_attempts_returns_empty(self, app, db_session, test_user):
        result = get_pronunciation_weaknesses(test_user.id)
        assert result == []

    def test_word_with_low_match_rate_returned(self, app, db_session, test_user):
        # 1 matched out of 4 = 25% → weak
        _make_pronunciation_attempt(db_session, test_user.id, 'hello', matched=True)
        _make_pronunciation_attempt(db_session, test_user.id, 'hello', matched=False)
        _make_pronunciation_attempt(db_session, test_user.id, 'hello', matched=False)
        _make_pronunciation_attempt(db_session, test_user.id, 'hello', matched=False)
        result = get_pronunciation_weaknesses(test_user.id)
        assert 'hello' in result

    def test_word_with_high_match_rate_not_returned(self, app, db_session, test_user):
        # 3 matched out of 4 = 75% → not weak
        _make_pronunciation_attempt(db_session, test_user.id, 'world', matched=True)
        _make_pronunciation_attempt(db_session, test_user.id, 'world', matched=True)
        _make_pronunciation_attempt(db_session, test_user.id, 'world', matched=True)
        _make_pronunciation_attempt(db_session, test_user.id, 'world', matched=False)
        result = get_pronunciation_weaknesses(test_user.id)
        assert 'world' not in result

    def test_fewer_than_min_attempts_excluded(self, app, db_session, test_user):
        # 2 attempts (< default min_attempts=3), both mismatched → still excluded
        _make_pronunciation_attempt(db_session, test_user.id, 'rare', matched=False)
        _make_pronunciation_attempt(db_session, test_user.id, 'rare', matched=False)
        result = get_pronunciation_weaknesses(test_user.id, min_attempts=3)
        assert 'rare' not in result

    def test_min_attempts_threshold_respected(self, app, db_session, test_user):
        # Exactly 3 attempts, all mismatched → included with min_attempts=3
        _make_pronunciation_attempt(db_session, test_user.id, 'exact', matched=False)
        _make_pronunciation_attempt(db_session, test_user.id, 'exact', matched=False)
        _make_pronunciation_attempt(db_session, test_user.id, 'exact', matched=False)
        result = get_pronunciation_weaknesses(test_user.id, min_attempts=3)
        assert 'exact' in result

    def test_result_is_sorted(self, app, db_session, test_user):
        for word in ['zebra', 'apple', 'mango']:
            for _ in range(3):
                _make_pronunciation_attempt(db_session, test_user.id, word, matched=False)
        result = get_pronunciation_weaknesses(test_user.id)
        assert result == sorted(result)

    def test_other_users_attempts_excluded(self, app, db_session, test_user):
        from app.auth.models import User
        other = User(
            email=f'other_{uuid.uuid4().hex[:8]}@test.com',
            username=f'other_{uuid.uuid4().hex[:8]}',
            onboarding_completed=True,
        )
        other.set_password('pass')
        db_session.add(other)
        db_session.flush()

        for _ in range(4):
            _make_pronunciation_attempt(db_session, other.id, 'shared', matched=False)
        result = get_pronunciation_weaknesses(test_user.id)
        assert result == []
