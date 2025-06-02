# app/admin/routes.py

"""
Основной модуль административной панели для LLT English
"""
import json
import logging
import os
from datetime import datetime, timedelta
from functools import wraps

from flask import Blueprint, flash, jsonify, redirect, render_template, request, url_for
from flask_babel import gettext as _
from flask_login import current_user, login_required
from sqlalchemy import desc, distinct, func

from app import csrf
from app.auth.models import User
from app.books.models import Book
from app.curriculum.models import CEFRLevel, LessonProgress, Lessons, Module
from app.utils.db import db
from app.words.forms import CollectionForm, TopicForm
from app.words.models import Collection, CollectionWordLink, CollectionWords, Topic, TopicWord

admin = Blueprint('admin', __name__, url_prefix='/admin')

# Настройка логирования
logger = logging.getLogger(__name__)

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
                if (datetime.utcnow() - cached_time).seconds < timeout:
                    logger.debug(f"Cache hit for {cache_key}")
                    return cached_data

            # Выполняем функцию и кэшируем результат
            result = func(*args, **kwargs)
            _cache[cache_key] = (result, datetime.utcnow())
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
    week_ago = datetime.utcnow() - timedelta(days=7)

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
        total_words = db.session.query(func.count(CollectionWords.id)).scalar() or 0
        words_with_audio = CollectionWords.query.filter_by(get_download=1).count()
    except Exception as e:
        logger.warning(f"Error getting word statistics: {e}")
        total_words = 0
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
        'total_words': total_words,
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


@admin.route('/users')
@admin_required
def users():
    """Управление пользователями"""
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 20, type=int)
    search = request.args.get('search', '')

    # Построение запроса с учетом поиска
    query = User.query

    if search:
        query = query.filter(
            (User.username.ilike(f'%{search}%')) |
            (User.email.ilike(f'%{search}%'))
        )

    # Пагинация
    pagination = query.order_by(desc(User.last_login)).paginate(
        page=page, per_page=per_page, error_out=False
    )

    users = pagination.items
    now = datetime.utcnow()

    return render_template(
        'admin/users.html',
        users=users,
        pagination=pagination,
        search=search,
        now=now
    )


@admin.route('/users/<int:user_id>/toggle_status', methods=['POST'])
@admin_required
def toggle_user_status(user_id):
    """Активация/деактивация пользователя"""
    user = User.query.get_or_404(user_id)
    user.active = not user.active
    db.session.commit()

    status = "активирован" if user.active else "деактивирован"
    flash(f'Пользователь {user.username} успешно {status}.', 'success')

    return redirect(url_for('admin.users'))


@admin.route('/users/<int:user_id>/toggle_admin', methods=['POST'])
@admin_required
def toggle_admin_status(user_id):
    """Предоставление/отзыв прав администратора"""
    if current_user.id == user_id:
        flash('Вы не можете изменить свои собственные права администратора.', 'danger')
        return redirect(url_for('admin.users'))

    user = User.query.get_or_404(user_id)
    user.is_admin = not user.is_admin
    db.session.commit()

    status = "предоставлены" if user.is_admin else "отозваны"
    flash(f'Права администратора для пользователя {user.username} успешно {status}.', 'success')

    return redirect(url_for('admin.users'))


@admin.route('/stats')
@admin_required
def stats():
    """Статистика приложения"""
    # Данные по регистрациям пользователей по дням за последний месяц
    month_ago = datetime.utcnow() - timedelta(days=30)
    user_registrations = db.session.query(
        func.date(User.created_at).label('date'),
        func.count(User.id).label('count')
    ).filter(User.created_at >= month_ago).group_by(func.date(User.created_at)).all()

    # Для графика активности пользователей
    user_logins = db.session.query(
        func.date(User.last_login).label('date'),
        func.count(User.id).label('count')
    ).filter(User.last_login >= month_ago).group_by(func.date(User.last_login)).all()

    # Активность по часам суток
    user_activity_by_hour = db.session.query(
        func.extract('hour', User.last_login).label('hour'),
        func.count(User.id).label('count')
    ).filter(User.last_login >= month_ago).group_by('hour').all()

    return render_template(
        'admin/stats.html',
        user_registrations=user_registrations,
        user_logins=user_logins,
        user_activity_by_hour=user_activity_by_hour
    )


@admin.route('/system/clear-cache', methods=['POST'])
@admin_required
def clear_cache():
    """Очистка административного кэша"""
    try:
        clear_admin_cache()
        flash('Кэш успешно очищен', 'success')
        logger.info(f"Cache cleared by admin user {current_user.username}")
    except Exception as e:
        logger.error(f"Error clearing cache: {str(e)}")
        flash(f'Ошибка при очистке кэша: {str(e)}', 'danger')

    return redirect(url_for('admin.system'))


@admin.route('/system')
@admin_required
def system():
    """Информация о системе"""
    import platform
    import psutil
    import os
    from flask import current_app

    # Get system information
    system_info = {
        'platform': platform.platform(),
        'python_version': platform.python_version(),
        'flask_version': '2.x',  # You can get actual version from flask.__version__
        'cpu_count': psutil.cpu_count(),
        'cpu_percent': psutil.cpu_percent(interval=1),
        'memory': {
            'total': psutil.virtual_memory().total // (1024 * 1024),  # MB
            'available': psutil.virtual_memory().available // (1024 * 1024),  # MB
            'used': psutil.virtual_memory().used // (1024 * 1024),  # MB
            'percent': psutil.virtual_memory().percent
        },
        'disk': {
            'total': psutil.disk_usage('/').total // (1024 * 1024 * 1024),  # GB
            'used': psutil.disk_usage('/').used // (1024 * 1024 * 1024),  # GB
            'free': psutil.disk_usage('/').free // (1024 * 1024 * 1024),  # GB
            'percent': psutil.disk_usage('/').percent
        }
    }

    # Database statistics
    db_stats = {
        'users': User.query.count(),
        'books': Book.query.count(),
        'words': CollectionWords.query.count(),
        'topics': Topic.query.count(),
        'collections': Collection.query.count(),
        'levels': CEFRLevel.query.count(),
        'modules': Module.query.count(),
        'lessons': Lessons.query.count()
    }

    # Application info
    app_info = {
        'debug': current_app.debug,
        'environment': os.environ.get('FLASK_ENV', 'production'),
        'database_url': current_app.config.get('SQLALCHEMY_DATABASE_URI', '').split('@')[
            -1] if '@' in current_app.config.get('SQLALCHEMY_DATABASE_URI', '') else 'Local SQLite'
    }

    return render_template(
        'admin/system.html',
        system_info=system_info,
        db_stats=db_stats,
        app_info=app_info
    )


@admin.route('/system/database')
@admin_required
def database_management():
    """Управление базой данных"""
    try:
        # Проверка подключения к БД
        db_connection_status = test_database_connection()

        # Статистика по пользовательским словам
        word_stats = get_word_status_statistics()

        # Статистика по книгам
        book_stats = get_book_statistics()

        # Недавние операции с БД (из логов, если доступны)
        recent_operations = get_recent_db_operations()

    except Exception as e:
        logger.error(f"Error getting database info: {str(e)}")
        flash(f'Ошибка при получении информации о БД: {str(e)}', 'danger')
        db_connection_status = {'status': 'error', 'message': str(e)}
        word_stats = {}
        book_stats = {}
        recent_operations = []

    return render_template(
        'admin/database.html',
        db_connection_status=db_connection_status,
        word_stats=word_stats,
        book_stats=book_stats,
        recent_operations=recent_operations
    )


@admin.route('/system/database/init', methods=['POST'])
@admin_required
def init_database():
    """Инициализация базы данных"""
    try:
        from app.utils.db_init import init_db
        init_db()
        flash('База данных успешно инициализирована!', 'success')
        logger.info(f"Database initialized by admin user {current_user.username}")
    except Exception as e:
        logger.error(f"Error initializing database: {str(e)}")
        flash(f'Ошибка при инициализации БД: {str(e)}', 'danger')

    return redirect(url_for('admin.database_management'))


@admin.route('/system/database/test-connection')
@admin_required
def test_db_connection():
    """Тест подключения к базе данных"""
    try:
        result = test_database_connection()
        return jsonify(result)
    except Exception as e:
        logger.error(f"Database connection test failed: {str(e)}")
        return jsonify({
            'status': 'error',
            'message': f'Ошибка подключения: {str(e)}'
        }), 500


# =============================================================================
# ГРУППА 2: Управление словами
# =============================================================================

@admin.route('/words')
@admin_required
def word_management():
    """Главная страница управления словами"""
    try:
        # Общая статистика по словам
        total_words = CollectionWords.query.count()

        # Статистика по статусам пользователей
        from app.study.models import UserWord
        status_stats = db.session.query(
            UserWord.status,
            func.count(UserWord.id).label('count')
        ).group_by(UserWord.status).all()

        # Недавно добавленные слова
        recent_words = CollectionWords.query.order_by(
            CollectionWords.id.desc()
        ).limit(10).all()

        # Слова без переводов
        words_without_translation = CollectionWords.query.filter(
            (CollectionWords.russian_word == None) |
            (CollectionWords.russian_word == '')
        ).count()

        return render_template(
            'admin/words/index.html',
            total_words=total_words,
            status_stats=status_stats,
            recent_words=recent_words,
            words_without_translation=words_without_translation
        )
    except Exception as e:
        logger.error(f"Error in word management: {str(e)}")
        flash(f'Ошибка при загрузке данных: {str(e)}', 'danger')
        return redirect(url_for('admin.dashboard'))


@admin.route('/words/bulk-status-update', methods=['GET', 'POST'])
@admin_required
@handle_admin_errors(return_json=False)
def bulk_status_update():
    """Массовое обновление статусов слов"""
    if request.method == 'POST':
        try:
            data = request.get_json()
            words = data.get('words', [])  # Список английских слов
            status = data.get('status')  # Новый статус
            user_id = data.get('user_id')  # ID пользователя (опционально)

            if not words or not status:
                return jsonify({
                    'success': False,
                    'error': 'Требуются words и status'
                }), 400

            # Если не указан пользователь, обновляем для всех активных пользователей
            if not user_id:
                active_users = User.query.filter_by(active=True).all()
                user_ids = [user.id for user in active_users]
            else:
                user_ids = [user_id]

            updated_count = 0

            for word_text in words:
                # Найти слово в базе
                word = CollectionWords.query.filter_by(
                    english_word=word_text.lower().strip()
                ).first()

                if word:
                    for uid in user_ids:
                        user = User.query.get(uid)
                        if user:
                            user.set_word_status(word.id, status)
                            updated_count += 1

            db.session.commit()

            # Очищаем кэш после массового обновления
            clear_admin_cache()

            return jsonify({
                'success': True,
                'updated_count': updated_count,
                'total_requested': len(words) * len(user_ids)
            })

        except Exception as e:
            logger.error(f"Error in bulk status update: {str(e)}")
            db.session.rollback()
            return jsonify({
                'success': False,
                'error': str(e)
            }), 500

    # GET запрос - показать форму
    users = User.query.filter_by(active=True).all()
    return render_template('admin/words/bulk_status_update.html', users=users)


@admin.route('/words/export')
@admin_required
def export_words():
    """Экспорт слов по различным критериям"""
    status = request.args.get('status')
    format_type = request.args.get('format', 'json')  # json, csv, txt
    user_id = request.args.get('user_id', type=int)

    try:
        if status and user_id:
            # Экспорт слов конкретного пользователя по статусу
            from app.study.models import UserWord
            words_query = db.session.query(
                CollectionWords.english_word,
                CollectionWords.russian_word,
                CollectionWords.level,
                UserWord.status
            ).join(
                UserWord, CollectionWords.id == UserWord.word_id
            ).filter(
                UserWord.user_id == user_id,
                UserWord.status == status
            )
        elif status:
            # Экспорт всех слов по статусу (любых пользователей)
            from app.study.models import UserWord
            words_query = db.session.query(
                CollectionWords.english_word,
                CollectionWords.russian_word,
                CollectionWords.level,
                UserWord.status
            ).join(
                UserWord, CollectionWords.id == UserWord.word_id
            ).filter(UserWord.status == status).distinct()
        else:
            # Экспорт всех слов
            words_query = db.session.query(
                CollectionWords.english_word,
                CollectionWords.russian_word,
                CollectionWords.level
            )

        words = words_query.all()

        if format_type == 'json':
            return export_words_json(words, status)
        elif format_type == 'csv':
            return export_words_csv(words, status)
        elif format_type == 'txt':
            return export_words_txt(words, status)
        else:
            flash('Неподдерживаемый формат экспорта', 'danger')
            return redirect(url_for('admin.word_management'))

    except Exception as e:
        logger.error(f"Error exporting words: {str(e)}")
        flash(f'Ошибка при экспорте: {str(e)}', 'danger')
        return redirect(url_for('admin.word_management'))


@admin.route('/words/import-translations', methods=['GET', 'POST'])
@admin_required
def import_translations():
    """Импорт переводов из файла"""
    if request.method == 'POST':
        try:
            # Проверяем, был ли загружен файл
            if 'translation_file' not in request.files:
                flash('Файл не выбран', 'danger')
                return redirect(request.url)

            file = request.files['translation_file']
            if file.filename == '':
                flash('Файл не выбран', 'danger')
                return redirect(request.url)

            # Читаем содержимое файла
            content = file.read().decode('utf-8')
            lines = content.strip().split('\n')

            updated_count = 0
            errors = []

            for line_num, line in enumerate(lines, 1):
                line = line.strip()
                if not line or line.startswith('#'):  # Пропускаем пустые строки и комментарии
                    continue

                # Ожидаем формат: english_word;russian_translate;english_sentence;russian_sentence;level
                parts = line.split(';')
                if len(parts) != 5:
                    errors.append(f'Строка {line_num}: неверный формат "{line}" (ожидается 5 частей через ;)')
                    continue

                english_word = parts[0].strip().lower()
                russian_translate = parts[1].strip()
                english_sentence = parts[2].strip()
                russian_sentence = parts[3].strip()
                level = parts[4].strip()

                # Найти слово в базе
                word = CollectionWords.query.filter_by(english_word=english_word).first()
                if word:
                    # Обновляем поля согласно новому формату
                    word.russian_word = russian_translate
                    word.sentences = f"{english_sentence}<br>{russian_sentence}"
                    word.level = level
                    word.listening = f"[sound:pronunciation_en_{english_word.replace(' ', '_').lower()}.mp3]"
                    updated_count += 1
                else:
                    errors.append(f'Строка {line_num}: слово "{english_word}" не найдено в базе')

            db.session.commit()

            if updated_count > 0:
                flash(f'Успешно обновлено переводов: {updated_count}', 'success')

            if errors:
                flash(f'Ошибки ({len(errors)}): ' + '; '.join(errors[:5]), 'warning')

            logger.info(
                f"Translations import completed by {current_user.username}: {updated_count} updated, {len(errors)} errors")

        except Exception as e:
            logger.error(f"Error importing translations: {str(e)}")
            db.session.rollback()
            flash(f'Ошибка при импорте: {str(e)}', 'danger')

    return render_template('admin/words/import_translations.html')


@admin.route('/words/statistics')
@admin_required
def word_statistics():
    """Детальная статистика по словам"""
    try:
        # Получаем статистику, аналогично main.py show_status_statistics
        from app.study.models import UserWord

        # Статистика по статусам
        status_stats = db.session.query(
            UserWord.status,
            func.count(UserWord.id).label('count'),
            func.count(func.distinct(UserWord.user_id)).label('users')
        ).group_by(UserWord.status).all()

        # Статистика по уровням
        level_stats = db.session.query(
            CollectionWords.level,
            func.count(CollectionWords.id).label('count')
        ).group_by(CollectionWords.level).all()

        # Топ пользователей по количеству изучаемых слов
        top_users = db.session.query(
            User.username,
            func.count(UserWord.id).label('word_count')
        ).join(
            UserWord, User.id == UserWord.user_id
        ).group_by(
            User.id, User.username
        ).order_by(
            func.count(UserWord.id).desc()
        ).limit(10).all()

        # Статистика по книгам
        book_stats = db.session.query(
            Book.title,
            Book.total_words,
            Book.unique_words
        ).order_by(Book.total_words.desc()).limit(10).all()

        return render_template(
            'admin/words/statistics.html',
            status_stats=status_stats,
            level_stats=level_stats,
            top_users=top_users,
            book_stats=book_stats
        )
    except Exception as e:
        logger.error(f"Error getting word statistics: {str(e)}")
        flash(f'Ошибка при получении статистики: {str(e)}', 'danger')
        return redirect(url_for('admin.word_management'))


@admin.route('/topics')
@login_required
@admin_required
def topic_list():
    """Отображение списка всех тем"""
    topics = Topic.query.order_by(Topic.name).all()

    # Количество слов вычисляется автоматически через гибридное свойство

    return render_template('admin/topics/list.html', topics=topics)


@admin.route('/topics/create', methods=['GET', 'POST'])
@login_required
@admin_required
def create_topic():
    """Создание новой темы"""
    form = TopicForm()

    if form.validate_on_submit():
        topic = Topic(
            name=form.name.data,
            description=form.description.data
        )
        db.session.add(topic)
        db.session.commit()

        flash(_('Topic created successfully!'), 'success')
        return redirect(url_for('admin.topic_list'))

    return render_template('admin/topics/form.html', form=form, title=_('Create Topic'))


@admin.route('/topics/<int:topic_id>/edit', methods=['GET', 'POST'])
@login_required
@admin_required
def edit_topic(topic_id):
    """Редактирование темы"""
    topic = Topic.query.get_or_404(topic_id)
    form = TopicForm(obj=topic)

    if form.validate_on_submit():
        form.populate_obj(topic)
        db.session.commit()

        flash(_('Topic updated successfully!'), 'success')
        return redirect(url_for('admin.topic_list'))

    return render_template('admin/topics/form.html', form=form, topic=topic, title=_('Edit Topic'))


@admin.route('/topics/<int:topic_id>/delete', methods=['POST'])
@login_required
@admin_required
def delete_topic(topic_id):
    """Удаление темы"""
    topic = Topic.query.get_or_404(topic_id)
    db.session.delete(topic)
    db.session.commit()

    flash(_('Topic deleted successfully!'), 'success')
    return redirect(url_for('admin.topic_list'))


@admin.route('/topics/<int:topic_id>/words')
@login_required
@admin_required
def topic_words(topic_id):
    """Управление словами в теме"""
    topic = Topic.query.get_or_404(topic_id)

    # Получаем слова, которые уже в теме
    topic_words = topic.words

    # Получаем слова, которые можно добавить в тему
    available_words = CollectionWords.query.filter(
        ~CollectionWords.id.in_([w.id for w in topic_words])
    ).order_by(CollectionWords.english_word).all()

    return render_template(
        'admin/topics/words.html',
        topic=topic,
        topic_words=topic_words,
        available_words=available_words
    )


@admin.route('/topics/<int:topic_id>/add_word/<int:word_id>', methods=['POST'])
@login_required
@admin_required
def add_word_to_topic(topic_id, word_id):
    """API для добавления слова в тему"""
    topic = Topic.query.get_or_404(topic_id)
    word = CollectionWords.query.get_or_404(word_id)

    # Проверяем, не добавлено ли уже слово в тему
    if word not in topic.words:
        topic_word = TopicWord(topic_id=topic_id, word_id=word_id)
        db.session.add(topic_word)
        db.session.commit()
        return jsonify({'success': True})

    return jsonify({'success': False, 'message': _('Word already in topic')})


@admin.route('/topics/<int:topic_id>/remove_word/<int:word_id>', methods=['POST'])
@login_required
@admin_required
def remove_word_from_topic(topic_id, word_id):
    """API для удаления слова из темы"""
    topic_word = TopicWord.query.filter_by(topic_id=topic_id, word_id=word_id).first_or_404()

    db.session.delete(topic_word)
    db.session.commit()

    return jsonify({'success': True})


# Маршруты для управления коллекциями (Collections)
@admin.route('/collections')
@login_required
@admin_required
def collection_list():
    """Отображение списка всех коллекций"""
    collections = Collection.query.order_by(Collection.name).all()

    # Для каждой коллекции получаем создателя
    for collection in collections:
        collection.creator_name = collection.creator.username if collection.creator else "Admin"

    return render_template('admin/collections/list.html', collections=collections)


@admin.route('/collections/create', methods=['GET', 'POST'])
@login_required
@admin_required
def create_collection():
    """Создание новой коллекции"""
    form = CollectionForm()

    if form.validate_on_submit():
        collection = Collection(
            name=form.name.data,
            description=form.description.data,
            created_by=current_user.id
        )
        db.session.add(collection)
        db.session.flush()  # Чтобы получить id коллекции

        # Добавляем слова в коллекцию
        if form.word_ids.data:
            word_ids = [int(word_id) for word_id in form.word_ids.data.split(',')]
            for word_id in word_ids:
                link = CollectionWordLink(collection_id=collection.id, word_id=word_id)
                db.session.add(link)

        db.session.commit()

        flash(_('Collection created successfully!'), 'success')
        return redirect(url_for('admin.collection_list'))

    # Получаем все темы для селектора
    topics = Topic.query.order_by(Topic.name).all()

    return render_template(
        'admin/collections/form.html',
        form=form,
        topics=topics,
        title=_('Create Collection')
    )


@admin.route('/collections/<int:collection_id>/edit', methods=['GET', 'POST'])
@login_required
@admin_required
def edit_collection(collection_id):
    """Редактирование коллекции"""
    collection = Collection.query.get_or_404(collection_id)
    form = CollectionForm(obj=collection)

    if form.validate_on_submit():
        # Обновляем основную информацию
        collection.name = form.name.data
        collection.description = form.description.data

        # Обновляем слова в коллекции
        if form.word_ids.data:
            # Удаляем все текущие связи
            CollectionWordLink.query.filter_by(collection_id=collection.id).delete()

            # Добавляем выбранные слова
            word_ids = [int(word_id) for word_id in form.word_ids.data.split(',')]
            for word_id in word_ids:
                link = CollectionWordLink(collection_id=collection.id, word_id=word_id)
                db.session.add(link)

        db.session.commit()

        flash(_('Collection updated successfully!'), 'success')
        return redirect(url_for('admin.collection_list'))

    # Предзаполняем form.word_ids значениями из коллекции
    current_word_ids = [str(word.id) for word in collection.words]
    form.word_ids.data = ','.join(current_word_ids)

    # Получаем все темы для селектора
    topics = Topic.query.order_by(Topic.name).all()

    return render_template(
        'admin/collections/form.html',
        form=form,
        collection=collection,
        topics=topics,
        title=_('Edit Collection')
    )


@admin.route('/collections/<int:collection_id>/delete', methods=['POST'])
@login_required
@admin_required
def delete_collection(collection_id):
    """Удаление коллекции"""
    collection = Collection.query.get_or_404(collection_id)
    db.session.delete(collection)
    db.session.commit()

    flash(_('Collection deleted successfully!'), 'success')
    return redirect(url_for('admin.collection_list'))


@admin.route('/api/get_words_by_topic')
@login_required
@admin_required
def get_words_by_topic():
    """API для получения слов по темам"""
    topic_ids = request.args.get('topic_ids', '')

    if not topic_ids:
        return jsonify([])

    topic_id_list = [int(topic_id) for topic_id in topic_ids.split(',')]

    # Получаем слова, связанные с выбранными темами
    words = db.session.query(CollectionWords).join(
        TopicWord, CollectionWords.id == TopicWord.word_id
    ).filter(
        TopicWord.topic_id.in_(topic_id_list)
    ).order_by(
        CollectionWords.english_word
    ).all()

    word_list = [{
        'id': word.id,
        'english_word': word.english_word,
        'russian_word': word.russian_word,
        'level': word.level
    } for word in words]

    return jsonify(word_list)


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


@csrf.exempt
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
            print('lesson_data.get(exercises)', lesson_data.get('exercises'))
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
            print(exercise_data)
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


# Вспомогательные функции для управления БД

def test_database_connection():
    """Тестирует подключение к базе данных"""
    try:
        from config.settings import DB_CONFIG
        from app.repository import DatabaseRepository

        repo = DatabaseRepository(DB_CONFIG)
        with repo.get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute("SELECT version()")
                version = cursor.fetchone()[0]

                # Дополнительные проверки
                cursor.execute("SELECT COUNT(*) FROM information_schema.tables WHERE table_schema = 'public'")
                table_count = cursor.fetchone()[0]

                cursor.execute("SELECT pg_size_pretty(pg_database_size(current_database()))")
                db_size = cursor.fetchone()[0]

        return {
            'status': 'success',
            'message': 'Подключение успешно',
            'version': version,
            'table_count': table_count,
            'database_size': db_size
        }
    except Exception as e:
        return {
            'status': 'error',
            'message': f'Ошибка подключения: {str(e)}'
        }


def get_word_status_statistics():
    """Получает статистику по статусам слов"""
    try:
        from app.study.models import UserWord

        # Статистика по всем пользователям
        status_stats = db.session.query(
            UserWord.status,
            func.count(UserWord.id).label('count'),
            func.count(func.distinct(UserWord.user_id)).label('users')
        ).group_by(UserWord.status).all()

        # Общая статистика
        total_user_words = UserWord.query.count()
        total_unique_words = db.session.query(func.count(func.distinct(UserWord.word_id))).scalar()
        total_users_with_words = db.session.query(func.count(func.distinct(UserWord.user_id))).scalar()

        return {
            'status_breakdown': [
                {
                    'status': stat.status,
                    'count': stat.count,
                    'users': stat.users,
                    'percentage': round((stat.count / total_user_words * 100), 1) if total_user_words > 0 else 0
                }
                for stat in status_stats
            ],
            'totals': {
                'total_user_words': total_user_words,
                'unique_words_tracked': total_unique_words,
                'users_with_words': total_users_with_words
            }
        }
    except Exception as e:
        logger.error(f"Error getting word statistics: {str(e)}")
        return {'error': str(e)}


def get_book_statistics():
    """Получает статистику по книгам"""
    try:
        # Топ-5 книг по количеству слов
        top_books = db.session.query(
            Book.title,
            Book.total_words,
            Book.unique_words
        ).order_by(Book.total_words.desc()).limit(5).all()

        # Общая статистика
        total_books = Book.query.count()
        total_words_all_books = db.session.query(func.sum(Book.total_words)).scalar() or 0
        total_unique_words_all = db.session.query(func.sum(Book.unique_words)).scalar() or 0

        return {
            'top_books': [
                {
                    'title': book.title,
                    'total_words': book.total_words,
                    'unique_words': book.unique_words
                }
                for book in top_books
            ],
            'totals': {
                'total_books': total_books,
                'total_words_all_books': total_words_all_books,
                'total_unique_words_all': total_unique_words_all
            }
        }
    except Exception as e:
        logger.error(f"Error getting book statistics: {str(e)}")
        return {'error': str(e)}


def get_recent_db_operations():
    """Получает список недавних операций с БД"""
    try:
        # Недавние уроки
        recent_lessons = Lessons.query.order_by(Lessons.created_at.desc()).limit(5).all()

        # Недавно зарегистрированные пользователи
        week_ago = datetime.utcnow() - timedelta(days=7)
        recent_users = User.query.filter(User.created_at >= week_ago).order_by(User.created_at.desc()).limit(5).all()

        return {
            'recent_lessons': [
                {
                    'title': lesson.title,
                    'type': lesson.type,
                    'created_at': lesson.created_at.strftime('%Y-%m-%d %H:%M') if lesson.created_at else 'N/A'
                }
                for lesson in recent_lessons
            ],
            'recent_users': [
                {
                    'username': user.username,
                    'created_at': user.created_at.strftime('%Y-%m-%d %H:%M') if user.created_at else 'N/A'
                }
                for user in recent_users
            ]
        }
    except Exception as e:
        logger.error(f"Error getting recent operations: {str(e)}")
        return {'error': str(e)}


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
        'export_date': datetime.utcnow().isoformat(),
        'total_words': len(words_data),
        'status_filter': status,
        'words': words_data
    }

    response = make_response(json.dumps(response_data, ensure_ascii=False, indent=2))
    response.headers['Content-Type'] = 'application/json; charset=utf-8'
    filename = f"words_export_{status or 'all'}_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.json"
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
    filename = f"words_export_{status or 'all'}_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.csv"
    response.headers['Content-Disposition'] = f'attachment; filename={filename}'

    return response


def export_words_txt(words, status=None):
    """Экспорт слов в текстовом формате"""
    from flask import make_response

    lines = [f"# Words Export - {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')}"]
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
    filename = f"words_export_{status or 'all'}_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.txt"
    response.headers['Content-Disposition'] = f'attachment; filename={filename}'

    return response


# =============================================================================
# ГРУППА 3: Управление книгами
# =============================================================================

@admin.route('/books')
@admin_required
def books():
    """Главная страница управления книгами"""
    try:
        # Статистика по книгам
        total_books = Book.query.count()

        # Книги с обработанными данными
        books_with_stats = Book.query.filter(
            Book.total_words.isnot(None),
            Book.total_words > 0
        ).count()

        # Книги без статистики
        books_without_stats = total_books - books_with_stats

        # Общая статистика слов во всех книгах
        total_words_all = db.session.query(func.sum(Book.total_words)).scalar() or 0
        unique_words_all = db.session.query(func.sum(Book.unique_words)).scalar() or 0

        # Недавно добавленные книги
        recent_books = Book.query.order_by(
            Book.scrape_date.desc().nullslast()
        ).limit(10).all()

        # Топ книг по количеству слов
        top_books = Book.query.filter(
            Book.total_words.isnot(None)
        ).order_by(Book.total_words.desc()).limit(5).all()

        return render_template(
            'admin/books/index.html',
            total_books=total_books,
            books_with_stats=books_with_stats,
            books_without_stats=books_without_stats,
            total_words_all=total_words_all,
            unique_words_all=unique_words_all,
            recent_books=recent_books,
            top_books=top_books
        )
    except Exception as e:
        logger.error(f"Error in book management: {str(e)}")
        flash(f'Ошибка при загрузке данных: {str(e)}', 'danger')
        return redirect(url_for('admin.dashboard'))


@admin.route('/books/scrape-website', methods=['POST'])
@admin_required
def scrape_website():
    """Web scraping для добавления новых книг"""
    try:
        data = request.get_json()
        url = data.get('url')
        max_pages = data.get('max_pages', 10)

        if not url:
            return jsonify({
                'success': False,
                'error': 'URL не указан'
            }), 400

        # Импортируем и используем web scraper
        from app.web.scraper import WebScraper
        from config.settings import USER_AGENT, REQUEST_TIMEOUT, MAX_RETRIES

        scraper = WebScraper(
            user_agent=USER_AGENT,
            timeout=REQUEST_TIMEOUT,
            max_retries=MAX_RETRIES
        )

        # Запускаем scraping
        results = scraper.scrape_website(url, max_pages)

        logger.info(f"Website scraping completed by {current_user.username}: {len(results)} books processed")

        return jsonify({
            'success': True,
            'scraped_count': len(results),
            'results': results[:10]  # Возвращаем первые 10 для предварительного просмотра
        })

    except Exception as e:
        logger.error(f"Error scraping website: {str(e)}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@admin.route('/books/update-statistics', methods=['POST'])
@admin_required
@handle_admin_errors(return_json=True)
def update_book_statistics():
    """Обновление статистики всех книг"""
    try:
        data = request.get_json()
        book_id = data.get('book_id')  # Опционально для конкретной книги

        if book_id:
            # Обновляем статистику одной книги
            book = Book.query.get_or_404(book_id)
            books_to_update = [book]
        else:
            # Обновляем статистику всех книг
            books_to_update = Book.query.all()

        updated_count = 0

        for book in books_to_update:
            try:
                # Используем DatabaseRepository для получения статистики
                from app.repository import DatabaseRepository
                repo = DatabaseRepository()

                # Получаем уникальные слова для книги
                unique_words_result = repo.execute_query(
                    "SELECT COUNT(DISTINCT word_id) FROM word_book_link WHERE book_id = %s",
                    (book.id,),
                    fetch=True
                )
                unique_words = unique_words_result[0][0] if unique_words_result else 0

                # Получаем общее количество слов (сумма частот)
                total_words_result = repo.execute_query(
                    "SELECT SUM(frequency) FROM word_book_link WHERE book_id = %s",
                    (book.id,),
                    fetch=True
                )
                total_words = total_words_result[0][0] if total_words_result else 0

                # Обновляем статистику книги
                book.unique_words = unique_words or 0
                book.total_words = total_words or 0
                book.scrape_date = datetime.utcnow()
                updated_count += 1

            except Exception as e:
                logger.warning(f"Error updating stats for book {book.id}: {str(e)}")
                continue

        db.session.commit()

        logger.info(f"Book statistics updated by {current_user.username}: {updated_count} books")

        return jsonify({
            'success': True,
            'updated_count': updated_count,
            'total_books': len(books_to_update)
        })

    except Exception as e:
        logger.error(f"Error updating book statistics: {str(e)}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@admin.route('/books/process-phrasal-verbs', methods=['POST'])
@admin_required
def process_phrasal_verbs():
    """Обработка файла с фразовыми глаголами"""
    try:
        # Проверяем, был ли загружен файл или используется текст
        phrasal_verbs_data = None

        if 'phrasal_verbs_file' in request.files and request.files['phrasal_verbs_file'].filename:
            # Получаем данные из файла
            file = request.files['phrasal_verbs_file']
            try:
                content = file.read().decode('utf-8')
                phrasal_verbs_data = content.strip().split('\n')
            except Exception as e:
                return jsonify({
                    'success': False,
                    'error': f'Ошибка при чтении файла: {str(e)}'
                }), 400
        elif request.form.get('phrasal_verbs_text'):
            # Получаем данные из текстового поля
            phrasal_verbs_data = request.form.get('phrasal_verbs_text').strip().split('\n')

        if not phrasal_verbs_data:
            return jsonify({
                'success': False,
                'error': 'Данные фразовых глаголов не предоставлены'
            }), 400

        # Обрабатываем фразовые глаголы
        from app.words.models import PhrasalVerb

        processed_count = 0
        errors = []

        for line_num, line in enumerate(phrasal_verbs_data, 1):
            line = line.strip()
            if not line or line.startswith('#'):  # Пропускаем пустые строки и комментарии
                continue

            # Ожидаем формат: phrasal_verb;russian_translate;using;english_sentence;russian_sentence
            parts = line.split(';')
            if len(parts) != 5:
                errors.append(f'Строка {line_num}: неверный формат "{line}"')
                continue

            phrasal_verb_text, russian_translate, using, english_sentence, russian_sentence = parts
            phrasal_verb_text = phrasal_verb_text.strip()

            # Получаем базовое слово (первое слово)
            english_word = phrasal_verb_text.split(' ')[0].lower()

            # Ищем базовое слово в коллекции
            base_word = CollectionWords.query.filter_by(english_word=english_word).first()

            if not base_word:
                errors.append(f'Строка {line_num}: базовое слово "{english_word}" не найдено')
                continue

            # Создаем или обновляем фразовый глагол
            phrasal_verb = PhrasalVerb.query.filter_by(phrasal_verb=phrasal_verb_text).first()

            if not phrasal_verb:
                phrasal_verb = PhrasalVerb(
                    phrasal_verb=phrasal_verb_text,
                    russian_translate=russian_translate.strip(),
                    using=using.strip(),
                    sentence=f"{english_sentence.strip()}<br>{russian_sentence.strip()}",
                    word_id=base_word.id,
                    listening=f"[sound:pronunciation_en_{phrasal_verb_text.lower().replace(' ', '_')}.mp3]",
                    get_download=0
                )
                db.session.add(phrasal_verb)
            else:
                # Обновляем существующий
                phrasal_verb.russian_translate = russian_translate.strip()
                phrasal_verb.using = using.strip()
                phrasal_verb.sentence = f"{english_sentence.strip()}<br>{russian_sentence.strip()}"

            processed_count += 1

        db.session.commit()

        result = {
            'success': True,
            'processed_count': processed_count,
            'total_lines': len(
                [line for line in phrasal_verbs_data if line.strip() and not line.strip().startswith('#')])
        }

        if errors:
            result['errors'] = errors[:10]  # Первые 10 ошибок
            result['total_errors'] = len(errors)

        logger.info(
            f"Phrasal verbs processed by {current_user.username}: {processed_count} processed, {len(errors)} errors")

        return jsonify(result)

    except Exception as e:
        logger.error(f"Error processing phrasal verbs: {str(e)}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@admin.route('/books/add', methods=['GET', 'POST'])
@admin_required
@handle_admin_errors(return_json=False)
def add_book():
    """Добавление новой книги через админку"""
    from app.books.forms import BookContentForm
    from app.books.parsers import process_uploaded_book
    from app.books.processors import process_book_words
    import threading
    import re

    form = BookContentForm()

    if form.validate_on_submit():
        # Создаем новую книгу с основными данными
        new_book = Book(
            title=form.title.data,
            author=form.author.data,
            level=form.level.data,
            scrape_date=datetime.utcnow()
        )

        # Обрабатываем обложку, если она загружена
        if form.cover_image.data and hasattr(form.cover_image.data, 'filename'):
            cover_filename = save_cover_image(form.cover_image.data)
            if cover_filename:
                new_book.cover_image = cover_filename

        # Если был загружен файл контента, обрабатываем его
        if form.file.data and hasattr(form.file.data, 'filename'):
            try:
                # Обрабатываем файл с помощью функции из parsers.py
                result = process_uploaded_book(
                    file=form.file.data,
                    title=form.title.data,
                    format_type=form.format_type.data
                )

                # Сохраняем результаты
                new_book.content = result['content']
                new_book.total_words = result['word_count']
                new_book.unique_words = result['unique_words']

            except Exception as e:
                flash(f'Ошибка при обработке файла: {str(e)}', 'danger')
                return render_template('admin/books/add.html', form=form)

        elif form.content.data:
            # Если контент был введен вручную
            content = form.content.data

            # Нормализуем текст
            content = re.sub(r'\s+', ' ', content)

            # Преобразуем простой текст в HTML с форматированием абзацев
            paragraphs = [p.strip() for p in content.split('\n\n') if p.strip()]
            content_html = '<p>' + '</p><p>'.join(paragraphs) + '</p>'

            # Подсчитываем статистику слов
            words = re.findall(r'\b[a-zA-Z]+\b', content.lower())
            new_book.content = content_html
            new_book.total_words = len(words)
            new_book.unique_words = len(set(words))

        # Сохраняем книгу в базу данных
        db.session.add(new_book)
        db.session.commit()

        # Очищаем кэш после добавления книги
        clear_admin_cache()

        # Запускаем обработку слов в отдельном потоке без ожидания
        if new_book.content:
            def start_processing():
                try:
                    process_book_words(new_book.id, new_book.content)
                except Exception as e:
                    logger.error(f"Ошибка при запуске обработки слов: {str(e)}")

            # Запускаем поток и не ждем его завершения
            processing_thread = threading.Thread(target=start_processing)
            processing_thread.daemon = True
            processing_thread.start()

            flash('Книга успешно добавлена! Обработка слов запущена в фоновом режиме.', 'success')
        else:
            flash('Книга успешно добавлена!', 'success')

        logger.info(f"Book added by admin {current_user.username}: {new_book.title}")
        return redirect(url_for('admin.books'))

    return render_template('admin/books/add.html', form=form)


@admin.route('/books/extract-metadata', methods=['POST'])
@admin_required
@handle_admin_errors(return_json=True)
def extract_book_metadata():
    """API для извлечения метаданных из загруженного файла"""
    try:
        if 'file' not in request.files:
            return jsonify({'success': False, 'error': 'Файл не найден'}), 400

        file = request.files['file']
        if file.filename == '':
            return jsonify({'success': False, 'error': 'Файл не выбран'}), 400

        # Сохраняем временный файл
        from werkzeug.utils import secure_filename
        filename = secure_filename(file.filename)
        file_ext = os.path.splitext(filename)[1].lower()

        # Создаем временную директорию
        temp_dir = os.path.join('app', 'temp')
        os.makedirs(temp_dir, exist_ok=True)

        temp_file_path = os.path.join(temp_dir, filename)
        file.save(temp_file_path)

        try:
            # Извлекаем метаданные
            from app.books.parsers import extract_file_metadata
            metadata = extract_file_metadata(temp_file_path, file_ext)

            # Логируем для отладки
            logger.info(
                f"Extracted metadata from {filename}: title='{metadata.get('title', '')}', author='{metadata.get('author', '')}'")

            return jsonify({
                'success': True,
                'metadata': metadata,
                'filename': filename,
                'file_ext': file_ext
            })

        finally:
            # Удаляем временный файл
            if os.path.exists(temp_file_path):
                try:
                    os.remove(temp_file_path)
                except:
                    pass

    except Exception as e:
        logger.error(f"Error extracting metadata: {str(e)}")
        return jsonify({
            'success': False,
            'error': f'Ошибка при извлечении метаданных: {str(e)}'
        }), 500


@admin.route('/books/cleanup', methods=['GET', 'POST'])
@admin_required
@handle_admin_errors(return_json=False)
def cleanup_books():
    """Очистка и оптимизация данных раздела Books"""

    if request.method == 'GET':
        # Анализируем данные для очистки
        cleanup_stats = {}

        try:
            # Книги без содержания
            books_no_content = db.session.execute(
                db.text("SELECT COUNT(*) FROM books WHERE content IS NULL OR content = ''")
            ).scalar()

            # Книги с нулевой статистикой
            books_no_stats = db.session.execute(
                db.text("SELECT COUNT(*) FROM books WHERE total_words = 0 OR total_words IS NULL")
            ).scalar()

            # Общее количество книг
            total_books = Book.query.count()

            cleanup_stats = {
                'books_no_content': books_no_content,
                'books_no_stats': books_no_stats,
                'total_books': total_books
            }

        except Exception as e:
            logger.error(f"Error analyzing books data: {str(e)}")
            cleanup_stats = {'error': str(e)}

        return render_template('admin/books/cleanup.html', stats=cleanup_stats)

    elif request.method == 'POST':
        # Выполняем очистку
        action = request.form.get('action')
        results = {'success': True, 'message': '', 'details': []}

        try:
            if action == 'remove_empty_books':
                # Удаляем книги без содержания
                empty_books = Book.query.filter(
                    db.or_(Book.content.is_(None), Book.content == '')
                ).all()

                count = len(empty_books)
                for book in empty_books:
                    db.session.delete(book)

                db.session.commit()
                results['details'].append(f"Удалено {count} книг без содержания")

            elif action == 'clean_temp_files':
                # Очищаем временные файлы
                import os
                temp_dir = os.path.join('app', 'temp')
                removed_files = 0

                if os.path.exists(temp_dir):
                    for filename in os.listdir(temp_dir):
                        try:
                            os.remove(os.path.join(temp_dir, filename))
                            removed_files += 1
                        except:
                            pass

                results['details'].append(f"Удалено {removed_files} временных файлов")

            results['message'] = 'Очистка выполнена успешно'

        except Exception as e:
            db.session.rollback()
            results['success'] = False
            results['message'] = f'Ошибка при очистке: {str(e)}'
            logger.error(f"Error in books cleanup: {str(e)}")

        flash(results['message'], 'success' if results['success'] else 'danger')
        for detail in results['details']:
            flash(detail, 'info')
        return redirect(url_for('admin.cleanup_books'))


def save_cover_image(file):
    """Сохраняет и обрабатывает обложку книги"""
    import os
    import uuid
    from PIL import Image
    from werkzeug.utils import secure_filename

    COVER_UPLOAD_FOLDER = 'app/static/uploads/covers'
    ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif'}
    MAX_COVER_WIDTH = 400
    MAX_COVER_HEIGHT = 600
    MAX_FILE_SIZE = 5 * 1024 * 1024  # 5MB

    # Ensure upload directory exists
    os.makedirs(COVER_UPLOAD_FOLDER, exist_ok=True)

    def allowed_file(filename):
        return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

    # Проверяем, что file не None и имеет атрибут filename
    if not file or not hasattr(file, 'filename'):
        return None

    if file and allowed_file(file.filename):
        # Проверка размера файла
        file.seek(0, os.SEEK_END)
        file_size = file.tell()
        file.seek(0)

        if file_size > MAX_FILE_SIZE:
            flash('Размер файла превышает максимальный лимит 5MB', 'danger')
            return None

        try:
            # Генерация уникального имени файла
            original_filename = secure_filename(file.filename)
            extension = original_filename.rsplit('.', 1)[1].lower()
            unique_filename = f"{uuid.uuid4().hex}.{extension}"
            filepath = os.path.join(COVER_UPLOAD_FOLDER, unique_filename)

            # Сохраняем исходный файл временно
            file.save(filepath)

            # Обрабатываем изображение с Pillow
            with Image.open(filepath) as img:
                # Преобразуем в RGB, если необходимо
                if img.mode in ('RGBA', 'LA') or (img.mode == 'P' and 'transparency' in img.info):
                    background = Image.new("RGB", img.size, (255, 255, 255))
                    background.paste(img, mask=img.split()[3] if img.split()[3] else None)
                    img = background

                # Изменяем размер при необходимости, сохраняя пропорции
                img_width, img_height = img.size
                if img_width > MAX_COVER_WIDTH or img_height > MAX_COVER_HEIGHT:
                    ratio = min(MAX_COVER_WIDTH / img_width, MAX_COVER_HEIGHT / img_height)
                    new_width = int(img_width * ratio)
                    new_height = int(img_height * ratio)
                    img = img.resize((new_width, new_height), Image.LANCZOS)

                # Сохраняем обработанное изображение
                img.save(filepath, quality=85, optimize=True)

            return f"uploads/covers/{unique_filename}"

        except Exception as e:
            logger.error(f"Error processing cover image: {str(e)}")
            # Очищаем временный файл при ошибке
            if os.path.exists(filepath):
                try:
                    os.remove(filepath)
                except:
                    pass
            return None

    return None


@admin.route('/books/statistics')
@admin_required
def book_statistics():
    """Детальная статистика по книгам"""
    try:
        # Получаем топ книг по количеству слов
        top_books_by_words = Book.query.filter(
            Book.total_words.isnot(None),
            Book.total_words > 0
        ).order_by(Book.total_words.desc()).limit(20).all()

        # Статистика по уникальным словам
        top_books_by_unique = Book.query.filter(
            Book.unique_words.isnot(None),
            Book.unique_words > 0
        ).order_by(Book.unique_words.desc()).limit(20).all()

        # Книги без статистики
        books_without_stats = Book.query.filter(
            (Book.total_words.is_(None)) | (Book.total_words == 0)
        ).order_by(Book.title).limit(50).all()

        # Общая статистика
        total_stats = db.session.query(
            func.count(Book.id).label('total_books'),
            func.sum(Book.total_words).label('total_words'),
            func.sum(Book.unique_words).label('unique_words'),
            func.avg(Book.total_words).label('avg_words'),
            func.avg(Book.unique_words).label('avg_unique')
        ).first()

        # Статистика по фразовым глаголам
        from app.words.models import PhrasalVerb
        phrasal_stats = db.session.query(
            func.count(PhrasalVerb.id).label('total_phrasal_verbs'),
            func.count(PhrasalVerb.id).filter(PhrasalVerb.get_download == 1).label('with_audio')
        ).first()

        return render_template(
            'admin/books/statistics.html',
            top_books_by_words=top_books_by_words,
            top_books_by_unique=top_books_by_unique,
            books_without_stats=books_without_stats,
            total_stats=total_stats,
            phrasal_stats=phrasal_stats
        )
    except Exception as e:
        logger.error(f"Error getting book statistics: {str(e)}")
        flash(f'Ошибка при получении статистики: {str(e)}', 'danger')
        return redirect(url_for('admin.books'))


# =============================================================================
# ГРУППА 4: Аудио и медиа управление
# =============================================================================

@admin.route('/audio')
@admin_required
def audio_management():
    """Главная страница управления аудио"""
    try:
        from config.settings import MEDIA_FOLDER, COLLECTIONS_TABLE

        # Статистика по аудио файлам
        total_words = CollectionWords.query.count()

        # Слова с доступным аудио (get_download = 1)
        words_with_audio = CollectionWords.query.filter_by(get_download=1).count()

        # Слова без аудио
        words_without_audio = total_words - words_with_audio

        # Слова с проблемными URL аудио (содержат http)
        problematic_audio = CollectionWords.query.filter(
            CollectionWords.listening.like('http%')
        ).count()

        # Недавно обновленные аудио записи
        recent_audio_updates = CollectionWords.query.filter_by(
            get_download=1
        ).order_by(CollectionWords.id.desc()).limit(10).all()

        return render_template(
            'admin/audio/index.html',
            total_words=total_words,
            words_with_audio=words_with_audio,
            words_without_audio=words_without_audio,
            problematic_audio=problematic_audio,
            recent_audio_updates=recent_audio_updates,
            media_folder=MEDIA_FOLDER
        )
    except Exception as e:
        logger.error(f"Error in audio management: {str(e)}")
        flash(f'Ошибка при загрузке данных: {str(e)}', 'danger')
        return redirect(url_for('admin.dashboard'))


@admin.route('/audio/update-download-status', methods=['POST'])
@admin_required
def update_audio_download_status():
    """Обновление статуса загрузки аудио файлов"""
    try:
        from config.settings import MEDIA_FOLDER, COLLECTIONS_TABLE
        from app.repository import DatabaseRepository

        # Получаем параметры
        data = request.get_json()
        table_name = data.get('table', COLLECTIONS_TABLE)

        # Определяем имя колонки в зависимости от таблицы
        column_name = "english_word" if table_name == COLLECTIONS_TABLE else "phrasal_verb"

        # Обновляем статус загрузки
        repo = DatabaseRepository()
        updated_count = repo.update_download_status(table_name, column_name, MEDIA_FOLDER)

        logger.info(f"Audio download status updated by {current_user.username}: {updated_count} records")

        return jsonify({
            'success': True,
            'updated_count': updated_count,
            'table_name': table_name
        })

    except Exception as e:
        logger.error(f"Error updating audio download status: {str(e)}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@admin.route('/audio/fix-listening-fields', methods=['POST'])
@admin_required
@handle_admin_errors(return_json=True)
def fix_audio_listening_fields():
    """Исправление полей прослушивания"""
    try:
        # Используем SQLAlchemy вместо DatabaseRepository для более надежного выполнения
        words_to_fix = CollectionWords.query.filter(
            # CollectionWords.get_download == 1,
            CollectionWords.russian_word.isnot(None),
            CollectionWords.english_word.isnot(None),
            CollectionWords.english_word != '',
            CollectionWords.listening.like('http%')
        ).all()

        if not words_to_fix:
            return jsonify({
                'success': True,
                'message': 'Нет записей, требующих исправления',
                'fixed_count': 0
            })

        # Исправляем поля listening
        count = 0
        try:
            from app.audio.manager import AudioManager
            audio_manager = AudioManager()

            for word in words_to_fix:
                try:
                    listening = audio_manager.update_anki_field_format(word.english_word)
                    word.listening = listening
                    count += 1
                except Exception as e:
                    logger.warning(f"Error processing word {word.english_word}: {str(e)}")
                    continue

        except ImportError:
            # Если модуль AudioManager недоступен, используем простую замену
            for word in words_to_fix:
                try:
                    word.listening = f"[sound:pronunciation_en_{word.english_word}.mp3]"
                    count += 1
                except Exception as e:
                    logger.warning(f"Error processing word {word.english_word}: {str(e)}")
                    continue

        # Сохраняем изменения
        db.session.commit()

        # Очищаем кэш после изменения данных
        clear_admin_cache()

        logger.info(f"Audio listening fields fixed by {current_user.username}: {count} records")

        return jsonify({
            'success': True,
            'message': f'Исправлено полей listening: {count}',
            'fixed_count': count
        })

    except Exception as e:
        logger.error(f"Error fixing listening fields: {str(e)}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@admin.route('/audio/get-download-list')
@admin_required
def get_audio_download_list():
    """Получение списка слов для загрузки аудио"""
    try:
        from config.settings import COLLECTIONS_TABLE
        from app.repository import DatabaseRepository

        # Получаем параметры фильтрации
        pattern = request.args.get('pattern')
        format_type = request.args.get('format', 'txt')

        # Формируем запрос
        repo = DatabaseRepository()
        query = f"""
            SELECT english_word FROM {COLLECTIONS_TABLE}
            WHERE russian_word IS NOT NULL AND (get_download = 0 OR get_download IS NULL)
        """

        params = []
        if pattern:
            query += " AND english_word LIKE %s"
            params.append(f"{pattern}%")

        query += " ORDER BY english_word"

        result = repo.execute_query(query, params, fetch=True)

        if not result:
            flash('Нет слов для загрузки аудио', 'info')
            return redirect(url_for('admin.audio_management'))

        # Получаем список слов
        words = [row[0] for row in result]

        if format_type == 'json':
            return export_audio_list_json(words, pattern)
        elif format_type == 'csv':
            return export_audio_list_csv(words, pattern)
        else:
            return export_audio_list_txt(words, pattern)

    except Exception as e:
        logger.error(f"Error getting download list: {str(e)}")
        flash(f'Ошибка при получении списка: {str(e)}', 'danger')
        return redirect(url_for('admin.audio_management'))


@admin.route('/audio/statistics')
@admin_required
def audio_statistics():
    """Детальная статистика по аудио"""
    try:
        from config.settings import COLLECTIONS_TABLE
        from app.repository import DatabaseRepository

        repo = DatabaseRepository()

        # Статистика по статусу загрузки
        download_stats = repo.execute_query(f"""
            SELECT 
                CASE 
                    WHEN get_download = 1 THEN 'Available'
                    WHEN get_download = 0 THEN 'Not Available'
                    ELSE 'Unknown'
                END as status,
                COUNT(*) as count
            FROM {COLLECTIONS_TABLE}
            GROUP BY get_download
            ORDER BY get_download DESC
        """, fetch=True)

        # Статистика по форматам listening
        listening_stats = repo.execute_query(f"""
            SELECT 
                CASE 
                    WHEN listening LIKE 'http%' THEN 'HTTP URL'
                    WHEN listening LIKE '[sound:%' THEN 'Anki Format'
                    WHEN listening IS NULL OR listening = '' THEN 'Empty'
                    ELSE 'Other Format'
                END as format_type,
                COUNT(*) as count
            FROM {COLLECTIONS_TABLE}
            GROUP BY 
                CASE 
                    WHEN listening LIKE 'http%' THEN 'HTTP URL'
                    WHEN listening LIKE '[sound:%' THEN 'Anki Format'
                    WHEN listening IS NULL OR listening = '' THEN 'Empty'
                    ELSE 'Other Format'
                END
            ORDER BY count DESC
        """, fetch=True)

        # Слова по уровням с аудио
        level_audio_stats = repo.execute_query(f"""
            SELECT 
                COALESCE(level, 'Unknown') as level,
                COUNT(*) as total_words,
                SUM(CASE WHEN get_download = 1 THEN 1 ELSE 0 END) as with_audio
            FROM {COLLECTIONS_TABLE}
            GROUP BY level
            ORDER BY level
        """, fetch=True)

        return render_template(
            'admin/audio/statistics.html',
            download_stats=download_stats,
            listening_stats=listening_stats,
            level_audio_stats=level_audio_stats
        )
    except Exception as e:
        logger.error(f"Error getting audio statistics: {str(e)}")
        flash(f'Ошибка при получении статистики: {str(e)}', 'danger')
        return redirect(url_for('admin.audio_management'))


# Функции экспорта аудио списков

def export_audio_list_json(words, pattern=None):
    """Экспорт списка аудио в формате JSON с Forvo URL"""
    from flask import make_response
    import json

    # Создаем список объектов с word и forvo_url
    words_data = []
    for word in words:
        words_data.append({
            'word': word,
            'forvo_url': f"https://forvo.com/word/{word}/#en"
        })

    response_data = {
        'export_date': datetime.utcnow().isoformat(),
        'total_words': len(words),
        'pattern_filter': pattern,
        'purpose': 'forvo_audio_download_list',
        'words': words_data
    }

    response = make_response(json.dumps(response_data, ensure_ascii=False, indent=2))
    response.headers['Content-Type'] = 'application/json; charset=utf-8'
    filename = f"forvo_download_list_{pattern or 'all'}_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.json"
    response.headers['Content-Disposition'] = f'attachment; filename={filename}'

    return response


def export_audio_list_csv(words, pattern=None):
    """Экспорт списка аудио в формате CSV с Forvo URL"""
    from flask import make_response
    import csv
    import io

    output = io.StringIO()
    writer = csv.writer(output)

    # Заголовки
    writer.writerow(['English Word', 'Forvo URL'])

    # Данные
    for word in words:
        forvo_url = f"https://forvo.com/word/{word}/#en"
        writer.writerow([word, forvo_url])

    response = make_response(output.getvalue())
    response.headers['Content-Type'] = 'text/csv; charset=utf-8'
    filename = f"forvo_download_list_{pattern or 'all'}_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.csv"
    response.headers['Content-Disposition'] = f'attachment; filename={filename}'

    return response


def export_audio_list_txt(words, pattern=None):
    """Экспорт списка аудио в текстовом формате с Forvo URL"""
    from flask import make_response

    lines = [f"# Audio Download List - {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')}"]
    if pattern:
        lines.append(f"# Pattern filter: {pattern}")
    lines.append(f"# Total words: {len(words)}")
    lines.append(f"# Format: https://forvo.com/word/{{word}}/#en")
    lines.append("")

    for word in words:
        # Создаем URL для Forvo
        forvo_url = f"https://forvo.com/word/{word}/#en"
        lines.append(forvo_url)

    content = '\n'.join(lines)
    response = make_response(content)
    response.headers['Content-Type'] = 'text/plain; charset=utf-8'
    filename = f"forvo_download_list_{pattern or 'all'}_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.txt"
    response.headers['Content-Disposition'] = f'attachment; filename={filename}'

    return response


# Импортируем роуты из curriculum.py
try:
    from . import curriculum
except ImportError:
    logger.warning("Не удалось импортировать модуль curriculum")
