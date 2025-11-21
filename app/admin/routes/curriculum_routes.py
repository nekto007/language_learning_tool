# app/admin/routes/curriculum_routes.py

"""
Curriculum Management Routes для административной панели
Маршруты для управления учебной программой, уровнями, модулями и уроками
"""
import json
import logging

from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import current_user
from sqlalchemy import distinct, func

from app.admin.services.curriculum_import_service import CurriculumImportService
from app.admin.utils.decorators import admin_required
from app.curriculum.models import CEFRLevel, LessonProgress, Lessons, Module
from app.utils.db import db
from app.auth.models import User

# Создаем blueprint для curriculum routes
# Note: Using 'admin_curriculum' to avoid conflict with 'curriculum_admin' in app/curriculum
curriculum_bp = Blueprint('admin_curriculum', __name__)

logger = logging.getLogger(__name__)


@curriculum_bp.route('/curriculum')
@admin_required
def curriculum():
    """Управление структурой курсов"""
    levels = CEFRLevel.query.order_by(CEFRLevel.order).all()

    # Получаем список последних уроков для быстрого доступа
    recent_lessons = Lessons.query.order_by(Lessons.created_at.desc()).limit(10).all()

    # Получаем количество уникальных пользователей с прогрессом
    user_progress_count = db.session.query(
        func.count(distinct(LessonProgress.user_id))
    ).scalar() or 0

    return render_template(
        'admin/curriculum/index.html',
        levels=levels,
        recent_lessons=recent_lessons,
        user_progress_count=user_progress_count
    )


@curriculum_bp.route('/curriculum/levels')
@admin_required
def level_list():
    """List all CEFR levels"""
    levels = CEFRLevel.query.order_by(CEFRLevel.order).all()

    # Add counts for each level
    for level in levels:
        level.module_count = Module.query.filter_by(level_id=level.id).count()
        level.lesson_count = db.session.query(Lessons).join(
            Module, Module.id == Lessons.module_id
        ).filter(
            Module.level_id == level.id
        ).count()

    return render_template('admin/curriculum/level_list.html', levels=levels)


@curriculum_bp.route('/curriculum/modules')
@admin_required
def module_list():
    """List all modules"""
    level_id = request.args.get('level_id', type=int)

    query = Module.query.join(CEFRLevel)

    if level_id:
        query = query.filter(Module.level_id == level_id)

    modules = query.order_by(CEFRLevel.order, Module.number).all()

    for module in modules:
        module.lesson_count = Lessons.query.filter_by(module_id=module.id).count()

    levels = CEFRLevel.query.order_by(CEFRLevel.order).all()

    return render_template(
        'admin/curriculum/module_list.html',
        modules=modules,
        levels=levels,
        level_id=level_id
    )


@curriculum_bp.route('/curriculum/lessons')
@admin_required
def lesson_list():
    """List all lessons"""
    level_id = request.args.get('level_id', type=int)
    module_id = request.args.get('module_id', type=int)
    search = request.args.get('search', '')

    query = Lessons.query.join(Module).join(CEFRLevel)

    if level_id:
        query = query.filter(Module.level_id == level_id)

    if module_id:
        query = query.filter(Lessons.module_id == module_id)

    if search:
        query = query.filter(Lessons.title.ilike(f'%{search}%'))

    lessons = query.order_by(CEFRLevel.order, Module.number, Lessons.number).all()

    levels = CEFRLevel.query.order_by(CEFRLevel.order).all()

    if level_id:
        modules = Module.query.filter_by(level_id=level_id).order_by(Module.number).all()
    else:
        modules = Module.query.join(CEFRLevel).order_by(CEFRLevel.order, Module.number).all()

    return render_template(
        'admin/curriculum/lesson_list.html',
        lessons=lessons,
        levels=levels,
        modules=modules,
        level_id=level_id,
        module_id=module_id,
        search=search
    )


@curriculum_bp.route('/curriculum/progress')
@admin_required
def user_progress():
    """View user progress through curriculum"""
    user_id = request.args.get('user_id', type=int)
    level_id = request.args.get('level_id', type=int)
    module_id = request.args.get('module_id', type=int)
    status = request.args.get('status')

    query = db.session.query(
        LessonProgress, Lessons, Module, CEFRLevel, User
    ).join(
        Lessons, LessonProgress.lesson_id == Lessons.id
    ).join(
        Module, Lessons.module_id == Module.id
    ).join(
        CEFRLevel, Module.level_id == CEFRLevel.id
    ).join(
        User, LessonProgress.user_id == User.id
    )

    if user_id:
        query = query.filter(LessonProgress.user_id == user_id)

    if level_id:
        query = query.filter(Module.level_id == level_id)

    if module_id:
        query = query.filter(Lessons.module_id == module_id)

    if status:
        query = query.filter(LessonProgress.status == status)

    progress_entries = query.order_by(
        User.username,
        CEFRLevel.order,
        Module.number,
        Lessons.number
    ).all()

    status_counts = db.session.query(
        LessonProgress.status,
        db.func.count(LessonProgress.id)
    ).group_by(LessonProgress.status).all()

    status_stats = {status: count for status, count in status_counts}

    users = User.query.order_by(User.username).all()
    levels = CEFRLevel.query.order_by(CEFRLevel.order).all()

    if level_id:
        modules = Module.query.filter_by(level_id=level_id).order_by(Module.number).all()
    else:
        modules = []

    return render_template(
        'admin/curriculum/user_progress.html',
        progress_entries=progress_entries,
        users=users,
        levels=levels,
        modules=modules,
        status_stats=status_stats,
        user_id=user_id,
        level_id=level_id,
        module_id=module_id,
        status=status
    )


@curriculum_bp.route('/curriculum/import', methods=['GET', 'POST'])
@admin_required
def import_curriculum():
    """Импорт учебного материала из JSON"""
    if request.method == 'POST':
        # Проверяем, был ли загружен файл или введен JSON-текст
        json_data = None

        if 'json_file' in request.files and request.files['json_file'].filename:
            # Получаем JSON из файла
            file = request.files['json_file']

            # SECURITY: Validate uploaded file
            from app.utils.file_security import validate_text_file_upload
            is_valid, error_msg = validate_text_file_upload(
                file,
                allowed_extensions={'json'},
                max_size_mb=10
            )

            if not is_valid:
                flash(f'Ошибка валидации файла: {error_msg}', 'danger')
                return redirect(url_for('admin_curriculum.import_curriculum'))

            try:
                json_text = file.read().decode('utf-8')
                json_data = json.loads(json_text)
            except Exception as e:
                flash(f'Ошибка при чтении файла: {str(e)}', 'danger')
                return redirect(url_for('admin_curriculum.import_curriculum'))

        elif request.form.get('json_text'):
            # Получаем JSON из текстового поля
            try:
                json_data = json.loads(request.form.get('json_text'))
            except Exception as e:
                flash(f'Ошибка в формате JSON: {str(e)}', 'danger')
                return redirect(url_for('admin_curriculum.import_curriculum'))

        if json_data:
            # Выполняем импорт через сервис
            try:
                result = CurriculumImportService.import_curriculum_data(json_data)
                flash(
                    f'Материал успешно импортирован! Создан урок ID: {result["lesson_id"]}',
                    'success'
                )

                # Перенаправляем на страницу списка уроков модуля
                module = Module.query.get(result["module_id"])
                if module:
                    return redirect(url_for('admin.lesson_list', module_id=module.id))
                else:
                    return redirect(url_for('admin_curriculum.curriculum'))

            except Exception as e:
                logger.error(f'Ошибка при импорте: {str(e)}', exc_info=True)
                flash(f'Ошибка при импорте: {str(e)}', 'danger')
                return redirect(url_for('admin_curriculum.import_curriculum'))

    return render_template('admin/curriculum/import.html')
