"""Route progress tracking for the infinite learning loop.

One row per user, updated each time a mission phase is completed.
Route steps are weighted by phase kind; a checkpoint fires every
CHECKPOINT_INTERVAL weighted steps.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import Column, DateTime, ForeignKey, Index, Integer, UniqueConstraint

from app.utils.db import db

# Weighted step values per phase kind.
PHASE_STEP_WEIGHTS: dict[str, int] = {
    "learn": 3,
    "recall": 2,
    "use": 2,
    "read": 2,
    "check": 1,
    "close": 1,
    "bonus": 0,
}

CHECKPOINT_INTERVAL = 20  # weighted steps per checkpoint


class UserRouteProgress(db.Model):
    """Cumulative route progress for a single user.

    total_steps: total weighted steps accumulated across all time.
    checkpoint_number: how many checkpoints have been reached (floor(total_steps / CHECKPOINT_INTERVAL)).
    steps_in_checkpoint: weighted steps within the current checkpoint stretch.
    last_updated: UTC timestamp of the last phase completion that changed this row.
    """
    __tablename__ = 'user_route_progress'

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    total_steps = Column(Integer, nullable=False, default=0)
    checkpoint_number = Column(Integer, nullable=False, default=0)
    steps_in_checkpoint = Column(Integer, nullable=False, default=0)
    last_updated = Column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    __table_args__ = (
        UniqueConstraint('user_id', name='uq_user_route_progress_user'),
        Index('idx_user_route_progress_user', 'user_id'),
    )


def get_phase_step_weight(phase_kind: str) -> int:
    """Return the weighted step value for a phase kind string."""
    return PHASE_STEP_WEIGHTS.get(phase_kind, 0)


def add_route_steps(user_id: int, phase_kind: str, db_session) -> tuple[UserRouteProgress, bool]:
    """Increment route progress for a completed phase.

    Returns (progress_row, checkpoint_reached) where checkpoint_reached is True
    if this addition crossed a checkpoint boundary.
    """
    weight = get_phase_step_weight(phase_kind)
    if weight == 0:
        row = _get_or_create(user_id, db_session)
        return row, False

    row = _get_or_create(user_id, db_session)
    old_checkpoint = row.checkpoint_number
    row.total_steps += weight
    row.checkpoint_number = row.total_steps // CHECKPOINT_INTERVAL
    row.steps_in_checkpoint = row.total_steps % CHECKPOINT_INTERVAL
    row.last_updated = datetime.now(timezone.utc)

    checkpoint_reached = row.checkpoint_number > old_checkpoint
    return row, checkpoint_reached


def _get_or_create(user_id: int, db_session) -> UserRouteProgress:
    row = db_session.query(UserRouteProgress).filter_by(user_id=user_id).first()
    if row is None:
        row = UserRouteProgress(
            user_id=user_id,
            total_steps=0,
            checkpoint_number=0,
            steps_in_checkpoint=0,
            last_updated=datetime.now(timezone.utc),
        )
        db_session.add(row)
        db_session.flush()
    return row


def get_route_state(user_id: int, steps_today: int, db_session) -> Optional[dict]:
    """Return a route state dict for API responses.

    steps_today is the sum of weighted steps completed in the current calendar day,
    passed in by the caller who already knows the day's phases.
    """
    row = db_session.query(UserRouteProgress).filter_by(user_id=user_id).first()
    if row is None:
        return {
            "steps_today": steps_today,
            "total_steps": 0,
            "checkpoint_number": 0,
            "steps_to_next_checkpoint": CHECKPOINT_INTERVAL,
            "percent_to_checkpoint": 0,
        }
    steps_to_next = CHECKPOINT_INTERVAL - row.steps_in_checkpoint
    percent = int(row.steps_in_checkpoint * 100 / CHECKPOINT_INTERVAL)
    return {
        "steps_today": steps_today,
        "total_steps": row.total_steps,
        "checkpoint_number": row.checkpoint_number,
        "steps_to_next_checkpoint": steps_to_next,
        "percent_to_checkpoint": percent,
    }
