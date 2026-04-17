"""Tests for the ghost rival system (Task 16 / Phase 3).

Covers:
- is_adult_user: various birth_year scenarios including None (unknown age)
- GhostRival dataclass label is always GHOST_RIVAL_LABEL
- Deterministic position: same inputs produce same output
- Time-based position: 0 before window, target after window, linear within
- Past date: position equals target
- Future date: position is 0
- Child-gating: callers must not call get_ghost_rival for child users
"""
from __future__ import annotations

from datetime import date, datetime, timezone, time

import pytest

from app.daily_plan.rivals import (
    GhostRival,
    GHOST_RIVAL_LABEL,
    _ADULT_AGE_THRESHOLD,
    _RIVAL_START_HOUR,
    _RIVAL_END_HOUR,
    _rival_seed,
    _progress_fraction,
    _ghost_target_position,
    get_ghost_rival,
    is_adult_user,
)

RACE_DATE = date(2026, 4, 18)
USER_ID = 42


class TestIsAdultUser:
    def test_none_birth_year_is_adult(self):
        assert is_adult_user(None) is True

    def test_exactly_18_is_adult(self):
        reference = 2026
        birth_year = reference - _ADULT_AGE_THRESHOLD
        assert is_adult_user(birth_year, reference_year=reference) is True

    def test_17_is_child(self):
        reference = 2026
        birth_year = reference - (_ADULT_AGE_THRESHOLD - 1)
        assert is_adult_user(birth_year, reference_year=reference) is False

    def test_old_user_is_adult(self):
        assert is_adult_user(1980, reference_year=2026) is True

    def test_future_birth_year_is_child(self):
        assert is_adult_user(2020, reference_year=2026) is False

    def test_reference_year_defaults_to_current(self):
        # A user born in 1900 is always an adult.
        assert is_adult_user(1900) is True


class TestRivalSeed:
    def test_same_inputs_same_seed(self):
        assert _rival_seed(USER_ID, RACE_DATE) == _rival_seed(USER_ID, RACE_DATE)

    def test_different_user_different_seed(self):
        assert _rival_seed(USER_ID, RACE_DATE) != _rival_seed(USER_ID + 1, RACE_DATE)

    def test_different_date_different_seed(self):
        other_date = date(2026, 4, 19)
        assert _rival_seed(USER_ID, RACE_DATE) != _rival_seed(USER_ID, other_date)

    def test_seed_is_positive_int(self):
        seed = _rival_seed(USER_ID, RACE_DATE)
        assert isinstance(seed, int)
        assert seed >= 0


class TestProgressFraction:
    def test_before_start_is_zero(self):
        t = time(_RIVAL_START_HOUR - 1, 0)
        assert _progress_fraction(t) == 0.0

    def test_at_start_is_zero(self):
        t = time(_RIVAL_START_HOUR, 0)
        assert _progress_fraction(t) == 0.0

    def test_at_end_is_one(self):
        t = time(_RIVAL_END_HOUR, 0)
        assert _progress_fraction(t) == 1.0

    def test_after_end_is_one(self):
        t = time(23, 59)
        assert _progress_fraction(t) == 1.0

    def test_midpoint(self):
        mid_hour = (_RIVAL_START_HOUR + _RIVAL_END_HOUR) / 2
        t = time(int(mid_hour), 0)
        frac = _progress_fraction(t)
        assert 0.45 < frac < 0.55


class TestGhostTargetPosition:
    def test_within_valid_range(self):
        for seed in range(0, 100_000, 1_000):
            pos = _ghost_target_position(seed)
            assert 0 <= pos <= 100, f"position {pos} out of range for seed {seed}"

    def test_in_slightly_behind_band(self):
        for seed in range(0, 100_000, 1_000):
            pos = _ghost_target_position(seed)
            assert pos <= 85, f"ghost target {pos} exceeds max band"
            assert pos >= 55, f"ghost target {pos} below min band"


class TestGetGhostRival:
    def _make_now(self, hour: int, minute: int = 0) -> datetime:
        import pytz
        tz = pytz.timezone('Europe/Moscow')
        return tz.localize(datetime(RACE_DATE.year, RACE_DATE.month, RACE_DATE.day, hour, minute))

    def test_returns_ghost_rival(self):
        now = self._make_now(12, 0)
        rival = get_ghost_rival(USER_ID, RACE_DATE, now=now, tz='Europe/Moscow')
        assert isinstance(rival, GhostRival)

    def test_display_label_is_training_rival(self):
        now = self._make_now(12, 0)
        rival = get_ghost_rival(USER_ID, RACE_DATE, now=now, tz='Europe/Moscow')
        assert rival.display_label == GHOST_RIVAL_LABEL

    def test_deterministic_same_inputs(self):
        now = self._make_now(15, 30)
        r1 = get_ghost_rival(USER_ID, RACE_DATE, now=now, tz='Europe/Moscow')
        r2 = get_ghost_rival(USER_ID, RACE_DATE, now=now, tz='Europe/Moscow')
        assert r1.route_position == r2.route_position
        assert r1.name == r2.name
        assert r1.avatar_seed == r2.avatar_seed

    def test_position_zero_before_window(self):
        now = self._make_now(_RIVAL_START_HOUR - 1, 0)
        rival = get_ghost_rival(USER_ID, RACE_DATE, now=now, tz='Europe/Moscow')
        assert rival.route_position == 0

    def test_position_nonzero_midday(self):
        now = self._make_now(14, 0)
        rival = get_ghost_rival(USER_ID, RACE_DATE, now=now, tz='Europe/Moscow')
        assert rival.route_position > 0

    def test_position_full_after_window(self):
        now = self._make_now(_RIVAL_END_HOUR, 30)
        rival = get_ghost_rival(USER_ID, RACE_DATE, now=now, tz='Europe/Moscow')
        seed = _rival_seed(USER_ID, RACE_DATE)
        expected_target = _ghost_target_position(seed)
        assert rival.route_position == expected_target

    def test_past_date_returns_full_target(self):
        import pytz
        tz = pytz.timezone('Europe/Moscow')
        past_date = date(2026, 4, 1)
        # now is after past_date
        now = tz.localize(datetime(2026, 4, 18, 12, 0))
        rival = get_ghost_rival(USER_ID, past_date, now=now, tz='Europe/Moscow')
        seed = _rival_seed(USER_ID, past_date)
        assert rival.route_position == _ghost_target_position(seed)

    def test_future_date_returns_zero(self):
        import pytz
        tz = pytz.timezone('Europe/Moscow')
        future_date = date(2026, 4, 30)
        now = tz.localize(datetime(2026, 4, 18, 12, 0))
        rival = get_ghost_rival(USER_ID, future_date, now=now, tz='Europe/Moscow')
        assert rival.route_position == 0

    def test_different_users_different_rivals(self):
        now = self._make_now(14, 0)
        r1 = get_ghost_rival(1, RACE_DATE, now=now, tz='Europe/Moscow')
        r2 = get_ghost_rival(9999, RACE_DATE, now=now, tz='Europe/Moscow')
        # At least name or position should differ (very high probability)
        differs = r1.name != r2.name or r1.route_position != r2.route_position
        assert differs

    def test_position_grows_through_day(self):
        pos_morning = get_ghost_rival(USER_ID, RACE_DATE, now=self._make_now(9, 0), tz='Europe/Moscow').route_position
        pos_noon = get_ghost_rival(USER_ID, RACE_DATE, now=self._make_now(13, 0), tz='Europe/Moscow').route_position
        pos_evening = get_ghost_rival(USER_ID, RACE_DATE, now=self._make_now(20, 0), tz='Europe/Moscow').route_position
        assert pos_morning <= pos_noon <= pos_evening


class TestChildGating:
    """Verify is_adult_user gates child users correctly."""

    def test_child_user_not_adult(self):
        assert is_adult_user(2015, reference_year=2026) is False

    def test_teen_not_adult(self):
        assert is_adult_user(2009, reference_year=2026) is False

    def test_just_turned_adult(self):
        assert is_adult_user(2008, reference_year=2026) is True

    def test_null_birth_year_is_adult_by_default(self):
        assert is_adult_user(None, reference_year=2026) is True
