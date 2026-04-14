from __future__ import annotations

from typing import Optional

from sqlalchemy import func

from app.utils.db import db
from app.curriculum.models import LessonProgress
from app.curriculum.book_courses import BookCourseEnrollment
from app.books.models import UserChapterProgress

from app.daily_plan.models import MissionType, SourceKind
from app.daily_plan.repair_pressure import REPAIR_THRESHOLD, calculate_repair_pressure


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


def select_mission(
    user_id: int, tz: Optional[str] = None
) -> tuple[MissionType, str, str]:
    """Pick mission type: (1) Repair if pressure >= 0.6, (2) Reading if primary track is books, (3) Progress otherwise."""
    pressure = calculate_repair_pressure(user_id, tz)
    if pressure.total_score >= REPAIR_THRESHOLD:
        return (
            MissionType.repair,
            "repair_pressure_high",
            "У тебя накопились слабые места — давай укрепим основу",
        )

    track = detect_primary_track(user_id)

    if _is_reading_track(track):
        return (
            MissionType.reading,
            "primary_track_reading",
            "Продолжим чтение — это твой основной трек",
        )

    if track is not None:
        return (
            MissionType.progress,
            "primary_track_progress",
            "Двигаемся вперёд по курсу",
        )

    return (
        MissionType.progress,
        "cold_start",
        "Начни с первого урока — всё впереди!",
    )
