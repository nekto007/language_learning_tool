# app/admin/routes/topic_routes.py

"""
Topic Management Routes для административной панели
Маршруты для управления темами (CRUD операции)
"""
import logging

from flask import Blueprint, flash, jsonify, redirect, render_template, request, url_for
from flask_babel import gettext as _
from flask_login import current_user

from app.admin.audit import log_admin_action
from app.admin.utils.decorators import admin_required
from app.utils.db import db
from app.words.forms import TopicForm
from app.words.models import CollectionWords, Topic, TopicWord

# Создаем blueprint для topic routes
topic_bp = Blueprint('topic_admin', __name__)

logger = logging.getLogger(__name__)


@topic_bp.route('/topics')
@admin_required
def topic_list():
    """Отображение списка всех тем"""
    topics = Topic.query.order_by(Topic.name).all()

    # Количество слов вычисляется автоматически через гибридное свойство

    return render_template('admin/topics/list.html', topics=topics)


@topic_bp.route('/topics/create', methods=['GET', 'POST'])
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
        db.session.flush()
        log_admin_action(current_user.id, 'topic.create', target_type='topic', target_id=topic.id)
        db.session.commit()

        flash(_('Topic created successfully!'), 'success')
        return redirect(url_for('topic_admin.topic_list'))

    return render_template('admin/topics/form.html', form=form, title=_('Create Topic'))


@topic_bp.route('/topics/<int:topic_id>/edit', methods=['GET', 'POST'])
@admin_required
def edit_topic(topic_id):
    """Редактирование темы"""
    topic = Topic.query.get_or_404(topic_id)
    form = TopicForm(obj=topic)

    if form.validate_on_submit():
        form.populate_obj(topic)
        log_admin_action(current_user.id, 'topic.update', target_type='topic', target_id=topic_id)
        db.session.commit()

        flash(_('Topic updated successfully!'), 'success')
        return redirect(url_for('topic_admin.topic_list'))

    return render_template('admin/topics/form.html', form=form, topic=topic, title=_('Edit Topic'))


@topic_bp.route('/topics/<int:topic_id>/delete', methods=['POST'])
@admin_required
def delete_topic(topic_id):
    """Удаление темы"""
    topic = Topic.query.get_or_404(topic_id)
    db.session.delete(topic)
    log_admin_action(current_user.id, 'topic.delete', target_type='topic', target_id=topic_id)
    db.session.commit()

    flash(_('Topic deleted successfully!'), 'success')
    return redirect(url_for('topic_admin.topic_list'))


@topic_bp.route('/topics/<int:topic_id>/words')
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


@topic_bp.route('/topics/<int:topic_id>/add_word/<int:word_id>', methods=['POST'])
@admin_required
def add_word_to_topic(topic_id, word_id):
    """API для добавления слова в тему"""
    topic = Topic.query.get_or_404(topic_id)
    word = CollectionWords.query.get_or_404(word_id)

    # Проверяем, не добавлено ли уже слово в тему
    if word not in topic.words:
        topic_word = TopicWord(topic_id=topic_id, word_id=word_id)
        db.session.add(topic_word)
        log_admin_action(current_user.id, 'topic.add_word', target_type='topic_word', target_id=topic_id)
        db.session.commit()
        return jsonify({'success': True})

    return jsonify({'success': False, 'message': _('Word already in topic')})


@topic_bp.route('/topics/<int:topic_id>/bulk_add_words', methods=['POST'])
@admin_required
def bulk_add_words_to_topic(topic_id):
    """API для массового добавления слов в тему только по точному совпадению."""
    topic = Topic.query.get_or_404(topic_id)
    data = request.get_json(silent=True) or {}
    words = data.get('words', [])

    if not isinstance(words, list):
        return jsonify({'success': False, 'message': 'words must be a list'}), 400

    existing_word_ids = {word.id for word in topic.words}
    results = {
        'added': [],
        'existing': [],
        'not_found': [],
    }

    for raw_word in words:
        word_text = str(raw_word).strip()
        normalized_word = word_text.lower()
        if not normalized_word:
            continue

        word = CollectionWords.query.filter(
            db.func.lower(CollectionWords.english_word) == normalized_word
        ).first()

        if word is None:
            results['not_found'].append(word_text)
            continue

        if word.id in existing_word_ids:
            results['existing'].append(word.english_word)
            continue

        db.session.add(TopicWord(topic_id=topic_id, word_id=word.id))
        existing_word_ids.add(word.id)
        results['added'].append(word.english_word)

    if results['added']:
        log_admin_action(
            current_user.id,
            'topic.bulk_add_words',
            target_type='topic',
            target_id=topic_id,
        )
    db.session.commit()

    return jsonify({
        'success': True,
        'added': len(results['added']),
        'existing': len(results['existing']),
        'not_found': len(results['not_found']),
        'details': results,
    })


@topic_bp.route('/topics/<int:topic_id>/remove_word/<int:word_id>', methods=['POST'])
@admin_required
def remove_word_from_topic(topic_id, word_id):
    """API для удаления слова из темы"""
    topic_word = TopicWord.query.filter_by(topic_id=topic_id, word_id=word_id).first_or_404()

    db.session.delete(topic_word)
    log_admin_action(current_user.id, 'topic.remove_word', target_type='topic_word', target_id=topic_id)
    db.session.commit()

    return jsonify({'success': True})
