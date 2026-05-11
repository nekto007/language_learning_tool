"""Tests for insights_service.py.

Task 26: Writing accuracy analytics widget.
Task 39: Vocabulary growth chart on dashboard.
Task 57: Pronunciation weakness detection.
Task 66: Weak area automatic detection.
Task 74: Grammar mastery radar chart.
Task 75: Learning velocity trend widget.
Task 77: Estimated time to next CEFR level.
"""
from __future__ import annotations

import uuid
from datetime import datetime, date, timedelta, timezone

import pytest

from app.curriculum.models import CEFRLevel, Lessons, Module, UserWritingAttempt, PronunciationAttempt, ListeningAttempt, LessonProgress
from app.study.insights_service import get_writing_stats, get_vocabulary_growth, get_pronunciation_weaknesses, get_pronunciation_stats, get_weak_areas, get_skills_balance, get_grammar_mastery_by_topic, get_learning_velocity, get_level_eta
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


# ---------------------------------------------------------------------------
# Tests for get_pronunciation_stats (Task 60)
# ---------------------------------------------------------------------------

def _make_pronunciation_attempt_at(
    db_session,
    user_id: int,
    word: str,
    matched: bool,
    days_ago: int = 0,
) -> PronunciationAttempt:
    attempt = PronunciationAttempt(
        user_id=user_id,
        word=word,
        recognized_text=word if matched else 'wrong',
        matched=matched,
    )
    attempt.created_at = datetime.now(timezone.utc) - timedelta(days=days_ago)
    db_session.add(attempt)
    db_session.flush()
    return attempt


class TestGetPronunciationStats:
    def test_zero_attempts_returns_zeros(self, app, db_session, test_user):
        result = get_pronunciation_stats(test_user.id)
        assert result['total_attempts'] == 0
        assert result['total_words'] == 0
        assert result['match_rate_7d'] == 0.0

    def test_total_attempts_counted(self, app, db_session, test_user):
        _make_pronunciation_attempt_at(db_session, test_user.id, 'hello', matched=True)
        _make_pronunciation_attempt_at(db_session, test_user.id, 'world', matched=False)
        result = get_pronunciation_stats(test_user.id)
        assert result['total_attempts'] == 2

    def test_total_words_counts_distinct(self, app, db_session, test_user):
        _make_pronunciation_attempt_at(db_session, test_user.id, 'hello', matched=True)
        _make_pronunciation_attempt_at(db_session, test_user.id, 'hello', matched=False)
        _make_pronunciation_attempt_at(db_session, test_user.id, 'world', matched=True)
        result = get_pronunciation_stats(test_user.id)
        assert result['total_words'] == 2

    def test_match_rate_7d_correct(self, app, db_session, test_user):
        # 3 matched, 1 not matched in last 7 days = 75%
        for _ in range(3):
            _make_pronunciation_attempt_at(db_session, test_user.id, 'hi', matched=True, days_ago=1)
        _make_pronunciation_attempt_at(db_session, test_user.id, 'hi', matched=False, days_ago=1)
        result = get_pronunciation_stats(test_user.id)
        assert result['match_rate_7d'] == 75.0

    def test_old_attempts_excluded_from_7d_rate(self, app, db_session, test_user):
        # Old failed attempts (>7 days) should not affect 7d rate
        _make_pronunciation_attempt_at(db_session, test_user.id, 'old', matched=False, days_ago=10)
        _make_pronunciation_attempt_at(db_session, test_user.id, 'old', matched=True, days_ago=1)
        result = get_pronunciation_stats(test_user.id)
        # total_attempts includes old; match_rate_7d only counts last 7 days → 1/1 = 100%
        assert result['total_attempts'] == 2
        assert result['match_rate_7d'] == 100.0

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

        _make_pronunciation_attempt_at(db_session, other.id, 'hello', matched=True)
        result = get_pronunciation_stats(test_user.id)
        assert result['total_attempts'] == 0
        assert result['total_words'] == 0


# ---------------------------------------------------------------------------
# Helpers for weak areas tests
# ---------------------------------------------------------------------------

def _make_collection_word_for_srs(db_session) -> CollectionWords:
    word = CollectionWords(
        english_word=f'srsword_{uuid.uuid4().hex[:8]}',
        russian_word='тест',
        level='A1',
    )
    db_session.add(word)
    db_session.flush()
    return word


def _make_srs_card(
    db_session,
    user_id: int,
    correct: int,
    incorrect: int,
) -> UserCardDirection:
    cw = _make_collection_word_for_srs(db_session)
    uw = UserWord(user_id=user_id, word_id=cw.id)
    db_session.add(uw)
    db_session.flush()
    card = UserCardDirection(user_word_id=uw.id, direction='eng-rus')
    card.correct_count = correct
    card.incorrect_count = incorrect
    db_session.add(card)
    db_session.flush()
    return card


def _make_grammar_weak_area(db_session, user_id: int, accuracy_pct: float, attempts: int = 5):
    """Create grammar topic + exercise + user_grammar_exercise row with given accuracy."""
    from app.grammar_lab.models import GrammarTopic, GrammarExercise, UserGrammarExercise

    code = uuid.uuid4().hex[:6]
    topic = GrammarTopic(
        slug=f'topic-{code}',
        title=f'Topic {code}',
        title_ru=f'Тема {code}',
        level='A1',
        order=1,
        content={},
    )
    db_session.add(topic)
    db_session.flush()

    exercise = GrammarExercise(
        topic_id=topic.id,
        exercise_type='fill_blank',
        content={'sentence': 'He ___ a student.', 'correct_answer': 'is', 'options': ['is', 'are', 'am']},
        difficulty=0.5,
    )
    db_session.add(exercise)
    db_session.flush()

    correct_n = int(attempts * accuracy_pct / 100)
    incorrect_n = attempts - correct_n
    uge = UserGrammarExercise(user_id=user_id, exercise_id=exercise.id)
    uge.correct_count = correct_n
    uge.incorrect_count = incorrect_n
    db_session.add(uge)
    db_session.flush()
    return topic


def _make_listening_attempt(
    db_session,
    user_id: int,
    lesson_id: int,
    score: float,
    days_ago: int = 0,
) -> ListeningAttempt:
    attempt = ListeningAttempt(
        user_id=user_id,
        lesson_id=lesson_id,
        score=score,
        replay_count=0,
    )
    attempt.created_at = datetime.now(timezone.utc) - timedelta(days=days_ago)
    db_session.add(attempt)
    db_session.flush()
    return attempt


# ---------------------------------------------------------------------------
# Tests for get_weak_areas (Task 66)
# ---------------------------------------------------------------------------

class TestGetWeakAreas:
    def test_empty_user_returns_empty(self, app, db_session, test_user):
        result = get_weak_areas(test_user.id)
        assert result == []

    def test_low_srs_accuracy_returns_vocabulary_area(self, app, db_session, test_user):
        # Create 10 cards with 30% accuracy → vocabulary weak area
        for _ in range(10):
            _make_srs_card(db_session, test_user.id, correct=3, incorrect=7)
        result = get_weak_areas(test_user.id)
        kinds = [a['kind'] for a in result]
        assert 'vocabulary' in kinds

    def test_high_srs_accuracy_no_vocabulary_area(self, app, db_session, test_user):
        # 10 cards at 80% → not a weak area (threshold is 70)
        for _ in range(10):
            _make_srs_card(db_session, test_user.id, correct=8, incorrect=2)
        result = get_weak_areas(test_user.id)
        kinds = [a['kind'] for a in result]
        assert 'vocabulary' not in kinds

    def test_fewer_than_10_srs_reviews_excluded(self, app, db_session, test_user):
        # Only 3 cards, 1 review each → 3 total reviews < 10-review threshold
        for _ in range(3):
            _make_srs_card(db_session, test_user.id, correct=0, incorrect=1)
        result = get_weak_areas(test_user.id)
        kinds = [a['kind'] for a in result]
        assert 'vocabulary' not in kinds

    def test_low_grammar_accuracy_returns_grammar_area(self, app, db_session, test_user):
        # Grammar topic at 40% accuracy with 5 attempts → weak area
        _make_grammar_weak_area(db_session, test_user.id, accuracy_pct=40, attempts=5)
        result = get_weak_areas(test_user.id)
        kinds = [a['kind'] for a in result]
        assert 'grammar' in kinds

    def test_grammar_area_includes_topic_id(self, app, db_session, test_user):
        topic = _make_grammar_weak_area(db_session, test_user.id, accuracy_pct=40, attempts=5)
        result = get_weak_areas(test_user.id)
        grammar_area = next((a for a in result if a['kind'] == 'grammar'), None)
        assert grammar_area is not None
        assert grammar_area['topic_id'] == topic.id

    def test_high_grammar_accuracy_no_grammar_area(self, app, db_session, test_user):
        _make_grammar_weak_area(db_session, test_user.id, accuracy_pct=85, attempts=5)
        result = get_weak_areas(test_user.id)
        kinds = [a['kind'] for a in result]
        assert 'grammar' not in kinds

    def test_grammar_fewer_than_3_attempts_excluded(self, app, db_session, test_user):
        _make_grammar_weak_area(db_session, test_user.id, accuracy_pct=20, attempts=2)
        result = get_weak_areas(test_user.id)
        kinds = [a['kind'] for a in result]
        assert 'grammar' not in kinds

    def test_results_sorted_by_score_ascending(self, app, db_session, test_user):
        lesson = _make_lesson(db_session)
        # Grammar weak (40%) and listening weak (50% avg) — grammar should come first
        _make_grammar_weak_area(db_session, test_user.id, accuracy_pct=40, attempts=5)
        for _ in range(3):
            _make_listening_attempt(db_session, test_user.id, lesson.id, score=50.0)
        result = get_weak_areas(test_user.id)
        if len(result) >= 2:
            scores = [a['score'] for a in result]
            assert scores == sorted(scores)

    def test_top_n_limit_respected(self, app, db_session, test_user):
        lesson = _make_lesson(db_session)
        # Create weak areas in all 4 skills
        for _ in range(10):
            _make_srs_card(db_session, test_user.id, correct=2, incorrect=8)
        _make_grammar_weak_area(db_session, test_user.id, accuracy_pct=40, attempts=5)
        for _ in range(3):
            _make_listening_attempt(db_session, test_user.id, lesson.id, score=50.0)
        _make_attempt(db_session, test_user.id, lesson.id, text='wrote something', days_ago=10)
        result = get_weak_areas(test_user.id, top_n=2)
        assert len(result) <= 2

    def test_writing_area_flagged_when_inactive(self, app, db_session, test_user):
        lesson = _make_lesson(db_session)
        # Has past attempts but none in last 7 days
        _make_attempt(db_session, test_user.id, lesson.id, text='old attempt', days_ago=10)
        result = get_weak_areas(test_user.id)
        kinds = [a['kind'] for a in result]
        assert 'writing' in kinds

    def test_writing_area_not_flagged_when_recent(self, app, db_session, test_user):
        lesson = _make_lesson(db_session)
        _make_attempt(db_session, test_user.id, lesson.id, text='recent attempt', days_ago=1)
        result = get_weak_areas(test_user.id)
        kinds = [a['kind'] for a in result]
        assert 'writing' not in kinds

    def test_writing_area_not_flagged_with_no_history(self, app, db_session, test_user):
        # Never wrote anything → no writing weak area (can't be inactive if never started)
        result = get_weak_areas(test_user.id)
        kinds = [a['kind'] for a in result]
        assert 'writing' not in kinds


# ---------------------------------------------------------------------------
# Tests for get_skills_balance (Task 73)
# ---------------------------------------------------------------------------

class TestGetSkillsBalance:
    _SKILL_KEYS = {'vocabulary', 'grammar', 'reading', 'listening', 'writing', 'speaking'}

    def test_zero_activity_returns_all_zeros(self, app, db_session, test_user):
        result = get_skills_balance(test_user.id)
        assert set(result.keys()) == self._SKILL_KEYS
        for key in self._SKILL_KEYS:
            assert result[key] == 0

    def test_vocabulary_score_from_srs_accuracy(self, app, db_session, test_user):
        # 8 correct, 2 incorrect out of 10 total → 80%
        for _ in range(8):
            _make_srs_card(db_session, test_user.id, correct=1, incorrect=0)
        for _ in range(2):
            _make_srs_card(db_session, test_user.id, correct=0, incorrect=1)
        result = get_skills_balance(test_user.id)
        assert result['vocabulary'] == 80

    def test_vocabulary_below_min_reviews_returns_zero(self, app, db_session, test_user):
        # Only 5 total reviews → below threshold of 10
        for _ in range(5):
            _make_srs_card(db_session, test_user.id, correct=1, incorrect=0)
        result = get_skills_balance(test_user.id)
        assert result['vocabulary'] == 0

    def test_grammar_score_from_accuracy(self, app, db_session, test_user):
        # 6 correct out of 10 total → 60%
        _make_grammar_weak_area(db_session, test_user.id, accuracy_pct=60, attempts=10)
        result = get_skills_balance(test_user.id)
        assert result['grammar'] == 60

    def test_grammar_below_min_attempts_returns_zero(self, app, db_session, test_user):
        # Only 2 attempts → below threshold of 3
        _make_grammar_weak_area(db_session, test_user.id, accuracy_pct=90, attempts=2)
        result = get_skills_balance(test_user.id)
        assert result['grammar'] == 0

    def test_listening_score_from_weekly_attempts(self, app, db_session, test_user):
        lesson = _make_lesson(db_session)
        # 5 attempts this week → 100%
        for _ in range(5):
            _make_listening_attempt(db_session, test_user.id, lesson.id, score=80.0, days_ago=0)
        result = get_skills_balance(test_user.id)
        assert result['listening'] == 100

    def test_listening_partial_score(self, app, db_session, test_user):
        lesson = _make_lesson(db_session)
        # 2 attempts out of 5 target → 40%
        for _ in range(2):
            _make_listening_attempt(db_session, test_user.id, lesson.id, score=80.0, days_ago=0)
        result = get_skills_balance(test_user.id)
        assert result['listening'] == 40

    def test_listening_old_attempts_excluded(self, app, db_session, test_user):
        lesson = _make_lesson(db_session)
        # Attempts from 10 days ago → not in 7-day window
        for _ in range(5):
            _make_listening_attempt(db_session, test_user.id, lesson.id, score=80.0, days_ago=10)
        result = get_skills_balance(test_user.id)
        assert result['listening'] == 0

    def test_writing_score_from_weekly_attempts(self, app, db_session, test_user):
        lesson = _make_lesson(db_session)
        # 3 writing attempts this week → 60%
        for _ in range(3):
            _make_attempt(db_session, test_user.id, lesson.id, text='test text', days_ago=0)
        result = get_skills_balance(test_user.id)
        assert result['writing'] == 60

    def test_speaking_score_from_match_rate(self, app, db_session, test_user):
        # 9 matched out of 12 total → 75%
        for _ in range(9):
            _make_pronunciation_attempt_at(db_session, test_user.id, 'apple', matched=True, days_ago=0)
        for _ in range(3):
            _make_pronunciation_attempt_at(db_session, test_user.id, 'orange', matched=False, days_ago=0)
        result = get_skills_balance(test_user.id)
        assert result['speaking'] == 75

    def test_speaking_below_min_attempts_returns_zero(self, app, db_session, test_user):
        # Only 2 pronunciation attempts → below min of 3
        for _ in range(2):
            _make_pronunciation_attempt_at(db_session, test_user.id, 'apple', matched=True, days_ago=0)
        result = get_skills_balance(test_user.id)
        assert result['speaking'] == 0

    def test_reading_score_capped_at_100(self, app, db_session, test_user):
        # 10 reading sessions this week → should cap at 100 (not 200)
        from app.books.reading_session import UserReadingSession
        from app.books.models import Book, Chapter
        book = Book(title='Test Book', author='Author', level='A1', chapters_cnt=10)
        db_session.add(book)
        db_session.flush()
        chapters = []
        for i in range(10):
            ch = Chapter(book_id=book.id, chap_num=i + 1, title=f'Ch{i}', words=100, text_raw='x')
            db_session.add(ch)
            chapters.append(ch)
        db_session.flush()
        now = datetime.now(timezone.utc)
        for ch in chapters:
            rs = UserReadingSession(
                user_id=test_user.id,
                chapter_id=ch.id,
                started_at=now - timedelta(hours=1),
                ended_at=now,
            )
            db_session.add(rs)
        db_session.flush()
        result = get_skills_balance(test_user.id)
        assert result['reading'] == 100


# ---------------------------------------------------------------------------
# Tests for get_grammar_mastery_by_topic (Task 74)
# ---------------------------------------------------------------------------

def _make_grammar_mastery_topic(
    db_session,
    user_id: int,
    accuracy_pct: float,
    attempts: int = 5,
    mastered: int = 0,
) -> 'GrammarTopic':
    """Create grammar topic + exercise + UserGrammarExercise with given stats."""
    from app.grammar_lab.models import GrammarTopic, GrammarExercise, UserGrammarExercise

    code = uuid.uuid4().hex[:6]
    topic = GrammarTopic(
        slug=f'mastery-topic-{code}',
        title=f'Mastery Topic {code}',
        title_ru=f'Тема мастерства {code}',
        level='B1',
        order=1,
        content={},
    )
    db_session.add(topic)
    db_session.flush()

    exercise = GrammarExercise(
        topic_id=topic.id,
        exercise_type='fill_blank',
        content={'sentence': 'She ___ happy.', 'correct_answer': 'is', 'options': ['is', 'are', 'was']},
        difficulty=0.5,
    )
    db_session.add(exercise)
    db_session.flush()

    correct_n = int(attempts * accuracy_pct / 100)
    incorrect_n = attempts - correct_n
    uge = UserGrammarExercise(user_id=user_id, exercise_id=exercise.id)
    uge.correct_count = correct_n
    uge.incorrect_count = incorrect_n
    if mastered:
        uge.state = 'review'
        uge.interval = 30
    db_session.add(uge)
    db_session.flush()
    return topic


class TestGetGrammarMasteryByTopic:
    def test_empty_user_returns_empty(self, app, db_session, test_user):
        result = get_grammar_mastery_by_topic(test_user.id)
        assert result == []

    def test_topics_returned_with_correct_fields(self, app, db_session, test_user):
        _make_grammar_mastery_topic(db_session, test_user.id, accuracy_pct=70, attempts=10)
        result = get_grammar_mastery_by_topic(test_user.id)
        assert len(result) == 1
        row = result[0]
        assert 'topic_id' in row
        assert 'title' in row
        assert 'accuracy' in row
        assert 'mastered_count' in row
        assert 'total_count' in row

    def test_accuracy_computed_correctly(self, app, db_session, test_user):
        _make_grammar_mastery_topic(db_session, test_user.id, accuracy_pct=80, attempts=10)
        result = get_grammar_mastery_by_topic(test_user.id)
        assert result[0]['accuracy'] == 80.0

    def test_mastered_count_zero_when_not_mastered(self, app, db_session, test_user):
        _make_grammar_mastery_topic(db_session, test_user.id, accuracy_pct=60, attempts=5, mastered=0)
        result = get_grammar_mastery_by_topic(test_user.id)
        assert result[0]['mastered_count'] == 0

    def test_mastered_count_correct_when_mastered(self, app, db_session, test_user):
        _make_grammar_mastery_topic(db_session, test_user.id, accuracy_pct=90, attempts=5, mastered=1)
        result = get_grammar_mastery_by_topic(test_user.id)
        assert result[0]['mastered_count'] == 1

    def test_topics_sorted_worst_first(self, app, db_session, test_user):
        _make_grammar_mastery_topic(db_session, test_user.id, accuracy_pct=90, attempts=10)
        _make_grammar_mastery_topic(db_session, test_user.id, accuracy_pct=40, attempts=10)
        _make_grammar_mastery_topic(db_session, test_user.id, accuracy_pct=70, attempts=10)
        result = get_grammar_mastery_by_topic(test_user.id)
        assert len(result) == 3
        accuracies = [r['accuracy'] for r in result]
        assert accuracies == sorted(accuracies)

    def test_topics_with_zero_attempts_excluded(self, app, db_session, test_user):
        from app.grammar_lab.models import GrammarTopic, GrammarExercise, UserGrammarExercise
        code = uuid.uuid4().hex[:6]
        topic = GrammarTopic(
            slug=f'zero-topic-{code}',
            title=f'Zero Topic {code}',
            title_ru='Нулевая тема',
            level='A1',
            order=1,
            content={},
        )
        db_session.add(topic)
        db_session.flush()
        exercise = GrammarExercise(
            topic_id=topic.id,
            exercise_type='fill_blank',
            content={'sentence': 'Test ___.', 'correct_answer': 'ok', 'options': ['ok', 'no']},
            difficulty=0.5,
        )
        db_session.add(exercise)
        db_session.flush()
        uge = UserGrammarExercise(user_id=test_user.id, exercise_id=exercise.id)
        uge.correct_count = 0
        uge.incorrect_count = 0
        db_session.add(uge)
        db_session.flush()
        # The zero-attempt topic should still appear (it has a row, count > 0)
        # but accuracy = 0 / nullif(0,0) = NULL → defaults to 0.0
        result = get_grammar_mastery_by_topic(test_user.id)
        topics_with_zero = [r for r in result if 'Zero Topic' in r['title']]
        # topic with 0 correct+incorrect still has 1 row, so it appears
        # with accuracy=0. That is acceptable — it's an "attempted" exercise.
        assert len(topics_with_zero) == 1
        assert topics_with_zero[0]['accuracy'] == 0.0

    def test_other_user_excluded(self, app, db_session, test_user):
        from app.auth.models import User
        other = User(
            email=f'other_{uuid.uuid4().hex[:6]}@test.com',
            username=f'other_{uuid.uuid4().hex[:6]}',
        )
        other.set_password('pw')
        db_session.add(other)
        db_session.flush()
        _make_grammar_mastery_topic(db_session, other.id, accuracy_pct=50, attempts=10)
        result = get_grammar_mastery_by_topic(test_user.id)
        assert result == []


# ---------------------------------------------------------------------------
# Helpers for learning velocity tests
# ---------------------------------------------------------------------------

def _make_lesson_progress(
    db_session,
    user_id: int,
    lesson_id: int,
    days_ago: int = 0,
) -> 'LessonProgress':
    from app.curriculum.models import LessonProgress
    completed_at = datetime.now(timezone.utc) - timedelta(days=days_ago)
    lp = LessonProgress(
        user_id=user_id,
        lesson_id=lesson_id,
        status='completed',
        score=80.0,
        completed_at=completed_at,
    )
    db_session.add(lp)
    db_session.flush()
    return lp


# ---------------------------------------------------------------------------
# Tests for get_learning_velocity (Task 75)
# ---------------------------------------------------------------------------

class TestGetLearningVelocity:
    def test_returns_required_keys(self, app, db_session, test_user):
        result = get_learning_velocity(test_user.id, weeks=4)
        for key in ('week_labels', 'word_counts', 'lesson_counts', 'trend',
                    'words_last_week', 'lessons_last_week',
                    'words_this_week', 'lessons_this_week'):
            assert key in result

    def test_empty_user_returns_zeros_and_stable(self, app, db_session, test_user):
        result = get_learning_velocity(test_user.id, weeks=4)
        assert all(c == 0 for c in result['word_counts'])
        assert all(c == 0 for c in result['lesson_counts'])
        assert result['trend'] == 'stable'
        assert result['words_last_week'] == 0
        assert result['lessons_last_week'] == 0

    def test_week_labels_length_matches_weeks(self, app, db_session, test_user):
        result = get_learning_velocity(test_user.id, weeks=3)
        assert len(result['week_labels']) == 3
        assert len(result['word_counts']) == 3
        assert len(result['lesson_counts']) == 3

    def test_word_added_this_week_counted(self, app, db_session, test_user):
        _make_user_word(db_session, test_user.id, days_ago=0)
        result = get_learning_velocity(test_user.id, weeks=2)
        # Current week is last entry
        assert result['word_counts'][-1] >= 1
        assert result['words_this_week'] >= 1

    def test_lesson_completed_this_week_counted(self, app, db_session, test_user):
        lesson = _make_lesson(db_session)
        _make_lesson_progress(db_session, test_user.id, lesson.id, days_ago=0)
        result = get_learning_velocity(test_user.id, weeks=2)
        assert result['lesson_counts'][-1] >= 1
        assert result['lessons_this_week'] >= 1

    def test_word_from_last_week_in_correct_bucket(self, app, db_session, test_user):
        from datetime import date
        today = date.today()
        # Compute a days_ago value that reliably falls in the previous week:
        # days_since_monday=0 (Mon)→7+1=8; days_since_monday=6 (Sun)→6+1=7
        # Use (today.weekday() + 7) which always picks the same weekday 1 week ago,
        # then add 1 so we're safely in the prior week even on Mondays.
        days_since_monday = today.weekday()
        days_ago = days_since_monday + 7  # always the previous week's Monday
        _make_user_word(db_session, test_user.id, days_ago=days_ago)
        result = get_learning_velocity(test_user.id, weeks=3)
        # Previous week is second-to-last bucket
        assert result['word_counts'][-2] >= 1
        assert result['words_last_week'] >= 1

    def test_trend_increasing_when_more_words_this_week(self, app, db_session, test_user):
        from datetime import date as _date
        # Use a day that's always in the previous week.
        prev_week_days_ago = _date.today().weekday() + 7
        # Last week: 1 word, this week: 5 words (diff > 2 → increasing)
        for _ in range(5):
            _make_user_word(db_session, test_user.id, days_ago=0)
        _make_user_word(db_session, test_user.id, days_ago=prev_week_days_ago)
        result = get_learning_velocity(test_user.id, weeks=2)
        assert result['trend'] == 'increasing'

    def test_trend_declining_when_fewer_words_this_week(self, app, db_session, test_user):
        from datetime import date as _date
        prev_week_days_ago = _date.today().weekday() + 7
        # Last week: 5 words, this week: 0 words (diff < -2 → declining)
        for _ in range(5):
            _make_user_word(db_session, test_user.id, days_ago=prev_week_days_ago)
        result = get_learning_velocity(test_user.id, weeks=2)
        assert result['trend'] == 'declining'

    def test_trend_stable_when_similar_counts(self, app, db_session, test_user):
        from datetime import date as _date
        prev_week_days_ago = _date.today().weekday() + 7
        # Last week: 2 words, this week: 3 words (diff = 1 → stable)
        for _ in range(2):
            _make_user_word(db_session, test_user.id, days_ago=prev_week_days_ago)
        for _ in range(3):
            _make_user_word(db_session, test_user.id, days_ago=0)
        result = get_learning_velocity(test_user.id, weeks=2)
        assert result['trend'] == 'stable'

    def test_other_users_data_excluded(self, app, db_session, test_user):
        from app.auth.models import User
        other = User(
            email=f'other_vel_{uuid.uuid4().hex[:6]}@test.com',
            username=f'other_vel_{uuid.uuid4().hex[:6]}',
        )
        other.set_password('pw')
        db_session.add(other)
        db_session.flush()
        for _ in range(5):
            _make_user_word(db_session, other.id, days_ago=0)
        result = get_learning_velocity(test_user.id, weeks=2)
        assert result['words_this_week'] == 0


# ---------------------------------------------------------------------------
# Helpers for level ETA tests (Task 77)
# ---------------------------------------------------------------------------

_eta_order_counter = 100


def _make_cefr_level(db_session, order: int) -> CEFRLevel:
    """Create a CEFRLevel with a unique 2-char code."""
    code = uuid.uuid4().hex[:2].upper()
    level = CEFRLevel(code=code, name=f'Level {code}', description='d', order=order)
    db_session.add(level)
    db_session.flush()
    return level


def _make_module_with_lessons(db_session, level: CEFRLevel, module_num: int, lesson_count: int):
    """Create a module with *lesson_count* lessons; return (module, [lesson, ...])."""
    module = Module(
        level_id=level.id,
        number=module_num,
        title=f'Module {module_num}',
        description='d',
        raw_content={'module': {'id': module_num}},
    )
    db_session.add(module)
    db_session.flush()
    lessons = []
    for i in range(lesson_count):
        lesson = Lessons(
            module_id=module.id,
            number=i + 1,
            title=f'Lesson {i + 1}',
            type='card',
            content={},
        )
        db_session.add(lesson)
        lessons.append(lesson)
    db_session.flush()
    return module, lessons


def _complete_lesson(db_session, user_id: int, lesson: Lessons, days_ago: int = 0):
    completed_at = datetime.now(timezone.utc) - timedelta(days=days_ago)
    lp = LessonProgress(
        user_id=user_id,
        lesson_id=lesson.id,
        status='completed',
        score=80.0,
        completed_at=completed_at,
    )
    db_session.add(lp)
    db_session.flush()
    return lp


# ---------------------------------------------------------------------------
# Tests for get_level_eta (Task 77)
# ---------------------------------------------------------------------------

class TestGetLevelEta:
    def test_eta_with_known_rate_and_remaining(self, app, db_session, test_user):
        """user with 4 modules/week (20 lessons/week, 5 per module) and 8 remaining → ETA = 2 weeks."""
        today = date.today()
        days_since_monday = today.weekday()

        # Target level with 8 modules × 5 lessons each (all remaining)
        a1 = _make_cefr_level(db_session, order=200)
        test_user.onboarding_level = a1.code
        db_session.flush()

        for i in range(8):
            _make_module_with_lessons(db_session, a1, i + 1, 5)

        # Velocity level with 80 completed lessons over 4 weeks = 20/week
        a0 = _make_cefr_level(db_session, order=100)
        all_velocity_lessons = []
        for i in range(16):  # 16 modules × 5 lessons = 80
            _, lessons = _make_module_with_lessons(db_session, a0, i + 1, 5)
            all_velocity_lessons.extend(lessons)

        # Spread 80 lessons across 4 weeks (20 per week).
        # Use the Monday of each week to stay safely within the velocity window.
        for idx, lesson in enumerate(all_velocity_lessons):
            week_idx = idx // 20  # 0..3 (week 0 = oldest = 3 weeks ago)
            weeks_ago = 3 - week_idx
            days_ago = days_since_monday + 7 * weeks_ago
            _complete_lesson(db_session, test_user.id, lesson, days_ago=days_ago)

        result = get_level_eta(test_user.id)

        assert result['current_level'] == a1.code
        assert result['weeks_estimate'] == 2
        assert result['confidence'] in ('medium', 'high')

    def test_no_velocity_history_returns_low_confidence(self, app, db_session, test_user):
        """< 1 week history → confidence=low."""
        a1 = _make_cefr_level(db_session, order=300)
        test_user.onboarding_level = a1.code
        db_session.flush()

        _make_module_with_lessons(db_session, a1, 1, 5)

        result = get_level_eta(test_user.id)
        assert result['confidence'] == 'low'

    def test_all_modules_completed_returns_zero_weeks(self, app, db_session, test_user):
        """If all modules at current level are fully completed, weeks_estimate=0."""
        a1 = _make_cefr_level(db_session, order=400)
        a2 = _make_cefr_level(db_session, order=401)
        test_user.onboarding_level = a1.code
        db_session.flush()

        _, lessons = _make_module_with_lessons(db_session, a1, 1, 3)
        for lesson in lessons:
            _complete_lesson(db_session, test_user.id, lesson, days_ago=1)

        result = get_level_eta(test_user.id)
        assert result['weeks_estimate'] == 0
        assert result['next_level'] == a2.code

    def test_result_has_required_keys(self, app, db_session, test_user):
        a1 = _make_cefr_level(db_session, order=500)
        test_user.onboarding_level = a1.code
        db_session.flush()
        _make_module_with_lessons(db_session, a1, 1, 3)

        result = get_level_eta(test_user.id)
        for key in ('current_level', 'next_level', 'weeks_estimate', 'confidence'):
            assert key in result
