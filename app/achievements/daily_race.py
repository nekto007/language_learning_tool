"""Daily race models and service helpers.

A daily race groups 3-5 users into a small competitive cohort for a given
calendar date. Points accrue from completed daily-plan mission phases using
the same point values defined in `app/words/routes.py::_MISSION_PHASE_POINTS`.

Only models and basic point helpers live here. Matchmaking and live updates
are layered on top in subsequent tasks.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Mapping

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
