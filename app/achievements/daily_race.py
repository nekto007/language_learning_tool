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

import logging
import random
from dataclasses import dataclass, field
from datetime import date as date_cls, datetime, time as time_cls, timezone
from typing import Iterable, List, Mapping, Optional

logger = logging.getLogger(__name__)

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


# ---------------------------------------------------------------------------
# Point updates
# ---------------------------------------------------------------------------


def _points_from_plan(
    phases: Iterable[Mapping], plan_completion: Mapping[str, bool],
) -> tuple[int, bool]:
    """Sum points for completed phases and report whether all required are done.

    Returns (total_points, all_required_done).
    """
    total = 0
    all_required_done = True
    saw_required = False
    for phase in phases:
        phase_id = phase.get('id')
        done = bool(plan_completion.get(phase_id, False))
        if phase.get('required', True):
            saw_required = True
            if not done:
                all_required_done = False
        if done:
            total += phase_points(phase.get('phase'))
    if not saw_required:
        all_required_done = False
    return total, all_required_done


def update_race_points(
    user_id: int,
    race_date: date_cls,
    points: int,
    *,
    finished: bool = False,
    now_utc: datetime | None = None,
) -> Optional[DailyRaceParticipant]:
    """Set a participant's race points and optionally mark them as finished.

    Silently returns ``None`` when the user is not enrolled in a race for
    ``race_date`` (so legacy users who never triggered matchmaking do not
    explode phase completion). Point totals are absolute, not deltas — this
    function is safe to call repeatedly with the same aggregate.
    """
    participant = (
        db.session.query(DailyRaceParticipant)
        .filter_by(user_id=user_id, race_date=race_date)
        .first()
    )
    if participant is None:
        return None
    participant.points = max(0, int(points))
    if finished and participant.finished_at is None:
        participant.finished_at = now_utc or datetime.now(timezone.utc)
    return participant


def update_race_points_from_plan(
    user_id: int,
    race_date: date_cls,
    phases: Iterable[Mapping],
    plan_completion: Mapping[str, bool],
    *,
    now_utc: datetime | None = None,
) -> Optional[DailyRaceParticipant]:
    """Recompute participant points from the current plan+completion view.

    Called on every dashboard/API request that rebuilds the plan, so point
    totals stay in sync with whichever phases have been completed today.
    """
    phase_list = list(phases)
    total, all_required_done = _points_from_plan(phase_list, plan_completion)
    return update_race_points(
        user_id,
        race_date,
        total,
        finished=all_required_done,
        now_utc=now_utc,
    )


# ---------------------------------------------------------------------------
# Ghost point calculation
# ---------------------------------------------------------------------------


# Ghost points grow linearly between these two local hours. Before the
# start hour ghosts have trivial points, after the end hour they sit at
# their full target. Kept as constants so tests can assert specific values
# at known local times without touching the wall clock.
_GHOST_START_HOUR = 8
_GHOST_END_HOUR = 20
_GHOST_MIN_TARGET = 30
_GHOST_MAX_TARGET = 90


def _ghost_target_points(seed: int) -> int:
    """Deterministic per-ghost ceiling of daily points.

    Uses the ghost's seed so every render shows the same ceiling for the
    same race, but different ghosts in the same cohort differ.
    """
    span = _GHOST_MAX_TARGET - _GHOST_MIN_TARGET
    return _GHOST_MIN_TARGET + (abs(int(seed)) % (span + 1))


def _progress_fraction(local_time: time_cls) -> float:
    """Fraction of the ghost-active window that has elapsed (0.0 - 1.0)."""
    if _GHOST_END_HOUR <= _GHOST_START_HOUR:
        return 1.0
    current = local_time.hour + local_time.minute / 60.0
    if current <= _GHOST_START_HOUR:
        return 0.0
    if current >= _GHOST_END_HOUR:
        return 1.0
    window = _GHOST_END_HOUR - _GHOST_START_HOUR
    return (current - _GHOST_START_HOUR) / window


def compute_ghost_points(
    ghost: GhostParticipant,
    race_date: date_cls,
    now: datetime | None = None,
    *,
    tz: str | None = None,
) -> int:
    """Time-based, deterministic point total for a ghost participant.

    Ghosts do not persist points. Every read derives them from the seed and
    the fraction of the day that has elapsed in the user's local timezone.
    Returns 0 for past/future dates outside the race window.
    """
    import pytz
    from config.settings import DEFAULT_TIMEZONE

    tz_name = tz or DEFAULT_TIMEZONE
    try:
        tz_obj = pytz.timezone(tz_name)
    except pytz.UnknownTimeZoneError:
        tz_obj = pytz.timezone(DEFAULT_TIMEZONE)

    if now is None:
        now = datetime.now(tz_obj)
    elif now.tzinfo is None:
        now = tz_obj.localize(now)
    else:
        now = now.astimezone(tz_obj)

    local_today = now.date()
    if local_today < race_date:
        # Race hasn't started in local time yet.
        return 0
    if local_today > race_date:
        # Race is over; ghost stays at full target for display.
        return _ghost_target_points(ghost.seed)

    target = _ghost_target_points(ghost.seed)
    return int(round(target * _progress_fraction(now.time())))


# ---------------------------------------------------------------------------
# Standings
# ---------------------------------------------------------------------------


def get_race_standings(
    user_id: int,
    race_date: date_cls,
    *,
    tz: str | None = None,
    now: datetime | None = None,
) -> Optional[dict]:
    """Return the current race view for ``user_id`` on ``race_date``.

    Enrolls the user if necessary (via ``get_or_create_race``) and returns a
    serializable dict suitable for the dashboard and API response:

    - ``race_id``, ``race_date``
    - ``participants``: list of entries sorted by points desc, each with
      ``user_id``, ``username``, ``points``, ``is_me``, ``is_ghost``,
      ``rank``, ``finished_at``
    - ``my_rank``: current user's 1-indexed rank
    """
    from app.auth.models import User

    cohort = get_or_create_race(user_id, race_date)

    entries: list[dict] = []

    for p in cohort.participants:
        username: Optional[str] = None
        user_obj = db.session.get(User, p.user_id) if p.user_id else None
        if user_obj is not None:
            username = user_obj.username
        entries.append({
            'user_id': p.user_id,
            'username': username or f'user_{p.user_id}',
            'points': int(p.points or 0),
            'is_me': p.user_id == user_id,
            'is_ghost': False,
            'finished_at': p.finished_at.isoformat() if p.finished_at else None,
        })

    for ghost in cohort.ghosts:
        entries.append({
            'user_id': None,
            'username': ghost.name,
            'points': compute_ghost_points(ghost, race_date, now=now, tz=tz),
            'is_me': False,
            'is_ghost': True,
            'finished_at': None,
        })

    entries.sort(
        key=lambda e: (-e['points'], 0 if e['is_me'] else 1, e['username'].lower()),
    )

    my_rank: Optional[int] = None
    for idx, entry in enumerate(entries, start=1):
        entry['rank'] = idx
        if entry['is_me']:
            my_rank = idx

    return {
        'race_id': cohort.race.id,
        'race_date': race_date.isoformat(),
        'participants': entries,
        'my_rank': my_rank,
        'total_participants': len(entries),
    }
