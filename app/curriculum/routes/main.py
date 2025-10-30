# app/curriculum/routes/main.py

import logging
from datetime import datetime, timedelta

from flask import Blueprint, abort, flash, redirect, render_template, url_for
from flask_login import current_user, login_required
from sqlalchemy import func, distinct

from app.curriculum.models import CEFRLevel, LessonProgress, Lessons, Module
from app.curriculum.security import check_module_access, require_module_access
from app.curriculum.url_helpers import (
    level_to_slug, slug_to_level, slug_to_module_number,
    get_level_by_beautiful_url, get_module_by_beautiful_url,
    generate_breadcrumbs
)
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
    """Главная страница учебной программы - редирект на красивый URL"""
    return redirect('/learn/', code=302)


@main_bp.route('/levels/<string:level_code>')
@login_required
def level_modules(level_code):
    """Редирект со старого URL уровня на новый красивый URL"""
    return redirect(f'/learn/{level_to_slug(level_code)}/', code=302)


@main_bp.route('/modules/<int:module_id>')
@login_required
def module_lessons(module_id):
    """Редирект со старого URL модуля на новый красивый URL"""
    module = Module.query.get_or_404(module_id)
    level_slug = level_to_slug(module.level.code)
    return redirect(f'/learn/{level_slug}/module-{module.number}/', code=302)


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


@learn_bp.route('/<string:level_slug>/')
@login_required
def learn_level(level_slug):
    """Модули для уровня - красивый URL"""
    level_code = slug_to_level(level_slug)
    if not level_code:
        abort(404, "Invalid level")

    # Validate level code
    if not level_code or len(level_code) > 2:
        abort(400, "Invalid level code")

    level = CEFRLevel.query.filter_by(code=level_code).first_or_404()

    # Get all modules for this level, ordered by number
    modules = Module.query.filter_by(level_id=level.id).order_by(Module.number).all()

    # Get user progress for modules and determine sequential access
    user_module_progress = {}
    unlocked_up_to = 0  # Index of the last unlocked module
    next_lesson_info = None  # Info about the next lesson to continue

    if current_user.is_authenticated:
        for i, module in enumerate(modules):
            # Count total and completed lessons
            total_lessons = Lessons.query.filter_by(module_id=module.id).count()

            completed_lessons = db.session.query(func.count(LessonProgress.id)).join(
                Lessons, Lessons.id == LessonProgress.lesson_id
            ).filter(
                Lessons.module_id == module.id,
                LessonProgress.user_id == current_user.id,
                LessonProgress.status == 'completed'
            ).scalar() or 0

            percentage = round((completed_lessons / total_lessons * 100) if total_lessons > 0 else 0)

            # Sequential access logic:
            # 1. First module is always accessible
            # 2. Next module is accessible only if previous is completed (80%+)
            is_accessible = False
            if i == 0:
                # First module is always accessible
                is_accessible = True
                unlocked_up_to = 0
            else:
                # Check if previous module is sufficiently completed
                prev_module = modules[i-1]
                prev_progress = user_module_progress.get(prev_module.id, {})
                if prev_progress.get('percentage', 0) >= 80:
                    is_accessible = True
                    unlocked_up_to = i

            # Find next lesson for this module if it's in progress
            next_lesson_for_module = None
            if is_accessible and percentage < 100:
                # Get the first incomplete lesson in this module
                all_lessons = Lessons.query.filter_by(module_id=module.id).order_by(Lessons.number).all()
                for lesson in all_lessons:
                    lesson_progress = LessonProgress.query.filter_by(
                        user_id=current_user.id,
                        lesson_id=lesson.id
                    ).first()

                    if not lesson_progress or lesson_progress.status != 'completed':
                        next_lesson_for_module = lesson
                        # Set this as the main next lesson if we don't have one yet
                        if not next_lesson_info:
                            next_lesson_info = {
                                'lesson': lesson,
                                'module': module,
                                'progress': lesson_progress
                            }
                        break

            # Calculate estimated time (15 min per lesson)
            remaining = total_lessons - completed_lessons
            estimated_hours = round((remaining * 15) / 60, 1)

            user_module_progress[module.id] = {
                'total_lessons': total_lessons,
                'completed_lessons': completed_lessons,
                'percentage': percentage,
                'is_accessible': is_accessible,
                'is_current': is_accessible and percentage < 100,
                'is_completed': percentage >= 80,
                'is_locked': not is_accessible,
                'estimated_hours': estimated_hours,
                'next_lesson': next_lesson_for_module
            }

    # Filter modules based on sequential access:
    # Show only unlocked modules + 1 next locked module for motivation
    visible_modules = []
    for i, module in enumerate(modules):
        progress = user_module_progress.get(module.id, {})
        
        # Show module if:
        # 1. It's accessible (unlocked)
        # 2. It's the next locked module (for motivation)
        # 3. It's completed
        if (progress.get('is_accessible') or 
            i == unlocked_up_to + 1 or 
            progress.get('is_completed')):
            visible_modules.append(module)
        
        # Don't show modules that are too far ahead
        if i > unlocked_up_to + 1 and not progress.get('is_completed'):
            break

    # Calculate overall level statistics
    total_lessons = sum(p.get('total_lessons', 0) for p in user_module_progress.values())
    completed_lessons = sum(p.get('completed_lessons', 0) for p in user_module_progress.values())
    level_progress = round((completed_lessons / total_lessons * 100) if total_lessons > 0 else 0)
    estimated_hours_total = round((total_lessons - completed_lessons) * 15 / 60, 1)

    level_stats = {
        'total_lessons': total_lessons,
        'completed_lessons': completed_lessons,
        'progress_percent': level_progress,
        'estimated_hours': estimated_hours_total,
        'total_modules': len(modules),
        'completed_modules': sum(1 for p in user_module_progress.values() if p.get('is_completed'))
    }

    return render_template(
        'curriculum/level_modules.html',
        level=level,
        modules=visible_modules,  # Only show relevant modules
        user_module_progress=user_module_progress,
        next_lesson_info=next_lesson_info,
        level_stats=level_stats
    )


@learn_bp.route('/<string:level_slug>/<string:module_slug>/')
@login_required
def learn_module(level_slug, module_slug):
    """Уроки для модуля - красивый URL"""
    level_code = slug_to_level(level_slug)
    module_number = slug_to_module_number(module_slug)
    
    if not level_code or not module_number:
        abort(404, "Invalid level or module")
    
    # Находим модуль по красивому URL
    module = get_module_by_beautiful_url(level_code, module_number)
    if not module:
        abort(404, "Module not found")
    
    # Get all module lessons
    lessons = Lessons.query.filter_by(
        module_id=module.id
    ).order_by(Lessons.order, Lessons.number).all()

    if not lessons:
        flash('В этом модуле пока нет уроков', 'info')
        return redirect(f'/learn/{level_slug}/')

    # Get user progress for lessons
    user_lesson_progress = {}

    if current_user.is_authenticated:
        # Create progress for first lesson if not exists
        first_lesson = lessons[0]
        first_lesson_progress = LessonProgress.query.filter_by(
            user_id=current_user.id,
            lesson_id=first_lesson.id
        ).first()

        if not first_lesson_progress:
            try:
                first_lesson_progress = LessonProgress(
                    user_id=current_user.id,
                    lesson_id=first_lesson.id,
                    status='in_progress',
                    started_at=datetime.utcnow(),
                    last_activity=datetime.utcnow()
                )
                db.session.add(first_lesson_progress)
                db.session.commit()
            except Exception as e:
                logger.error(f"Error creating lesson progress: {str(e)}")
                db.session.rollback()

        # Get all progress entries
        progress_entries = LessonProgress.query.filter(
            LessonProgress.user_id == current_user.id,
            LessonProgress.lesson_id.in_([lesson.id for lesson in lessons])
        ).all()

        for progress in progress_entries:
            user_lesson_progress[progress.lesson_id] = {
                'status': progress.status,
                'score': progress.score,
                'completed_at': progress.completed_at
            }

    return render_template(
        'curriculum/module_lessons.html',
        module=module,
        lessons=lessons,
        user_lesson_progress=user_lesson_progress
    )


# =============================================================================
# РЕДИРЕКТЫ ДЛЯ ОБРАТНОЙ СОВМЕСТИМОСТИ
# =============================================================================

@main_bp.route('/redirect-to-beautiful/<path:old_path>')
def redirect_to_beautiful(old_path):
    """Редирект со старых URL на новые красивые"""
    # Простое преобразование основных путей
    if old_path.startswith('levels/'):
        level_code = old_path.replace('levels/', '')
        return redirect(f'/learn/{level_to_slug(level_code)}/', code=301)
    
    return redirect('/learn/', code=301)


# Обновим существующие функции для редиректа
def index():
    """Главная страница учебной программы - с редиректом на красивый URL"""
    return redirect('/learn/', code=302)  # Temporary redirect


def level_modules(level_code):
    """Модули для уровня - с редиректом на красивый URL"""
    return redirect(f'/learn/{level_to_slug(level_code)}/', code=302)


def module_lessons(module_id):
    """Уроки для модуля - с редиректом на красивый URL"""
    module = Module.query.get_or_404(module_id)
    level_slug = level_to_slug(module.level.code)
    return redirect(f'/learn/{level_slug}/module-{module.number}/', code=302)
