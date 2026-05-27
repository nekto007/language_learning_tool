"""Tests for Task 27: Daily Race — matchmaking и ghost participants.

Covers:
- get_or_create_race does not create duplicate participants under concurrent-style inserts
- Ghost points are computed in memory, never stored in the DB
- Adult-gate: birth_year=None is treated as adult (no blocking)
- route_position values stay within [0, 100]
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
from app.daily_plan.rivals import (
    GhostRival,
    _ghost_target_position,
    _RIVAL_TARGET_MIN_FRACTION,
    _RIVAL_TARGET_MAX_FRACTION,
    get_ghost_rival,
    is_adult_user,
)


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
# Adult-gate: birth_year=None treated as adult
# ---------------------------------------------------------------------------

class TestAdultGate:
    def test_none_birth_year_is_adult(self):
        """is_adult_user(None) must return True for backward compatibility."""
        assert is_adult_user(None) is True

    def test_none_birth_year_not_adult_gate(self):
        """is_adult_user(None) must not block any user."""
        assert is_adult_user(None, reference_year=2026) is True

    def test_young_birth_year_is_not_adult(self):
        assert is_adult_user(2015, reference_year=2026) is False

    def test_borderline_adult(self):
        assert is_adult_user(2008, reference_year=2026) is True
        assert is_adult_user(2009, reference_year=2026) is False

    def test_get_ghost_rival_not_blocked_by_none_birth_year(self, db_session):
        """get_ghost_rival must work normally — caller is responsible for the
        adult check. None birth_year should not cause an error inside the
        function (no birth_year param in get_ghost_rival)."""
        rival = get_ghost_rival(
            user_id=1,
            race_date=date(2026, 5, 27),
            now=datetime(2026, 5, 27, 12, 0, tzinfo=timezone.utc),
        )
        assert isinstance(rival, GhostRival)

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


# ---------------------------------------------------------------------------
# route_position bounds [0, 100]
# ---------------------------------------------------------------------------

class TestRoutePositionBounds:
    def test_ghost_target_position_within_0_100(self):
        """_ghost_target_position must always return a value in [0, 100]."""
        for seed in range(0, 100_000, 1009):
            pos = _ghost_target_position(seed)
            assert 0 <= pos <= 100, (
                f'seed={seed} gave out-of-bounds target={pos}'
            )

    def test_ghost_target_position_in_expected_band(self):
        """Target positions must fall in the slightly-behind band."""
        min_expected = int(_RIVAL_TARGET_MIN_FRACTION * 100)
        max_expected = int(round(_RIVAL_TARGET_MAX_FRACTION * 100))
        for seed in range(0, 100_000, 997):
            pos = _ghost_target_position(seed)
            assert min_expected <= pos <= max_expected, (
                f'seed={seed} gave pos={pos} outside [{min_expected}, {max_expected}]'
            )

    def test_get_ghost_rival_position_within_0_100(self):
        """get_ghost_rival must produce route_position in [0, 100] for any time."""
        test_cases = [
            datetime(2026, 5, 27, 0, 0, tzinfo=timezone.utc),   # midnight
            datetime(2026, 5, 27, 8, 0, tzinfo=timezone.utc),   # start hour
            datetime(2026, 5, 27, 14, 30, tzinfo=timezone.utc), # midday
            datetime(2026, 5, 27, 22, 0, tzinfo=timezone.utc),  # end hour
            datetime(2026, 5, 27, 23, 59, tzinfo=timezone.utc), # near midnight
        ]
        for now in test_cases:
            rival = get_ghost_rival(
                user_id=42,
                race_date=date(2026, 5, 27),
                now=now,
            )
            assert 0 <= rival.route_position <= 100, (
                f'now={now} gave out-of-bounds position={rival.route_position}'
            )

    def test_get_ghost_rival_past_date_returns_full_target(self):
        """Past race dates should return the ghost's full target position."""
        now = datetime(2026, 5, 28, 12, 0, tzinfo=timezone.utc)  # day after
        rival = get_ghost_rival(
            user_id=1,
            race_date=date(2026, 5, 27),
            now=now,
        )
        # Should be the full target (> 0) and within bounds
        assert rival.route_position > 0
        assert rival.route_position <= 100

    def test_get_ghost_rival_future_date_returns_zero(self):
        """Future race dates should return position 0."""
        now = datetime(2026, 5, 26, 12, 0, tzinfo=timezone.utc)  # day before
        rival = get_ghost_rival(
            user_id=1,
            race_date=date(2026, 5, 27),
            now=now,
        )
        assert rival.route_position == 0

    def test_compute_ghost_points_within_target_bounds(self):
        """compute_ghost_points (for DailyRace ghosts) must not exceed target."""
        ghost = GhostParticipant(name='Сириус', seed=7777)
        # At end of day the ghost should reach its full target
        now = datetime(2026, 5, 27, 23, 0, tzinfo=timezone.utc)
        pts = compute_ghost_points(ghost, date(2026, 5, 27), now=now, tz='UTC')
        assert pts >= 0
        assert pts <= _GHOST_MAX_TARGET
