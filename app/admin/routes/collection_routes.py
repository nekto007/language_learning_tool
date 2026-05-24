# app/admin/routes/collection_routes.py

"""
Collection Management Routes для административной панели
Маршруты для управления коллекциями (CRUD операции)
"""
import logging
from collections import defaultdict

from flask import Blueprint, flash, jsonify, redirect, render_template, request, url_for
from flask_babel import gettext as _
from flask_login import current_user
from sqlalchemy.orm import joinedload

from app.admin.audit import log_admin_action
from app.admin.utils.decorators import admin_required
from app.admin.utils.request_validators import escape_like
from app.utils.db import db
from app.words.forms import CollectionForm
from app.words.models import Collection, CollectionWordLink, CollectionWords, Topic, TopicWord

# Создаем blueprint для collection routes
collection_bp = Blueprint('collection_admin', __name__)

logger = logging.getLogger(__name__)

COLLECTION_LIST_PER_PAGE_DEFAULT = 25
COLLECTION_LIST_PER_PAGE_MAX = 100
ALLOWED_SORTS = {'name', 'word_count', 'created_at'}


class _AdminPagination:
    """Lightweight pagination object mimicking flask_sqlalchemy.Pagination
    interface used by templates (page, pages, total, has_prev/next, iter_pages)."""

    def __init__(self, page: int, per_page: int, total: int, pages: int):
        self.page = page
        self.per_page = per_page
        self.total = total
        self.pages = pages
        self.has_prev = page > 1
        self.has_next = page < pages
        self.prev_num = page - 1 if self.has_prev else None
        self.next_num = page + 1 if self.has_next else None

    def iter_pages(self, left_edge=2, left_current=2, right_current=3, right_edge=2):
        last = 0
        for num in range(1, self.pages + 1):
            if (
                num <= left_edge
                or (self.page - left_current - 1 < num < self.page + right_current)
                or num > self.pages - right_edge
            ):
                if last + 1 != num:
                    yield None
                yield num
                last = num


def _collection_name_taken(name: str, exclude_id: int | None = None) -> bool:
    query = Collection.query.filter(db.func.lower(Collection.name) == name.lower())
    if exclude_id is not None:
        query = query.filter(Collection.id != exclude_id)
    return db.session.query(query.exists()).scalar()


@collection_bp.route('/collections')
@admin_required
def collection_list():
    """Отображение списка всех коллекций с поиском, фильтрацией, пагинацией"""
    try:
        page = max(int(request.args.get('page', 1)), 1)
    except (TypeError, ValueError):
        page = 1
    try:
        per_page = int(request.args.get('per_page', COLLECTION_LIST_PER_PAGE_DEFAULT))
    except (TypeError, ValueError):
        per_page = COLLECTION_LIST_PER_PAGE_DEFAULT
    per_page = max(1, min(per_page, COLLECTION_LIST_PER_PAGE_MAX))

    search = (request.args.get('search') or '').strip()
    topic_filter = request.args.get('topic')
    sort = request.args.get('sort') or 'name'
    if sort not in ALLOWED_SORTS:
        sort = 'name'

    word_count_subq = (
        db.session.query(
            CollectionWordLink.collection_id.label('collection_id'),
            db.func.count(CollectionWordLink.word_id).label('cnt'),
        )
        .group_by(CollectionWordLink.collection_id)
        .subquery()
    )

    query = (
        db.session.query(
            Collection,
            db.func.coalesce(word_count_subq.c.cnt, 0).label('words_total'),
        )
        .options(joinedload(Collection.creator))
        .outerjoin(word_count_subq, word_count_subq.c.collection_id == Collection.id)
    )

    if search:
        like_term = f"%{escape_like(search)}%"
        query = query.filter(Collection.name.ilike(like_term, escape='\\'))

    if topic_filter:
        try:
            topic_id_int = int(topic_filter)
            query = query.filter(
                Collection.id.in_(
                    db.session.query(CollectionWordLink.collection_id)
                    .join(TopicWord, TopicWord.word_id == CollectionWordLink.word_id)
                    .filter(TopicWord.topic_id == topic_id_int)
                )
            )
        except (TypeError, ValueError):
            pass

    if sort == 'word_count':
        query = query.order_by(db.text('words_total DESC'))
    elif sort == 'created_at':
        query = query.order_by(Collection.created_at.desc())
    else:
        query = query.order_by(Collection.name)

    total = query.order_by(None).count()
    rows = query.limit(per_page).offset((page - 1) * per_page).all()

    collection_ids = [row[0].id for row in rows]

    topics_by_collection: dict[int, list[Topic]] = defaultdict(list)
    if collection_ids:
        topic_rows = (
            db.session.query(CollectionWordLink.collection_id, Topic)
            .join(TopicWord, TopicWord.word_id == CollectionWordLink.word_id)
            .join(Topic, Topic.id == TopicWord.topic_id)
            .filter(CollectionWordLink.collection_id.in_(collection_ids))
            .distinct()
            .all()
        )
        for collection_id, topic in topic_rows:
            topics_by_collection[collection_id].append(topic)

    collections = []
    for collection, words_total in rows:
        collection.creator_name = collection.creator.username if collection.creator else "Admin"
        collection.word_count_cached = int(words_total or 0)
        collection.topics_cached = topics_by_collection.get(collection.id, [])
        collections.append(collection)

    total_pages = (total + per_page - 1) // per_page if total else 0
    pagination = _AdminPagination(page=page, per_page=per_page, total=total, pages=total_pages)

    topics = Topic.query.order_by(Topic.name).all()

    return render_template(
        'admin/collections/list.html',
        collections=collections,
        topics=topics,
        pagination=pagination,
    )


@collection_bp.route('/collections/create', methods=['GET', 'POST'])
@admin_required
def create_collection():
    """Создание новой коллекции"""
    form = CollectionForm()

    if form.validate_on_submit():
        if _collection_name_taken(form.name.data):
            form.name.errors.append(_('Collection with this name already exists.'))
            topics = Topic.query.order_by(Topic.name).all()
            return render_template(
                'admin/collections/form.html',
                form=form,
                topics=topics,
                title=_('Create Collection'),
            )

        collection = Collection(
            name=form.name.data,
            description=form.description.data,
            created_by=current_user.id
        )
        db.session.add(collection)
        db.session.flush()  # Чтобы получить id коллекции

        # Добавляем слова в коллекцию
        if form.word_ids.data:
            try:
                word_ids = [int(word_id) for word_id in form.word_ids.data.split(',') if word_id.strip()]
            except ValueError:
                word_ids = []
            for word_id in word_ids:
                link = CollectionWordLink(collection_id=collection.id, word_id=word_id)
                db.session.add(link)

        log_admin_action(current_user.id, 'collection.create', target_type='collection', target_id=collection.id)
        db.session.commit()

        flash(_('Collection created successfully!'), 'success')
        return redirect(url_for('collection_admin.collection_list'))

    # Получаем все темы для селектора
    topics = Topic.query.order_by(Topic.name).all()

    return render_template(
        'admin/collections/form.html',
        form=form,
        topics=topics,
        title=_('Create Collection')
    )


@collection_bp.route('/collections/<int:collection_id>/edit', methods=['GET', 'POST'])
@admin_required
def edit_collection(collection_id):
    """Редактирование коллекции"""
    collection = Collection.query.get_or_404(collection_id)
    form = CollectionForm(obj=collection)

    if form.validate_on_submit():
        if _collection_name_taken(form.name.data, exclude_id=collection.id):
            form.name.errors.append(_('Collection with this name already exists.'))
            topics = Topic.query.order_by(Topic.name).all()
            current_word_ids = [str(word.id) for word in collection.words]
            form.word_ids.data = ','.join(current_word_ids)
            return render_template(
                'admin/collections/form.html',
                form=form,
                collection=collection,
                topics=topics,
                title=_('Edit Collection'),
            )

        # Обновляем основную информацию
        collection.name = form.name.data
        collection.description = form.description.data

        # Обновляем слова в коллекции
        if form.word_ids.data:
            # Удаляем все текущие связи
            CollectionWordLink.query.filter_by(collection_id=collection.id).delete()

            # Добавляем выбранные слова
            try:
                word_ids = [int(word_id) for word_id in form.word_ids.data.split(',') if word_id.strip()]
            except ValueError:
                word_ids = []
            for word_id in word_ids:
                link = CollectionWordLink(collection_id=collection.id, word_id=word_id)
                db.session.add(link)

        log_admin_action(current_user.id, 'collection.update', target_type='collection', target_id=collection_id)
        db.session.commit()

        flash(_('Collection updated successfully!'), 'success')
        return redirect(url_for('collection_admin.collection_list'))

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


@collection_bp.route('/collections/<int:collection_id>/delete', methods=['POST'])
@admin_required
def delete_collection(collection_id):
    """Удаление коллекции"""
    collection = Collection.query.get_or_404(collection_id)
    db.session.delete(collection)
    log_admin_action(current_user.id, 'collection.delete', target_type='collection', target_id=collection_id)
    db.session.commit()

    flash(_('Collection deleted successfully!'), 'success')
    return redirect(url_for('collection_admin.collection_list'))


@collection_bp.route('/api/get_words_by_topic')
@admin_required
def get_words_by_topic():
    """API для получения слов по темам"""
    topic_ids = request.args.get('topic_ids', '')

    if not topic_ids:
        return jsonify([])

    try:
        topic_id_list = [int(topic_id) for topic_id in topic_ids.split(',') if topic_id.strip()]
    except ValueError:
        return jsonify({'error': 'invalid topic_ids'}), 400
    if not topic_id_list:
        return jsonify([])

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
