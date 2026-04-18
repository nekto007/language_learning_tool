from __future__ import annotations

import logging
from datetime import date, datetime, timezone
from typing import Any, Optional

from app.daily_plan.models import DailyPlanLog, MissionPlan, MissionType, SourceKind
from app.daily_plan.mission_selector import select_mission, detect_primary_track, save_mission_type
from app.daily_plan.assembler import (
    assemble_progress_mission,
    assemble_reading_mission,
    assemble_repair_mission,
)

logger = logging.getLogger(__name__)


def compute_day_secured(phases: list[dict]) -> bool:
    """Return True when all required phases are marked completed."""
    required = [p for p in phases if p.get('required', True)]
    if not required:
        return False
    return all(p.get('completed', False) for p in required)


def write_secured_at(user_id: int, plan_date: date, mission_type: Optional[str] = None) -> None:
    """Write secured_at timestamp to DailyPlanLog if not already set.

    Creates the log row if it doesn't exist; updates only if secured_at is null.
    This is idempotent — calling it multiple times is safe.
    Callers are responsible for wrapping in try/except and rolling back on failure.
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
        log.secured_at = datetime.now(timezone.utc)
    db.session.flush()


def _with_plan_meta(
    payload: dict[str, Any],
    *,
    mission_plan_enabled: bool,
    effective_mode: str,
    fallback_reason: Optional[str] = None,
) -> dict[str, Any]:
    enriched = dict(payload)
    enriched['_plan_meta'] = {
        'mission_plan_enabled': mission_plan_enabled,
        'effective_mode': effective_mode,
        'fallback_reason': fallback_reason,
    }
    return enriched


def _mission_plan_to_dict(plan: MissionPlan) -> dict[str, Any]:
    def _enum_value(obj: Any) -> Any:
        if hasattr(obj, 'value'):
            return obj.value
        return obj

    phases_list = [
        {
            'id': p.id,
            'phase': _enum_value(p.phase),
            'title': p.title,
            'source_kind': _enum_value(p.source_kind),
            'mode': p.mode,
            'required': p.required,
            'completed': p.completed,
            'preview': {
                'item_count': p.preview.item_count,
                'content_title': p.preview.content_title,
                'estimated_minutes': p.preview.estimated_minutes,
            } if p.preview else None,
        }
        for p in plan.phases
    ]

    result: dict[str, Any] = {
        'plan_version': plan.plan_version,
        'day_secured': compute_day_secured(phases_list),
        'mission': {
            'type': _enum_value(plan.mission.type),
            'title': plan.mission.title,
            'reason_code': plan.mission.reason_code,
            'reason_text': plan.mission.reason_text,
        },
        'primary_goal': {
            'type': plan.primary_goal.type,
            'title': plan.primary_goal.title,
            'success_criterion': plan.primary_goal.success_criterion,
        },
        'primary_source': {
            'kind': _enum_value(plan.primary_source.kind),
            'id': plan.primary_source.id,
            'label': plan.primary_source.label,
        },
        'phases': phases_list,
        'completion': plan.completion,
    }

    if plan.legacy:
        result['legacy'] = plan.legacy
        for k, v in plan.legacy.items():
            if k not in result:
                result[k] = v

    return result


def get_mission_plan(user_id: int, tz: Optional[str] = None) -> Optional[dict[str, Any]]:
    """Select mission type → assemble phases → return JSON-serializable dict. Returns None on failure (caller falls back to legacy)."""
    try:
        mission_type, reason_code, reason_text, repair_breakdown = select_mission(user_id, tz)

        plan: Optional[MissionPlan] = None

        if mission_type == MissionType.repair:
            plan = assemble_repair_mission(
                user_id,
                repair_breakdown,
                reason_code=reason_code,
                reason_text=reason_text,
                tz=tz,
            )

        elif mission_type == MissionType.reading:
            plan = assemble_reading_mission(
                user_id,
                reason_code=reason_code,
                reason_text=reason_text,
                tz=tz,
            )

        elif mission_type == MissionType.progress:
            track = detect_primary_track(user_id)
            primary_source = track if track in (SourceKind.normal_course, SourceKind.book_course) else SourceKind.normal_course
            plan = assemble_progress_mission(
                user_id,
                primary_source,
                reason_code=reason_code,
                reason_text=reason_text,
                tz=tz,
            )

        if plan is None:
            logger.warning(
                "%s assembler returned None for user_id=%s, falling back to legacy",
                mission_type.value,
                user_id,
            )
            return None

        # Persist selected mission type for rotation logic without committing the
        # outer request transaction. This helper is used inside dashboard/widget
        # code paths that may already be running under a savepoint.
        from app.utils.db import db
        try:
            from datetime import datetime
            import pytz
            from config.settings import DEFAULT_TIMEZONE
            try:
                tz_obj = pytz.timezone(tz or DEFAULT_TIMEZONE)
            except pytz.UnknownTimeZoneError:
                tz_obj = pytz.timezone(DEFAULT_TIMEZONE)
            user_today = datetime.now(tz_obj).date()
            with db.session.begin_nested():
                save_mission_type(user_id, mission_type, user_today)
        except Exception:
            logger.warning(
                "Failed to persist mission type for user %s", user_id,
                exc_info=True,
            )

        return _mission_plan_to_dict(plan)

    except Exception:
        logger.exception("Failed to build mission plan for user %s", user_id)
        return None


def get_daily_plan_unified(user_id: int, tz: Optional[str] = None) -> dict[str, Any]:
    """Entry point: returns mission plan if user.use_mission_plan is True, otherwise legacy get_daily_plan_v2()."""
    from app.auth.models import User

    user = User.query.get(user_id)
    if user and user.use_mission_plan:
        mission_payload = get_mission_plan(user_id, tz)
        if mission_payload is not None:
            return _with_plan_meta(
                mission_payload,
                mission_plan_enabled=True,
                effective_mode='mission',
            )
        logger.warning("mission assembler failed for user_id=%s, falling back to legacy", user_id)
        from app.telegram.queries import get_daily_plan_v2
        legacy_payload = get_daily_plan_v2(user_id, tz) if tz else get_daily_plan_v2(user_id)
        return _with_plan_meta(
            legacy_payload,
            mission_plan_enabled=True,
            effective_mode='legacy_fallback',
            fallback_reason='mission_build_failed',
        )

    from app.telegram.queries import get_daily_plan_v2
    payload = get_daily_plan_v2(user_id, tz) if tz else get_daily_plan_v2(user_id)
    return _with_plan_meta(
        payload,
        mission_plan_enabled=False,
        effective_mode='legacy',
    )
