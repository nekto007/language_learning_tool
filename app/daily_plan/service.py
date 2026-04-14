from __future__ import annotations

import logging
from dataclasses import asdict
from typing import Any, Optional

from app.daily_plan.models import MissionPlan, MissionType, SourceKind
from app.daily_plan.mission_selector import select_mission, detect_primary_track
from app.daily_plan.assembler import (
    assemble_progress_mission,
    assemble_reading_mission,
    assemble_repair_mission,
)
from app.daily_plan.repair_pressure import calculate_repair_pressure

logger = logging.getLogger(__name__)


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

    return result


def get_mission_plan(user_id: int, tz: Optional[str] = None) -> Optional[dict[str, Any]]:
    try:
        mission_type, reason_code, reason_text = select_mission(user_id, tz)

        plan: Optional[MissionPlan] = None

        if mission_type == MissionType.repair:
            breakdown = calculate_repair_pressure(user_id, tz)
            plan = assemble_repair_mission(user_id, breakdown, tz)

        elif mission_type == MissionType.reading:
            plan = assemble_reading_mission(user_id, tz)

        elif mission_type == MissionType.progress:
            track = detect_primary_track(user_id)
            primary_source = track if track in (SourceKind.normal_course, SourceKind.book_course) else SourceKind.normal_course
            plan = assemble_progress_mission(user_id, primary_source, tz)

        if plan is None:
            return None

        return _mission_plan_to_dict(plan)

    except Exception:
        logger.exception("Failed to build mission plan for user %s", user_id)
        return None


def get_daily_plan_unified(user_id: int, tz: Optional[str] = None) -> dict[str, Any]:
    from app.auth.models import User

    user = User.query.get(user_id)
    if user and user.use_mission_plan:
        mission_payload = get_mission_plan(user_id, tz)
        if mission_payload is not None:
            return mission_payload

    from app.telegram.queries import get_daily_plan_v2
    return get_daily_plan_v2(user_id, tz or 'UTC')
