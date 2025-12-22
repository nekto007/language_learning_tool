# app/curriculum/routes/admin.py

import json
import logging
from datetime import UTC, datetime

from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import login_required
from sqlalchemy import or_

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
        logger.info("=== Import curriculum POST request received ===")
        logger.info(f"Request files: {list(request.files.keys())}")
        logger.info(f"Request form: {list(request.form.keys())}")

        try:
            # Check if file was uploaded
            if 'file' not in request.files:
                logger.error("No 'file' in request.files")
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

            # Проверяем формат JSON - поддерживаем два формата:
            # 1. Новый формат: {"module": {...}} - один модуль
            # 2. Старый формат: {"levels": [{...}]} - полная структура с уровнями

            if 'module' in data:
                # Новый формат - преобразуем в старый формат для совместимости
                module_data = data['module']
                logger.info(f"Detected new format with module: {module_data.get('title')}")

                # Используем уровень из JSON, если указан, иначе A0
                level_code = module_data.get('level', 'A0')
                logger.info(f"Using level from JSON: {level_code}")

                # Преобразуем в старый формат с правильным уровнем
                cleaned_data = {
                    'levels': [{
                        'code': level_code,
                        'name': level_code,
                        'modules': [module_data]
                    }]
                }
                logger.info(f"Converted to old format with level {level_code}, modules count: {len(cleaned_data['levels'][0]['modules'])}")
            else:
                # Старый формат - валидируем как обычно
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
                        # Поддержка обоих форматов: 'number' (старый) и 'id' (новый)
                        module_number = module_data.get('number') or module_data.get('id')

                        if not module_number:
                            logger.error("Module missing both 'number' and 'id' fields")
                            continue

                        # Check if module exists
                        module = Module.query.filter_by(
                            level_id=level.id,
                            number=module_number
                        ).first()

                        if not module:
                            module = Module(
                                level_id=level.id,
                                number=module_number,
                                title=sanitize_json_content(
                                    module_data.get('title', f'Module {module_number}')
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
                            # Поддержка обоих форматов: 'number' и 'order'
                            lesson_number = lesson_data.get('number') or lesson_data.get('order', 0)

                            # Skip if lesson exists
                            existing_lesson = Lessons.query.filter_by(
                                module_id=module.id,
                                number=lesson_number
                            ).first()

                            if existing_lesson:
                                continue

                            # Маппинг типов уроков из JSON в типы БД
                            type_mapping = {
                                'vocabulary': 'vocabulary',
                                'grammar': 'grammar',
                                'quiz': 'quiz',
                                'flashcards': 'card',
                                'listening': 'matching',
                                'reading': 'text',
                                'listening_immersion': 'text',
                                'test': 'final_test',
                                'final_test': 'final_test',
                                'dialogue_completion': 'quiz',  # Диалоги как quiz
                                'ordering': 'quiz',  # Упорядочивание как quiz
                                'translation': 'quiz',  # Перевод как quiz
                                'card': 'card'  # Карточки
                            }

                            # Получаем тип урока и преобразуем его
                            original_type = lesson_data.get('type', 'text')
                            mapped_type = type_mapping.get(original_type, 'quiz')

                            # Sanitize and normalize lesson content
                            content = lesson_data.get('content', {})
                            if isinstance(content, dict):
                                # Normalize content structure for different lesson types
                                if mapped_type == 'vocabulary' and 'vocabulary' in content:
                                    # Transform {"vocabulary": [...]} to {"words": [...]}
                                    # Also normalize field names in vocabulary items
                                    words = content['vocabulary']
                                    for word in words:
                                        # Map english->word/front, russian->translation/back
                                        if 'english' in word and 'word' not in word:
                                            word['word'] = word['english']
                                            word['front'] = word['english']
                                        if 'russian' in word and 'translation' not in word:
                                            word['translation'] = word['russian']
                                            word['back'] = word['russian']
                                        # Map example_translation to usage or hint
                                        if 'example_translation' in word and 'usage' not in word:
                                            word['usage'] = word['example_translation']
                                    content = {'words': words}
                                elif mapped_type == 'grammar' and 'grammar' in content:
                                    # Extract grammar data from nested structure
                                    grammar_data = content['grammar']
                                    if isinstance(grammar_data, dict):
                                        content = grammar_data
                                elif mapped_type == 'quiz' and 'questions' not in content:
                                    # For quiz types, ensure questions are at top level
                                    if 'quiz' in content:
                                        content = content['quiz']
                                    elif 'exercises' in content:
                                        content = {'questions': content['exercises']}
                                elif mapped_type == 'matching' and 'matching' in content:
                                    # Transform {"matching": [...]} to {"pairs": [...]}
                                    content = {'pairs': content['matching']}
                                elif mapped_type == 'text' and 'dialogue' in content:
                                    # Extract dialogue content
                                    dialogue_data = content['dialogue']
                                    if isinstance(dialogue_data, dict):
                                        content = dialogue_data
                                elif mapped_type == 'card' and 'flashcards' in content:
                                    # Transform {"flashcards": [...]} to {"cards": [...]}
                                    content = {'cards': content['flashcards']}
                                elif mapped_type == 'final_test' and 'test' in content:
                                    test_data = content['test']
                                    if isinstance(test_data, dict):
                                        content = test_data

                                content = sanitize_json_content(content)
                            elif isinstance(content, list):
                                content = sanitize_json_content(content)

                            # Для foreign keys используем None вместо 0
                            collection_id = lesson_data.get('collection_id')
                            book_id = lesson_data.get('book_id')

                            lesson = Lessons(
                                module_id=module.id,
                                number=lesson_number,
                                title=sanitize_json_content(
                                    lesson_data.get('title', 'Untitled Lesson')
                                ),
                                type=mapped_type,
                                description=sanitize_json_content(
                                    lesson_data.get('grammar_focus', lesson_data.get('description', ''))
                                ),
                                order=lesson_number,  # используем lesson_number и для order
                                content=content,
                                collection_id=safe_int(collection_id) if collection_id else None,
                                book_id=safe_int(book_id) if book_id else None
                            )

                            db.session.add(lesson)
                            imported_stats['lessons'] += 1

                db.session.commit()

                logger.info(f"Import completed: {imported_stats}")
                flash(
                    f'Импорт завершен успешно! '
                    f'Импортировано: {imported_stats["levels"]} уровней, '
                    f'{imported_stats["modules"]} модулей, '
                    f'{imported_stats["lessons"]} уроков',
                    'success'
                )
                return redirect(url_for('curriculum_admin.admin_lessons'))

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


@admin_bp.route('/admin/lessons')
@login_required
@admin_required
def admin_lessons():
    """List all lessons for admin"""
    # Get filter parameters
    level_id = request.args.get('level_id', type=int)
    module_id = request.args.get('module_id', type=int)
    search = request.args.get('search', '').strip()
    
    # Start with all lessons
    query = Lessons.query.join(Module).join(CEFRLevel)
    
    # Apply filters
    if level_id:
        query = query.filter(CEFRLevel.id == level_id)
    if module_id:
        query = query.filter(Module.id == module_id)
    if search:
        query = query.filter(
            or_(
                Lessons.title.ilike(f'%{search}%'),
                Lessons.description.ilike(f'%{search}%')
            )
        )
    
    # Get lessons ordered by level, module, and lesson number
    lessons = query.order_by(
        CEFRLevel.order,
        Module.number,
        Lessons.number
    ).all()
    
    # Get levels and modules for filters
    levels = CEFRLevel.query.order_by(CEFRLevel.order).all()
    modules = Module.query.order_by(Module.level_id, Module.number).all()
    
    # Filter modules by level if level is selected
    if level_id:
        modules = [m for m in modules if m.level_id == level_id]
    
    return render_template(
        'admin/curriculum/lesson_list.html',
        lessons=lessons,
        levels=levels,
        modules=modules,
        level_id=level_id,
        module_id=module_id,
        search=search
    )


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
            level.updated_at = datetime.now(UTC)

            db.session.commit()
            flash('Уровень успешно обновлен', 'success')
            return redirect(url_for('curriculum_admin.admin_levels'))

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
            module.updated_at = datetime.now(UTC)

            db.session.commit()
            flash('Модуль успешно обновлен', 'success')
            return redirect('/learn/')

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
        # Check if it's the JSON content form
        if 'content' in request.form:
            try:
                # Parse and validate content
                content_str = request.form.get('content', '{}')
                try:
                    content = json.loads(content_str)
                except json.JSONDecodeError:
                    flash('Неверный формат JSON в содержимом', 'error')
                    return redirect(request.url)

                # Basic content validation
                if not isinstance(content, (dict, list)):
                    flash('Содержимое должно быть объектом или массивом JSON', 'error')
                    return redirect(request.url)

                # Update lesson content
                lesson.content = content
                lesson.updated_at = datetime.now(UTC)

                db.session.commit()
                flash('Содержимое урока успешно обновлено', 'success')
                return redirect(url_for('curriculum_admin.view_lesson', lesson_id=lesson.id))

            except Exception as e:
                db.session.rollback()
                logger.error(f"Error updating lesson content: {str(e)}")
                flash('Ошибка при обновлении содержимого', 'error')
                return redirect(request.url)
        
        # Otherwise handle basic lesson data update
        else:
            try:
                # Get form data
                title = request.form.get('title', '').strip()
                description = request.form.get('description', '').strip()
                module_id = safe_int(request.form.get('module_id', lesson.module_id))
                number = safe_int(request.form.get('number', lesson.number))

                # Validate basic fields
                if not title:
                    flash('Название урока обязательно', 'error')
                    return redirect(request.url)

                if len(title) > 200:
                    flash('Название слишком длинное (максимум 200 символов)', 'error')
                    return redirect(request.url)

                # Update lesson
                lesson.title = sanitize_json_content(title)
                lesson.description = sanitize_json_content(description)
                lesson.module_id = module_id
                lesson.number = number
                lesson.updated_at = datetime.now(UTC)

                db.session.commit()
                flash('Урок успешно обновлен', 'success')
                return redirect(url_for('curriculum_admin.view_lesson', lesson_id=lesson.id))

            except Exception as e:
                db.session.rollback()
                logger.error(f"Error updating lesson: {str(e)}")
                flash('Ошибка при обновлении урока', 'error')
                return redirect(request.url)

    # Get data for template
    modules = Module.query.order_by(Module.level_id, Module.number).all()
    
    return render_template(
        'admin/curriculum/edit_lesson.html',
        lesson=lesson,
        modules=modules,
        content_json=json.dumps(lesson.content, ensure_ascii=False, indent=2) if lesson.content else '{}'
    )


@admin_bp.route('/admin/lesson/<int:lesson_id>/view')
@login_required
@admin_required
def view_lesson(lesson_id):
    """View lesson details with full content display"""
    lesson = Lessons.query.get_or_404(lesson_id)
    
    # Get lesson progress statistics
    all_progress = LessonProgress.query.filter_by(lesson_id=lesson_id).all()
    
    # Calculate statistics manually
    total_attempts = len(all_progress)
    completed = len([p for p in all_progress if p.status == 'completed'])
    avg_score = sum(p.score for p in all_progress if p.score) / len([p for p in all_progress if p.score]) if any(p.score for p in all_progress) else 0
    
    # Create a stats object similar to the query result
    class ProgressStats:
        def __init__(self, total, completed, avg):
            self.total_attempts = total
            self.completed = completed
            self.avg_score = avg
    
    progress_stats = ProgressStats(total_attempts, completed, avg_score)
    
    # Get recent progress entries
    recent_progress = LessonProgress.query.filter_by(lesson_id=lesson_id)\
        .order_by(LessonProgress.last_activity.desc())\
        .limit(10).all()
    
    return render_template(
        'admin/curriculum/view_lesson.html',
        lesson=lesson,
        progress_stats=progress_stats,
        recent_progress=recent_progress
    )


@admin_bp.route('/admin/lesson/<int:lesson_id>/delete', methods=['POST'])
@login_required
@admin_required
def delete_lesson(lesson_id):
    """Delete lesson with confirmation"""
    try:
        lesson = Lessons.query.get_or_404(lesson_id)
        
        # Check if lesson has any user progress
        progress_count = LessonProgress.query.filter_by(lesson_id=lesson_id).count()

        if progress_count > 0:
            flash(
                f'Невозможно удалить урок: {progress_count} пользователей имеют прогресс в этом уроке',
                'error'
            )
            # Возвращаемся туда, откуда пришли, или на список уроков по умолчанию
            return redirect(request.referrer or url_for('curriculum_admin.admin_lessons'))

        db.session.delete(lesson)
        db.session.commit()

        flash('Урок успешно удален', 'success')
        # Возвращаемся туда, откуда пришли, или на список уроков по умолчанию
        return redirect(request.referrer or url_for('curriculum_admin.admin_lessons'))

    except Exception as e:
        db.session.rollback()
        logger.error(f"Error deleting lesson: {str(e)}")
        flash('Ошибка при удалении урока', 'error')
        return redirect(url_for('curriculum_admin.admin_lessons'))
