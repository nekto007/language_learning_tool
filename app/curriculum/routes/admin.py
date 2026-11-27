# app/curriculum/routes/admin.py

import hashlib
import json
import logging
from datetime import UTC, datetime
from types import SimpleNamespace
from urllib.parse import urlsplit

from flask import Blueprint, Response, abort, current_app, flash, jsonify, make_response, redirect, render_template, request, url_for
from flask_login import current_user, login_required
from itsdangerous import BadData, URLSafeSerializer, URLSafeTimedSerializer
from sqlalchemy import or_

from app.admin.audit import log_admin_action
from app.admin.services.curriculum_import_service import CurriculumImportService
from app.admin.services.guided_topic_guard import managed_lesson_editor
from app.admin.utils.decorators import admin_required
from app.curriculum.models import CEFRLevel, LessonProgress, Lessons, Module
from app.curriculum.security import safe_int, sanitize_json_content, validate_file_upload
from app.utils.audio import parse_audio_filename
from app.utils.db import db

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
                log_admin_action(
                    current_user.id,
                    'curriculum.lesson.import',
                    target_type='lesson',
                    target_id=result.get('lesson_id') if isinstance(result, dict) else None,
                )
                db.session.commit()
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
            logger.exception("Failed to rollback DB session after import")

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
def admin_stats() -> Response:
    """Display curriculum statistics for admin"""
    return redirect(url_for('admin.curriculum_overview', _anchor='learning-statistics'))


@admin_bp.route('/admin/levels')
@login_required
@admin_required
def admin_levels() -> Response:
    """Manage CEFR levels"""
    return redirect(url_for('admin_curriculum.level_list'))


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

            log_admin_action(
                current_user.id,
                'curriculum.level.update',
                target_type='cefr_level',
                target_id=level_id,
            )
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

            log_admin_action(
                current_user.id,
                'curriculum.module.update',
                target_type='module',
                target_id=module_id,
            )
            db.session.commit()
            flash('Модуль успешно обновлен', 'success')
            return redirect('/learn/')

        except Exception as e:
            db.session.rollback()
            logger.error(f"Error updating module: {str(e)}")
            flash('Ошибка при обновлении модуля', 'error')
            return redirect(request.url)

    return render_template('admin/curriculum/edit_module.html', module=module)


def _quiz_choice_error(content: dict | list) -> str | None:
    """Run the learner projection on each choice row without changing stored content."""
    from app.api.native_content import is_extended, project
    from app.api.native_lessons import NativeLessonError, project_questions

    questions = content.get('questions') if isinstance(content, dict) else None
    if not isinstance(questions, list):
        return None
    choice_rows = [
        (number, question) for number, question in enumerate(questions, start=1)
        if isinstance(question, dict) and question.get('type', 'multiple_choice') == 'multiple_choice'
    ]
    if not choice_rows:
        return None
    candidate = SimpleNamespace(type='quiz', content=content)
    extended = is_extended(candidate)
    project_rows = project if extended else project_questions
    maximum = 30 if extended else 12
    for number, question in choice_rows:
        candidate.content = {'questions': [question]}
        try:
            project_rows(candidate)
        except NativeLessonError:
            return (
                f'Вопрос №{number} не откроется при прохождении теста. '
                f'Проверьте текст вопроса и укажите от 2 до {maximum} непустых вариантов и ключ ответа.'
            )
    return None


def _lesson_content_revision(lesson: Lessons) -> str:
    data = [lesson.id, lesson.type, lesson.grammar_topic_id, lesson.content]
    encoded = json.dumps(data, ensure_ascii=True, sort_keys=True, separators=(',', ':'))
    return hashlib.sha256(encoded.encode('ascii')).hexdigest()


def _choice_preview_response(payload: dict, status: int = 200) -> tuple[Response, int]:
    response = jsonify(payload)
    response.headers['Cache-Control'] = 'private, no-store'
    return response, status


@admin_bp.post('/admin/lesson/<int:lesson_id>/preview-choice')
@login_required
@admin_required
def preview_lesson_choice(lesson_id: int) -> tuple[Response, int]:
    """Project and grade one choice question from the editor's in-memory draft."""
    from app.api.native_content import check_course_answer
    from app.api.native_lessons import NativeLessonError, project_questions
    from app.curriculum.language_support import language_support_mode

    lesson = Lessons.query.get_or_404(lesson_id)
    if lesson.type != 'quiz':
        return _choice_preview_response({'error': 'Предпросмотр доступен для обычного квиза.'}, 404)
    body = request.get_json(silent=True)
    if (not isinstance(body, dict) or not isinstance(body.get('content'), str)
            or type(body.get('question_number')) is not int or body['question_number'] < 1):
        return _choice_preview_response({'error': 'Укажите номер вопроса и содержимое черновика.'}, 400)
    try:
        content = json.loads(body['content'])
    except (ValueError, RecursionError):
        return _choice_preview_response({'error': 'Исправьте формат JSON и обновите предпросмотр.'}, 422)
    rows = content.get('questions') if isinstance(content, dict) else None
    index = body['question_number'] - 1
    if not isinstance(rows, list) or index >= len(rows):
        return _choice_preview_response({'error': 'Проверьте номер вопроса. Такого задания нет.'}, 422)
    row = rows[index]
    if not isinstance(row, dict) or row.get('type', 'multiple_choice') != 'multiple_choice':
        return _choice_preview_response({'error': 'Выберите вопрос формата multiple_choice.'}, 422)
    media_error = {'error': 'Предпросмотр поддерживает выбор текстового варианта без медиа.'}
    if any(content.get(key) for key in ('audio', 'audio_url', 'video', 'video_url', 'transcript')):
        return _choice_preview_response(media_error, 422)

    candidate = SimpleNamespace(id=lesson.id, type=lesson.type, module=lesson.module, content=content)
    try:
        question = project_questions(candidate)[index]
        if question.get('input') != 'choice' or any(
            question.get(key) for key in ('audio_url', 'image_url', 'video_url')
        ):
            return _choice_preview_response(media_error, 422)
    except (NativeLessonError, TypeError, ValueError, RecursionError, IndexError):
        return _choice_preview_response(
            {'error': 'Проверьте текст, варианты и ключ ответа. Черновик не открывается в ученической практике.'}, 422,
        )

    payload = {'question': question, 'support_mode': language_support_mode(candidate)}
    if 'answer' in body:
        try:
            payload['feedback'] = check_course_answer(candidate, question, body['answer'])
        except NativeLessonError:
            return _choice_preview_response({'error': 'Выберите один из вариантов в предпросмотре.'}, 422)
    return _choice_preview_response(payload)


@admin_bp.route('/admin/lesson/<int:lesson_id>/edit', methods=['GET', 'POST'])
@login_required
@admin_required
def edit_lesson(lesson_id):
    """Edit lesson with content validation"""
    from app.admin.routes.materials import materials_return_url

    lesson = Lessons.query.get_or_404(lesson_id)
    if guided_editor := managed_lesson_editor(lesson):
        return guided_editor

    signer = URLSafeSerializer(current_app.secret_key, salt='admin-lesson-content-v1')
    submitted_json = None
    submitted_revision = ''
    response_status = 200
    if request.method == 'POST':
        # Check if it's the JSON content form
        if 'content' in request.form:
            submitted_json = request.form['content']
            submitted_revision = request.form.get('content_revision', '')
            try:
                # The guided-topic guard above takes its topic lock first.
                lesson = (Lessons.query.filter_by(id=lesson_id).populate_existing()
                          .with_for_update().first_or_404())
                revision = _lesson_content_revision(lesson)
                try:
                    form_revision = signer.loads(submitted_revision)
                except BadData:
                    form_revision = None
                confirmed = request.form.get('reviewed_content_conflict') == '1'
                if form_revision != [revision, False] and not (confirmed and form_revision == [revision, True]):
                    response_status = 409
                else:
                    try:
                        content = json.loads(submitted_json)
                    except (ValueError, RecursionError):
                        flash('Неверный формат JSON в содержимом', 'danger')
                        response_status = 422
                    else:
                        if not isinstance(content, (dict, list)):
                            error = 'Содержимое должно быть объектом или массивом JSON'
                        else:
                            error = _quiz_choice_error(content) if lesson.type == 'quiz' else None
                        if error:
                            flash(error, 'danger')
                            response_status = 422
                        else:
                            lesson.content = content
                            lesson.updated_at = datetime.now(UTC)
                            log_admin_action(
                                current_user.id,
                                'curriculum.lesson.update_content',
                                target_type='lesson',
                                target_id=lesson_id,
                            )
                            db.session.commit()
                            flash('Содержимое урока успешно обновлено', 'success')
                            return redirect(materials_return_url() or url_for('curriculum_admin.view_lesson', lesson_id=lesson.id))

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

                log_admin_action(
                    current_user.id,
                    'curriculum.lesson.update',
                    target_type='lesson',
                    target_id=lesson_id,
                )
                db.session.commit()
                flash('Урок успешно обновлен', 'success')
                return redirect(materials_return_url() or url_for('curriculum_admin.view_lesson', lesson_id=lesson.id))

            except Exception as e:
                db.session.rollback()
                logger.error(f"Error updating lesson: {str(e)}")
                flash('Ошибка при обновлении урока', 'error')
                return redirect(request.url)

    # Get data for template
    modules = Module.query.order_by(Module.level_id, Module.number).all()
    published_json = json.dumps(lesson.content or {}, ensure_ascii=False, indent=2)
    content_conflict = response_status == 409
    return render_template(
        'admin/curriculum/edit_lesson.html',
        lesson=lesson,
        modules=modules,
        content_json=published_json if submitted_json is None else submitted_json,
        submitted_draft=submitted_json is not None,
        content_revision=signer.dumps([_lesson_content_revision(lesson), content_conflict]),
        conflict_json=published_json if content_conflict else None,
        draft_revision=submitted_revision if content_conflict else None,
    ), response_status


def _lesson_audio_href(row: object) -> str | None:
    """Resolve an authored audio reference without failing the admin preview."""
    from app.api.native_content import media_url

    if not isinstance(row, dict):
        return None
    for field in ('audio_url', 'audio', 'audio_clip_url'):
        value = row.get(field)
        if isinstance(value, dict):
            value = value.get('url') or value.get('src')
        if not isinstance(value, str):
            continue
        value = value.strip()
        if value.startswith('[sound:'):
            filename = parse_audio_filename(value)
            if filename is None or value != f'[sound:{filename}]':
                continue
            value = filename.strip()
        if not value or len(value) > 4096 or '\\' in value or any(ord(char) < 32 or ord(char) == 127 for char in value):
            continue
        try:
            parts = urlsplit(value)
            if parts.scheme or parts.netloc:
                if (parts.scheme in ('', 'http', 'https') and parts.hostname and not parts.username
                        and not parts.password and not any(char.isspace() for char in parts.netloc)):
                    _ = parts.port  # Validate an explicit port without changing signed URLs.
                    return value
                continue
        except ValueError:
            continue
        if parts.path and not value.startswith('[') and (href := media_url(value)):
            return href
    return None


@admin_bp.route('/admin/lesson/<int:lesson_id>/view')
@login_required
@admin_required
def view_lesson(lesson_id):
    """View lesson details with full content display"""
    lesson = Lessons.query.get_or_404(lesson_id)
    
    all_progress = LessonProgress.query.filter_by(lesson_id=lesson_id).all()
    total_attempts = len(all_progress)
    completed = len([p for p in all_progress if p.status == 'completed'])
    scored = [p for p in all_progress if p.score]
    avg_score = sum(p.score for p in scored) / len(scored) if scored else 0

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
        recent_progress=recent_progress,
        lesson_audio_href=_lesson_audio_href,
    )


def _reading_preview_lesson(lesson_id: int) -> Lessons:
    from app.curriculum.constants import is_objective_practice

    lesson = Lessons.query.get_or_404(lesson_id)
    if lesson.type != 'reading' or not is_objective_practice(lesson):
        abort(404)
    return lesson


_READING_PREVIEW_SECONDS = 6 * 60 * 60


def _reading_preview_signer() -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(current_app.secret_key, salt='admin-reading-preview-v1')


def _reading_preview_response(payload: dict, status: int = 200) -> tuple[Response, int]:
    from app.api.native_lessons import private_response

    return private_response(jsonify(payload)), status


@admin_bp.get('/admin/lesson/<int:lesson_id>/reading-preview')
@admin_required
def reading_preview(lesson_id: int) -> Response:
    lesson = _reading_preview_lesson(lesson_id)
    response = make_response(render_template('curriculum/lessons/guided_practice.html',
        lesson=lesson, reading_preview_endpoint=url_for('.reading_preview_document', lesson_id=lesson.id)))
    response.headers['Cache-Control'] = 'private, no-store'
    return response


@admin_bp.get('/admin/lesson/<int:lesson_id>/reading-preview/practice')
@admin_required
def reading_preview_document(lesson_id: int) -> tuple[Response, int]:
    from app.api.native_lessons import NativeLessonError, _content, project_course_document, project_questions

    lesson = _reading_preview_lesson(lesson_id)
    try:
        payload = project_course_document(lesson, project_questions(lesson), _content(lesson))
    except NativeLessonError as error:
        return _reading_preview_response({'success': False, 'error': error.code}, error.status)
    payload['session_token'] = _reading_preview_signer().dumps(
        [current_user.id, lesson.id, payload['content_revision']],
    )
    return _reading_preview_response({'success': True, 'account_id': str(current_user.id), 'lesson': payload})


@admin_bp.post('/admin/lesson/<int:lesson_id>/reading-preview/practice/check')
@admin_required
def reading_preview_check(lesson_id: int) -> tuple[Response, int]:
    from app.api.native_content import check_course_answer
    from app.api.native_lessons import NativeLessonError, _content, _digest
    from app.api.native_lessons import project_course_document, project_questions

    lesson = _reading_preview_lesson(lesson_id)
    body = request.get_json(silent=True)
    fields = {'session_token', 'question_id', 'answer'}
    try:
        if not isinstance(body, dict) or body.keys() != fields or not all(isinstance(body[key], str) for key in fields):
            raise NativeLessonError('invalid_input')
        content = _content(lesson)
        if _reading_preview_signer().loads(body['session_token'], max_age=_READING_PREVIEW_SECONDS) != [
            current_user.id, lesson.id, _digest(content),
        ]:
            raise NativeLessonError('lesson_changed', 409)
        questions = project_questions(lesson)
        project_course_document(lesson, questions, content)
        question = next((item for item in questions if item['id'] == body['question_id']), None)
        if question is None:
            raise NativeLessonError('invalid_input')
        feedback = check_course_answer(lesson, question, body['answer'])
    except BadData:
        return _reading_preview_response({'success': False, 'error': 'lesson_changed'}, 409)
    except NativeLessonError as error:
        return _reading_preview_response({'success': False, 'error': error.code}, error.status)
    return _reading_preview_response({'success': True, 'feedback': feedback})


@admin_bp.route('/admin/lesson/<int:lesson_id>/delete', methods=['POST'])
@login_required
@admin_required
def delete_lesson(lesson_id):
    """Delete lesson with confirmation"""
    try:
        lesson = Lessons.query.get_or_404(lesson_id)
        if guided_editor := managed_lesson_editor(lesson):
            return guided_editor
        
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
        log_admin_action(
            current_user.id,
            'curriculum.lesson.delete',
            target_type='lesson',
            target_id=lesson_id,
        )
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
    return parse_audio_filename(value)


def _extract_audio_filename(value: object) -> str | None:
    """Extract an MP3 filename from supported lesson audio reference shapes."""
    if not isinstance(value, str):
        return None
    value = value.strip()
    if not value:
        return None

    fn = _extract_sound_filename(value)
    if fn and fn.endswith('.mp3'):
        return fn.rsplit('/', 1)[-1]

    if value.endswith('.mp3'):
        return value.rsplit('/', 1)[-1]

    return None


def _iter_lesson_audio_refs(content: object):
    """Yield audio refs from nested lesson content, including arrays."""
    audio_keys = {'audio', 'audio_url', 'audio_clip_url', 'listening'}

    def _label_from_context(ctx: dict | None) -> str:
        if not isinstance(ctx, dict):
            return ''
        for key in (
            'english', 'word', 'front', 'text', 'audio_text', 'question',
            'correct', 'example', 'case', 'title',
        ):
            value = ctx.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()[:80]
        return ''

    def _source_from_path(path: str) -> str:
        def has(segment: str) -> bool:
            return path.startswith(segment) or f'.{segment}' in path

        if has('vocabulary') or has('words'):
            return 'vocabulary'
        if has('cards'):
            return 'card'
        if has('test_sections'):
            return 'test'
        if has('exercises'):
            return 'exercise'
        if has('lines'):
            return 'reading'
        if has('sections') or has('grammar_explanation'):
            return 'grammar'
        return 'lesson'

    def _walk(node: object, path: str, parent: dict | None = None):
        if isinstance(node, dict):
            for key, value in node.items():
                next_path = f'{path}.{key}' if path else key
                if key in audio_keys:
                    yield from _walk_audio_value(value, next_path, node)
                yield from _walk(value, next_path, node)
        elif isinstance(node, list):
            for idx, item in enumerate(node):
                yield from _walk(item, f'{path}[{idx}]', parent)

    def _walk_audio_value(value: object, path: str, parent: dict | None):
        if isinstance(value, str):
            filename = _extract_audio_filename(value)
            if filename:
                label = _label_from_context(parent)
                yield label, filename, _source_from_path(path)
        elif isinstance(value, list):
            for idx, item in enumerate(value):
                yield from _walk_audio_value(item, f'{path}[{idx}]', parent)
        elif isinstance(value, dict):
            yield from _walk(value, path, value)

    yield from _walk(content, '')


@admin_bp.route('/admin/audio-stats')
@login_required
@admin_required
def audio_stats():
    """Show audio file statistics per module — all sources."""
    import os

    from flask import current_app

    from app.words.models import CollectionWordLink, CollectionWords

    audio_dir = os.path.join(current_app.static_folder, 'audio')

    # Walk audio_dir recursively — immersion lessons (dictation, audio_fill_blank,
    # shadow_reading, listening_immersion) store their MP3s in subdirectories
    # like audio/immersion/dictation/foo.mp3.  Storing only basenames is enough:
    # this project's filenames already encode level/module/lesson and are
    # unique across the tree.
    existing_files: set[str] = set()
    if os.path.exists(audio_dir):
        for root, _dirs, files in os.walk(audio_dir):
            for f in files:
                if not f.endswith('.mp3'):
                    continue
                filepath = os.path.join(root, f)
                try:
                    if os.path.getsize(filepath) > 0:
                        existing_files.add(f)
                except OSError:
                    # Broken symlink or file disappeared between listdir and getsize —
                    # treat as missing so the stats page surfaces it instead of 500'ing.
                    continue

    def _filename_from_url(url: str) -> str | None:
        """Extract trailing filename from a `/static/audio/...` style URL."""
        if not url or not isinstance(url, str):
            return None
        name = os.path.basename(url.strip())
        return name if name.endswith('.mp3') else None

    module_stats = []
    modules = Module.query.join(CEFRLevel).order_by(CEFRLevel.order, Module.number).all()

    for module in modules:
        level_code = module.level.code if module.level else 'A1'
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

            # --- 2b. audio_url field (immersion lesson types: dictation, shadow_reading,
            #         audio_fill_blank, listening_immersion) ---
            top_audio_url = content.get('audio_url', '')
            fn = _filename_from_url(str(top_audio_url))
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

            # --- 6. Nested lesson content fallback ---
            # Grammar examples, flashcard cards, final_test sections, and similar
            # shapes can keep audio refs deeper than the historical flat fields
            # above.  Walk known audio keys recursively; _add_ref de-duplicates
            # filenames already counted by the explicit legacy branches.
            for label, fn, source in _iter_lesson_audio_refs(content):
                _add_ref(label or f'Урок: {lesson.title}', fn, source)

        if audio_refs:
            module_stats.append({
                'id': module.number,
                'title': module.title,
                'level': level_code,
                'level_order': module.level.order if module.level else 0,
                # Unique key combining level + module number, used as DOM id
                # for the collapse target so each "Показать" button toggles
                # ONLY its own module's missing-files block.
                'uid': f"{level_code}-{module.number}",
                'total_audio': len(audio_refs),
                'missing_count': len(missing_files),
                'missing_files': missing_files,
                'completion_percent': round(
                    (len(audio_refs) - len(missing_files)) / len(audio_refs) * 100
                ),
            })

    # Sort by (level_order, module number) so output reads A1/M1, A1/M2, ...,
    # A2/M1, ..., not all M1 from every level interleaved.
    module_stats.sort(key=lambda x: (x['level_order'], x['id']))

    return render_template(
        'admin/curriculum/audio_stats.html',
        module_stats=module_stats,
        total_existing=len(existing_files),
    )
