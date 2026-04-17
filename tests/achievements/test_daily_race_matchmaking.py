"""Tests for daily race matchmaking (Task 21).

`get_or_create_race` places a user into a race cohort on a given calendar
date. It must:

- Create a new race when the user is not yet in one
- Return the same race on subsequent calls for the same user+date
- Prefer an existing race whose participants have similar stats
  (streak_days +-10 and plans_completed_total +-20)
- Refuse full races (5 humans)
- Fill the cohort with deterministic ghost participants when fewer than 3
  humans are present
"""
from __future__ import annotations

import uuid
from datetime import date

import pytest

from app.achievements.daily_race import (
    DailyRace,
    DailyRaceParticipant,
    RACE_MAX_PARTICIPANTS,
    RACE_MIN_PARTICIPANTS,
    GhostParticipant,
    RaceCohort,
    get_or_create_race,
)
from app.achievements.models import UserStatistics
from app.auth.models import User


def _make_user(db_session, *, suffix: str | None = None) -> User:
    suffix = suffix or uuid.uuid4().hex[:8]
    user = User(
        username=f'race_{suffix}',
        email=f'race_{suffix}@test.com',
        active=True,
    )
    user.set_password('test123')
    db_session.add(user)
    db_session.flush()
    return user


def _with_stats(
    db_session,
    user: User,
    *,
    streak: int = 0,
    plans: int = 0,
) -> UserStatistics:
    stats = UserStatistics(
        user_id=user.id,
        current_streak_days=streak,
        plans_completed_total=plans,
    )
    db_session.add(stats)
    db_session.flush()
    return stats


class TestCreateOnFirstCall:
    def test_creates_new_race_for_first_user(self, db_session):
        user = _make_user(db_session)
        _with_stats(db_session, user, streak=5, plans=10)

        cohort = get_or_create_race(user.id, date(2026, 4, 17))

        assert isinstance(cohort, RaceCohort)
        assert cohort.race.id is not None
        assert cohort.race.race_date == date(2026, 4, 17)
        assert len(cohort.participants) == 1
        assert cohort.participants[0].user_id == user.id

    def test_user_without_stats_is_accepted(self, db_session):
        """Users without a UserStatistics row are treated as (0, 0)."""
        user = _make_user(db_session)
        cohort = get_or_create_race(user.id, date(2026, 4, 17))

        assert cohort.race is not None
        assert len(cohort.participants) == 1


class TestIdempotency:
    def test_second_call_returns_same_race(self, db_session):
        user = _make_user(db_session)
        _with_stats(db_session, user, streak=5, plans=10)

        first = get_or_create_race(user.id, date(2026, 4, 17))
        second = get_or_create_race(user.id, date(2026, 4, 17))

        assert first.race.id == second.race.id
        # No duplicate participant row created
        count = (
            db_session.query(DailyRaceParticipant)
            .filter_by(user_id=user.id, race_date=date(2026, 4, 17))
            .count()
        )
        assert count == 1

    def test_different_dates_get_different_races(self, db_session):
        user = _make_user(db_session)
        _with_stats(db_session, user, streak=5, plans=10)

        a = get_or_create_race(user.id, date(2026, 4, 17))
        b = get_or_create_race(user.id, date(2026, 4, 18))

        assert a.race.id != b.race.id


class TestSimilarityMatching:
    def test_joins_race_with_similar_stats(self, db_session):
        race_date = date(2026, 4, 17)
        u1 = _make_user(db_session)
        _with_stats(db_session, u1, streak=12, plans=30)
        u2 = _make_user(db_session)
        _with_stats(db_session, u2, streak=15, plans=35)

        first = get_or_create_race(u1.id, race_date)
        second = get_or_create_race(u2.id, race_date)

        assert first.race.id == second.race.id
        user_ids = {p.user_id for p in second.participants}
        assert {u1.id, u2.id} <= user_ids

    def test_does_not_join_race_with_dissimilar_streak(self, db_session):
        race_date = date(2026, 4, 17)
        novice = _make_user(db_session)
        _with_stats(db_session, novice, streak=2, plans=3)
        veteran = _make_user(db_session)
        _with_stats(db_session, veteran, streak=100, plans=200)

        r1 = get_or_create_race(novice.id, race_date)
        r2 = get_or_create_race(veteran.id, race_date)

        assert r1.race.id != r2.race.id

    def test_does_not_join_race_with_dissimilar_plans(self, db_session):
        race_date = date(2026, 4, 17)
        beginner = _make_user(db_session)
        _with_stats(db_session, beginner, streak=10, plans=5)
        expert = _make_user(db_session)
        _with_stats(db_session, expert, streak=10, plans=150)

        r1 = get_or_create_race(beginner.id, race_date)
        r2 = get_or_create_race(expert.id, race_date)

        assert r1.race.id != r2.race.id

    def test_borderline_similarity_still_matches(self, db_session):
        """Boundary: streak diff exactly 10 and plans diff exactly 20 still
        counts as similar."""
        race_date = date(2026, 4, 17)
        a = _make_user(db_session)
        _with_stats(db_session, a, streak=10, plans=30)
        b = _make_user(db_session)
        _with_stats(db_session, b, streak=20, plans=50)

        r1 = get_or_create_race(a.id, race_date)
        r2 = get_or_create_race(b.id, race_date)

        assert r1.race.id == r2.race.id


class TestCapacity:
    def test_does_not_join_full_race(self, db_session):
        """A race at RACE_MAX_PARTICIPANTS is full - new user creates a new
        race even if stats match."""
        race_date = date(2026, 4, 17)
        cohort_ids = []
        existing = []
        for _ in range(RACE_MAX_PARTICIPANTS):
            u = _make_user(db_session)
            _with_stats(db_session, u, streak=5, plans=10)
            cohort = get_or_create_race(u.id, race_date)
            cohort_ids.append(cohort.race.id)
            existing.append(u.id)

        assert len(set(cohort_ids)) == 1, 'first 5 users should share a race'
        full_race_id = cohort_ids[0]
        participant_count = (
            db_session.query(DailyRaceParticipant)
            .filter_by(race_id=full_race_id)
            .count()
        )
        assert participant_count == RACE_MAX_PARTICIPANTS

        newcomer = _make_user(db_session)
        _with_stats(db_session, newcomer, streak=5, plans=10)
        new_cohort = get_or_create_race(newcomer.id, race_date)

        assert new_cohort.race.id != full_race_id


class TestGhostFilling:
    def test_solo_user_gets_ghost_fillers_to_minimum(self, db_session):
        user = _make_user(db_session)
        _with_stats(db_session, user, streak=3, plans=5)

        cohort = get_or_create_race(user.id, date(2026, 4, 17))

        assert len(cohort.participants) == 1
        total = len(cohort.participants) + len(cohort.ghosts)
        assert total >= RACE_MIN_PARTICIPANTS
        assert all(isinstance(g, GhostParticipant) for g in cohort.ghosts)
        assert all(g.name for g in cohort.ghosts)

    def test_two_users_get_one_ghost(self, db_session):
        race_date = date(2026, 4, 17)
        a = _make_user(db_session)
        _with_stats(db_session, a, streak=5, plans=10)
        b = _make_user(db_session)
        _with_stats(db_session, b, streak=5, plans=10)

        get_or_create_race(a.id, race_date)
        cohort = get_or_create_race(b.id, race_date)

        assert len(cohort.participants) == 2
        assert len(cohort.ghosts) == 1

    def test_three_users_get_no_ghosts(self, db_session):
        race_date = date(2026, 4, 17)
        users = []
        for _ in range(3):
            u = _make_user(db_session)
            _with_stats(db_session, u, streak=5, plans=10)
            users.append(u)
            cohort = get_or_create_race(u.id, race_date)

        assert len(cohort.participants) == 3
        assert len(cohort.ghosts) == 0

    def test_ghost_names_are_deterministic_per_race(self, db_session):
        user = _make_user(db_session)
        _with_stats(db_session, user, streak=3, plans=5)

        first = get_or_create_race(user.id, date(2026, 4, 17))
        second = get_or_create_race(user.id, date(2026, 4, 17))

        assert [g.name for g in first.ghosts] == [g.name for g in second.ghosts]
        assert [g.seed for g in first.ghosts] == [g.seed for g in second.ghosts]

    def test_ghosts_unique_within_cohort(self, db_session):
        user = _make_user(db_session)
        _with_stats(db_session, user, streak=3, plans=5)

        cohort = get_or_create_race(user.id, date(2026, 4, 17))
        names = [g.name for g in cohort.ghosts]
        assert len(names) == len(set(names)), 'ghost names must be unique'
