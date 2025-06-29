# app/curriculum/routes/main.py

import logging
from datetime import datetime

from flask import Blueprint, abort, flash, redirect, render_template, url_for
from flask_login import current_user, login_required
from sqlalchemy import func

from app.curriculum.models import CEFRLevel, LessonProgress, Lessons, Module
from app.curriculum.security import check_module_access, require_module_access
from app.curriculum.url_helpers import (
    level_to_slug, slug_to_level, slug_to_module_number, 
    get_level_by_beautiful_url, get_module_by_beautiful_url,
    generate_breadcrumbs
)
from app.utils.db import db

logger = logging.getLogger(__name__)

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
    """Главная страница обучения - красивый URL"""
    try:
        # Получаем все уровни CEFR
        levels = CEFRLevel.query.order_by(CEFRLevel.order).all()
        
        if not levels:
            flash('Учебные материалы еще не загружены. Обратитесь к администратору.', 'info')
            return render_template('curriculum/index.html', levels_data=[], recent_activity=[], total_stats={})
        
        # Подготавливаем данные для каждого уровня
        levels_data = []
        total_stats = {'total_lessons': 0, 'completed_lessons': 0}
        
        for level in levels:
            # Получаем модули для уровня
            modules = Module.query.filter_by(level_id=level.id).order_by(Module.number).all()
            
            # Считаем уроки в уровне
            level_lessons = 0
            level_completed = 0
            
            modules_data = []
            for module in modules:
                lessons = Lessons.query.filter_by(module_id=module.id).order_by(Lessons.number).all()
                module_total = len(lessons)
                
                # Считаем завершенные уроки в модуле для текущего пользователя
                module_completed = 0
                if current_user.is_authenticated and lessons:
                    lesson_ids = [lesson.id for lesson in lessons]
                    completed_count = db.session.query(func.count(LessonProgress.id)).filter(
                        LessonProgress.user_id == current_user.id,
                        LessonProgress.lesson_id.in_(lesson_ids),
                        LessonProgress.status == 'completed'
                    ).scalar() or 0
                    module_completed = completed_count
                
                modules_data.append({
                    'module': module,
                    'total_lessons': module_total,
                    'completed_lessons': module_completed,
                    'progress_percent': round((module_completed / module_total * 100) if module_total > 0 else 0),
                    'is_available': True  # Все модули доступны для простоты
                })
                
                level_lessons += module_total
                level_completed += module_completed
            
            # Прогресс по уровню
            level_progress = round((level_completed / level_lessons * 100) if level_lessons > 0 else 0)
            
            level_data = {
                'level': level,
                'modules': modules_data,
                'total_lessons': level_lessons,
                'completed_lessons': level_completed,
                'progress_percent': level_progress,
                'is_available': True  # Все уровни доступны
            }
            
            levels_data.append(level_data)
            total_stats['total_lessons'] += level_lessons
            total_stats['completed_lessons'] += level_completed
        
        # Последние активности пользователя
        recent_activity = []
        if current_user.is_authenticated:
            recent_progress = db.session.query(LessonProgress)\
                .join(Lessons).join(Module).join(CEFRLevel)\
                .filter(LessonProgress.user_id == current_user.id)\
                .order_by(LessonProgress.last_activity.desc())\
                .limit(5).all()
            
            for progress in recent_progress:
                recent_activity.append({
                    'lesson': progress.lesson,
                    'module': progress.lesson.module,
                    'level': progress.lesson.module.level,
                    'status': progress.status,
                    'score': progress.score,
                    'last_activity': progress.last_activity
                })
        
        # Общая статистика
        total_stats['progress_percent'] = round((total_stats['completed_lessons'] / total_stats['total_lessons'] * 100) 
                                              if total_stats['total_lessons'] > 0 else 0)
        
        return render_template('curriculum/index.html',
                             levels_data=levels_data,
                             recent_activity=recent_activity,
                             total_stats=total_stats)
                             
    except Exception as e:
        logger.error(f"Ошибка загрузки curriculum: {str(e)}")
        flash('Произошла ошибка при загрузке учебной программы.', 'error')
        return render_template('curriculum/index.html', levels_data=[], recent_activity=[], total_stats={})


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

            user_module_progress[module.id] = {
                'total_lessons': total_lessons,
                'completed_lessons': completed_lessons,
                'percentage': percentage,
                'is_accessible': is_accessible,
                'is_current': is_accessible and percentage < 100,
                'is_completed': percentage >= 80,
                'is_locked': not is_accessible
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

    return render_template(
        'curriculum/level_modules.html',
        level=level,
        modules=visible_modules,  # Only show relevant modules
        user_module_progress=user_module_progress
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
