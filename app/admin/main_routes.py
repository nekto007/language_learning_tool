# app/admin/routes.py

"""
Основной модуль административной панели для LLT English
"""
import json
import logging
import os
import subprocess
import uuid
from datetime import datetime, timedelta, timezone
from functools import wraps

from flask import Blueprint, flash, jsonify, redirect, render_template, request, session, url_for
from flask_babel import gettext as _
from flask_login import current_user, login_required
from sqlalchemy import desc, distinct, func

from app import csrf
from app.auth.models import User
from app.books.models import Book, Chapter
from app.curriculum.models import CEFRLevel, LessonProgress, Lessons, Module
from app.utils.db import db
from app.words.forms import CollectionForm, TopicForm
from app.words.models import Collection, CollectionWordLink, CollectionWords, Topic, TopicWord

admin = Blueprint('admin', __name__, url_prefix='/admin')

# Настройка логирования
logger = logging.getLogger(__name__)

# Директория для временных файлов импорта
IMPORT_TEMP_DIR = 'app/temp/import_translations'
os.makedirs(IMPORT_TEMP_DIR, exist_ok=True)


def save_import_data(data):
    """Сохраняет данные импорта во временный файл"""
    import_id = str(uuid.uuid4())
    file_path = os.path.join(IMPORT_TEMP_DIR, f"{import_id}.json")

    with open(file_path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    # Удаляем старые файлы (старше 1 часа)
    cleanup_old_imports()

    return import_id


def load_import_data(import_id):
    """Загружает данные импорта из временного файла"""
    file_path = os.path.join(IMPORT_TEMP_DIR, f"{import_id}.json")

    if not os.path.exists(file_path):
        return None

    with open(file_path, 'r', encoding='utf-8') as f:
        return json.load(f)


def delete_import_data(import_id):
    """Удаляет временный файл импорта"""
    file_path = os.path.join(IMPORT_TEMP_DIR, f"{import_id}.json")

    if os.path.exists(file_path):
        os.remove(file_path)


def cleanup_old_imports():
    """Удаляет старые файлы импорта"""
    current_time = datetime.now().timestamp()

    for filename in os.listdir(IMPORT_TEMP_DIR):
        if filename.endswith('.json'):
            file_path = os.path.join(IMPORT_TEMP_DIR, filename)
            file_time = os.path.getmtime(file_path)

            # Удаляем файлы старше 1 часа
            if current_time - file_time > 3600:
                os.remove(file_path)


# Простое in-memory кэширование для статистики
_cache = {}
_cache_timeout = 300  # 5 минут


def cache_result(key, timeout=_cache_timeout):
    """Декоратор для кэширования результатов функций"""

    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            cache_key = f"{key}_{hash(str(args) + str(kwargs))}"

            # Проверяем кэш
            if cache_key in _cache:
                cached_data, cached_time = _cache[cache_key]
                if (datetime.now(timezone.utc) - cached_time).seconds < timeout:
                    logger.debug(f"Cache hit for {cache_key}")
                    return cached_data

            # Выполняем функцию и кэшируем результат
            result = func(*args, **kwargs)
            _cache[cache_key] = (result, datetime.now(timezone.utc))
            logger.debug(f"Cache miss for {cache_key}, result cached")

            return result

        return wrapper

    return decorator


def clear_admin_cache():
    """Очищает административный кэш"""
    global _cache
    _cache.clear()
    logger.info("Admin cache cleared")


def handle_admin_errors(return_json=True):
    """Декоратор для обработки ошибок в админ операциях"""

    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            try:
                return func(*args, **kwargs)
            except Exception as e:
                logger.error(f"Error in {func.__name__}: {str(e)}", exc_info=True)

                # Откатываем изменения в базе данных
                try:
                    db.session.rollback()
                except:
                    pass

                if return_json:
                    return jsonify({
                        'success': False,
                        'error': f'Внутренняя ошибка сервера: {str(e)}',
                        'operation': func.__name__
                    }), 500
                else:
                    flash(f'Ошибка в операции {func.__name__}: {str(e)}', 'danger')
                    return redirect(url_for('admin.dashboard'))

        return wrapper

    return decorator


# Декоратор для проверки прав администратора
def admin_required(view_func):
    """Декоратор для проверки прав администратора"""

    def wrapped_view(*args, **kwargs):
        if not current_user.is_authenticated or not current_user.is_admin:
            flash('У вас нет прав для доступа к этой странице.', 'danger')
            return redirect(url_for('auth.login'))
        return view_func(*args, **kwargs)

    wrapped_view.__name__ = view_func.__name__
    return login_required(wrapped_view)


@cache_result('dashboard_stats', timeout=180)  # Кэш на 3 минуты
def get_dashboard_statistics():
    """Получает статистику для дашборда с кэшированием"""
    week_ago = datetime.now(timezone.utc) - timedelta(days=7)

    # Основная статистика пользователей
    total_users = User.query.count()
    active_users = User.query.filter_by(active=True).count()
    new_users = User.query.filter(User.created_at >= week_ago).count()
    active_recently = User.query.filter(User.last_login >= week_ago).count()

    # Статистика по книгам
    try:
        total_books = db.session.query(func.count(Book.id)).scalar() or 0
        total_readings = db.session.query(func.sum(Book.unique_words)).scalar() or 0
    except Exception as e:
        logger.warning(f"Error getting book statistics: {e}")
        total_books = 0
        total_readings = 0

    # Статистика по словам
    try:
        words_total = db.session.query(func.count(CollectionWords.id)).scalar() or 0
        words_with_audio = CollectionWords.query.filter_by(get_download=1).count()
    except Exception as e:
        logger.warning(f"Error getting word statistics: {e}")
        words_total = 0
        words_with_audio = 0

    # Статистика по учебной программе
    try:
        total_lessons = Lessons.query.count()
        active_lessons = db.session.query(func.count(distinct(LessonProgress.lesson_id))).scalar() or 0
    except Exception as e:
        logger.warning(f"Error getting curriculum statistics: {e}")
        total_lessons = 0
        active_lessons = 0

    return {
        'total_users': total_users,
        'active_users': active_users,
        'new_users': new_users,
        'active_recently': active_recently,
        'total_books': total_books,
        'total_readings': total_readings,
        'words_total': words_total,
        'words_with_audio': words_with_audio,
        'total_lessons': total_lessons,
        'active_lessons': active_lessons
    }


@admin.route('/')
@admin_required
def dashboard():
    """Главная страница административной панели"""
    # Получаем кэшированную статистику
    stats = get_dashboard_statistics()

    # Последние пользователи не кэшируем, так как они часто меняются
    recent_users = User.query.order_by(desc(User.created_at)).limit(10).all()

    return render_template(
        'admin/dashboard.html',
        recent_users=recent_users,
        **stats
    )



@admin.route('/curriculum')
@admin_required
def curriculum():
    """Управление структурой курсов"""
    levels = CEFRLevel.query.order_by(CEFRLevel.order).all()

    # Получаем список последних уроков для быстрого доступа
    recent_lessons = Lessons.query.order_by(Lessons.created_at.desc()).limit(10).all()

    # Получаем количество уникальных пользователей с прогрессом
    user_progress_count = db.session.query(func.count(distinct(LessonProgress.user_id))).scalar() or 0

    return render_template(
        'admin/curriculum/index.html',
        levels=levels,
        recent_lessons=recent_lessons,
        user_progress_count=user_progress_count
    )


@admin.route('/curriculum/levels')
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


@admin.route('/curriculum/modules')
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


@admin.route('/curriculum/lessons')
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


@admin.route('/curriculum/progress')
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


@admin.route('/curriculum/import', methods=['GET', 'POST'])
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
                return redirect(url_for('admin.import_curriculum'))

            try:
                json_text = file.read().decode('utf-8')
                json_data = json.loads(json_text)
            except Exception as e:
                flash(f'Ошибка при чтении файла: {str(e)}', 'danger')
                return redirect(url_for('admin.import_curriculum'))
        elif request.form.get('json_text'):
            # Получаем JSON из текстового поля
            try:
                json_data = json.loads(request.form.get('json_text'))
            except Exception as e:
                flash(f'Ошибка в формате JSON: {str(e)}', 'danger')
                return redirect(url_for('admin.import_curriculum'))

        if json_data:
            # Выполняем импорт
            try:
                result = import_curriculum_data(json_data)
                flash(f'Материал успешно импортирован! Создан урок ID: {result["lesson_id"]}', 'success')

                # Перенаправляем на страницу списка уроков модуля
                module = Module.query.get(result["module_id"])
                if module:
                    return redirect(url_for('admin.lesson_list', module_id=module.id))
                else:
                    return redirect(url_for('admin.curriculum'))
            except Exception as e:
                logger.error(f'Ошибка при импорте: {str(e)}', exc_info=True)
                flash(f'Ошибка при импорте: {str(e)}', 'danger')
                return redirect(url_for('admin.import_curriculum'))

    return render_template('admin/curriculum/import.html')


# Вспомогательные функции
def import_curriculum_data(data):
    """
    Импортирует данные курса из JSON

    Args:
        data (dict): JSON-структура курса

    Returns:
        dict: Информация о созданных объектах
    """
    logger.info("Начинаем импорт данных курса из JSON")

    # Проверяем наличие обязательных полей
    if 'level' not in data or 'module' not in data:
        raise ValueError("В JSON отсутствуют обязательные поля 'level' и 'module'")

    # 1. Создаем или находим уровень CEFR
    level_code = data['level']
    level = CEFRLevel.query.filter_by(code=level_code).first()

    if not level:
        # Создаем новый уровень
        level_name = get_level_name(level_code)
        level = CEFRLevel(
            code=level_code,
            name=level_name,
            description=f"Level {level_code}",
            order=get_level_order(level_code)
        )
        db.session.add(level)
        db.session.flush()
        logger.info(f"Создан новый уровень: {level.code}")

    # 2. Создаем или находим модуль
    module_number = data['module']
    module_description = data.get('description', '')
    module = Module.query.filter_by(level_id=level.id, number=module_number).first()

    if not module:
        # Создаем новый модуль
        module_title = data.get('title', f"Module {module_number}")
        module = Module(
            level_id=level.id,
            number=module_number,
            title=module_title,
            description=module_description,
            raw_content=data
        )
        db.session.add(module)
        db.session.flush()
        logger.info(f"Создан новый модуль: {module.number}")
    else:
        # Обновляем существующий модуль
        module.raw_content = data
        if data.get('title'):
            module.title = data.get('title')
        if module_description:
            module.description = module_description

    # 3. Создаём уроки из списка data['lessons']
    for lesson_data in data.get('lessons', []):
        number = lesson_data['lesson_number']
        lesson_type = lesson_data['lesson_type']
        title = lesson_data.get('title', '')
        lesson = Lessons.query.filter_by(module_id=module.id, number=number).first()
        if not lesson:
            lesson = Lessons(
                module_id=module.id,
                number=number,
                title=title,
                type=lesson_type if lesson_type != 'text' else 'text',
                order=number,
                description=title
            )
            db.session.add(lesson)
            db.session.flush()
        # Обрабатываем контент по типу урока
        if lesson_type == 'grammar':
            theory = lesson_data.get('theory', {})

            grammar_input = {
                'rule': theory.get('rule', ''),
                'description': theory.get('description', ''),
                'examples': theory.get('examples', []),
                'exercises': lesson_data.get('exercises', [])
            }
            lesson.content = process_grammar(grammar_input)
        elif lesson_type == 'vocabulary':
            vocab_list = lesson_data.get('words', [])
            # Создаем или получаем коллекцию
            collection_name = f"{module.title} - {level_code} Module {module_number} Vocabulary"
            collection = Collection.query.filter_by(name=collection_name).first()
            if not collection:
                collection = Collection(
                    name=collection_name,
                    description=module.title,
                    created_by=current_user.id
                )
                db.session.add(collection)
                db.session.flush()
            # Очищаем старые связи и обрабатываем слова
            CollectionWordLink.query.filter_by(collection_id=collection.id).delete()
            process_vocabulary(vocab_list, collection, level_code)
            lesson.collection_id = collection.id
            lesson.content = vocab_list
        elif lesson_type == 'card':
            lesson.content = {
                'settings': lesson_data.get('settings', {}),
                'cards': lesson_data.get('cards', []),
                'note': lesson_data.get('note', '')
            }
        elif lesson_type == 'quiz':
            lesson.content = {'exercises': lesson_data.get('exercises', [])}
        elif lesson_type == 'text':
            lesson.content = lesson_data.get('content', {})
        elif lesson_type == 'final_test':
            lesson.content = {
                'passing_score_percent': lesson_data.get('passing_score_percent', 0),
                'exercises': lesson_data.get('exercises', [])
            }
        else:
            lesson.content = lesson_data

    # 4. Сохраняем все изменения
    db.session.commit()

    # Возвращаем результат
    # Определяем id первого урока, если есть
    first_lesson = Lessons.query.filter_by(module_id=module.id).order_by(Lessons.order).first()
    first_lesson_id = first_lesson.id if first_lesson else None

    result = {
        "level_id": level.id,
        "module_id": module.id,
        "lesson_id": first_lesson_id
    }

    logger.info("Импорт завершен успешно.")
    return result


def process_vocabulary(vocabulary_data, collection, level_code):
    """Обрабатывает словарь без тегов"""
    for word_data in vocabulary_data:
        english_word = word_data['word'].lower()
        translation = word_data['translation']
        # Find or create the word
        word = CollectionWords.query.filter_by(english_word=english_word).first()
        if not word:
            word = CollectionWords(
                english_word=english_word,
                russian_word=translation,
                level=level_code,
                frequency_rank=word_data.get('frequency_rank', 0)
            )
            db.session.add(word)
            db.session.flush()
        else:
            # Update translation or rank if provided
            if word_data.get('frequency_rank'):
                word.frequency_rank = word_data['frequency_rank']
            word.russian_word = translation

        # Link the word to the collection
        existing = CollectionWordLink.query.filter_by(collection_id=collection.id, word_id=word.id).first()
        if not existing:
            link = CollectionWordLink(collection_id=collection.id, word_id=word.id)
            db.session.add(link)


def process_grammar(grammar_data):
    """Преобразует грамматические данные в формат для хранения"""
    exercises = []

    if 'exercises' in grammar_data:
        for exercise in grammar_data['exercises']:
            exercise_type = exercise.get('type')

            exercise_data = {
                'type': exercise_type,
                'text': exercise.get('prompt', ''),
                'explanation': exercise.get('explanation', '')
            }

            if exercise_type == 'fill_in_blank':
                exercise_data['answer'] = exercise.get('correct_answer', [])
                if exercise.get('alternative_answers'):
                    exercise_data['alternative_answers'] = exercise.get('alternative_answers', [])
            elif exercise_type == 'multiple_choice':
                exercise_data['options'] = exercise.get('options', [])
                exercise_data['question'] = exercise.get('question', '')
                exercise_data['answer'] = exercise.get('correct_index')
            elif exercise_type == 'true_false':
                exercise_data['question'] = exercise.get('question', '')
                exercise_data['answer'] = exercise.get('correct_answer')
            elif exercise_type == 'match':
                exercise_data['pairs'] = exercise.get('pairs', [])
            elif exercise_type == 'reorder':
                exercise_data['words'] = exercise.get('words', [])
                exercise_data['answer'] = exercise.get('correct_answer', '')
            elif exercise_type == 'translation':
                exercise_data['answer'] = exercise.get('correct_answer', '')
                exercise_data['alternative_answers'] = exercise.get('alternative_answers', [])
            else:
                # Для других типов сохраняем как есть
                exercise_data['answer'] = exercise.get('answer', '')

            exercises.append(exercise_data)

    return {
        'rule': grammar_data.get('rule', ''),
        'description': grammar_data.get('description', ''),
        'examples': grammar_data.get('examples', []),
        'exercises': exercises
    }


def get_level_name(level_code):
    """Возвращает название для кода уровня CEFR"""
    level_names = {
        'A0': 'Pre-Beginner',
        'A1': 'Beginner',
        'A2': 'Elementary',
        'B1': 'Intermediate',
        'B2': 'Upper Intermediate',
        'C1': 'Advanced',
        'C2': 'Proficiency'
    }
    return level_names.get(level_code, f'Level {level_code}')


def get_level_order(level_code):
    """Возвращает порядок для уровня CEFR"""
    level_orders = {
        'A0': 0,
        'A1': 1,
        'A2': 2,
        'B1': 3,
        'B2': 4,
        'C1': 5,
        'C2': 6
    }
    return level_orders.get(level_code, 99)


# Функции экспорта слов

def export_words_json(words, status=None):
    """Экспорт слов в формате JSON"""
    from flask import make_response
    import json

    words_data = []
    for word in words:
        word_dict = {
            'english_word': word.english_word,
            'russian_word': word.russian_word,
            'level': word.level if hasattr(word, 'level') else None
        }
        if hasattr(word, 'status'):
            word_dict['status'] = word.status
        words_data.append(word_dict)

    response_data = {
        'export_date': datetime.now(timezone.utc).isoformat(),
        'words_total': len(words_data),
        'status_filter': status,
        'words': words_data
    }

    response = make_response(json.dumps(response_data, ensure_ascii=False, indent=2))
    response.headers['Content-Type'] = 'application/json; charset=utf-8'
    filename = f"words_export_{status or 'all'}_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.json"
    response.headers['Content-Disposition'] = f'attachment; filename={filename}'

    return response


def export_words_csv(words, status=None):
    """Экспорт слов в формате CSV"""
    from flask import make_response
    import csv
    import io

    output = io.StringIO()
    writer = csv.writer(output)

    # Заголовки
    headers = ['English', 'Russian', 'Level']
    if words and hasattr(words[0], 'status'):
        headers.append('Status')
    writer.writerow(headers)

    # Данные
    for word in words:
        row = [word.english_word, word.russian_word, word.level if hasattr(word, 'level') else '']
        if hasattr(word, 'status'):
            row.append(word.status)
        writer.writerow(row)

    response = make_response(output.getvalue())
    response.headers['Content-Type'] = 'text/csv; charset=utf-8'
    filename = f"words_export_{status or 'all'}_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.csv"
    response.headers['Content-Disposition'] = f'attachment; filename={filename}'

    return response


def export_words_txt(words, status=None):
    """Экспорт слов в текстовом формате"""
    from flask import make_response

    lines = [f"# Words Export - {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')}"]
    if status:
        lines.append(f"# Status filter: {status}")
    lines.append(f"# Total words: {len(words)}")
    lines.append("")

    for word in words:
        if hasattr(word, 'status'):
            lines.append(f"{word.english_word} | {word.russian_word} | {word.status}")
        else:
            lines.append(f"{word.english_word} | {word.russian_word}")

    content = '\n'.join(lines)
    response = make_response(content)
    response.headers['Content-Type'] = 'text/plain; charset=utf-8'
    filename = f"words_export_{status or 'all'}_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.txt"
    response.headers['Content-Disposition'] = f'attachment; filename={filename}'

    return response


try:
    from . import curriculum
except ImportError:
    logger.warning("Не удалось импортировать модуль curriculum")
