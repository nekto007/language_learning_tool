# app/admin/routes/topic_routes.py

"""
Topic Management Routes для административной панели
Маршруты для управления темами (CRUD операции)
"""
import logging

from flask import Blueprint, flash, jsonify, redirect, render_template, url_for
from flask_babel import gettext as _
from flask_login import login_required

from app.admin.utils.decorators import admin_required
from app.utils.db import db
from app.words.forms import TopicForm
from app.words.models import CollectionWords, Topic, TopicWord

# Создаем blueprint для topic routes
topic_bp = Blueprint('topic_admin', __name__)

logger = logging.getLogger(__name__)


@topic_bp.route('/topics')
@login_required
@admin_required
def topic_list():
    """Отображение списка всех тем"""
    topics = Topic.query.order_by(Topic.name).all()

    # Количество слов вычисляется автоматически через гибридное свойство

    return render_template('admin/topics/list.html', topics=topics)


@topic_bp.route('/topics/create', methods=['GET', 'POST'])
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
        return redirect(url_for('topic_admin.topic_list'))

    return render_template('admin/topics/form.html', form=form, title=_('Create Topic'))


@topic_bp.route('/topics/<int:topic_id>/edit', methods=['GET', 'POST'])
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
        return redirect(url_for('topic_admin.topic_list'))

    return render_template('admin/topics/form.html', form=form, topic=topic, title=_('Edit Topic'))


@topic_bp.route('/topics/<int:topic_id>/delete', methods=['POST'])
@login_required
@admin_required
def delete_topic(topic_id):
    """Удаление темы"""
    topic = Topic.query.get_or_404(topic_id)
    db.session.delete(topic)
    db.session.commit()

    flash(_('Topic deleted successfully!'), 'success')
    return redirect(url_for('topic_admin.topic_list'))


@topic_bp.route('/topics/<int:topic_id>/words')
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


@topic_bp.route('/topics/<int:topic_id>/add_word/<int:word_id>', methods=['POST'])
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


@topic_bp.route('/topics/<int:topic_id>/remove_word/<int:word_id>', methods=['POST'])
@login_required
@admin_required
def remove_word_from_topic(topic_id, word_id):
    """API для удаления слова из темы"""
    topic_word = TopicWord.query.filter_by(topic_id=topic_id, word_id=word_id).first_or_404()

    db.session.delete(topic_word)
    db.session.commit()

    return jsonify({'success': True})
