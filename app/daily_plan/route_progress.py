"""Route progress tracking for the infinite learning loop.

One row per user, updated each time a mission phase is completed.
Route steps are weighted by phase kind; a checkpoint fires every
CHECKPOINT_INTERVAL weighted steps.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import Column, DateTime, ForeignKey, Index, Integer, UniqueConstraint
from sqlalchemy.exc import IntegrityError

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

    row = _get_or_create(user_id, db_session, for_update=True)
    old_checkpoint = row.checkpoint_number
    row.total_steps += weight
    row.checkpoint_number = row.total_steps // CHECKPOINT_INTERVAL
    row.steps_in_checkpoint = row.total_steps % CHECKPOINT_INTERVAL
    row.last_updated = datetime.now(timezone.utc)

    checkpoint_reached = row.checkpoint_number > old_checkpoint
    return row, checkpoint_reached


def _get_or_create(user_id: int, db_session, for_update: bool = False) -> UserRouteProgress:
    q = db_session.query(UserRouteProgress).filter_by(user_id=user_id)
    if for_update:
        q = q.with_for_update()
    row = q.first()
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


def add_route_steps_idempotent(
    user_id: int,
    phase_kind: str,
    plan_date,
    db_session,
) -> tuple["UserRouteProgress", bool]:
    """Idempotent wrapper around add_route_steps keyed by (user_id, phase_kind, plan_date).

    Safe to call on every dashboard load: skips the update if a route_step_added event
    already exists for this (user_id, phase_kind, plan_date).  When a checkpoint boundary
    is crossed a checkpoint_reached event is also persisted for H5 analysis.

    Returns (progress_row, checkpoint_reached).
    """
    from app.daily_plan.models import DailyPlanEvent

    existing = db_session.query(DailyPlanEvent).filter_by(
        user_id=user_id,
        event_type='route_step_added',
        step_kind=phase_kind,
        plan_date=plan_date,
    ).first()

    if existing:
        row = _get_or_create(user_id, db_session)
        return row, False

    savepoint = db_session.begin_nested()
    try:
        row, checkpoint_reached = add_route_steps(user_id, phase_kind, db_session)

        marker = DailyPlanEvent(
            user_id=user_id,
            event_type='route_step_added',
            plan_date=plan_date,
            step_kind=phase_kind,
        )
        db_session.add(marker)

        if checkpoint_reached:
            db_session.add(DailyPlanEvent(
                user_id=user_id,
                event_type='checkpoint_reached',
                plan_date=plan_date,
                step_kind=phase_kind,
            ))

        savepoint.commit()
    except IntegrityError:
        savepoint.rollback()
        # Two distinct races can cause IntegrityError:
        # 1. Duplicate DailyPlanEvent marker (same phase/date already recorded) → idempotent skip.
        # 2. Duplicate UserRouteProgress row (two requests racing to create the first row for
        #    this user) → the other request won row creation, but did NOT record this phase's
        #    marker, so we must retry the increment now that the row exists.
        duplicate_event = db_session.query(DailyPlanEvent).filter_by(
            user_id=user_id,
            event_type='route_step_added',
            step_kind=phase_kind,
            plan_date=plan_date,
        ).first()
        if duplicate_event:
            row = _get_or_create(user_id, db_session)
            return row, False
        # UserRouteProgress row now exists (created by the other request); retry increment.
        row, checkpoint_reached = add_route_steps(user_id, phase_kind, db_session)
        db_session.add(DailyPlanEvent(
            user_id=user_id,
            event_type='route_step_added',
            plan_date=plan_date,
            step_kind=phase_kind,
        ))
        if checkpoint_reached:
            db_session.add(DailyPlanEvent(
                user_id=user_id,
                event_type='checkpoint_reached',
                plan_date=plan_date,
                step_kind=phase_kind,
            ))
        return row, checkpoint_reached

    return row, checkpoint_reached


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
