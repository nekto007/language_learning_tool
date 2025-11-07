# app/curriculum/routes/main.py

import logging
from datetime import datetime, timedelta

from flask import Blueprint, abort, flash, redirect, render_template, url_for
from flask_login import current_user, login_required
from sqlalchemy import func, distinct

from app.curriculum.models import CEFRLevel, LessonProgress, Lessons, Module
from app.curriculum.security import check_module_access, require_module_access
from app.utils.db import db

logger = logging.getLogger(__name__)


def calculate_gamification_stats(user_id):
    """Calculate gamification statistics for user"""
    # Calculate learning streak (consecutive days)
    streak = 0
    current_date = datetime.utcnow().date()

    # Get all distinct activity dates, ordered by date descending
    activity_dates = db.session.query(
        func.date(LessonProgress.last_activity).label('activity_date')
    ).filter(
        LessonProgress.user_id == user_id
    ).distinct().order_by(
        func.date(LessonProgress.last_activity).desc()
    ).all()

    # Calculate consecutive days
    if activity_dates:
        activity_dates_list = [d[0] for d in activity_dates]

        # Check if user was active today or yesterday
        if activity_dates_list and (
            activity_dates_list[0] == current_date or
            activity_dates_list[0] == current_date - timedelta(days=1)
        ):
            streak = 1
            check_date = activity_dates_list[0] - timedelta(days=1)

            for date in activity_dates_list[1:]:
                if date == check_date:
                    streak += 1
                    check_date -= timedelta(days=1)
                else:
                    break

    # Calculate total points (based on completed lessons and scores)
    points_data = db.session.query(
        func.count(LessonProgress.id).label('completed_count'),
        func.coalesce(func.avg(LessonProgress.score), 0).label('avg_score')
    ).filter(
        LessonProgress.user_id == user_id,
        LessonProgress.status == 'completed'
    ).first()

    completed_lessons = points_data[0] or 0
    avg_score = points_data[1] or 0

    # Points formula: 10 points per lesson + bonus for high scores
    total_points = completed_lessons * 10
    if avg_score >= 90:
        total_points += completed_lessons * 5  # +5 bonus for excellent scores
    elif avg_score >= 80:
        total_points += completed_lessons * 3  # +3 bonus for good scores

    # Calculate user level based on points
    user_level = 1 + (total_points // 100)  # Level up every 100 points

    # Calculate today's progress
    today_completed = db.session.query(func.count(LessonProgress.id)).filter(
        LessonProgress.user_id == user_id,
        LessonProgress.status == 'completed',
        func.date(LessonProgress.completed_at) == current_date
    ).scalar() or 0

    # Daily goal: 3 lessons per day
    daily_goal = 3
    daily_progress = min(today_completed, daily_goal)

    return {
        'streak': streak,
        'total_points': total_points,
        'user_level': user_level,
        'daily_progress': daily_progress,
        'daily_goal': daily_goal,
        'completed_lessons': completed_lessons,
        'avg_score': round(avg_score, 1)
    }

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


