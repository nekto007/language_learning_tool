"""Tests for daily race point updates and ghost point calculation (Task 22).

Covers:
- `update_race_points` writes totals onto the participant row
- `update_race_points_from_plan` sums phase points via the completion map
- `finished_at` is set when all required phases are done
- `compute_ghost_points` is deterministic and time-based
- `get_race_standings` assembles sorted entries with ranks and ghost fillers
"""
from __future__ import annotations

import uuid
from datetime import date, datetime
from unittest.mock import patch

import pytz

from app.achievements.daily_race import (
    DailyRaceParticipant,
    GhostParticipant,
    compute_ghost_points,
    get_or_create_race,
    get_race_standings,
    update_race_points,
    update_race_points_from_plan,
    _ghost_target_points,
    _progress_fraction,
)
from app.achievements.models import UserStatistics
from app.auth.models import User


def _make_user(db_session, *, suffix: str | None = None) -> User:
    suffix = suffix or uuid.uuid4().hex[:8]
    user = User(
        username=f'race_pts_{suffix}',
        email=f'race_pts_{suffix}@test.com',
        active=True,
    )
    user.set_password('test123')
    db_session.add(user)
    db_session.flush()
    return user


def _with_stats(db_session, user: User, *, streak: int = 0, plans: int = 0):
    stats = UserStatistics(
        user_id=user.id,
        current_streak_days=streak,
        plans_completed_total=plans,
    )
    db_session.add(stats)
    db_session.flush()
    return stats


class TestUpdateRacePoints:
    def test_sets_absolute_points_value(self, db_session):
        user = _make_user(db_session)
        _with_stats(db_session, user, streak=3, plans=5)
        race_date = date(2026, 4, 17)
        get_or_create_race(user.id, race_date)

        result = update_race_points(user.id, race_date, 42)
        db_session.flush()

        assert result is not None
        assert result.points == 42

    def test_noop_when_user_not_enrolled(self, db_session):
        user = _make_user(db_session)
        race_date = date(2026, 4, 17)

        result = update_race_points(user.id, race_date, 10)
        assert result is None

    def test_negative_clamped_to_zero(self, db_session):
        user = _make_user(db_session)
        race_date = date(2026, 4, 17)
        get_or_create_race(user.id, race_date)

        result = update_race_points(user.id, race_date, -5)
        assert result is not None
        assert result.points == 0

    def test_finished_flag_sets_timestamp_once(self, db_session):
        user = _make_user(db_session)
        race_date = date(2026, 4, 17)
        get_or_create_race(user.id, race_date)

        first_stamp = datetime(2026, 4, 17, 10, 0, 0)
        second_stamp = datetime(2026, 4, 17, 18, 0, 0)

        update_race_points(user.id, race_date, 20, finished=True, now_utc=first_stamp)
        update_race_points(user.id, race_date, 30, finished=True, now_utc=second_stamp)

        participant = (
            db_session.query(DailyRaceParticipant)
            .filter_by(user_id=user.id, race_date=race_date)
            .first()
        )
        assert participant.points == 30
        assert participant.finished_at == first_stamp


class TestUpdateRacePointsFromPlan:
    def test_sums_points_for_completed_phases(self, db_session):
        user = _make_user(db_session)
        race_date = date(2026, 4, 17)
        get_or_create_race(user.id, race_date)

        phases = [
            {'id': 'p1', 'phase': 'recall', 'required': True},   # 8
            {'id': 'p2', 'phase': 'learn',  'required': True},   # 22
            {'id': 'p3', 'phase': 'check',  'required': True},   # 12
        ]
        completion = {'p1': True, 'p2': True, 'p3': False}

        result = update_race_points_from_plan(
            user.id, race_date, phases, completion,
        )
        assert result is not None
        assert result.points == 8 + 22
        assert result.finished_at is None

    def test_all_required_done_sets_finished(self, db_session):
        user = _make_user(db_session)
        race_date = date(2026, 4, 17)
        get_or_create_race(user.id, race_date)

        phases = [
            {'id': 'a', 'phase': 'recall', 'required': True},
            {'id': 'b', 'phase': 'learn', 'required': True},
            {'id': 'c', 'phase': 'close', 'required': False},
        ]
        completion = {'a': True, 'b': True, 'c': False}

        result = update_race_points_from_plan(
            user.id, race_date, phases, completion,
        )
        assert result is not None
        assert result.finished_at is not None
        assert result.points == 8 + 22

    def test_empty_phase_list_not_finished(self, db_session):
        user = _make_user(db_session)
        race_date = date(2026, 4, 17)
        get_or_create_race(user.id, race_date)

        result = update_race_points_from_plan(user.id, race_date, [], {})
        assert result is not None
        assert result.points == 0
        assert result.finished_at is None

    def test_idempotent_recompute_does_not_drift(self, db_session):
        user = _make_user(db_session)
        race_date = date(2026, 4, 17)
        get_or_create_race(user.id, race_date)

        phases = [
            {'id': 'a', 'phase': 'recall', 'required': True},
            {'id': 'b', 'phase': 'learn', 'required': True},
        ]
        completion = {'a': True, 'b': False}

        for _ in range(3):
            result = update_race_points_from_plan(
                user.id, race_date, phases, completion,
            )
        assert result.points == 8


class TestGhostPointsCalculation:
    def test_zero_before_active_window(self, db_session):
        ghost = GhostParticipant(name='Луна', seed=123)
        race_date = date(2026, 4, 17)
        dawn = pytz.timezone('Europe/Moscow').localize(
            datetime(2026, 4, 17, 5, 0, 0)
        )
        assert compute_ghost_points(ghost, race_date, now=dawn, tz='Europe/Moscow') == 0

    def test_target_reached_after_active_window(self, db_session):
        ghost = GhostParticipant(name='Луна', seed=123)
        race_date = date(2026, 4, 17)
        night = pytz.timezone('Europe/Moscow').localize(
            datetime(2026, 4, 17, 22, 0, 0)
        )
        expected = _ghost_target_points(ghost.seed)
        assert compute_ghost_points(ghost, race_date, now=night, tz='Europe/Moscow') == expected

    def test_midpoint_is_roughly_half(self, db_session):
        ghost = GhostParticipant(name='Луна', seed=321)
        race_date = date(2026, 4, 17)
        midday = pytz.timezone('Europe/Moscow').localize(
            datetime(2026, 4, 17, 14, 0, 0)
        )
        target = _ghost_target_points(ghost.seed)
        got = compute_ghost_points(ghost, race_date, now=midday, tz='Europe/Moscow')
        # 14:00 is halfway between 08:00 and 20:00.
        assert abs(got - target // 2) <= 1

    def test_deterministic_for_same_seed_and_time(self, db_session):
        ghost = GhostParticipant(name='Комета', seed=777)
        race_date = date(2026, 4, 17)
        stamp = pytz.timezone('Europe/Moscow').localize(
            datetime(2026, 4, 17, 13, 30, 0)
        )
        a = compute_ghost_points(ghost, race_date, now=stamp, tz='Europe/Moscow')
        b = compute_ghost_points(ghost, race_date, now=stamp, tz='Europe/Moscow')
        assert a == b

    def test_different_seeds_give_different_targets(self):
        assert _ghost_target_points(1) != _ghost_target_points(37)

    def test_progress_fraction_boundaries(self):
        from datetime import time as time_cls
        assert _progress_fraction(time_cls(6, 0)) == 0.0
        assert _progress_fraction(time_cls(22, 0)) == 1.0

    def test_past_date_returns_full_target(self):
        ghost = GhostParticipant(name='Звёзд', seed=9)
        race_date = date(2026, 4, 17)
        tomorrow = pytz.timezone('Europe/Moscow').localize(
            datetime(2026, 4, 18, 3, 0, 0)
        )
        assert compute_ghost_points(
            ghost, race_date, now=tomorrow, tz='Europe/Moscow'
        ) == _ghost_target_points(ghost.seed)

    def test_future_date_returns_zero(self):
        ghost = GhostParticipant(name='Феникс', seed=11)
        race_date = date(2026, 4, 17)
        yesterday = pytz.timezone('Europe/Moscow').localize(
            datetime(2026, 4, 16, 23, 0, 0)
        )
        assert compute_ghost_points(
            ghost, race_date, now=yesterday, tz='Europe/Moscow'
        ) == 0


class TestRaceStandings:
    def test_includes_user_and_ghost_fillers(self, db_session):
        user = _make_user(db_session)
        _with_stats(db_session, user, streak=3, plans=5)
        race_date = date(2026, 4, 17)

        standings = get_race_standings(user.id, race_date, tz='Europe/Moscow')

        assert standings is not None
        assert standings['race_date'] == race_date.isoformat()
        # one human + two ghosts to hit the 3-participant minimum
        assert standings['total_participants'] >= 3
        humans = [e for e in standings['participants'] if not e['is_ghost']]
        ghosts = [e for e in standings['participants'] if e['is_ghost']]
        assert len(humans) == 1
        assert len(ghosts) >= 2
        assert humans[0]['is_me'] is True

    def test_ranks_sorted_by_points_descending(self, db_session):
        user_a = _make_user(db_session)
        _with_stats(db_session, user_a, streak=3, plans=5)
        user_b = _make_user(db_session)
        _with_stats(db_session, user_b, streak=3, plans=5)
        race_date = date(2026, 4, 17)

        get_or_create_race(user_a.id, race_date)
        get_or_create_race(user_b.id, race_date)
        update_race_points(user_a.id, race_date, 5)
        update_race_points(user_b.id, race_date, 40)

        # Freeze time before ghost active window so ghost points are zero
        # and ranks depend only on the human entries.
        pre_dawn = pytz.timezone('Europe/Moscow').localize(
            datetime(2026, 4, 17, 6, 0, 0)
        )
        standings = get_race_standings(
            user_a.id, race_date, tz='Europe/Moscow', now=pre_dawn,
        )
        # With ghosts at 0 and both humans enrolled, the higher-scoring human
        # should take first place.
        humans = [e for e in standings['participants'] if not e['is_ghost']]
        humans_sorted = sorted(humans, key=lambda e: -e['points'])
        assert humans_sorted[0]['user_id'] == user_b.id
        assert humans_sorted[0]['points'] == 40

        # my_rank should match the user's sorted position.
        me = next(e for e in standings['participants'] if e['is_me'])
        assert me['rank'] == standings['my_rank']

    def test_enrolls_caller_on_first_call(self, db_session):
        user = _make_user(db_session)
        _with_stats(db_session, user, streak=2, plans=3)
        race_date = date(2026, 4, 17)

        assert db_session.query(DailyRaceParticipant).filter_by(
            user_id=user.id, race_date=race_date,
        ).count() == 0

        standings = get_race_standings(user.id, race_date, tz='Europe/Moscow')
        assert standings is not None

        assert db_session.query(DailyRaceParticipant).filter_by(
            user_id=user.id, race_date=race_date,
        ).count() == 1
