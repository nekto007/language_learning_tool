"""Learner-facing routes for curated themed word sets.

This section replaces the old topics listing. That page rendered every row of
`topics` — thousands, nearly all of them single-word machine-generated labels —
and counted each group with its own query, so it could not be used. Sets are
the curated, browsable subset; the topics data itself is untouched and still
serves the admin side and the deck "add from topic" API.
"""
from flask import abort, flash, jsonify, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from app.modules.decorators import module_required
from app.study.blueprint import study
from app.study.services import WordSetService


@study.route('/sets')
@login_required
@module_required('study')
def word_sets():
    """Grid of published sets with the user's best score on each."""
    entries = WordSetService.list_published(current_user.id)
    return render_template('study/word_sets.html', entries=entries)


@study.route('/sets/<slug>')
@login_required
@module_required('study')
def word_set_detail(slug):
    """One set: its words, the user's progress, and the quiz entry point."""
    is_admin = bool(getattr(current_user, 'is_admin', False))
    word_set = WordSetService.get_set(slug, include_unpublished=is_admin)
    if word_set is None:
        abort(404)

    words = WordSetService.get_words(word_set.id)
    progress = WordSetService.get_progress(current_user.id, word_set.id)

    return render_template(
        'study/word_set_detail.html',
        word_set=word_set,
        words=words,
        progress=progress,
    )


@study.route('/sets/<slug>/add', methods=['POST'])
@login_required
@module_required('study')
def add_word_set(slug):
    """Add every word of a set to the study list."""
    word_set = WordSetService.get_set(slug)
    if word_set is None:
        abort(404)

    added = WordSetService.add_to_study(word_set.id, current_user.id)

    if added:
        message = f'{added} слов из набора «{word_set.name}» добавлено в изучение'
        flash(message, 'success')
    else:
        message = 'Все слова из этого набора уже в вашем списке'
        flash(message, 'info')

    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return jsonify({'success': True, 'added_count': added, 'message': message})

    return redirect(url_for('study.word_set_detail', slug=slug))
