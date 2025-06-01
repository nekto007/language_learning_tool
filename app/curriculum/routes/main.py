# app/curriculum/routes/main.py

import logging
from datetime import datetime

from flask import Blueprint, abort, flash, redirect, render_template, url_for
from flask_login import current_user, login_required
from sqlalchemy import func

from app.curriculum.models import CEFRLevel, LessonProgress, Lessons, Module
from app.curriculum.security import check_module_access, require_module_access
from app.utils.db import db

logger = logging.getLogger(__name__)

# Create blueprint for main routes - use curriculum name for compatibility
main_bp = Blueprint('curriculum', __name__)


@main_bp.route('/')
@login_required
def index():
    """Main curriculum page with improved UX and security"""
    try:
        # Get all CEFR levels
        all_levels = CEFRLevel.query.order_by(CEFRLevel.order).all()

        # If no levels exist, show a helpful message
        if not all_levels:
            flash('Учебные материалы еще не загружены. Обратитесь к администратору.', 'info')
            return render_template('curriculum/index.html', levels=[], user_progress={}, active_lessons=[],
                                   recommended_level=None)

        # Filter levels based on sequential completion
        user_progress = {}
        active_lessons = []
        recommended_level = None
        unlocked_levels = []

        if current_user.is_authenticated:
            # Determine which levels are accessible based on sequential completion
            for i, level in enumerate(all_levels):
                # First level is always accessible
                if i == 0:
                    unlocked_levels.append(level)
                else:
                    # Check if previous level is sufficiently completed (80%+)
                    prev_level = all_levels[i-1]
                    prev_progress = user_progress.get(prev_level.id, {})
                    if prev_progress.get('percentage', 0) >= 80:
                        unlocked_levels.append(level)
                    else:
                        # Show one locked level for motivation, then stop
                        unlocked_levels.append(level)
                        break

            # Get detailed progress for accessible levels
            for level in unlocked_levels:
                # Get all modules for the level
                modules = Module.query.filter_by(level_id=level.id).all()
                module_ids = [m.id for m in modules]

                if module_ids:
                    # Count total and completed lessons for the level
                    total_lessons = db.session.query(func.count(Lessons.id)).filter(
                        Lessons.module_id.in_(module_ids)
                    ).scalar() or 0

                    completed_lessons = db.session.query(func.count(LessonProgress.id)).join(
                        Lessons, Lessons.id == LessonProgress.lesson_id
                    ).filter(
                        Lessons.module_id.in_(module_ids),
                        LessonProgress.user_id == current_user.id,
                        LessonProgress.status == 'completed'
                    ).scalar() or 0

                    in_progress_lessons = db.session.query(func.count(LessonProgress.id)).join(
                        Lessons, Lessons.id == LessonProgress.lesson_id
                    ).filter(
                        Lessons.module_id.in_(module_ids),
                        LessonProgress.user_id == current_user.id,
                        LessonProgress.status == 'in_progress'
                    ).scalar() or 0

                    user_progress[level.id] = {
                        'total_lessons': total_lessons,
                        'completed_lessons': completed_lessons,
                        'in_progress_lessons': in_progress_lessons,
                        'percentage': round((completed_lessons / total_lessons * 100) if total_lessons > 0 else 0)
                    }

                    # Find active lessons
                    if in_progress_lessons > 0:
                        active_lesson_entries = db.session.query(LessonProgress).join(
                            Lessons, Lessons.id == LessonProgress.lesson_id
                        ).join(
                            Module, Module.id == Lessons.module_id
                        ).filter(
                            Lessons.module_id.in_(module_ids),
                            LessonProgress.user_id == current_user.id,
                            LessonProgress.status == 'in_progress'
                        ).order_by(LessonProgress.last_activity.desc()).limit(3).all()

                        for progress in active_lesson_entries:
                            active_lessons.append({
                                'lesson': progress.lesson,
                                'module': progress.lesson.module,
                                'level': level,
                                'last_activity': progress.last_activity
                            })

            # Determine recommended level (first level with < 80% completion)
            for level in unlocked_levels:
                progress = user_progress.get(level.id, {})
                if progress.get('percentage', 0) < 80:
                    recommended_level = level
                    break
        else:
            # For non-authenticated users, show first level as recommended
            unlocked_levels = all_levels[:1] if all_levels else []
            recommended_level = unlocked_levels[0] if unlocked_levels else None

        return render_template(
            'curriculum/index.html',
            levels=unlocked_levels,  # Only show accessible levels
            user_progress=user_progress,
            active_lessons=active_lessons,
            recommended_level=recommended_level
        )

    except Exception as e:
        logger.error(f"Error in curriculum index: {str(e)}")
        flash('Произошла ошибка при загрузке учебного курса', 'error')
        return redirect(url_for('words.dashboard'))


@main_bp.route('/levels/<string:level_code>')
@login_required
def level_modules(level_code):
    """Display modules for a specific CEFR level with sequential access logic"""
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


@main_bp.route('/modules/<int:module_id>')
@login_required
@require_module_access
def module_lessons(module_id):
    """Display lessons for selected module with proper access control"""
    module = Module.query.get_or_404(module_id)

    # Get all module lessons
    lessons = Lessons.query.filter_by(
        module_id=module.id
    ).order_by(Lessons.order, Lessons.number).all()

    if not lessons:
        flash('В этом модуле пока нет уроков', 'info')
        return redirect(url_for('curriculum.level_modules', level_code=module.level.code))

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
