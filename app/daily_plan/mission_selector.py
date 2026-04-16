from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Optional

from app.utils.db import db
from app.curriculum.models import LessonProgress
from app.curriculum.book_courses import BookCourseEnrollment
from app.books.models import UserChapterProgress

from app.daily_plan.models import MissionType, SourceKind
from app.daily_plan.repair_pressure import REPAIR_THRESHOLD, RepairBreakdown, calculate_repair_pressure

logger = logging.getLogger(__name__)


def _has_active_book_course(user_id: int) -> bool:
    return db.session.query(
        BookCourseEnrollment.query.filter_by(
            user_id=user_id, status='active'
        ).exists()
    ).scalar()


def _has_lesson_progress(user_id: int) -> bool:
    return db.session.query(
        LessonProgress.query.filter(
            LessonProgress.user_id == user_id,
            LessonProgress.status == 'completed',
        ).exists()
    ).scalar()


def _has_book_reading(user_id: int) -> bool:
    return db.session.query(
        UserChapterProgress.query.filter(
            UserChapterProgress.user_id == user_id,
        ).exists()
    ).scalar()


def detect_primary_track(user_id: int) -> Optional[SourceKind]:
    if _has_active_book_course(user_id):
        return SourceKind.book_course
    if _has_lesson_progress(user_id):
        return SourceKind.normal_course
    if _has_book_reading(user_id):
        return SourceKind.books
    return None


def _is_reading_track(track: Optional[SourceKind]) -> bool:
    return track == SourceKind.books


def get_last_mission_type(user_id: int, before_date: date) -> Optional[MissionType]:
    """Return the mission type used on the most recent day before *before_date*.

    Queries StreakEvent rows with event_type='mission_selected'.
    """
    from app.achievements.models import StreakEvent

    event = (
        StreakEvent.query
        .filter(
            StreakEvent.user_id == user_id,
            StreakEvent.event_type == 'mission_selected',
            StreakEvent.event_date < before_date,
        )
        .order_by(StreakEvent.event_date.desc())
        .first()
    )
    if event and event.details:
        raw = event.details.get('mission_type')
        try:
            return MissionType(raw)
        except (ValueError, KeyError):
            return None
    return None


def save_mission_type(user_id: int, mission_type: MissionType,
                      for_date: date) -> None:
    """Persist which mission type was selected for *for_date*.

    Creates or updates a StreakEvent with event_type='mission_selected'.
    """
    from app.achievements.models import StreakEvent

    existing = StreakEvent.query.filter_by(
        user_id=user_id,
        event_type='mission_selected',
        event_date=for_date,
    ).first()
    if existing:
        existing.details = {'mission_type': mission_type.value}
    else:
        db.session.add(StreakEvent(
            user_id=user_id,
            event_type='mission_selected',
            coins_delta=0,
            event_date=for_date,
            details={'mission_type': mission_type.value},
        ))


def _pick_non_repair_mission(
    user_id: int,
    tz: Optional[str],
) -> tuple[MissionType, str, str, None]:
    """Pick between reading and progress based on primary track."""
    track = detect_primary_track(user_id)

    if _is_reading_track(track):
        return (
            MissionType.reading,
            "primary_track_reading",
            "Продолжим чтение — это твой основной трек",
            None,
        )

    if track is not None:
        return (
            MissionType.progress,
            "primary_track_progress",
            "Двигаемся вперёд по курсу",
            None,
        )

    return (
        MissionType.progress,
        "cold_start",
        "Начни с первого урока — всё впереди!",
        None,
    )


# Maps each non-repair mission type to reason overrides when rotation kicks in.
_ROTATION_REASON: dict[MissionType, tuple[str, str]] = {
    MissionType.reading: (
        "rotation_reading",
        "Сегодня — день чтения для разнообразия",
    ),
    MissionType.progress: (
        "rotation_progress",
        "Сегодня двигаемся вперёд — для баланса",
    ),
}


def select_mission(
    user_id: int, tz: Optional[str] = None
) -> tuple[MissionType, str, str, Optional[RepairBreakdown]]:
    """Pick mission type with rotation.

    Priority:
    1. Repair — always wins when pressure >= threshold.
    2. Non-repair pick (reading / progress) based on primary track.
    3. If the non-repair pick equals yesterday's type AND an alternative
       is viable, swap to the alternative for variety.
    """
    pressure = calculate_repair_pressure(user_id, tz)
    if pressure.total_score >= REPAIR_THRESHOLD:
        return (
            MissionType.repair,
            "repair_pressure_high",
            "У тебя накопились слабые места — давай укрепим основу",
            pressure,
        )

    mission_type, reason_code, reason_text, _ = _pick_non_repair_mission(user_id, tz)

    # ── Rotation: avoid same non-repair type two days in a row ──
    try:
        import pytz
        from config.settings import DEFAULT_TIMEZONE
        try:
            tz_obj = pytz.timezone(tz or DEFAULT_TIMEZONE)
        except pytz.UnknownTimeZoneError:
            tz_obj = pytz.timezone(DEFAULT_TIMEZONE)
        from datetime import datetime
        user_today = datetime.now(tz_obj).date()

        yesterday_type = get_last_mission_type(user_id, before_date=user_today)
        if yesterday_type and yesterday_type == mission_type:
            alternative = _find_rotation_alternative(user_id, mission_type)
            if alternative is not None:
                rot_reason_code, rot_reason_text = _ROTATION_REASON.get(
                    alternative, (reason_code, reason_text)
                )
                logger.info(
                    "Mission rotation for user %s: %s → %s (yesterday was %s)",
                    user_id, mission_type.value, alternative.value,
                    yesterday_type.value,
                )
                mission_type = alternative
                reason_code = rot_reason_code
                reason_text = rot_reason_text
    except Exception:
        logger.warning(
            "Mission rotation check failed for user %s, using default pick",
            user_id, exc_info=True,
        )

    return (mission_type, reason_code, reason_text, None)


def _find_rotation_alternative(
    user_id: int, current_type: MissionType
) -> Optional[MissionType]:
    """Return a viable alternative mission type, or None if none available.

    Only swaps between progress ↔ reading. If the alternative track
    isn't available for this user, returns None (keep current).
    """
    if current_type == MissionType.progress:
        if _has_book_reading(user_id):
            return MissionType.reading
    elif current_type == MissionType.reading:
        track = detect_primary_track(user_id)
        if track in (SourceKind.normal_course, SourceKind.book_course, SourceKind.books):
            return MissionType.progress
    return None
