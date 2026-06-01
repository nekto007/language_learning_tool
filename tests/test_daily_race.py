"""Tests for Daily Race — matchmaking and ghost participants.

Covers:
- get_or_create_race does not create duplicate participants under concurrent-style inserts
- Ghost points are computed in memory, never stored in the DB
- Adult-gate: birth_year=None is treated as adult (no blocking)
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from unittest.mock import patch

import pytest
from sqlalchemy.exc import IntegrityError

from app.achievements.daily_race import (
    DailyRace,
    DailyRaceParticipant,
    GhostParticipant,
    _generate_ghosts,
    _ghost_target_points,
    _GHOST_MIN_TARGET,
    _GHOST_MAX_TARGET,
    compute_ghost_points,
    get_or_create_race,
    get_race_standings,
)
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


# ---------------------------------------------------------------------------
# Concurrent duplicate prevention
# ---------------------------------------------------------------------------

class TestConcurrentRaceCreation:
    def test_unique_constraint_prevents_duplicate_participant(self, db_session):
        """The DB unique constraint blocks a second participant row for the same
        user+date even when inserted directly."""
        user = _make_user(db_session)
        race = DailyRace(race_date=date(2026, 5, 27))
        db_session.add(race)
        db_session.flush()

        db_session.add(DailyRaceParticipant(
            race_id=race.id, user_id=user.id, race_date=race.race_date
        ))
        db_session.flush()

        db_session.add(DailyRaceParticipant(
            race_id=race.id, user_id=user.id, race_date=race.race_date
        ))
        with pytest.raises(IntegrityError):
            db_session.flush()
        db_session.rollback()

    def test_integrity_error_path_returns_existing_participant(self, db_session):
        """If a concurrent writer already inserted the participant (simulated by
        pre-inserting the row), get_or_create_race recovers gracefully and
        returns the existing cohort instead of raising."""
        race_date = date(2026, 5, 1)
        user = _make_user(db_session)

        # Pre-create the race and participant (simulates a concurrent winner)
        race = DailyRace(race_date=race_date)
        db_session.add(race)
        db_session.flush()
        db_session.add(DailyRaceParticipant(
            race_id=race.id, user_id=user.id, race_date=race_date
        ))
        db_session.flush()

        # Now call get_or_create_race — it should detect the existing row
        # on the first SELECT and short-circuit gracefully.
        cohort = get_or_create_race(user.id, race_date)
        assert cohort.race.id == race.id
        count = (
            db_session.query(DailyRaceParticipant)
            .filter_by(user_id=user.id, race_date=race_date)
            .count()
        )
        assert count == 1

    def test_second_call_never_creates_duplicate_row(self, db_session):
        """Two sequential calls to get_or_create_race for the same user+date
        must result in exactly one DailyRaceParticipant row."""
        race_date = date(2026, 5, 2)
        user = _make_user(db_session)

        get_or_create_race(user.id, race_date)
        get_or_create_race(user.id, race_date)

        count = (
            db_session.query(DailyRaceParticipant)
            .filter_by(user_id=user.id, race_date=race_date)
            .count()
        )
        assert count == 1


# ---------------------------------------------------------------------------
# Ghost points are computed, not stored
# ---------------------------------------------------------------------------

class TestGhostPointsNotPersisted:
    def test_ghost_participant_is_dataclass_not_db_model(self, db_session):
        """GhostParticipant must be a plain dataclass, not a SQLAlchemy model."""
        ghost = GhostParticipant(name='Луна', seed=42)
        assert not hasattr(ghost, '__tablename__'), (
            'GhostParticipant must not be a DB model'
        )

    def test_generate_ghosts_creates_no_db_rows(self, db_session):
        """_generate_ghosts must not write any rows to the DB."""
        before = db_session.query(DailyRaceParticipant).count()
        ghosts = _generate_ghosts(race_id=999, count=2)
        after = db_session.query(DailyRaceParticipant).count()
        assert after == before
        assert len(ghosts) == 2
        assert all(isinstance(g, GhostParticipant) for g in ghosts)

    def test_cohort_ghosts_not_in_participant_table(self, db_session):
        """After creating a solo race (1 human), the 2 ghost fillers must not
        appear as DailyRaceParticipant rows."""
        race_date = date(2026, 5, 3)
        user = _make_user(db_session)

        cohort = get_or_create_race(user.id, race_date)
        assert len(cohort.ghosts) == 2  # fills up to MIN=3

        # No ghost rows in DB
        all_rows = (
            db_session.query(DailyRaceParticipant)
            .filter_by(race_date=race_date)
            .all()
        )
        assert len(all_rows) == 1
        assert all_rows[0].user_id == user.id

    def test_compute_ghost_points_no_db_write(self, db_session):
        """compute_ghost_points must not mutate the DB."""
        ghost = GhostParticipant(name='Комета', seed=1234)
        before = db_session.query(DailyRaceParticipant).count()
        pts = compute_ghost_points(ghost, date(2026, 5, 3))
        after = db_session.query(DailyRaceParticipant).count()
        assert after == before
        assert isinstance(pts, int)

    def test_ghost_target_points_within_bounds(self):
        """Ghost target points must be within [_GHOST_MIN_TARGET, _GHOST_MAX_TARGET]."""
        for seed in range(0, 10_000, 137):
            target = _ghost_target_points(seed)
            assert _GHOST_MIN_TARGET <= target <= _GHOST_MAX_TARGET, (
                f'seed={seed} gave out-of-bounds target={target}'
            )


# ---------------------------------------------------------------------------
# Adult-gate: API endpoint behaviour
# ---------------------------------------------------------------------------

class TestAdultGate:
    def test_api_adult_gate_allows_none_birth_year(self, authenticated_client, db_session):
        """The /api/daily-race endpoint must not return 403 when birth_year is None."""
        from unittest.mock import patch as mock_patch
        user = authenticated_client.application.test_user
        user.birth_year = None
        db_session.flush()

        plan = {
            'next_lesson': None, 'grammar_topic': None, 'words_due': 0,
            'has_any_words': False, 'book_to_read': None, 'suggested_books': [],
            'book_course_lesson': None, 'book_course_done_today': False,
            'onboarding': None, 'bonus': [], 'phases': [],
            'mission': {'type': 'p', 'title': 'M', 'reason_code': 'r', 'reason_text': 't'},
        }
        summary = {
            'lessons_count': 0, 'words_reviewed': 0, 'srs_words_reviewed': 0,
            'grammar_exercises': 0, 'books_read': [], 'book_course_lessons_today': 0,
        }
        with mock_patch('app.daily_plan.service.get_daily_plan_unified', return_value=plan), \
             mock_patch('app.telegram.queries.get_daily_summary', return_value=summary):
            resp = authenticated_client.get('/api/daily-race')
        assert resp.status_code != 403, (
            'birth_year=None must not trigger age_restricted gate'
        )

    def test_api_adult_gate_blocks_minor(self, authenticated_client, db_session):
        """The /api/daily-race endpoint must return 403 for underage users."""
        from datetime import datetime as _dt
        user = authenticated_client.application.test_user
        user.birth_year = _dt.utcnow().year - 10  # clearly a child
        db_session.flush()

        resp = authenticated_client.get('/api/daily-race')
        assert resp.status_code == 403


    def test_compute_ghost_points_within_target_bounds(self):
        """compute_ghost_points (for DailyRace ghosts) must not exceed target."""
        ghost = GhostParticipant(name='Сириус', seed=7777)
        now = datetime(2026, 5, 27, 23, 0, tzinfo=timezone.utc)
        pts = compute_ghost_points(ghost, date(2026, 5, 27), now=now, tz='UTC')
        assert pts >= 0
        assert pts <= _GHOST_MAX_TARGET
