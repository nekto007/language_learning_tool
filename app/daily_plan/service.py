from __future__ import annotations

import logging
from datetime import date, datetime, timezone
from typing import Any, Optional

from app.daily_plan.models import DailyPlanLog

logger = logging.getLogger(__name__)


def is_plan_paused(user: Any) -> bool:
    """Return True when the user has an active plan-pause.

    Centralised so route guards (study, lesson, daily-plan API) share one
    definition. ``user.plan_paused_until`` is a date — pause is active
    while it is strictly greater than the user's local today.
    """
    if user is None:
        return False
    paused_until = getattr(user, 'plan_paused_until', None)
    if not paused_until:
        return False
    from app.utils.time_utils import get_user_local_date
    return paused_until > get_user_local_date(getattr(user, 'id', None))


def compute_day_secured_from_activity(
    plan: dict[str, Any],
    plan_completion: dict[str, bool],
) -> bool:
    """Real-time day_secured derived from actual user activity.

    Only ``unified`` and ``paused`` modes are supported now. Other shapes
    fall through to the plan payload's own ``day_secured``.

    Graduated users (all curriculum exhausted, has history): required is []
    and _plan_meta.graduated=True. Day secured only when the user has
    logged any learning activity today — keeps the streak meaningful.
    """
    plan_meta = plan.get('_plan_meta') or {}
    effective_mode = plan_meta.get('effective_mode')
    if effective_mode == 'paused':
        return bool(plan.get('day_secured', False))
    if effective_mode == 'unified':
        required = plan.get('required') or []
        if not required:
            graduated = plan_meta.get('graduated', False)
            if not graduated:
                return False
            user_id = plan_meta.get('user_id')
            if not user_id:
                return False
            from app.utils.activity_tracker import has_learning_activity
            from app.utils.time_utils import get_user_local_day_bounds
            from app.utils.db import db as _db
            start_of_day, end_of_day = get_user_local_day_bounds(user_id, _db)
            now_utc = datetime.now(timezone.utc).replace(tzinfo=None)
            return has_learning_activity(user_id, start_of_day, min(end_of_day, now_utc))
        return all(
            plan_completion.get(item.get('id', ''), False)
            or bool(item.get('completed'))
            or bool(item.get('skipped'))
            or bool(item.get('blocked'))
            for item in required
        )
    return bool(plan.get('day_secured', False))


def has_extra_review_capacity(user_id: int, deck_id: Optional[int] = None) -> bool:
    """True when SRS cards are due AND the user still has review budget today."""
    try:
        from app.srs.counting import count_due_cards, get_new_card_budget
        from app.study.models import QuizDeckWord
        from app.utils.db import db

        word_ids: Optional[list[int]] = None
        if deck_id is not None:
            word_ids = [
                wid for (wid,) in db.session.query(QuizDeckWord.word_id)
                .filter(QuizDeckWord.deck_id == deck_id, QuizDeckWord.word_id.isnot(None))
                .all()
            ]
            if not word_ids:
                return False

        due = count_due_cards(user_id, db, word_ids=word_ids)
        _, remaining_reviews = get_new_card_budget(user_id, db)
        return due > 0 and remaining_reviews > 0
    except Exception:
        logger.exception("Failed to compute review capacity for user %s", user_id)
        return False


def write_secured_at(user_id: int, plan_date: date, mission_type: Optional[str] = None) -> None:
    """Write secured_at timestamp to DailyPlanLog if not already set.

    ``mission_type`` is nullable and kept for backward compat with existing
    rows; unified users always pass ``None``.
    """
    from app.utils.db import db
    log = DailyPlanLog.query.filter_by(user_id=user_id, plan_date=plan_date).first()
    if log is None:
        log = DailyPlanLog(
            user_id=user_id,
            plan_date=plan_date,
            mission_type=mission_type,
        )
        db.session.add(log)
    if log.secured_at is None:
        log.secured_at = datetime.now(timezone.utc).replace(tzinfo=None)
    db.session.flush()


def _with_plan_meta(
    payload: dict[str, Any],
    *,
    effective_mode: str,
    fallback_reason: Optional[str] = None,
    graduated: bool = False,
    user_id: Optional[int] = None,
) -> dict[str, Any]:
    enriched = dict(payload)
    enriched['_plan_meta'] = {
        'mission_plan_enabled': False,
        'effective_mode': effective_mode,
        'fallback_reason': fallback_reason,
        'graduated': graduated,
        'user_id': user_id,
    }
    return enriched


def get_daily_plan_unified(user_id: int, tz: Optional[str] = None) -> dict[str, Any]:
    """Entry point: paused short-circuit, otherwise unified plan.

    Linear/mission/legacy modes have been removed. ``tz`` is accepted for
    API compatibility but unused (item builders read authoritative DB
    state; the API layer handles user-local date concerns).
    """
    from app.auth.models import User
    from app.utils.time_utils import get_user_local_date

    user = User.query.get(user_id)

    if user and user.plan_paused_until and user.plan_paused_until > get_user_local_date(user_id):
        today = get_user_local_date(user_id)
        secured_row = DailyPlanLog.query.filter_by(
            user_id=user_id, plan_date=today,
        ).first()
        pre_pause_secured = bool(secured_row and secured_row.secured_at)
        logger.info(
            "daily_plan_unified user=%s mode=paused until=%s day_secured=%s",
            user_id, user.plan_paused_until, pre_pause_secured,
        )
        return _with_plan_meta(
            {
                'mode': 'paused',
                'paused_until': user.plan_paused_until.isoformat(),
                'day_secured': pre_pause_secured,
            },
            effective_mode='paused',
        )

    from app.daily_plan.plan import get_daily_plan
    try:
        payload = get_daily_plan(user_id)
        graduated = bool(payload.get('graduated', False))
        logger.info("daily_plan_unified user=%s mode=unified graduated=%s", user_id, graduated)
        return _with_plan_meta(
            payload, effective_mode='unified', graduated=graduated, user_id=user_id,
        )
    except Exception:
        logger.exception(
            "unified plan assembly failed for user_id=%s — returning empty payload",
            user_id,
        )
        # Defensive empty payload: every required is empty, so day_secured=False.
        return _with_plan_meta(
            {
                'mode': 'unified',
                'required': [],
                'optional': [],
                'setup': [],
                'day_secured': False,
            },
            effective_mode='unified',
            fallback_reason='unified_build_failed',
        )
