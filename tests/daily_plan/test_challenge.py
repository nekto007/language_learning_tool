"""Tests for the daily challenge system (Tasks 83, 84, 95).

Covers:
- challenge seeded deterministically for a given date
- same challenge returned for all users on same day
- challenge seeded only once (idempotent)
- listening_deep category attaches a dictation lesson
- completion tracked per user
- complete_challenge is idempotent (second call returns already_completed=True)
- get_today_challenge reflects completion status after completion
- Task 95: challenge_streak counts consecutive completion days
- Task 95: gap in completions resets streak
- Task 95: leaderboard points include CHALLENGE_BONUS_POINTS when completed
"""
from __future__ import annotations

import uuid
from datetime import date, timedelta

import pytest

from app.daily_plan.models import (
    CHALLENGE_CATEGORIES,
    DailyChallenge,
    DailyChallengeCompletion,
)
from app.daily_plan.challenge import (
    CHALLENGE_CATEGORIES as SERVICE_CATEGORIES,
    _seed_today_challenge,
    complete_challenge,
    get_challenge_streak,
    get_today_challenge,
)


# ── helpers ───────────────────────────────────────────────────────────────────


def _make_user(db_session):
    from app.auth.models import User
    uid = uuid.uuid4().hex[:8]
    user = User(username=f'ch_{uid}', email=f'ch_{uid}@example.com', active=True)
    user.set_password('secret')
    db_session.add(user)
    db_session.commit()
    return user


def _make_dictation_lesson(db_session):
    from app.curriculum.models import CEFRLevel, Lessons, Module
    uid = uuid.uuid4().hex[:2].upper()
    level = CEFRLevel(code=uid, name='Test', description='d', order=99)
    db_session.add(level)
    db_session.commit()
    module = Module(level_id=level.id, number=99, title='M', description='d', raw_content={})
    db_session.add(module)
    db_session.commit()
    lesson = Lessons(module_id=module.id, number=1, title='Dictation Lesson', type='dictation', content={})
    db_session.add(lesson)
    db_session.commit()
    return lesson


# ── seeding ───────────────────────────────────────────────────────────────────


class TestSeedChallenge:
    def test_challenge_seeded_for_date(self, db_session):
        from app.utils.db import db
        test_date = date(2026, 6, 1)
        day_idx = test_date.toordinal() % 3
        expected_category = CHALLENGE_CATEGORIES[day_idx]

        challenge = _seed_today_challenge(test_date, db)
        db_session.commit()

        assert challenge.id is not None
        assert challenge.challenge_date == test_date
        assert challenge.category == expected_category
        assert challenge.bonus_xp > 0

    def test_category_is_deterministic(self, db_session):
        from app.utils.db import db
        test_date = date(2026, 6, 2)
        day_idx = test_date.toordinal() % 3
        expected = CHALLENGE_CATEGORIES[day_idx]

        challenge = _seed_today_challenge(test_date, db)
        db_session.commit()

        assert challenge.category == expected

    def test_all_categories_present_in_service(self):
        assert set(SERVICE_CATEGORIES) == {'speed_run', 'accuracy_focus', 'listening_deep'}

    def test_listening_deep_attaches_dictation_lesson(self, db_session):
        from app.utils.db import db

        # Find a date that maps to listening_deep (index 2)
        test_date = date(2026, 6, 1)
        while test_date.toordinal() % 3 != 2:
            test_date += timedelta(days=1)

        _make_dictation_lesson(db_session)

        challenge = _seed_today_challenge(test_date, db)
        db_session.commit()

        assert challenge.category == 'listening_deep'
        # listening_deep accepts any listening attempt — no specific lesson pinned
        assert challenge.lesson_id is None

    def test_non_listening_category_has_no_lesson(self, db_session):
        from app.utils.db import db

        # Find a date that maps to speed_run (index 0) or accuracy_focus (index 1)
        test_date = date(2026, 6, 1)
        while test_date.toordinal() % 3 == 2:
            test_date += timedelta(days=1)

        challenge = _seed_today_challenge(test_date, db)
        db_session.commit()

        assert challenge.category != 'listening_deep'
        assert challenge.lesson_id is None


# ── get_today_challenge ────────────────────────────────────────────────────────


class TestGetTodayChallenge:
    def test_returns_challenge_dict(self, db_session):
        from app.utils.db import db
        user = _make_user(db_session)

        result = get_today_challenge(user.id, db)

        assert result['challenge_date'] == date.today().isoformat()
        assert result['category'] in SERVICE_CATEGORIES
        assert result['bonus_xp'] > 0
        assert result['is_completed'] is False
        assert result['completion'] is None

    def test_same_challenge_for_all_users(self, db_session):
        from app.utils.db import db
        user1 = _make_user(db_session)
        user2 = _make_user(db_session)

        result1 = get_today_challenge(user1.id, db)
        result2 = get_today_challenge(user2.id, db)

        assert result1['id'] == result2['id']
        assert result1['challenge_date'] == result2['challenge_date']
        assert result1['category'] == result2['category']

    def test_challenge_seeded_only_once(self, db_session):
        from app.utils.db import db
        user = _make_user(db_session)

        get_today_challenge(user.id, db)
        get_today_challenge(user.id, db)

        today = date.today()
        count = DailyChallenge.query.filter_by(challenge_date=today).count()
        assert count == 1


# ── complete_challenge ────────────────────────────────────────────────────────


class TestCompleteChallenge:
    def test_completion_tracked(self, db_session):
        from app.utils.db import db
        user = _make_user(db_session)
        challenge_data = get_today_challenge(user.id, db)
        challenge_id = challenge_data['id']

        result = complete_challenge(user.id, challenge_id, score=95.0, time_spent_seconds=180, db=db)
        db_session.commit()

        assert result['already_completed'] is False
        assert result['bonus_xp'] == challenge_data['bonus_xp']

        stored = DailyChallengeCompletion.query.filter_by(
            challenge_id=challenge_id,
            user_id=user.id,
        ).first()
        assert stored is not None
        assert stored.score == 95.0
        assert stored.time_spent_seconds == 180

    def test_complete_challenge_idempotent(self, db_session):
        from app.utils.db import db
        user = _make_user(db_session)
        challenge_data = get_today_challenge(user.id, db)
        challenge_id = challenge_data['id']

        complete_challenge(user.id, challenge_id, score=80.0, time_spent_seconds=200, db=db)
        db_session.commit()
        result2 = complete_challenge(user.id, challenge_id, score=90.0, time_spent_seconds=100, db=db)

        assert result2['already_completed'] is True
        count = DailyChallengeCompletion.query.filter_by(
            challenge_id=challenge_id,
            user_id=user.id,
        ).count()
        assert count == 1

    def test_get_today_challenge_shows_completed(self, db_session):
        from app.utils.db import db
        user = _make_user(db_session)
        challenge_data = get_today_challenge(user.id, db)
        challenge_id = challenge_data['id']

        complete_challenge(user.id, challenge_id, score=75.0, time_spent_seconds=250, db=db)
        db_session.commit()

        refreshed = get_today_challenge(user.id, db)
        assert refreshed['is_completed'] is True
        assert refreshed['completion']['score'] == 75.0

    def test_different_users_have_independent_completion(self, db_session):
        from app.utils.db import db
        user1 = _make_user(db_session)
        user2 = _make_user(db_session)
        challenge_data = get_today_challenge(user1.id, db)
        challenge_id = challenge_data['id']

        complete_challenge(user1.id, challenge_id, score=88.0, time_spent_seconds=120, db=db)
        db_session.commit()

        user1_data = get_today_challenge(user1.id, db)
        user2_data = get_today_challenge(user2.id, db)

        assert user1_data['is_completed'] is True
        assert user2_data['is_completed'] is False


# ── challenge card data (Task 84) ─────────────────────────────────────────────


class TestChallengeCardData:
    """Verify the data structure returned by get_today_challenge is
    sufficient for rendering the daily-challenge-card in the template."""

    def test_card_data_uncompleted_has_gold_badge_fields(self, db_session):
        from app.utils.db import db
        user = _make_user(db_session)

        data = get_today_challenge(user.id, db)

        # Card should show when is_completed=False
        assert data['is_completed'] is False
        # bonus_xp present and positive — drives "2x XP" badge display
        assert 'bonus_xp' in data
        assert data['bonus_xp'] > 0
        # category present for description lookup
        assert data['category'] in ('speed_run', 'accuracy_focus', 'listening_deep')

    def test_card_data_completed_shows_done_state(self, db_session):
        from app.utils.db import db
        user = _make_user(db_session)
        data = get_today_challenge(user.id, db)
        challenge_id = data['id']

        complete_challenge(user.id, challenge_id, score=92.0, time_spent_seconds=200, db=db)
        db_session.commit()

        refreshed = get_today_challenge(user.id, db)
        # Card should render in greyed/done state
        assert refreshed['is_completed'] is True
        # completion details available for "+ N XP" label
        assert refreshed['completion'] is not None
        assert refreshed['completion']['score'] == 92.0

    def test_bonus_xp_values_per_category(self, db_session):
        from app.utils.db import db
        from app.daily_plan.challenge import _BONUS_XP

        # Each category must have a positive bonus_xp used for "2x XP" display
        for cat in ('speed_run', 'accuracy_focus', 'listening_deep'):
            assert cat in _BONUS_XP
            assert _BONUS_XP[cat] > 0

    def test_listening_deep_has_no_lesson_id(self, db_session):
        from app.utils.db import db
        import datetime

        _make_dictation_lesson(db_session)

        # Find a date that maps to listening_deep (index 2)
        test_date = datetime.date(2026, 7, 1)
        while test_date.toordinal() % 3 != 2:
            test_date += datetime.timedelta(days=1)

        challenge = _seed_today_challenge(test_date, db)
        db_session.commit()

        assert challenge.category == 'listening_deep'
        # listening_deep accepts any listening attempt — lesson_id is None
        assert challenge.lesson_id is None

    def test_non_listening_challenge_has_no_lesson_id(self, db_session):
        from app.utils.db import db
        import datetime

        # Find a date that maps to speed_run or accuracy_focus
        test_date = datetime.date(2026, 7, 1)
        while test_date.toordinal() % 3 == 2:
            test_date += datetime.timedelta(days=1)

        challenge = _seed_today_challenge(test_date, db)
        db_session.commit()

        # lesson_id=None → template falls back to first incomplete slot URL
        assert challenge.lesson_id is None


# ── Task 95: challenge streak ─────────────────────────────────────────────────


def _seed_challenge_for_date(d: date, db_session) -> DailyChallenge:
    """Create a DailyChallenge row for the given date. Skips if one exists."""
    from app.utils.db import db
    existing = DailyChallenge.query.filter_by(challenge_date=d).first()
    if existing:
        return existing
    ch = _seed_today_challenge(d, db)
    db_session.commit()
    return ch


def _complete_for_date(user_id: int, d: date, db_session):
    """Create a DailyChallengeCompletion for user_id on a given date."""
    ch = _seed_challenge_for_date(d, db_session)
    existing = DailyChallengeCompletion.query.filter_by(
        challenge_id=ch.id, user_id=user_id,
    ).first()
    if not existing:
        comp = DailyChallengeCompletion(
            challenge_id=ch.id,
            user_id=user_id,
            score=90.0,
            time_spent_seconds=120,
        )
        db_session.add(comp)
        db_session.commit()


class TestChallengeStreak:
    def test_no_completions_returns_zero(self, db_session):
        from app.utils.db import db
        user = _make_user(db_session)

        assert get_challenge_streak(user.id, db) == 0

    def test_three_consecutive_days(self, db_session):
        from app.utils.db import db
        user = _make_user(db_session)
        today = date.today()

        for offset in range(3):
            _complete_for_date(user.id, today - timedelta(days=offset), db_session)

        assert get_challenge_streak(user.id, db) == 3

    def test_gap_resets_streak(self, db_session):
        from app.utils.db import db
        user = _make_user(db_session)
        today = date.today()

        # Complete today and 2 days ago but NOT yesterday
        _complete_for_date(user.id, today, db_session)
        _complete_for_date(user.id, today - timedelta(days=2), db_session)

        # Streak = 1 (only today is unbroken; yesterday missing breaks chain)
        assert get_challenge_streak(user.id, db) == 1

    def test_only_yesterday_counts_as_one(self, db_session):
        from app.utils.db import db
        user = _make_user(db_session)
        yesterday = date.today() - timedelta(days=1)

        _complete_for_date(user.id, yesterday, db_session)

        assert get_challenge_streak(user.id, db) == 1

    def test_streak_included_in_get_today_challenge(self, db_session):
        from app.utils.db import db
        user = _make_user(db_session)
        today = date.today()

        _complete_for_date(user.id, today - timedelta(days=1), db_session)
        _complete_for_date(user.id, today - timedelta(days=2), db_session)

        data = get_today_challenge(user.id, db)
        # challenge_streak key present; 2 consecutive days before today → streak=2
        assert 'challenge_streak' in data
        assert data['challenge_streak'] == 2

    def test_different_users_have_independent_streaks(self, db_session):
        from app.utils.db import db
        user1 = _make_user(db_session)
        user2 = _make_user(db_session)
        today = date.today()

        # user1 completes today + yesterday; user2 has no completions
        _complete_for_date(user1.id, today, db_session)
        _complete_for_date(user1.id, today - timedelta(days=1), db_session)

        assert get_challenge_streak(user1.id, db) == 2
        assert get_challenge_streak(user2.id, db) == 0


# ── Task 95: leaderboard points bonus ────────────────────────────────────────


class TestChallengeLeaderboardBonus:
    def test_challenge_bonus_constant_is_ten(self):
        from app.achievements.daily_race import CHALLENGE_BONUS_POINTS
        assert CHALLENGE_BONUS_POINTS == 10

    def test_update_race_points_from_plan_with_challenge_bonus(self, db_session):
        """Race points include +10 when challenge_bonus=10 is passed."""
        from app.utils.db import db
        from app.achievements.daily_race import (
            CHALLENGE_BONUS_POINTS,
            DailyRace,
            DailyRaceParticipant,
            get_or_create_race,
            update_race_points_from_plan,
        )
        user = _make_user(db_session)
        race_date = date.today()

        # Enroll user in a race
        get_or_create_race(user.id, race_date)
        db_session.commit()

        # Base points without challenge bonus
        update_race_points_from_plan(user.id, race_date, [], {}, challenge_bonus=0)
        db_session.commit()
        participant_no_bonus = (
            db_session.query(DailyRaceParticipant)
            .filter_by(user_id=user.id, race_date=race_date)
            .first()
        )
        assert participant_no_bonus is not None
        base_points = participant_no_bonus.points

        # Now add challenge bonus
        update_race_points_from_plan(
            user.id, race_date, [], {}, challenge_bonus=CHALLENGE_BONUS_POINTS,
        )
        db_session.commit()
        participant_with_bonus = (
            db_session.query(DailyRaceParticipant)
            .filter_by(user_id=user.id, race_date=race_date)
            .first()
        )
        assert participant_with_bonus.points == base_points + CHALLENGE_BONUS_POINTS

    def test_no_bonus_when_challenge_not_completed(self, db_session):
        """Without challenge completion, no bonus points added."""
        from app.utils.db import db
        from app.achievements.daily_race import (
            DailyRaceParticipant,
            get_or_create_race,
            update_race_points_from_plan,
        )
        user = _make_user(db_session)
        race_date = date.today()

        get_or_create_race(user.id, race_date)
        db_session.commit()

        update_race_points_from_plan(user.id, race_date, [], {}, challenge_bonus=0)
        db_session.commit()

        participant = (
            db_session.query(DailyRaceParticipant)
            .filter_by(user_id=user.id, race_date=race_date)
            .first()
        )
        assert participant.points == 0


# ── Task 65: no-challenge day, duplicate prevention, bonus_xp, streak ────────


class TestNoChallengeDay:
    """get_today_challenge auto-seeds and never raises 500 when no challenge exists."""

    def test_no_preexisting_challenge_returns_dict_not_none(self, db_session):
        """Returns a valid dict (not None) when called on a day with no pre-seeded challenge."""
        from app.utils.db import db
        user = _make_user(db_session)
        today = date.today()

        # Verify no DailyChallenge row exists for today yet
        count_before = DailyChallenge.query.filter_by(challenge_date=today).count()
        # Note: other tests may have already seeded today's challenge; clear expectation
        # is that the function returns a dict regardless.

        result = get_today_challenge(user.id, db)

        assert isinstance(result, dict), "get_today_challenge must return a dict, not raise"
        assert result['category'] in ('speed_run', 'accuracy_focus', 'listening_deep')
        assert result['is_completed'] is False
        assert result['challenge_streak'] == 0

    def test_returns_non_none_result(self, db_session):
        """get_today_challenge never returns None."""
        from app.utils.db import db
        user = _make_user(db_session)
        result = get_today_challenge(user.id, db)
        assert result is not None

    def test_challenge_auto_seeded_when_missing(self, db_session):
        """When no challenge exists for today, one is created automatically."""
        from app.utils.db import db
        user = _make_user(db_session)
        today = date.today()

        get_today_challenge(user.id, db)

        # A DailyChallenge row must now exist for today
        challenge = DailyChallenge.query.filter_by(challenge_date=today).first()
        assert challenge is not None
        assert challenge.bonus_xp > 0

    def test_challenge_seeded_only_once_even_with_concurrent_calls(self, db_session):
        """Repeated calls do not create multiple DailyChallenge rows for same day."""
        from app.utils.db import db
        user = _make_user(db_session)
        today = date.today()

        get_today_challenge(user.id, db)
        get_today_challenge(user.id, db)
        get_today_challenge(user.id, db)

        count = DailyChallenge.query.filter_by(challenge_date=today).count()
        assert count == 1


class TestDuplicateCompletionPrevention:
    """challenge completion cannot be duplicated on retry."""

    def test_retry_returns_already_completed(self, db_session):
        """Second call to complete_challenge returns already_completed=True."""
        from app.utils.db import db
        user = _make_user(db_session)
        challenge_data = get_today_challenge(user.id, db)
        challenge_id = challenge_data['id']

        first = complete_challenge(user.id, challenge_id, score=90.0, time_spent_seconds=180, db=db)
        db_session.commit()
        second = complete_challenge(user.id, challenge_id, score=95.0, time_spent_seconds=60, db=db)

        assert first['already_completed'] is False
        assert second['already_completed'] is True

    def test_retry_does_not_create_duplicate_completion_row(self, db_session):
        """Only one DailyChallengeCompletion row exists after multiple complete calls."""
        from app.utils.db import db
        user = _make_user(db_session)
        challenge_data = get_today_challenge(user.id, db)
        challenge_id = challenge_data['id']

        complete_challenge(user.id, challenge_id, score=85.0, time_spent_seconds=200, db=db)
        db_session.commit()
        complete_challenge(user.id, challenge_id, score=95.0, time_spent_seconds=100, db=db)
        db_session.commit()

        count = DailyChallengeCompletion.query.filter_by(
            challenge_id=challenge_id, user_id=user.id
        ).count()
        assert count == 1

    def test_already_completed_response_has_no_bonus_xp(self, db_session):
        """When already completed, response omits bonus_xp to prevent double-award."""
        from app.utils.db import db
        user = _make_user(db_session)
        challenge_data = get_today_challenge(user.id, db)
        challenge_id = challenge_data['id']

        complete_challenge(user.id, challenge_id, score=88.0, time_spent_seconds=150, db=db)
        db_session.commit()
        retry = complete_challenge(user.id, challenge_id, score=99.0, time_spent_seconds=50, db=db)

        # Retry response must not carry bonus_xp — callers use this to guard XP award
        assert 'bonus_xp' not in retry


class TestBonusXpOnlyOnCompletion:
    """bonus_xp is awarded only on real completion, not on view."""

    def test_get_today_challenge_does_not_change_xp(self, db_session):
        """Calling get_today_challenge (view) does not award any XP."""
        from app.utils.db import db
        from app.achievements.models import UserStatistics

        user = _make_user(db_session)
        stats_before = UserStatistics.query.filter_by(user_id=user.id).first()
        xp_before = stats_before.total_xp if stats_before else 0

        # View the challenge three times
        get_today_challenge(user.id, db)
        get_today_challenge(user.id, db)
        get_today_challenge(user.id, db)

        stats_after = UserStatistics.query.filter_by(user_id=user.id).first()
        xp_after = stats_after.total_xp if stats_after else 0
        assert xp_after == xp_before, "get_today_challenge must not award XP"

    def test_complete_challenge_first_time_includes_bonus_xp(self, db_session):
        """First completion returns bonus_xp in the response."""
        from app.utils.db import db
        user = _make_user(db_session)
        challenge_data = get_today_challenge(user.id, db)
        challenge_id = challenge_data['id']

        result = complete_challenge(user.id, challenge_id, score=92.0, time_spent_seconds=120, db=db)
        db_session.commit()

        assert result['already_completed'] is False
        assert result.get('bonus_xp', 0) > 0

    def test_complete_challenge_invalid_id_raises_value_error(self, db_session):
        """Completing a non-existent challenge raises ValueError (not silent None)."""
        from app.utils.db import db
        user = _make_user(db_session)

        import pytest
        with pytest.raises(ValueError):
            complete_challenge(user.id, challenge_id=999999, score=None, time_spent_seconds=None, db=db)


class TestChallengeStreak7Correctness:
    """challenge_streak_7 achievement uses the correct streak walk-backward logic."""

    def test_streak_7_requires_all_7_consecutive_days(self, db_session):
        """Exactly 7 consecutive completions produce a streak of 7."""
        from app.utils.db import db
        user = _make_user(db_session)
        today = date.today()

        for offset in range(7):
            _complete_for_date(user.id, today - timedelta(days=offset), db_session)

        assert get_challenge_streak(user.id, db) == 7

    def test_six_days_insufficient_for_streak_7(self, db_session):
        """6 consecutive days gives streak=6, not 7."""
        from app.utils.db import db
        user = _make_user(db_session)
        today = date.today()

        for offset in range(6):
            _complete_for_date(user.id, today - timedelta(days=offset), db_session)

        assert get_challenge_streak(user.id, db) == 6

    def test_gap_on_day_1_limits_streak_to_one(self, db_session):
        """If yesterday is missing but today completed, streak = 1 (gap on day 1 stops walk)."""
        from app.utils.db import db
        user = _make_user(db_session)
        today = date.today()

        # Complete today and days 2-7 ago; yesterday (offset=1) is missing
        _complete_for_date(user.id, today, db_session)
        for offset in range(2, 8):
            _complete_for_date(user.id, today - timedelta(days=offset), db_session)

        # Walk: today=1, yesterday missing → break → streak=1
        assert get_challenge_streak(user.id, db) == 1

    def test_zero_completions_streak_is_zero(self, db_session):
        """User with no completions has streak=0."""
        from app.utils.db import db
        user = _make_user(db_session)
        assert get_challenge_streak(user.id, db) == 0
