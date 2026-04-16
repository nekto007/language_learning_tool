# app/curriculum/service.py
import logging
from datetime import datetime, UTC
from typing import Any, Dict, List, Optional

from sqlalchemy import func
from sqlalchemy.exc import SQLAlchemyError

from app.curriculum.models import LessonProgress, Lessons, Module
from app.utils.db import db
from app.utils.db_utils import query_by_ids
from app.utils.normalization import normalize_text  # noqa: F401 — re-export

logger = logging.getLogger(__name__)

# Re-exports for backward compatibility
from app.curriculum.grading import (  # noqa: E402, F401
    process_grammar_submission,
    process_quiz_submission,
    process_matching_submission,
    process_final_test_submission,
)
from app.curriculum.card_service import (  # noqa: E402, F401
    get_audio_filename,
    get_cards_for_lesson,
    smart_shuffle_cards,
    process_card_review_for_lesson,
    get_card_session_for_lesson,
    calculate_card_intervals,
    sync_lesson_cards_to_words,
)


def get_user_level_progress(user_id: int) -> Dict[int, Dict[str, Any]]:
    """
    Получает прогресс пользователя по всем уровням CEFR

    Args:
        user_id (int): ID пользователя

    Returns:
        dict: Словарь с данными о прогрессе пользователя по уровням
    """
    from app.curriculum.models import CEFRLevel

    # Получаем все уровни
    levels = CEFRLevel.query.all()
    level_ids = [level.id for level in levels]

    # Получаем все модули для этих уровней
    modules = query_by_ids(Module.query, Module.level_id, level_ids)
    module_ids = [module.id for module in modules]

    # Получаем все уроки для этих модулей
    lessons = query_by_ids(Lessons.query, Lessons.module_id, module_ids)
    lesson_ids = [lesson.id for lesson in lessons]

    # Получаем статистику по завершенным урокам
    completed_lessons = LessonProgress.query.filter(
        LessonProgress.user_id == user_id,
        LessonProgress.lesson_id.in_(lesson_ids),
        LessonProgress.status == 'completed'
    ).all()

    # Вычисляем прогресс для каждого уровня
    level_progress = {}

    for level in levels:
        # Получаем все уроки для этого уровня
        level_modules = [module for module in modules if module.level_id == level.id]
        level_module_ids = [module.id for module in level_modules]
        level_lessons = [lesson for lesson in lessons if lesson.module_id in level_module_ids]

        # Общее количество уроков на этом уровне
        total_lessons = len(level_lessons)

        # Количество завершенных уроков
        completed_lesson_ids = [progress.lesson_id for progress in completed_lessons]
        completed_count = sum(1 for lesson in level_lessons if lesson.id in completed_lesson_ids)

        # Вычисляем процент прогресса
        progress_percent = int((completed_count / total_lessons) * 100) if total_lessons > 0 else 0

        # Сохраняем данные о прогрессе
        level_progress[level.id] = {
            'level': level,
            'total_lessons': total_lessons,
            'completed_lessons': completed_count,
            'progress_percent': progress_percent
        }

    return level_progress


def get_user_active_lessons(user_id: int, limit: int = 5) -> List[Dict[str, Any]]:
    """
    Получает список активных уроков пользователя

    Args:
        user_id (int): ID пользователя
        limit (int): Максимальное количество уроков для возврата

    Returns:
        list: Список активных уроков с данными о прогрессе
    """
    # Получаем уроки, которые пользователь начал, но не завершил
    in_progress_lessons = db.session.query(
        Lessons,
        LessonProgress
    ).join(
        LessonProgress,
        Lessons.id == LessonProgress.lesson_id
    ).filter(
        LessonProgress.user_id == user_id,
        LessonProgress.status == 'in_progress'
    ).order_by(
        LessonProgress.last_activity.desc()
    ).limit(limit).all()

    # Форматируем результаты
    active_lessons = []
    for lesson, progress in in_progress_lessons:
        module = Module.query.get(lesson.module_id)
        level = module.level

        active_lessons.append({
            'lesson': lesson,
            'module': module,
            'level': level,
            'progress': progress,
            'last_activity': progress.last_activity
        })

    return active_lessons


def get_next_lesson(current_lesson_id: int) -> Optional[Lessons]:
    """
    Находит следующий урок после текущего в рамках модуля

    Args:
        current_lesson_id (int): ID текущего урока

    Returns:
        Lessons: Объект следующего урока или None, если текущий урок последний
    """
    current_lesson = Lessons.query.get(current_lesson_id)
    if not current_lesson:
        return None

    # Находим следующий урок в порядке 'order' в рамках модуля
    next_lesson = None
    if current_lesson.order is not None:
        next_lesson = Lessons.query.filter(
            Lessons.module_id == current_lesson.module_id,
            Lessons.order > current_lesson.order
        ).order_by(
            Lessons.order
        ).first()

    # Если урок с большим order не найден, пробуем найти по номеру урока
    if not next_lesson and current_lesson.number is not None:
        next_lesson = Lessons.query.filter(
            Lessons.module_id == current_lesson.module_id,
            Lessons.number > current_lesson.number
        ).order_by(
            Lessons.number
        ).first()

    return next_lesson


def complete_lesson(user_id: int, lesson_id: int, score: float = 100.0) -> Optional[LessonProgress]:
    """
    Отмечает урок как завершенный для пользователя

    Args:
        user_id (int): ID пользователя
        lesson_id (int): ID урока
        score (float): Оценка за урок (0-100)

    Returns:
        LessonProgress: Объект прогресса урока или None при ошибке
    """
    progress = LessonProgress.query.filter_by(
        user_id=user_id,
        lesson_id=lesson_id
    ).first()

    # Track if this is an existing progress (for legacy attempt detection)
    existing_progress = progress is not None
    previous_score = progress.score if existing_progress else 0

    if not progress:
        progress = LessonProgress(
            user_id=user_id,
            lesson_id=lesson_id,
            status='in_progress',
            started_at=datetime.now(UTC),
            last_activity=datetime.now(UTC)
        )
        db.session.add(progress)

    progress.status = 'completed'
    progress.completed_at = datetime.now(UTC)
    progress.score = round(score, 2)
    progress.last_activity = datetime.now(UTC)

    try:
        # First commit to get progress.id
        db.session.commit()

        # Now create LessonAttempt record with valid progress_id
        from app.curriculum.models import LessonAttempt

        # Check if this is a legacy progress without attempts
        # If so, create a retroactive attempt for the previous completion
        # Only for existing progress that was already completed with a score
        if existing_progress and len(progress.attempts) == 0 and previous_score > 0:
            # Create retroactive attempt for the existing score
            legacy_attempt = LessonAttempt(
                user_id=user_id,
                lesson_id=lesson_id,
                lesson_progress_id=progress.id,
                attempt_number=1,
                started_at=progress.started_at,
                completed_at=progress.completed_at or progress.last_activity,
                score=progress.score,
                passed=(progress.score >= 70)
            )
            db.session.add(legacy_attempt)
            db.session.commit()
            db.session.refresh(progress)

        # Create new attempt
        attempt_number = len(progress.attempts) + 1
        attempt = LessonAttempt(
            user_id=user_id,
            lesson_id=lesson_id,
            lesson_progress_id=progress.id,
            attempt_number=attempt_number,
            started_at=progress.started_at,
            completed_at=progress.completed_at,
            score=score,
            passed=(score >= 70)  # Assuming 70% is passing score
        )
        db.session.add(attempt)
        db.session.commit()

        # Refresh to load relationships
        db.session.refresh(progress)

        # Award XP for completing lesson (optional - may not be available)
        try:
            from app.study.xp_service import XPService
            xp_breakdown = XPService.calculate_lesson_xp()
            XPService.award_xp(user_id, xp_breakdown['total_xp'])
        except (ImportError, AttributeError):
            logger.warning("XP service not available, skipping XP award")

        return progress
    except SQLAlchemyError as e:
        logger.exception("Lesson completion recording failed for user=%s lesson=%s: %s", user_id, lesson_id, e)
        db.session.rollback()
        return None


def get_lesson_statistics() -> Dict[str, Any]:
    """
    Получает статистику по всем урокам

    Returns:
        dict: Статистические данные по урокам
    """
    # Получаем общее количество уроков
    total_lessons = Lessons.query.count()

    # Получаем количество уроков по типам
    lesson_types = db.session.query(
        Lessons.type,
        func.count(Lessons.id)
    ).group_by(Lessons.type).all()

    # Получаем количество завершенных уроков
    completed_lessons = db.session.query(
        func.count(LessonProgress.id)
    ).filter(
        LessonProgress.status == 'completed'
    ).scalar()

    # Получаем средний балл по всем завершенным урокам
    avg_score = db.session.query(
        func.avg(LessonProgress.score)
    ).filter(
        LessonProgress.status == 'completed'
    ).scalar()

    # Получаем количество уроков по модулям
    lessons_by_module = db.session.query(
        Lessons.module_id,
        func.count(Lessons.id)
    ).group_by(Lessons.module_id).all()

    return {
        'total_lessons': total_lessons,
        'by_type': dict(lesson_types),  # Consistent naming
        'by_module': dict(lessons_by_module),  # Add missing field
        'lesson_types': dict(lesson_types),  # Keep for backward compatibility
        'completed_lessons': completed_lessons or 0,
        'avg_score': float(avg_score) if avg_score else 0
    }


def calculate_user_curriculum_progress(user_id: int) -> Dict[str, Any]:
    """
    Рассчитывает общий прогресс пользователя по учебному плану

    Args:
        user_id (int): ID пользователя

    Returns:
        dict: Данные о прогрессе пользователя
    """
    # Получаем общее количество уроков
    total_lessons = Lessons.query.count()

    # Получаем количество завершенных уроков пользователя
    completed_lessons = LessonProgress.query.filter(
        LessonProgress.user_id == user_id,
        LessonProgress.status == 'completed'
    ).count()

    # Вычисляем процент прогресса
    progress_percent = (completed_lessons / total_lessons) * 100 if total_lessons > 0 else 0

    # Получаем средний балл пользователя
    avg_score = db.session.query(
        func.avg(LessonProgress.score)
    ).filter(
        LessonProgress.user_id == user_id,
        LessonProgress.status == 'completed'
    ).scalar()

    # Получаем последний завершенный урок
    last_completed = LessonProgress.query.filter(
        LessonProgress.user_id == user_id,
        LessonProgress.status == 'completed'
    ).order_by(
        LessonProgress.completed_at.desc()
    ).first()

    if last_completed:
        last_lesson = Lessons.query.get(last_completed.lesson_id)
        last_module = Module.query.get(last_lesson.module_id)
        last_level = last_module.level
    else:
        last_lesson = None
        last_module = None
        last_level = None

    return {
        'user_id': user_id,
        'total_lessons': total_lessons,
        'completed_lessons': completed_lessons,
        'progress_percent': progress_percent,
        'avg_score': float(avg_score) if avg_score else 0,
        'last_completed_lesson': last_lesson,
        'last_completed_module': last_module,
        'last_completed_level': last_level,
        'last_completed_at': last_completed.completed_at if last_completed else None
    }
