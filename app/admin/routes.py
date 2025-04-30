"""
Основной модуль административной панели для LLT English
"""
import logging
from datetime import datetime, timedelta

from flask import Blueprint, flash, jsonify, redirect, render_template, request, url_for
from flask_babel import gettext as _
from flask_login import current_user, login_required
from sqlalchemy import desc, func

from app.auth.models import User
from app.utils.db import db
from app.words.forms import CollectionForm, TopicForm
from app.words.models import Collection, CollectionWordLink, CollectionWords, Topic, TopicWord

admin = Blueprint('admin', __name__, url_prefix='/admin')

# Настройка логирования
logger = logging.getLogger(__name__)


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


@admin.route('/')
@admin_required
def dashboard():
    """Главная страница административной панели"""
    # Основная статистика для панели управления
    total_users = User.query.count()
    active_users = User.query.filter_by(active=True).count()

    # Пользователи, зарегистрировавшиеся за последние 7 дней
    week_ago = datetime.utcnow() - timedelta(days=7)
    new_users = User.query.filter(User.created_at >= week_ago).count()

    # Активные пользователи за последние 7 дней
    active_recently = User.query.filter(User.last_login >= week_ago).count()

    # Последние зарегистрированные пользователи
    recent_users = User.query.order_by(desc(User.created_at)).limit(10).all()

    # Статистика по книгам
    try:
        from app.books.models import Book
        total_books = db.session.query(func.count(Book.id)).scalar() or 0
        total_readings = db.session.query(func.sum(Book.unique_words)).scalar() or 0
    except:
        total_books = 0
        total_readings = 0

    # Статистика по словам
    try:
        from app.words.models import CollectionWords
        total_words = db.session.query(func.count(CollectionWords.id)).scalar() or 0
    except:
        total_words = 0

    return render_template(
        'admin/dashboard.html',
        total_users=total_users,
        active_users=active_users,
        new_users=new_users,
        active_recently=active_recently,
        recent_users=recent_users,
        total_books=total_books,
        total_readings=total_readings,
        total_words=total_words
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


@admin.route('/system')
@admin_required
def system():
    """Информация о системе"""
    import platform
    import psutil

    system_info = {
        'platform': platform.platform(),
        'python_version': platform.python_version(),
        'cpu_count': psutil.cpu_count(),
        'memory': {
            'total': psutil.virtual_memory().total // (1024 * 1024),  # МБ
            'available': psutil.virtual_memory().available // (1024 * 1024),  # МБ
            'used_percent': psutil.virtual_memory().percent
        },
        'disk': {
            'total': psutil.disk_usage('/').total // (1024 * 1024 * 1024),  # ГБ
            'used': psutil.disk_usage('/').used // (1024 * 1024 * 1024),  # ГБ
            'free': psutil.disk_usage('/').free // (1024 * 1024 * 1024),  # ГБ
            'used_percent': psutil.disk_usage('/').percent
        }
    }


@admin.route('/topics')
@login_required
@admin_required
def topic_list():
    """Отображение списка всех тем"""
    topics = Topic.query.order_by(Topic.name).all()

    # Добавляем к каждой теме количество слов
    for topic in topics:
        topic.word_count = len(topic.words)

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

    # Для каждой коллекции получаем создателя и количество слов
    for collection in collections:
        collection.creator_name = collection.creator.username if collection.creator else "Admin"
        # collection.word_count = len(collection.words)

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
