# app/admin/curriculum.py

"""
Управление учебной программой в LLT English
Модуль для администрирования уровней CEFR, модулей, уроков и компонентов
"""

import logging
from datetime import datetime

from flask import flash, jsonify, redirect, render_template, request, url_for
from flask_babel import gettext as _, lazy_gettext as _l
from flask_wtf import FlaskForm
from wtforms import IntegerField, SelectField, StringField, SubmitField, TextAreaField
from wtforms.validators import DataRequired, Length, NumberRange, Optional

from app.admin.routes import admin, admin_required
from app.auth.models import User
from app.books.models import Book
from app.curriculum.models import CEFRLevel, LessonProgress, Lessons, Module
from app.utils.db import db
from app.words.models import CollectionWordLink, CollectionWords

# Настройка логирования
logger = logging.getLogger(__name__)


# Формы для управления программой обучения
class CEFRLevelForm(FlaskForm):
    """Форма для создания/редактирования уровня CEFR"""
    code = StringField(_l('Code'), validators=[DataRequired(), Length(min=2, max=2)])
    name = StringField(_l('Name'), validators=[DataRequired(), Length(max=100)])
    description = TextAreaField(_l('Description'), validators=[Optional()])
    order = IntegerField(_l('Order'), validators=[Optional(), NumberRange(min=0)], default=0)
    submit = SubmitField(_l('Save'))


class ModuleForm(FlaskForm):
    """Форма для создания/редактирования модуля"""
    level_id = SelectField(_l('Level'), coerce=int, validators=[DataRequired()])
    number = IntegerField(_l('Number'), validators=[DataRequired(), NumberRange(min=1)])
    title = StringField(_l('Title'), validators=[DataRequired(), Length(max=200)])
    description = TextAreaField(_l('Description'), validators=[Optional()])
    submit = SubmitField(_l('Save'))

    def __init__(self, *args, **kwargs):
        super(ModuleForm, self).__init__(*args, **kwargs)
        self.level_id.choices = [(level.id, f"{level.code} - {level.name}")
                                 for level in CEFRLevel.query.order_by(CEFRLevel.order).all()]


class LessonForm(FlaskForm):
    """Форма для создания/редактирования урока"""
    module_id = SelectField(_l('Module'), coerce=int, validators=[DataRequired()])
    number = IntegerField(_l('Number'), validators=[DataRequired(), NumberRange(min=1)])
    title = StringField(_l('Title'), validators=[DataRequired(), Length(max=200)])
    description = TextAreaField(_l('Description'), validators=[Optional()])
    submit = SubmitField(_l('Save'))

    def __init__(self, *args, **kwargs):
        super(LessonForm, self).__init__(*args, **kwargs)
        # Заполняем список модулей
        modules = Module.query.join(CEFRLevel).order_by(CEFRLevel.order, Module.number).all()
        self.module_id.choices = [(m.id, f"{m.level.code} - {m.title} (Module {m.number})")
                                  for m in modules]


# Страница управления учебной программой
@admin.route('/curriculum/overview')
@admin_required
def curriculum_overview():
    """Общий обзор учебной программы"""
    # Получаем статистику
    levels_count = CEFRLevel.query.count()
    modules_count = Module.query.count()
    lessons_count = Lessons.query.count()

    # Получаем уровни и их модули
    levels = CEFRLevel.query.order_by(CEFRLevel.order).all()

    # Получаем недавно добавленные уроки
    recent_lessons = Lessons.query.order_by(Lessons.created_at.desc()).limit(10).all()

    # Статистика по пользователям
    user_progress_count = db.session.query(LessonProgress.user_id).distinct().count()

    # Получение данных для графика прогресса студентов по уровням
    level_progress = {}
    for level in levels:
        # Находим все уроки для этого уровня
        lesson_ids = db.session.query(Lessons.id).join(
            Module, Module.id == Lessons.module_id
        ).filter(
            Module.level_id == level.id
        ).subquery()

        # Подсчитываем прогресс
        total_lessons = db.session.query(lesson_ids).count()
        completed_lessons = db.session.query(LessonProgress).filter(
            LessonProgress.lesson_id.in_(lesson_ids),
            LessonProgress.status == 'completed'
        ).count()

        if total_lessons > 0:
            percentage = int((completed_lessons / total_lessons) * 100)
        else:
            percentage = 0

        level_progress[level.code] = {
            'total': total_lessons,
            'completed': completed_lessons,
            'percentage': percentage
        }

    return render_template(
        'admin/curriculum/overview.html',
        levels_count=levels_count,
        modules_count=modules_count,
        lessons_count=lessons_count,
        levels=levels,
        recent_lessons=recent_lessons,
        user_progress_count=user_progress_count,
        level_progress=level_progress
    )


# Управление уровнями CEFR
@admin.route('/curriculum/levels/create', methods=['GET', 'POST'])
@admin_required
def create_level():
    """Создание нового уровня CEFR"""
    form = CEFRLevelForm()

    if form.validate_on_submit():
        level = CEFRLevel(
            code=form.code.data.upper(),
            name=form.name.data,
            description=form.description.data,
            order=form.order.data
        )

        db.session.add(level)
        db.session.commit()

        flash(_('Уровень успешно создан!'), 'success')
        return redirect(url_for('admin.level_list'))

    return render_template(
        'admin/curriculum/create_level.html',
        form=form
    )


@admin.route('/curriculum/levels/<int:level_id>/edit', methods=['GET', 'POST'])
@admin_required
def edit_level(level_id):
    """Редактирование уровня CEFR"""
    level = CEFRLevel.query.get_or_404(level_id)
    form = CEFRLevelForm(obj=level)

    if form.validate_on_submit():
        form.populate_obj(level)
        level.code = level.code.upper()  # Преобразуем в верхний регистр
        db.session.commit()

        flash(_('Уровень успешно обновлен!'), 'success')
        return redirect(url_for('admin.level_list'))

    return render_template(
        'admin/curriculum/edit_level.html',
        form=form,
        level=level
    )


@admin.route('/curriculum/levels/<int:level_id>/delete', methods=['POST'])
@admin_required
def delete_level(level_id):
    """Удаление уровня CEFR"""
    level = CEFRLevel.query.get_or_404(level_id)

    # Проверяем наличие связанных модулей
    if level.modules.count() > 0:
        flash(_('Невозможно удалить уровень с модулями. Сначала удалите связанные модули.'), 'danger')
        return redirect(url_for('admin.level_list'))

    db.session.delete(level)
    db.session.commit()

    flash(_('Уровень успешно удален!'), 'success')
    return redirect(url_for('admin.level_list'))


# Управление модулями
@admin.route('/curriculum/modules/create', methods=['GET', 'POST'])
@admin_required
def create_module():
    """Создание нового модуля"""
    form = ModuleForm()

    # Предварительно выбираем уровень из URL-параметра, если есть
    level_id = request.args.get('level_id', type=int)
    if level_id:
        form.level_id.data = level_id

    if form.validate_on_submit():
        # Проверяем, не существует ли уже модуль с таким номером для этого уровня
        existing_module = Module.query.filter_by(
            level_id=form.level_id.data,
            number=form.number.data
        ).first()

        if existing_module:
            flash(_('Модуль с таким номером уже существует для этого уровня.'), 'danger')
            return render_template('admin/curriculum/create_module.html', form=form)

        module = Module(
            level_id=form.level_id.data,
            number=form.number.data,
            title=form.title.data,
            description=form.description.data
        )

        db.session.add(module)
        db.session.commit()

        flash(_('Модуль успешно создан!'), 'success')
        return redirect(url_for('admin.module_list'))

    return render_template(
        'admin/curriculum/create_module.html',
        form=form,
        level_id=level_id
    )


@admin.route('/curriculum/modules/<int:module_id>/edit', methods=['GET', 'POST'])
@admin_required
def edit_module(module_id):
    """Редактирование модуля"""
    module = Module.query.get_or_404(module_id)
    form = ModuleForm(obj=module)

    if form.validate_on_submit():
        # Проверяем, не существует ли уже модуль с таким номером для этого уровня
        existing_module = Module.query.filter_by(
            level_id=form.level_id.data,
            number=form.number.data
        ).first()

        if existing_module and existing_module.id != module.id:
            flash(_('Модуль с таким номером уже существует для этого уровня.'), 'danger')
            return render_template('admin/curriculum/edit_module.html', form=form, module=module)

        form.populate_obj(module)
        db.session.commit()

        flash(_('Модуль успешно обновлен!'), 'success')
        return redirect(url_for('admin.module_list'))

    return render_template(
        'admin/curriculum/edit_module.html',
        form=form,
        module=module
    )


@admin.route('/curriculum/modules/<int:module_id>/delete', methods=['POST'])
@admin_required
def delete_module(module_id):
    """Удаление модуля (вместе со всеми уроками благодаря cascade)"""
    module = Module.query.get_or_404(module_id)

    lesson_count = len(module.lessons)
    module_title = module.title

    db.session.delete(module)
    db.session.commit()

    if lesson_count > 0:
        flash(_('Модуль "{}" и {} урок(ов) успешно удалены!').format(module_title, lesson_count), 'success')
    else:
        flash(_('Модуль "{}" успешно удален!').format(module_title), 'success')

    return redirect(url_for('admin.curriculum_overview'))


# Управление уроками
@admin.route('/curriculum/lessons/create', methods=['GET', 'POST'])
@admin_required
def create_lesson():
    """Создание нового урока"""
    form = LessonForm()

    # Предварительно выбираем модуль из URL-параметра, если есть
    module_id = request.args.get('module_id', type=int)
    if module_id:
        form.module_id.data = module_id

    if form.validate_on_submit():
        # Проверяем, не существует ли уже урок с таким номером для этого модуля
        existing_lesson = Lessons.query.filter_by(
            module_id=form.module_id.data,
            number=form.number.data
        ).first()

        if existing_lesson:
            flash(_('Урок с таким номером уже существует для этого модуля.'), 'danger')
            return render_template('admin/curriculum/create_lesson.html', form=form)

        lesson = Lessons(
            module_id=form.module_id.data,
            number=form.number.data,
            title=form.title.data,
            description=form.description.data
        )

        db.session.add(lesson)
        db.session.commit()

        flash(_('Урок успешно создан!'), 'success')
        return redirect(url_for('admin.edit_lesson', lesson_id=lesson.id))

    return render_template(
        'admin/curriculum/create_lesson.html',
        form=form,
        module_id=module_id
    )


@admin.route('/curriculum/lessons/<int:lesson_id>/edit', methods=['GET', 'POST'])
@admin_required
def edit_lesson(lesson_id):
    """Редактирование урока"""
    lesson = Lessons.query.get_or_404(lesson_id)
    form = LessonForm(obj=lesson)

    if form.validate_on_submit():
        # Проверяем, не существует ли уже урок с таким номером для этого модуля
        existing_lesson = Lessons.query.filter_by(
            module_id=form.module_id.data,
            number=form.number.data
        ).first()

        if existing_lesson and existing_lesson.id != lesson.id:
            flash(_('Урок с таким номером уже существует для этого модуля.'), 'danger')
            return render_template('admin/curriculum/edit_lesson.html', form=form, lesson=lesson)

        form.populate_obj(lesson)
        db.session.commit()

        flash(_('Урок успешно обновлен!'), 'success')
        return redirect(url_for('admin.edit_lesson', lesson_id=lesson.id))

    return render_template(
        'admin/curriculum/edit_lesson.html',
        form=form,
        lesson=lesson
    )


@admin.route('/curriculum/lessons/<int:lesson_id>/delete', methods=['POST'])
@admin_required
def delete_lesson(lesson_id):
    """Удаление урока"""
    lesson = Lessons.query.get_or_404(lesson_id)
    module_id = lesson.module_id

    # Удаляем прогресс пользователей по этому уроку
    LessonProgress.query.filter_by(lesson_id=lesson.id).delete()

    db.session.delete(lesson)
    db.session.commit()

    flash(_('Урок и все связанные данные успешно удалены!'), 'success')
    return redirect(url_for('admin.lesson_list', module_id=module_id))


# Редактирование содержимого уроков по типам
@admin.route('/curriculum/lessons/<int:lesson_id>/edit_grammar', methods=['GET', 'POST'])
@admin_required
def edit_grammar_lesson(lesson_id):
    """Редактирование грамматического урока"""
    lesson = Lessons.query.get_or_404(lesson_id)

    if lesson.type != 'grammar':
        flash(_('Неверный тип урока!'), 'danger')
        return redirect(url_for('admin.lesson_list'))

    if request.method == 'POST':
        # Получаем данные из формы
        rule = request.form.get('rule', '')
        examples = request.form.getlist('examples[]')

        # Получаем упражнения
        exercise_count = int(request.form.get('exercise_count', 0))
        exercises = []

        for i in range(exercise_count):
            exercise_type = request.form.get(f'exercise_type_{i}')

            if exercise_type == 'fill_blanks':
                exercises.append({
                    'type': 'fill_blanks',
                    'text': request.form.get(f'exercise_text_{i}', ''),
                    'answers': request.form.getlist(f'exercise_answers_{i}[]'),
                    'explanation': request.form.get(f'exercise_explanation_{i}', '')
                })
            elif exercise_type == 'multiple_choice':
                exercises.append({
                    'type': 'multiple_choice',
                    'question': request.form.get(f'exercise_question_{i}', ''),
                    'options': request.form.getlist(f'exercise_options_{i}[]'),
                    'correct_answer': request.form.get(f'exercise_correct_{i}', ''),
                    'explanation': request.form.get(f'exercise_explanation_{i}', '')
                })
            elif exercise_type == 'true_false':
                exercises.append({
                    'type': 'true_false',
                    'question': request.form.get(f'exercise_question_{i}', ''),
                    'answer': request.form.get(f'exercise_correct_{i}', '') == 'true',
                    'explanation': request.form.get(f'exercise_explanation_{i}', '')
                })

        # Обновляем контент
        lesson.content = {
            'rule': rule,
            'examples': examples,
            'exercises': exercises
        }

        db.session.commit()

        flash(_('Грамматический урок успешно обновлен!'), 'success')
        return redirect(url_for('admin.lesson_list'))

    # Получаем текущий контент
    content = lesson.content or {}
    rule = content.get('rule', '')
    examples = content.get('examples', [])
    exercises = content.get('exercises', [])

    return render_template(
        'admin/curriculum/edit_grammar.html',
        lesson=lesson,
        rule=rule,
        examples=examples,
        exercises=exercises
    )


@admin.route('/curriculum/lessons/<int:lesson_id>/edit_quiz', methods=['GET', 'POST'])
@admin_required
def edit_quiz_lesson(lesson_id):
    """Редактирование урока-викторины"""
    lesson = Lessons.query.get_or_404(lesson_id)

    if lesson.type != 'quiz':
        flash(_('Неверный тип урока!'), 'danger')
        return redirect(url_for('admin.lesson_list'))

    if request.method == 'POST':
        # Получаем проходной балл
        passing_score = int(request.form.get('passing_score', 60))

        # Получаем вопросы
        question_count = int(request.form.get('question_count', 0))
        questions = []

        for i in range(question_count):
            question_type = request.form.get(f'question_type_{i}')

            if question_type == 'multiple_choice':
                questions.append({
                    'type': 'multiple_choice',
                    'text': request.form.get(f'question_text_{i}', ''),
                    'options': request.form.getlist(f'question_options_{i}[]'),
                    'answer': request.form.get(f'question_correct_{i}', '')
                })
            elif question_type == 'true_false':
                questions.append({
                    'type': 'true_false',
                    'text': request.form.get(f'question_text_{i}', ''),
                    'answer': request.form.get(f'question_correct_{i}', '') == 'true'
                })
            elif question_type == 'fill_blank':
                questions.append({
                    'type': 'fill_blank',
                    'text': request.form.get(f'question_text_{i}', ''),
                    'answer': request.form.get(f'question_correct_{i}', ''),
                    'acceptable_answers': request.form.getlist(f'question_acceptable_{i}[]')
                })

        # Обновляем контент
        lesson.content = {
            'questions': questions,
            'passing_score': passing_score
        }

        db.session.commit()

        flash(_('Урок-викторина успешно обновлен!'), 'success')
        return redirect(url_for('admin.lesson_list'))

    # Получаем текущий контент
    content = lesson.content or {}
    questions = content.get('questions', [])
    passing_score = content.get('passing_score', 60)

    return render_template(
        'admin/curriculum/edit_quiz.html',
        lesson=lesson,
        questions=questions,
        passing_score=passing_score
    )


@admin.route('/curriculum/lessons/<int:lesson_id>/edit_matching', methods=['GET', 'POST'])
@admin_required
def edit_matching_lesson(lesson_id):
    """Редактирование урока сопоставления"""
    lesson = Lessons.query.get_or_404(lesson_id)

    if lesson.type != 'matching':
        flash(_('Неверный тип урока!'), 'danger')
        return redirect(url_for('admin.lesson_list'))

    if request.method == 'POST':
        # Получаем лимит времени
        time_limit = int(request.form.get('time_limit', 0))

        # Получаем пары для сопоставления
        pairs_count = int(request.form.get('pairs_count', 0))
        pairs = []

        for i in range(pairs_count):
            left = request.form.get(f'pair_left_{i}', '')
            right = request.form.get(f'pair_right_{i}', '')

            if left and right:
                pairs.append({
                    'left': left,
                    'right': right
                })

        # Обновляем контент
        lesson.content = {
            'pairs': pairs,
            'time_limit': time_limit
        }

        db.session.commit()

        flash(_('Урок сопоставления успешно обновлен!'), 'success')
        return redirect(url_for('admin.lesson_list'))

    # Получаем текущий контент
    content = lesson.content or {}
    pairs = content.get('pairs', [])
    time_limit = content.get('time_limit', 0)

    return render_template(
        'admin/curriculum/edit_matching.html',
        lesson=lesson,
        pairs=pairs,
        time_limit=time_limit
    )


@admin.route('/curriculum/lessons/<int:lesson_id>/edit_text', methods=['GET', 'POST'])
@admin_required
def edit_text_lesson(lesson_id):
    """Редактирование текстового урока"""
    lesson = Lessons.query.get_or_404(lesson_id)

    if lesson.type != 'text':
        flash(_('Неверный тип урока!'), 'danger')
        return redirect(url_for('admin.lesson_list'))

    if request.method == 'POST':
        # Получаем книгу, если указана
        book_id = request.form.get('book_id', type=int)
        lesson.book_id = book_id if book_id and book_id > 0 else None

        # Получаем текст, если не выбрана книга
        text = request.form.get('text', '')

        # Получаем параметры отображения
        starting_paragraph = int(request.form.get('starting_paragraph', 0))
        ending_paragraph = int(request.form.get('ending_paragraph', 0))

        # Получаем метаданные
        metadata = {
            'title': request.form.get('meta_title', ''),
            'source': request.form.get('meta_source', ''),
            'type': request.form.get('meta_type', 'article'),
            'level': request.form.get('meta_level', '')
        }

        # Обновляем контент
        lesson.content = {
            'text': text if not lesson.book_id else '',
            'starting_paragraph': starting_paragraph,
            'ending_paragraph': ending_paragraph,
            'metadata': metadata
        }

        db.session.commit()

        flash(_('Текстовый урок успешно обновлен!'), 'success')
        return redirect(url_for('admin.lesson_list'))

    # Получаем текущий контент
    content = lesson.content or {}
    text = content.get('text', '')
    starting_paragraph = content.get('starting_paragraph', 0)
    ending_paragraph = content.get('ending_paragraph', 0)
    metadata = content.get('metadata', {})

    # Получаем книгу, если связана
    book = None
    if lesson.book_id:
        book = Book.query.get(lesson.book_id)

    # Получаем все книги для выбора
    books = Book.query.order_by(Book.title).all()

    return render_template(
        'admin/curriculum/edit_text.html',
        lesson=lesson,
        text=text,
        starting_paragraph=starting_paragraph,
        ending_paragraph=ending_paragraph,
        metadata=metadata,
        book=book,
        books=books
    )


@admin.route('/curriculum/export/<int:lesson_id>')
@admin_required
def export_lesson(lesson_id):
    """Экспорт урока в формате JSON"""
    lesson = Lessons.query.get_or_404(lesson_id)
    module = Module.query.get(lesson.module_id)
    level = CEFRLevel.query.get(module.level_id)

    # Создаем базовую структуру
    export_data = {
        'level': level.code,
        'module': module.number,
        'title': lesson.title,
        'type': lesson.type,
        'content': lesson.content
    }

    # Если урок связан с коллекцией слов
    if lesson.type == 'vocabulary' and lesson.collection_id:
        # Получаем слова коллекции
        words = db.session.query(CollectionWords).join(
            CollectionWordLink,
            CollectionWords.id == CollectionWordLink.word_id
        ).filter(
            CollectionWordLink.collection_id == lesson.collection_id
        ).all()

        vocabulary_items = []
        for word in words:
            # Получаем теги слова
            tags = [topic.name for topic in word.topics]

            vocabulary_items.append({
                'word': word.english_word,
                'translation': word.russian_word,
                'tags': tags,
                'frequency_rank': word.frequency_rank
            })

        export_data['vocabulary'] = vocabulary_items

    return jsonify(export_data)


# Управление прогрессом пользователей
@admin.route('/curriculum/progress/<int:progress_id>/details')
@admin_required
def progress_details(progress_id):
    """Детальная информация о прогрессе"""
    # Получаем запись о прогрессе
    progress = LessonProgress.query.get_or_404(progress_id)
    user = User.query.get(progress.user_id)
    lesson = Lessons.query.get(progress.lesson_id)
    module = Module.query.get(lesson.module_id)
    level = CEFRLevel.query.get(module.level_id)

    return render_template(
        'admin/curriculum/progress_details.html',
        progress=progress,
        user=user,
        lesson=lesson,
        module=module,
        level=level
    )


@admin.route('/curriculum/progress/<int:progress_id>/reset', methods=['POST'])
@admin_required
def reset_progress(progress_id):
    """Сброс прогресса пользователя"""
    progress = LessonProgress.query.get_or_404(progress_id)

    # Сбрасываем прогресс урока
    progress.status = 'not_started'
    progress.score = 0
    progress.completed_at = None
    progress.last_activity = datetime.utcnow()
    progress.data = {}

    db.session.commit()

    flash(_('Прогресс успешно сброшен!'), 'success')
    return redirect(url_for('admin.user_progress'))


@admin.route('/curriculum/progress/<int:progress_id>/delete', methods=['POST'])
@admin_required
def delete_progress(progress_id):
    """Удаление записи о прогрессе"""
    progress = LessonProgress.query.get_or_404(progress_id)

    # Удаляем запись о прогрессе
    db.session.delete(progress)
    db.session.commit()

    flash(_('Запись о прогрессе успешно удалена!'), 'success')
    return redirect(url_for('admin.user_progress'))


@admin.route('/curriculum/api/modules')
@admin_required
def api_get_modules():
    """API для получения модулей по уровню"""
    level_id = request.args.get('level_id', type=int)

    if not level_id:
        return jsonify([])

    modules = Module.query.filter_by(level_id=level_id).order_by(Module.number).all()

    return jsonify([
        {'id': module.id, 'number': module.number, 'title': module.title}
        for module in modules
    ])


@admin.route('/curriculum/api/lessons')
@admin_required
def api_get_lessons():
    """API для получения уроков по модулю"""
    module_id = request.args.get('module_id', type=int)

    if not module_id:
        return jsonify([])

    lessons = Lessons.query.filter_by(module_id=module_id).order_by(Lessons.number).all()

    return jsonify([
        {'id': lesson.id, 'number': lesson.number, 'title': lesson.title}
        for lesson in lessons
    ])
