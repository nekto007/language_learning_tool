"""Canonical SRS counting and budget functions.

Single source of truth for due-card counts and daily-budget math across
mission-plan (`app/daily_plan/assembler.py`), linear-plan
(`app/daily_plan/linear/slots/srs_slot.py`) and the /study card API
(`app/study/api_routes.py`).

Design:
- All DateTime columns (`next_review`, `first_reviewed`, `last_reviewed`)
  are naive UTC. We normalize `now` to naive UTC before comparison.
- `count_due_cards` includes state IN (learning, relearning, review) and
  filters out `UserWord.status IN ('new','learning','review')` and
  buried cards. No mix filter — we count all due cards the user has.
- `today_start` is naive UTC midnight (matches how /study tallies the day).
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import func, or_

from app.srs.constants import CardState
from app.study.models import UserCardDirection, UserWord
from app.utils.db import db as _db


def _naive_utc_now(now_utc: Optional[datetime] = None) -> datetime:
    if now_utc is None:
        return datetime.now(timezone.utc).replace(tzinfo=None)
    if now_utc.tzinfo is not None:
        return now_utc.astimezone(timezone.utc).replace(tzinfo=None)
    return now_utc


def _today_start_naive(now_utc: Optional[datetime] = None) -> datetime:
    now = _naive_utc_now(now_utc)
    return now.replace(hour=0, minute=0, second=0, microsecond=0)


def count_due_cards(user_id: int, db: Any = _db, now_utc: Optional[datetime] = None) -> int:
    """Count review/learning/relearning cards due for the user right now.

    Includes all three due states. Excludes NEW state (not yet activated),
    mastered UserWords, and currently-buried cards.
    """
    now = _naive_utc_now(now_utc)
    return int(
        db.session.query(func.count(UserCardDirection.id))
        .join(UserWord, UserCardDirection.user_word_id == UserWord.id)
        .filter(
            UserWord.user_id == user_id,
            UserWord.status.in_(('new', 'learning', 'review')),
            UserCardDirection.state.in_(
                (
                    CardState.LEARNING.value,
                    CardState.RELEARNING.value,
                    CardState.REVIEW.value,
                )
            ),
            UserCardDirection.next_review <= now,
            or_(
                UserCardDirection.buried_until.is_(None),
                UserCardDirection.buried_until <= now,
            ),
        )
        .scalar()
        or 0
    )


def count_new_cards_today(user_id: int, db: Any = _db, now_utc: Optional[datetime] = None) -> int:
    """Count card directions first reviewed today (naive UTC midnight boundary)."""
    today_start = _today_start_naive(now_utc)
    user_word_ids_subq = db.session.query(UserWord.id).filter_by(user_id=user_id)
    return int(
        db.session.query(func.count(UserCardDirection.id))
        .filter(
            UserCardDirection.user_word_id.in_(user_word_ids_subq),
            UserCardDirection.first_reviewed.isnot(None),
            UserCardDirection.first_reviewed >= today_start,
        )
        .scalar()
        or 0
    )


def count_reviews_today(user_id: int, db: Any = _db, now_utc: Optional[datetime] = None) -> int:
    """Count card reviews that happened today excluding first-time reviews."""
    today_start = _today_start_naive(now_utc)
    user_word_ids_subq = db.session.query(UserWord.id).filter_by(user_id=user_id)
    return int(
        db.session.query(func.count(UserCardDirection.id))
        .filter(
            UserCardDirection.user_word_id.in_(user_word_ids_subq),
            UserCardDirection.last_reviewed.isnot(None),
            UserCardDirection.last_reviewed >= today_start,
            UserCardDirection.first_reviewed.isnot(None),
            UserCardDirection.first_reviewed < today_start,
        )
        .scalar()
        or 0
    )
