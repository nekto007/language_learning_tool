"""Daily race models and service helpers.

A daily race groups 3-5 users into a small competitive cohort for a given
calendar date. Points accrue from completed daily-plan mission phases using
the same point values defined in `app/words/routes.py::_MISSION_PHASE_POINTS`.

This module also exposes `get_or_create_race`, the matchmaking entrypoint
used when a user visits their dashboard: it either finds an existing cohort
with similar streak/plan stats or creates a new one, and synthesises
deterministic ghost participants when the cohort has fewer than three
humans.
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field
from datetime import date as date_cls, datetime, timezone
from typing import List, Mapping, Optional

from sqlalchemy import (
    Column,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    UniqueConstraint,
)
from sqlalchemy.orm import relationship

from app.utils.db import db


# Capacity limits for a single daily race cohort.
RACE_MIN_PARTICIPANTS = 3
RACE_MAX_PARTICIPANTS = 5

# Points awarded per mission phase type. Kept in sync with
# `_MISSION_PHASE_POINTS` in app/words/routes.py so that the race scoreboard
# and the dashboard point counter never drift apart.
MISSION_PHASE_POINTS: Mapping[str, int] = {
    'recall': 8,
    'learn': 22,
    'use': 18,
    'read': 20,
    'check': 12,
    'close': 0,
}


def phase_points(phase: str | None) -> int:
    """Return points awarded for a completed mission phase kind."""
    if not phase:
        return 0
    return MISSION_PHASE_POINTS.get(phase, 0)


class DailyRace(db.Model):
    """A single daily race cohort for a given calendar date."""
    __tablename__ = 'daily_races'

    id = Column(Integer, primary_key=True, autoincrement=True)
    race_date = Column(Date, nullable=False)
    created_at = Column(
        DateTime, nullable=False, default=lambda: datetime.now(timezone.utc)
    )

    participants = relationship(
        'DailyRaceParticipant',
        back_populates='race',
        cascade='all, delete-orphan',
        passive_deletes=True,
    )

    __table_args__ = (
        Index('idx_daily_races_date', 'race_date'),
    )

    def __repr__(self) -> str:  # pragma: no cover - trivial
        return f'<DailyRace id={self.id} date={self.race_date}>'


class DailyRaceParticipant(db.Model):
    """Membership row linking a user to a daily race cohort."""
    __tablename__ = 'daily_race_participants'

    id = Column(Integer, primary_key=True, autoincrement=True)
    race_id = Column(
        Integer,
        ForeignKey('daily_races.id', ondelete='CASCADE'),
        nullable=False,
    )
    user_id = Column(
        Integer,
        ForeignKey('users.id', ondelete='CASCADE'),
        nullable=False,
    )
    race_date = Column(Date, nullable=False)
    points = Column(Integer, nullable=False, default=0, server_default='0')
    rank = Column(Integer, nullable=True)
    finished_at = Column(DateTime, nullable=True)
    joined_at = Column(
        DateTime, nullable=False, default=lambda: datetime.now(timezone.utc)
    )

    race = relationship('DailyRace', back_populates='participants')
    user = relationship('User')

    __table_args__ = (
        UniqueConstraint(
            'user_id', 'race_date', name='uq_daily_race_participants_user_date'
        ),
        Index(
            'idx_daily_race_participants_user_date', 'user_id', 'race_date'
        ),
        Index('idx_daily_race_participants_race_id', 'race_id'),
    )

    def __repr__(self) -> str:  # pragma: no cover - trivial
        return (
            f'<DailyRaceParticipant user={self.user_id} race={self.race_id} '
            f'points={self.points}>'
        )


# ---------------------------------------------------------------------------
# Matchmaking
# ---------------------------------------------------------------------------


# Tolerance for considering two users in the same cohort.
_STREAK_TOLERANCE = 10
_PLANS_TOLERANCE = 20

# Pool of flavourful ghost names used to fill small cohorts. Kept short so a
# race can never run out of options (RACE_MIN_PARTICIPANTS - 1 ghosts at most).
_GHOST_NAMES: tuple[str, ...] = (
    'Луна',
    'Комета',
    'Орион',
    'Феникс',
    'Атлас',
    'Звёзд',
    'Вега',
    'Сириус',
)


@dataclass
class GhostParticipant:
    """A synthesised cohort filler used when fewer than 3 humans matched.

    Ghosts are not persisted: their points are computed on read (see Task 22)
    using the seed as a deterministic source.
    """

    name: str
    seed: int
    points: int = 0


@dataclass
class RaceCohort:
    """The full cohort for a user on a given date: race + humans + ghosts."""

    race: DailyRace
    participants: List[DailyRaceParticipant]
    ghosts: List[GhostParticipant] = field(default_factory=list)


def _user_stats_snapshot(user_id: int) -> tuple[int, int]:
    """Return (current_streak_days, plans_completed_total) for matchmaking.

    Users without a UserStatistics row match the zero bucket.
    """
    from app.achievements.models import UserStatistics

    stats = (
        db.session.query(UserStatistics)
        .filter_by(user_id=user_id)
        .first()
    )
    if stats is None:
        return (0, 0)
    return (
        int(stats.current_streak_days or 0),
        int(stats.plans_completed_total or 0),
    )


def _is_similar(
    candidate: tuple[int, int], reference: tuple[int, int]
) -> bool:
    return (
        abs(candidate[0] - reference[0]) <= _STREAK_TOLERANCE
        and abs(candidate[1] - reference[1]) <= _PLANS_TOLERANCE
    )


def _find_matching_race(
    user_id: int,
    race_date: date_cls,
    user_stats: tuple[int, int],
) -> Optional[DailyRace]:
    """Find an existing race on ``race_date`` with room and matching stats.

    A race matches when every existing human participant's stats are within
    tolerance of ``user_stats``. Ordering is by id to keep behaviour stable
    across calls within the same date.
    """
    races = (
        db.session.query(DailyRace)
        .filter_by(race_date=race_date)
        .order_by(DailyRace.id.asc())
        .all()
    )
    for race in races:
        participants = (
            db.session.query(DailyRaceParticipant)
            .filter_by(race_id=race.id)
            .all()
        )
        humans = [p for p in participants if p.user_id is not None]
        if len(humans) >= RACE_MAX_PARTICIPANTS:
            continue
        if any(p.user_id == user_id for p in humans):
            continue
        if humans and not all(
            _is_similar(_user_stats_snapshot(p.user_id), user_stats)
            for p in humans
        ):
            continue
        return race
    return None


def _generate_ghosts(race_id: int, count: int) -> List[GhostParticipant]:
    """Deterministic ghost filler derived from the race id.

    Seeding with ``race_id`` guarantees the same names and seeds on every
    page load for the same race.
    """
    if count <= 0:
        return []
    rng = random.Random(race_id * 1009 + 17)
    pool = list(_GHOST_NAMES)
    rng.shuffle(pool)
    names = pool[:count]
    return [
        GhostParticipant(name=name, seed=rng.randint(1, 10_000))
        for name in names
    ]


def _build_cohort(race: DailyRace) -> RaceCohort:
    participants = (
        db.session.query(DailyRaceParticipant)
        .filter_by(race_id=race.id)
        .order_by(DailyRaceParticipant.joined_at.asc())
        .all()
    )
    humans = [p for p in participants if p.user_id is not None]
    ghosts: List[GhostParticipant] = []
    if len(humans) < RACE_MIN_PARTICIPANTS:
        ghosts = _generate_ghosts(race.id, RACE_MIN_PARTICIPANTS - len(humans))
    return RaceCohort(race=race, participants=humans, ghosts=ghosts)


def get_or_create_race(user_id: int, race_date: date_cls) -> RaceCohort:
    """Place the user into a daily race cohort and return its full view.

    Behaviour:
    - If the user is already a participant for ``race_date``, returns that
      race's cohort unchanged.
    - Otherwise, picks the first existing race on that date whose human
      participants all have stats within tolerance of the user's
      (current_streak_days, plans_completed_total), provided the race is not
      at capacity.
    - If no match is found, a new race is created.
    - Ghost fillers are synthesised when the cohort still has fewer than
      RACE_MIN_PARTICIPANTS humans.
    """
    existing = (
        db.session.query(DailyRaceParticipant)
        .filter_by(user_id=user_id, race_date=race_date)
        .first()
    )
    if existing is not None:
        race = db.session.get(DailyRace, existing.race_id)
        return _build_cohort(race)

    user_stats = _user_stats_snapshot(user_id)
    race = _find_matching_race(user_id, race_date, user_stats)
    if race is None:
        race = DailyRace(race_date=race_date)
        db.session.add(race)
        db.session.flush()

    participant = DailyRaceParticipant(
        race_id=race.id,
        user_id=user_id,
        race_date=race_date,
    )
    db.session.add(participant)
    db.session.flush()

    return _build_cohort(race)
