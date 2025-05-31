# app/curriculum/routes/admin.py

import json
import logging
from datetime import datetime

from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import login_required

from app.curriculum.models import CEFRLevel, LessonProgress, Lessons, Module
from app.curriculum.security import (safe_int, sanitize_json_content, validate_file_upload)
from app.curriculum.validators import ImportDataSchema, validate_request_data
from app.utils.db import db
from app.utils.decorators import admin_required
from app.words.models import Collection

logger = logging.getLogger(__name__)

# Create blueprint for admin routes
admin_bp = Blueprint('curriculum_admin', __name__)


@admin_bp.route('/admin/import', methods=['GET', 'POST'])
@login_required
@admin_required
def import_curriculum():
    """Import curriculum from JSON file with validation and sanitization"""
    if request.method == 'POST':
        try:
            # Check if file was uploaded
            if 'file' not in request.files:
                flash('Файл не выбран', 'error')
                return redirect(request.url)

            file = request.files['file']
            if file.filename == '':
                flash('Файл не выбран', 'error')
                return redirect(request.url)

            # Validate file
            is_valid, error_msg = validate_file_upload(
                file,
                max_size_mb=10,
                allowed_extensions={'json'}
            )

            if not is_valid:
                flash(error_msg, 'error')
                return redirect(request.url)

            # Read and parse JSON
            try:
                data = json.load(file)
            except json.JSONDecodeError as e:
                flash(f'Ошибка при чтении JSON: {str(e)}', 'error')
                return redirect(request.url)

            # Validate import data structure
            is_valid, error_msg, cleaned_data = validate_request_data(
                ImportDataSchema, data
            )

            if not is_valid:
                flash(f'Ошибка валидации данных: {error_msg}', 'error')
                return redirect(request.url)

            # Process import in transaction
            imported_stats = {
                'levels': 0,
                'modules': 0,
                'lessons': 0
            }

            try:
                # Import levels
                for level_data in cleaned_data['levels']:
                    # Check if level exists
                    level = CEFRLevel.query.filter_by(
                        code=level_data['code']
                    ).first()

                    if not level:
                        level = CEFRLevel(
                            code=level_data['code'],
                            name=level_data.get('name', level_data['code']),
                            description=sanitize_json_content(
                                level_data.get('description', '')
                            ),
                            order=level_data.get('order', 0)
                        )
                        db.session.add(level)
                        db.session.flush()
                        imported_stats['levels'] += 1

                    # Import modules
                    for module_data in level_data.get('modules', []):
                        # Check if module exists
                        module = Module.query.filter_by(
                            level_id=level.id,
                            number=module_data['number']
                        ).first()

                        if not module:
                            module = Module(
                                level_id=level.id,
                                number=module_data['number'],
                                title=sanitize_json_content(
                                    module_data.get('title', f'Module {module_data["number"]}')
                                ),
                                description=sanitize_json_content(
                                    module_data.get('description', '')
                                )
                            )
                            db.session.add(module)
                            db.session.flush()
                            imported_stats['modules'] += 1

                        # Import lessons
                        for lesson_data in module_data.get('lessons', []):
                            # Skip if lesson exists
                            existing_lesson = Lessons.query.filter_by(
                                module_id=module.id,
                                number=lesson_data.get('number', 0)
                            ).first()

                            if existing_lesson:
                                continue

                            # Sanitize lesson content
                            content = lesson_data.get('content', {})
                            if isinstance(content, (dict, list)):
                                content = sanitize_json_content(content)

                            lesson = Lessons(
                                module_id=module.id,
                                number=lesson_data.get('number', 0),
                                title=sanitize_json_content(
                                    lesson_data.get('title', 'Untitled Lesson')
                                ),
                                type=lesson_data.get('type', 'text'),
                                description=sanitize_json_content(
                                    lesson_data.get('description', '')
                                ),
                                order=lesson_data.get('order', 0),
                                content=content,
                                collection_id=safe_int(lesson_data.get('collection_id')),
                                book_id=safe_int(lesson_data.get('book_id'))
                            )

                            db.session.add(lesson)
                            imported_stats['lessons'] += 1

                db.session.commit()

                flash(
                    f'Импорт завершен успешно! '
                    f'Импортировано: {imported_stats["levels"]} уровней, '
                    f'{imported_stats["modules"]} модулей, '
                    f'{imported_stats["lessons"]} уроков',
                    'success'
                )
                return redirect(url_for('curriculum.index'))

            except Exception as e:
                db.session.rollback()
                logger.error(f"Error importing curriculum: {str(e)}")
                flash(f'Ошибка при импорте: {str(e)}', 'error')
                return redirect(request.url)

        except Exception as e:
            logger.error(f"Error in import_curriculum: {str(e)}")
            flash('Произошла непредвиденная ошибка', 'error')
            return redirect(request.url)

    return render_template('admin/curriculum/import.html')


@admin_bp.route('/admin/stats')
@login_required
@admin_required
def admin_stats():
    """Display curriculum statistics for admin"""
    try:
        # Get curriculum statistics
        stats = {
            'total_levels': CEFRLevel.query.count(),
            'total_modules': Module.query.count(),
            'total_lessons': Lessons.query.count(),
            'lesson_types': db.session.query(
                Lessons.type, db.func.count(Lessons.id)
            ).group_by(Lessons.type).all(),
            'total_users_enrolled': db.session.query(
                db.func.count(db.func.distinct(LessonProgress.user_id))
            ).scalar() or 0,
            'total_lessons_completed': LessonProgress.query.filter_by(
                status='completed'
            ).count(),
            'average_score': db.session.query(
                db.func.avg(LessonProgress.score)
            ).filter(
                LessonProgress.status == 'completed',
                LessonProgress.score > 0
            ).scalar() or 0
        }

        # Get recent activity
        recent_progress = LessonProgress.query.order_by(
            LessonProgress.last_activity.desc()
        ).limit(20).all()

        return render_template(
            'admin/curriculum/stats.html',
            stats=stats,
            recent_progress=recent_progress
        )

    except Exception as e:
        logger.error(f"Error getting admin stats: {str(e)}")
        flash('Ошибка при загрузке статистики', 'error')
        return redirect(url_for('curriculum.index'))


@admin_bp.route('/admin/levels')
@login_required
@admin_required
def admin_levels():
    """Manage CEFR levels"""
    levels = CEFRLevel.query.order_by(CEFRLevel.order).all()
    return render_template('admin/curriculum/levels.html', levels=levels)


@admin_bp.route('/admin/level/<int:level_id>/edit', methods=['GET', 'POST'])
@login_required
@admin_required
def edit_level(level_id):
    """Edit CEFR level with validation"""
    level = CEFRLevel.query.get_or_404(level_id)

    if request.method == 'POST':
        try:
            # Validate input
            name = request.form.get('name', '').strip()
            description = request.form.get('description', '').strip()
            order = safe_int(request.form.get('order', 0))

            if not name:
                flash('Название уровня обязательно', 'error')
                return redirect(request.url)

            if len(name) > 100:
                flash('Название слишком длинное (максимум 100 символов)', 'error')
                return redirect(request.url)

            # Update level
            level.name = sanitize_json_content(name)
            level.description = sanitize_json_content(description)
            level.order = order
            level.updated_at = datetime.utcnow()

            db.session.commit()
            flash('Уровень успешно обновлен', 'success')
            return redirect(url_for('curriculum.admin_levels'))

        except Exception as e:
            db.session.rollback()
            logger.error(f"Error updating level: {str(e)}")
            flash('Ошибка при обновлении уровня', 'error')
            return redirect(request.url)

    return render_template('admin/curriculum/edit_level.html', level=level)


@admin_bp.route('/admin/module/<int:module_id>/edit', methods=['GET', 'POST'])
@login_required
@admin_required
def edit_module(module_id):
    """Edit module with validation"""
    module = Module.query.get_or_404(module_id)

    if request.method == 'POST':
        try:
            # Validate input
            title = request.form.get('title', '').strip()
            description = request.form.get('description', '').strip()

            if not title:
                flash('Название модуля обязательно', 'error')
                return redirect(request.url)

            if len(title) > 200:
                flash('Название слишком длинное (максимум 200 символов)', 'error')
                return redirect(request.url)

            # Update module
            module.title = sanitize_json_content(title)
            module.description = sanitize_json_content(description)
            module.updated_at = datetime.utcnow()

            db.session.commit()
            flash('Модуль успешно обновлен', 'success')
            return redirect(url_for('curriculum.level_modules', level_code=module.level.code))

        except Exception as e:
            db.session.rollback()
            logger.error(f"Error updating module: {str(e)}")
            flash('Ошибка при обновлении модуля', 'error')
            return redirect(request.url)

    return render_template('admin/curriculum/edit_module.html', module=module)


@admin_bp.route('/admin/lesson/<int:lesson_id>/edit', methods=['GET', 'POST'])
@login_required
@admin_required
def edit_lesson(lesson_id):
    """Edit lesson with content validation"""
    lesson = Lessons.query.get_or_404(lesson_id)

    if request.method == 'POST':
        try:
            # Get form data
            title = request.form.get('title', '').strip()
            description = request.form.get('description', '').strip()
            lesson_type = request.form.get('type', lesson.type)
            order = safe_int(request.form.get('order', lesson.order))

            # Validate basic fields
            if not title:
                flash('Название урока обязательно', 'error')
                return redirect(request.url)

            if len(title) > 200:
                flash('Название слишком длинное (максимум 200 символов)', 'error')
                return redirect(request.url)

            # Parse and validate content
            content_str = request.form.get('content', '{}')
            try:
                content = json.loads(content_str)
            except json.JSONDecodeError:
                flash('Неверный формат JSON в содержимом', 'error')
                return redirect(request.url)

            # Validate content based on lesson type
            if lesson_type != lesson.type:
                flash('Изменение типа урока не разрешено', 'error')
                return redirect(request.url)

            is_valid, error_msg, cleaned_content = LessonContentValidator.validate(
                lesson_type, content
            )

            if not is_valid:
                flash(f'Ошибка в содержимом урока: {error_msg}', 'error')
                return redirect(request.url)

            # Update lesson
            lesson.title = sanitize_json_content(title)
            lesson.description = sanitize_json_content(description)
            lesson.order = order
            lesson.content = cleaned_content
            lesson.updated_at = datetime.utcnow()

            # Update related fields if needed
            if lesson_type == 'vocabulary':
                collection_id = safe_int(request.form.get('collection_id'))
                if collection_id:
                    # Verify collection exists
                    if Collection.query.get(collection_id):
                        lesson.collection_id = collection_id

            db.session.commit()
            flash('Урок успешно обновлен', 'success')
            return redirect(url_for('curriculum.module_lessons', module_id=lesson.module_id))

        except Exception as e:
            db.session.rollback()
            logger.error(f"Error updating lesson: {str(e)}")
            flash('Ошибка при обновлении урока', 'error')
            return redirect(request.url)

    # Get collections for vocabulary lessons
    collections = []
    if lesson.type == 'vocabulary':
        collections = Collection.query.order_by(Collection.name).all()

    return render_template(
        'admin/curriculum/edit_lesson.html',
        lesson=lesson,
        collections=collections,
        content_json=json.dumps(lesson.content, ensure_ascii=False, indent=2)
    )


@admin_bp.route('/admin/lesson/<int:lesson_id>/delete', methods=['POST'])
@login_required
@admin_required
def delete_lesson(lesson_id):
    """Delete lesson with confirmation"""
    try:
        lesson = Lessons.query.get_or_404(lesson_id)
        module_id = lesson.module_id

        # Check if lesson has any user progress
        progress_count = LessonProgress.query.filter_by(lesson_id=lesson_id).count()

        if progress_count > 0:
            flash(
                f'Невозможно удалить урок: {progress_count} пользователей имеют прогресс в этом уроке',
                'error'
            )
            return redirect(url_for('curriculum.module_lessons', module_id=module_id))

        db.session.delete(lesson)
        db.session.commit()

        flash('Урок успешно удален', 'success')
        return redirect(url_for('curriculum.module_lessons', module_id=module_id))

    except Exception as e:
        db.session.rollback()
        logger.error(f"Error deleting lesson: {str(e)}")
        flash('Ошибка при удалении урока', 'error')
        return redirect(url_for('curriculum.index'))
