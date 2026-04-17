"""Unit tests for the DailyRace and DailyRaceParticipant models.

Covers:
- Model creation for both tables
- Unique constraint: one participant per user per race_date
- Cascade delete from race to participants
- MISSION_PHASE_POINTS helper parity with the dashboard scoreboard
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, timezone

import pytest
from sqlalchemy.exc import IntegrityError

from app.achievements.daily_race import (
    DailyRace,
    DailyRaceParticipant,
    MISSION_PHASE_POINTS,
    RACE_MAX_PARTICIPANTS,
    RACE_MIN_PARTICIPANTS,
    phase_points,
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


class TestDailyRaceModel:
    def test_create_race(self, db_session):
        race = DailyRace(race_date=date(2026, 4, 17))
        db_session.add(race)
        db_session.flush()
        assert race.id is not None
        assert race.race_date == date(2026, 4, 17)
        assert race.created_at is not None

    def test_default_created_at_is_utc(self, db_session):
        race = DailyRace(race_date=date(2026, 4, 17))
        db_session.add(race)
        db_session.flush()
        assert isinstance(race.created_at, datetime)


class TestDailyRaceParticipantModel:
    def test_create_participant(self, db_session):
        user = _make_user(db_session)
        race = DailyRace(race_date=date(2026, 4, 17))
        db_session.add(race)
        db_session.flush()

        participant = DailyRaceParticipant(
            race_id=race.id,
            user_id=user.id,
            race_date=race.race_date,
        )
        db_session.add(participant)
        db_session.flush()

        assert participant.id is not None
        assert participant.points == 0
        assert participant.rank is None
        assert participant.finished_at is None

    def test_participant_points_default_zero(self, db_session):
        user = _make_user(db_session)
        race = DailyRace(race_date=date(2026, 4, 17))
        db_session.add(race)
        db_session.flush()

        participant = DailyRaceParticipant(
            race_id=race.id,
            user_id=user.id,
            race_date=race.race_date,
        )
        db_session.add(participant)
        db_session.flush()
        db_session.refresh(participant)

        assert participant.points == 0

    def test_unique_user_per_date(self, db_session):
        """A user cannot join two races on the same calendar date."""
        user = _make_user(db_session)
        race_date = date(2026, 4, 17)

        race_a = DailyRace(race_date=race_date)
        race_b = DailyRace(race_date=race_date)
        db_session.add_all([race_a, race_b])
        db_session.flush()

        db_session.add(
            DailyRaceParticipant(
                race_id=race_a.id, user_id=user.id, race_date=race_date
            )
        )
        db_session.flush()

        db_session.add(
            DailyRaceParticipant(
                race_id=race_b.id, user_id=user.id, race_date=race_date
            )
        )
        with pytest.raises(IntegrityError):
            db_session.flush()
        db_session.rollback()

    def test_same_user_different_date_allowed(self, db_session):
        user = _make_user(db_session)
        race_a = DailyRace(race_date=date(2026, 4, 17))
        race_b = DailyRace(race_date=date(2026, 4, 18))
        db_session.add_all([race_a, race_b])
        db_session.flush()

        db_session.add_all([
            DailyRaceParticipant(
                race_id=race_a.id,
                user_id=user.id,
                race_date=race_a.race_date,
            ),
            DailyRaceParticipant(
                race_id=race_b.id,
                user_id=user.id,
                race_date=race_b.race_date,
            ),
        ])
        db_session.flush()  # must not raise

    def test_cascade_delete_from_race(self, db_session):
        """Deleting the race removes its participants."""
        user = _make_user(db_session)
        race = DailyRace(race_date=date(2026, 4, 17))
        db_session.add(race)
        db_session.flush()

        db_session.add(
            DailyRaceParticipant(
                race_id=race.id, user_id=user.id, race_date=race.race_date
            )
        )
        db_session.flush()

        race_id = race.id
        db_session.delete(race)
        db_session.flush()

        remaining = (
            db_session.query(DailyRaceParticipant)
            .filter_by(race_id=race_id)
            .count()
        )
        assert remaining == 0

    def test_relationship_race_participants(self, db_session):
        user_a = _make_user(db_session)
        user_b = _make_user(db_session)

        race = DailyRace(race_date=date(2026, 4, 17))
        db_session.add(race)
        db_session.flush()

        db_session.add_all([
            DailyRaceParticipant(
                race_id=race.id, user_id=user_a.id, race_date=race.race_date
            ),
            DailyRaceParticipant(
                race_id=race.id, user_id=user_b.id, race_date=race.race_date
            ),
        ])
        db_session.flush()
        db_session.refresh(race)

        user_ids = {p.user_id for p in race.participants}
        assert user_ids == {user_a.id, user_b.id}


class TestCapacityConstants:
    def test_capacity_range(self):
        assert RACE_MIN_PARTICIPANTS == 3
        assert RACE_MAX_PARTICIPANTS == 5
        assert RACE_MIN_PARTICIPANTS <= RACE_MAX_PARTICIPANTS


class TestMissionPhasePoints:
    """phase_points() must agree with the dashboard scoreboard."""

    def test_covers_all_phase_kinds(self):
        # Pulled from app/words/routes.py::_MISSION_PHASE_POINTS
        expected = {
            'recall': 8,
            'learn': 22,
            'use': 18,
            'read': 20,
            'check': 12,
            'close': 0,
        }
        assert MISSION_PHASE_POINTS == expected

    def test_agrees_with_dashboard_points(self):
        from app.words.routes import _MISSION_PHASE_POINTS

        assert dict(MISSION_PHASE_POINTS) == _MISSION_PHASE_POINTS

    @pytest.mark.parametrize(
        'phase,expected',
        [
            ('recall', 8),
            ('learn', 22),
            ('use', 18),
            ('read', 20),
            ('check', 12),
            ('close', 0),
        ],
    )
    def test_phase_points_known_kinds(self, phase, expected):
        assert phase_points(phase) == expected

    def test_phase_points_unknown_returns_zero(self):
        assert phase_points('unknown') == 0
        assert phase_points('') == 0
        assert phase_points(None) == 0
