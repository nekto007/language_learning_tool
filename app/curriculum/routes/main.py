# app/curriculum/routes/main.py

import logging

from flask import Blueprint, flash, redirect, render_template, url_for
from flask_login import current_user, login_required

from app.curriculum.models import CEFRLevel, LessonProgress, Lessons, Module
from app.curriculum.security import check_module_access, require_module_access
from app.utils.db import db

logger = logging.getLogger(__name__)

# Create blueprint for main routes - use curriculum name for compatibility
main_bp = Blueprint('curriculum', __name__)


@main_bp.route('/')
@login_required
def index():
    """Главная страница учебной программы - редирект на /learn/"""
    return redirect('/learn/', code=302)


# =============================================================================
# НОВЫЕ КРАСИВЫЕ URL МАРШРУТЫ
# =============================================================================

# Создаем новый blueprint для красивых URL
learn_bp = Blueprint('learn', __name__)


@learn_bp.route('/')
@login_required
def learn_index():
    """Главная страница обучения - оптимизированная версия с eager loading"""
    try:
        from app.curriculum.services.curriculum_cache_service import CurriculumCacheService

        # Используем оптимизированный сервис - 3 запроса вместо 1000+
        levels_data = CurriculumCacheService.get_levels_with_progress(current_user.id)

        if not levels_data:
            flash('Учебные материалы еще не загружены. Обратитесь к администратору.', 'info')
            return render_template('curriculum/index.html',
                                 levels_data=[],
                                 recent_activity=[],
                                 total_stats={},
                                 gamification={})

        # Рассчитываем общую статистику
        total_stats = {
            'total_lessons': sum(ld['total_lessons'] for ld in levels_data),
            'completed_lessons': sum(ld['completed_lessons'] for ld in levels_data)
        }
        total_stats['progress_percent'] = round(
            (total_stats['completed_lessons'] / total_stats['total_lessons'] * 100)
            if total_stats['total_lessons'] > 0 else 0
        )

        # Получаем последние активности (1 оптимизированный запрос)
        recent_activity = CurriculumCacheService.get_recent_activity(current_user.id, limit=5)

        # Получаем геймификацию (2 оптимизированных запроса)
        gamification = CurriculumCacheService.get_gamification_stats(current_user.id)

        return render_template('curriculum/index.html',
                             levels_data=levels_data,
                             recent_activity=recent_activity,
                             total_stats=total_stats,
                             gamification=gamification)

    except Exception as e:
        logger.error(f"Ошибка загрузки curriculum: {str(e)}")
        flash('Произошла ошибка при загрузке учебной программы.', 'error')
        return render_template('curriculum/index.html',
                             levels_data=[],
                             recent_activity=[],
                             total_stats={},
                             gamification={})






@learn_bp.route('/<int:lesson_id>/')
@login_required
def lesson_by_id(lesson_id):
    """Короткий URL для урока: /learn/{lesson_id}/"""
    # Редирект на соответствующий обработчик уроков
    return redirect(url_for('curriculum_lessons.lesson_detail', lesson_id=lesson_id))


