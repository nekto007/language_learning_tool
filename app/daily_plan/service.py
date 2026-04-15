from __future__ import annotations

import logging
from typing import Any, Optional

from app.daily_plan.models import MissionPlan, MissionType, SourceKind
from app.daily_plan.mission_selector import select_mission, detect_primary_track
from app.daily_plan.assembler import (
    assemble_progress_mission,
    assemble_reading_mission,
    assemble_repair_mission,
)

logger = logging.getLogger(__name__)


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

    result: dict[str, Any] = {
        'plan_version': plan.plan_version,
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
        'phases': [
            {
                'id': p.id,
                'phase': _enum_value(p.phase),
                'title': p.title,
                'source_kind': _enum_value(p.source_kind),
                'mode': p.mode,
                'required': p.required,
                'completed': p.completed,
            }
            for p in plan.phases
        ],
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
                "%s assembler returned None for user_id=%s",
                mission_type.value if mission_type else "unknown",
                user_id,
            )
            return None

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
        logger.warning("Mission plan enabled but fallback to legacy plan for user %s", user_id)
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
