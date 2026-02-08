# app/curriculum/routes/main.py

import logging
from datetime import UTC, datetime

from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from app.curriculum.models import CEFRLevel, LessonProgress, Lessons, Module
from app.curriculum.security import check_module_access, require_lesson_access, require_module_access
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






@learn_bp.route('/<string:level_code>/')
@login_required
def learn_by_level(level_code):
    """Страница уровня: /learn/a1/, /learn/a2/ и т.д."""
    from app.curriculum.services.curriculum_cache_service import CurriculumCacheService

    # Валидация и нормализация кода уровня
    level_code_upper = level_code.upper()
    valid_levels = ['A0', 'A1', 'A2', 'B1', 'B2', 'C1', 'C2']
    if level_code_upper not in valid_levels:
        flash('Уровень не найден', 'error')
        return redirect(url_for('learn.learn_index'))

    # Получаем уровень из БД
    level = CEFRLevel.query.filter_by(code=level_code_upper).first()
    if not level:
        flash('Уровень не найден', 'error')
        return redirect(url_for('learn.learn_index'))

    try:
        # Получаем все данные через существующий сервис и фильтруем
        levels_data = CurriculumCacheService.get_levels_with_progress(current_user.id)
        level_data = next((ld for ld in levels_data if ld['level'].code == level_code_upper), None)

        if not level_data:
            flash('Данные уровня не найдены', 'error')
            return redirect(url_for('learn.learn_index'))

        # Преобразуем данные в формат для шаблона level_modules.html
        modules = [m['module'] for m in level_data['modules']]
        user_module_progress = {
            m['module'].id: {
                'total_lessons': m['total_lessons'],
                'completed_lessons': m['completed_lessons'],
                'progress_percent': m['progress_percent'],
                'percentage': m['progress_percent'],  # alias для шаблона
                'is_accessible': m['is_available'],
                'is_completed': m['progress_percent'] == 100,
                'is_locked': not m['is_available'],
                'is_current': m['is_available'] and m['progress_percent'] > 0 and m['progress_percent'] < 100
            }
            for m in level_data['modules']
        }

        level_stats = {
            'total_lessons': level_data['total_lessons'],
            'completed_lessons': level_data['completed_lessons'],
            'progress_percent': level_data['progress_percent'],
            'total_modules': len(modules),
            'completed_modules': sum(1 for m in level_data['modules'] if m['progress_percent'] == 100),
            'estimated_hours': level_data.get('estimated_time', 0) // 60
        }

        # Находим следующий урок
        next_lesson_info = None
        if level_data.get('next_lesson'):
            next_lesson_info = {'lesson': level_data['next_lesson']}

        return render_template('curriculum/level_modules.html',
                             level=level,
                             modules=modules,
                             user_module_progress=user_module_progress,
                             level_stats=level_stats,
                             next_lesson_info=next_lesson_info)

    except Exception as e:
        logger.error(f"Ошибка загрузки уровня {level_code}: {str(e)}")
        flash('Произошла ошибка при загрузке уровня.', 'error')
        return redirect(url_for('learn.learn_index'))


@learn_bp.route('/<string:level_code>/module-<int:module_number>/')
@login_required
def learn_by_module(level_code, module_number):
    """Страница модуля: /learn/a1/module-1/ - показывает список уроков модуля"""
    # Валидация уровня
    level_code_upper = level_code.upper()
    valid_levels = ['A0', 'A1', 'A2', 'B1', 'B2', 'C1', 'C2']
    if level_code_upper not in valid_levels:
        flash('Уровень не найден', 'error')
        return redirect(url_for('learn.learn_index'))

    # Находим модуль
    module = Module.query.join(CEFRLevel).filter(
        CEFRLevel.code == level_code_upper,
        Module.number == module_number
    ).first()

    if not module:
        flash('Модуль не найден', 'error')
        return redirect(url_for('learn.learn_by_level', level_code=level_code))

    # Сортируем уроки по номеру
    sorted_lessons = sorted(module.lessons, key=lambda l: l.number)

    if not sorted_lessons:
        flash('В модуле нет уроков', 'info')
        return redirect(url_for('learn.learn_by_level', level_code=level_code))

    # Получаем прогресс пользователя по урокам этого модуля
    lesson_ids = [l.id for l in sorted_lessons]
    user_progress = LessonProgress.query.filter(
        LessonProgress.user_id == current_user.id,
        LessonProgress.lesson_id.in_(lesson_ids)
    ).all()

    # Создаём словарь прогресса
    user_lesson_progress = {p.lesson_id: p for p in user_progress}

    return render_template(
        'curriculum/module_lessons.html',
        module=module,
        lessons=sorted_lessons,
        user_lesson_progress=user_lesson_progress
    )


@learn_bp.route('/<int:lesson_id>/', methods=['GET', 'POST'])
@login_required
@require_lesson_access
def lesson_by_id(lesson_id):
    """Прямой рендер урока: /learn/{lesson_id}/"""
    from app.curriculum.routes.lessons import (
        render_vocabulary_lesson, render_grammar_lesson, render_quiz_lesson,
        render_matching_lesson, render_text_lesson, render_card_lesson,
        render_final_test_lesson
    )

    lesson = Lessons.query.get_or_404(lesson_id)

    # Get or create user progress
    progress = LessonProgress.query.filter_by(
        user_id=current_user.id,
        lesson_id=lesson.id
    ).first()

    if not progress:
        try:
            progress = LessonProgress(
                user_id=current_user.id,
                lesson_id=lesson.id,
                status='in_progress',
                started_at=datetime.now(UTC),
                last_activity=datetime.now(UTC)
            )
            db.session.add(progress)
            db.session.commit()
        except Exception as e:
            logger.error(f"Error creating lesson progress: {str(e)}")
            db.session.rollback()
            flash('Ошибка при создании прогресса урока', 'error')
            return redirect('/learn/')
    else:
        # Update last activity
        progress.last_activity = datetime.now(UTC)
        db.session.commit()

    # Маппинг типов уроков на render-функции
    render_map = {
        'vocabulary': render_vocabulary_lesson,
        'flashcards': render_vocabulary_lesson,
        'grammar': render_grammar_lesson,
        'matching': render_matching_lesson,
        'text': render_text_lesson,
        'reading': render_text_lesson,
        'listening_immersion': render_text_lesson,
        'card': render_card_lesson,
        'final_test': render_final_test_lesson,
        # Quiz-based lessons
        'quiz': render_quiz_lesson,
        'ordering_quiz': render_quiz_lesson,
        'translation_quiz': render_quiz_lesson,
        'listening_quiz': render_quiz_lesson,
        'dialogue_completion_quiz': render_quiz_lesson,
        'listening_immersion_quiz': render_text_lesson,
    }

    render_func = render_map.get(lesson.type)
    if render_func:
        return render_func(lesson)
    else:
        flash(f'Неизвестный тип урока: {lesson.type}', 'error')
        return redirect('/learn/')


