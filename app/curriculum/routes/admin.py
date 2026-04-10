# app/curriculum/routes/admin.py

import json
import logging
from datetime import UTC, datetime

from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import login_required
from sqlalchemy import or_

from app.admin.services.curriculum_import_service import CurriculumImportService
from app.curriculum.models import CEFRLevel, LessonProgress, Lessons, Module
from app.curriculum.security import (safe_int, sanitize_json_content, validate_file_upload)
from app.curriculum.validators import ImportDataSchema, validate_request_data
from app.utils.db import db
from app.admin.utils.decorators import admin_required
from app.words.models import Collection

logger = logging.getLogger(__name__)

# Create blueprint for admin routes
admin_bp = Blueprint('curriculum_admin', __name__)


@admin_bp.route('/admin/import', methods=['GET', 'POST'])
@login_required
@admin_required
def import_curriculum():
    """Import curriculum from JSON file(s) using CurriculumImportService"""
    if request.method == 'POST':
        logger.info("=== Import curriculum POST request received ===")

        # Collect datasets: list of (data_dict, source_name)
        datasets: list[tuple[dict, str]] = []
        errors: list[str] = []

        # 1. Try files first (supports multiple)
        files = request.files.getlist('file')
        for file in files:
            if not file or not file.filename:
                continue
            is_valid, error_msg = validate_file_upload(
                file, max_size_mb=10, allowed_extensions={'json'}
            )
            if not is_valid:
                errors.append(f'{file.filename}: {error_msg}')
                continue
            try:
                data = json.load(file)
                datasets.append((data, file.filename))
            except json.JSONDecodeError as e:
                errors.append(f'{file.filename}: ошибка JSON — {e}')

        # 2. If no files, try pasted JSON text
        if not datasets:
            json_text = request.form.get('json_text', '').strip()
            if json_text:
                try:
                    data = json.loads(json_text)
                    datasets.append((data, 'JSON текст'))
                except json.JSONDecodeError as e:
                    errors.append(f'JSON текст: ошибка — {e}')

        # Nothing to import?
        if not datasets and not errors:
            flash('Файл не выбран', 'error')
            return redirect(request.url)

        # 3. Import each dataset independently
        results: list[tuple[str, dict | None, str | None]] = []
        for data, source_name in datasets:
            try:
                result = CurriculumImportService.import_curriculum_data(data)
                results.append((source_name, result, None))
            except Exception as e:
                # Полный rollback чтобы очистить broken state сессии
                db.session.rollback()
                logger.error(f"Import error in {source_name}: {e}")
                results.append((source_name, None, str(e)))

        # Убедимся что сессия чистая перед redirect
        try:
            db.session.rollback()
        except Exception:
            pass

        # 4. Flash summary
        success = [r for r in results if r[2] is None]
        import_errors = [r for r in results if r[2] is not None]

        if success:
            names = ', '.join(r[0] for r in success)
            flash(
                f'Импортировано {len(success)} из {len(results)} файлов: {names}',
                'success'
            )

        for name, _, err in import_errors:
            flash(f'Ошибка в {name}: {err}', 'danger')

        for err_msg in errors:
            flash(err_msg, 'danger')

        return redirect(url_for('curriculum_admin.admin_lessons'))

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
            from app.auth.routes import get_safe_redirect_url
            return redirect(get_safe_redirect_url(request.referrer, fallback='curriculum_admin.admin_lessons'))

        db.session.delete(lesson)
        db.session.commit()

        flash('Урок успешно удален', 'success')
        # Возвращаемся туда, откуда пришли, или на список уроков по умолчанию
        from app.auth.routes import get_safe_redirect_url
        return redirect(get_safe_redirect_url(request.referrer, fallback='curriculum_admin.admin_lessons'))

    except Exception as e:
        db.session.rollback()
        logger.error(f"Error deleting lesson: {str(e)}")
        flash('Ошибка при удалении урока', 'error')
        return redirect(url_for('curriculum_admin.admin_lessons'))


def _extract_sound_filename(value: str) -> str | None:
    """Extract filename from '[sound:name.mp3]' or plain 'name.mp3'."""
    from app.utils.audio import parse_audio_filename
    return parse_audio_filename(value)


@admin_bp.route('/admin/audio-stats')
@login_required
@admin_required
def audio_stats():
    """Show audio file statistics per module — all sources."""
    import os
    from flask import current_app
    from app.words.models import CollectionWords, CollectionWordLink

    audio_dir = os.path.join(current_app.static_folder, 'audio')

    existing_files: set[str] = set()
    if os.path.exists(audio_dir):
        for f in os.listdir(audio_dir):
            if f.endswith('.mp3'):
                filepath = os.path.join(audio_dir, f)
                if os.path.getsize(filepath) > 0:
                    existing_files.add(f)

    module_stats = []
    modules = Module.query.join(CEFRLevel).order_by(CEFRLevel.order, Module.number).all()

    for module in modules:
        level_code = module.level.code if module.level else 'A0'
        audio_refs: list[dict] = []
        missing_files: list[dict] = []
        seen_files: set[str] = set()

        def _add_ref(label: str, filename: str, source: str) -> None:
            if filename in seen_files:
                return
            seen_files.add(filename)
            audio_refs.append({'word': label, 'file': filename, 'source': source})
            if filename not in existing_files:
                missing_files.append({'word': label, 'file': filename, 'source': source})

        lessons = Lessons.query.filter_by(module_id=module.id).all()
        for lesson in lessons:
            content = lesson.content or {}
            if not isinstance(content, dict):
                continue

            # --- 1. Vocabulary / words in content ---
            vocabulary = content.get('vocabulary', []) or content.get('words', []) or []
            if isinstance(vocabulary, list):
                for word in vocabulary:
                    if not isinstance(word, dict):
                        continue
                    audio_val = word.get('audio', '') or word.get('audio_url', '')
                    fn = _extract_sound_filename(str(audio_val))
                    if fn:
                        label = word.get('english') or word.get('word') or word.get('front', '')
                        _add_ref(label, fn, 'vocabulary')

            # --- 2. Top-level audio (text / listening lessons) ---
            top_audio = content.get('audio', '')
            fn = _extract_sound_filename(str(top_audio))
            if fn:
                _add_ref(f'Урок: {lesson.title}', fn, 'lesson')

            # --- 3. Exercises with audio (listening_quiz, etc.) ---
            exercises = content.get('exercises', [])
            if isinstance(exercises, list):
                for ex in exercises:
                    if not isinstance(ex, dict):
                        continue
                    audio_val = ex.get('audio', '')
                    fn = _extract_sound_filename(str(audio_val))
                    if fn:
                        label = ex.get('correct', '') or ex.get('question', '')
                        _add_ref(label, fn, 'exercise')

            # --- 4. Reading lines with audio ---
            text_obj = content.get('text', {})
            if isinstance(text_obj, dict):
                lines = text_obj.get('lines', [])
                if isinstance(lines, list):
                    for line in lines:
                        if not isinstance(line, dict):
                            continue
                        audio_val = line.get('audio', '')
                        fn = _extract_sound_filename(str(audio_val))
                        if fn:
                            _add_ref(line.get('text', '')[:40], fn, 'reading')

            # --- 5. Card lessons → CollectionWords.listening ---
            if lesson.type in ('card', 'flashcards', 'anki_cards'):
                coll_id = lesson.collection_id or content.get('collection_id')
                word_ids: list[int] = []
                if coll_id:
                    links = CollectionWordLink.query.filter_by(
                        collection_id=coll_id,
                    ).all()
                    word_ids = [lnk.word_id for lnk in links]
                extra_ids = content.get('word_ids', [])
                if isinstance(extra_ids, list):
                    word_ids.extend(extra_ids)
                word_ids = list(set(word_ids))

                if word_ids:
                    coll_words = CollectionWords.query.filter(
                        CollectionWords.id.in_(word_ids),
                    ).all()
                    for cw in coll_words:
                        fn = _extract_sound_filename(str(cw.listening or ''))
                        if fn:
                            _add_ref(cw.english_word or '', fn, 'collection')

        if audio_refs:
            module_stats.append({
                'id': module.number,
                'title': module.title,
                'level': level_code,
                'total_audio': len(audio_refs),
                'missing_count': len(missing_files),
                'missing_files': missing_files,
                'completion_percent': round(
                    (len(audio_refs) - len(missing_files)) / len(audio_refs) * 100
                ),
            })

    module_stats.sort(key=lambda x: x['id'])

    return render_template(
        'admin/curriculum/audio_stats.html',
        module_stats=module_stats,
        total_existing=len(existing_files),
    )
