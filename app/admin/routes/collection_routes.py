# app/admin/routes/collection_routes.py

"""
Collection Management Routes для административной панели
Маршруты для управления коллекциями (CRUD операции)
"""
import logging

from flask import Blueprint, flash, jsonify, redirect, render_template, request, url_for
from flask_babel import gettext as _
from flask_login import current_user, login_required

from app.admin.utils.decorators import admin_required
from app.utils.db import db
from app.words.forms import CollectionForm
from app.words.models import Collection, CollectionWordLink, CollectionWords, Topic, TopicWord

# Создаем blueprint для collection routes
collection_bp = Blueprint('collection_admin', __name__)

logger = logging.getLogger(__name__)


@collection_bp.route('/collections')
@login_required
@admin_required
def collection_list():
    """Отображение списка всех коллекций"""
    collections = Collection.query.order_by(Collection.name).all()

    # Для каждой коллекции получаем создателя
    for collection in collections:
        collection.creator_name = collection.creator.username if collection.creator else "Admin"

    return render_template('admin/collections/list.html', collections=collections)


@collection_bp.route('/collections/create', methods=['GET', 'POST'])
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
@login_required
@admin_required
def delete_collection(collection_id):
    """Удаление коллекции"""
    collection = Collection.query.get_or_404(collection_id)
    db.session.delete(collection)
    db.session.commit()

    flash(_('Collection deleted successfully!'), 'success')
    return redirect(url_for('collection_admin.collection_list'))


@collection_bp.route('/api/get_words_by_topic')
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
