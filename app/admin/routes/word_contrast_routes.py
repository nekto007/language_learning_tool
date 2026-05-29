# app/admin/routes/word_contrast_routes.py

"""Admin UI for curated word-contrast pairs.

Lets an editor add, edit, and remove ``WordContrast`` rows without touching
the seed JSON or running CLI commands. Each pair stores two
``CollectionWords`` ids (canonicalised so ``word_a_id < word_b_id``) and a
free-form Russian note (HTML ``<b>`` and ``<br>`` allowed — that's the same
contract as the seed file).

Patterns reused from existing admin blueprints:
- ``admin_audit_required`` decorator for destructive mutations (delete, edit).
- ``flash`` + redirect for actions.
- Search/pagination via plain query params, no JS dependencies.
"""

import logging

from flask import Blueprint, flash, redirect, render_template, request, url_for
from sqlalchemy import func, or_
from sqlalchemy.exc import IntegrityError

from app.admin.utils.decorators import admin_audit_required, admin_required
from app.utils.db import db
from app.words.models import CollectionWords, WordContrast

word_contrast_bp = Blueprint('word_contrast_admin', __name__)

logger = logging.getLogger(__name__)

# Keep ``note_ru`` sane — long notes break the visual rhythm of the word
# page and the channel post. 2000 chars is comfortably more than any
# curated seed entry.
_MAX_NOTE_LENGTH = 2000
_PER_PAGE = 50


def _lookup_word(name: str) -> CollectionWords | None:
    """Case-insensitive english_word lookup."""
    cleaned = (name or '').strip()
    if not cleaned:
        return None
    return (
        CollectionWords.query
        .filter(func.lower(CollectionWords.english_word) == cleaned.lower())
        .first()
    )


@word_contrast_bp.route('/word-contrasts')
@admin_required
def word_contrast_index():
    page = max(1, request.args.get('page', 1, type=int))
    search = (request.args.get('q', '') or '').strip()

    query = WordContrast.query.join(
        CollectionWords, CollectionWords.id == WordContrast.word_a_id,
    )
    if search:
        # Filter by either side of the pair: an admin searching "much" wants
        # the much/many row whether much sits in word_a or word_b.
        like = f'%{search.lower()}%'
        word_ids = [
            row[0] for row in db.session.query(CollectionWords.id).filter(
                func.lower(CollectionWords.english_word).like(like),
            ).all()
        ]
        if word_ids:
            query = WordContrast.query.filter(
                or_(
                    WordContrast.word_a_id.in_(word_ids),
                    WordContrast.word_b_id.in_(word_ids),
                )
            )
        else:
            query = WordContrast.query.filter(False)
    else:
        query = WordContrast.query

    pagination = query.order_by(WordContrast.id.desc()).paginate(
        page=page, per_page=_PER_PAGE, error_out=False,
    )

    return render_template(
        'admin/word_contrasts/index.html',
        contrasts=pagination.items,
        pagination=pagination,
        search=search,
        max_note_length=_MAX_NOTE_LENGTH,
    )


@word_contrast_bp.route('/word-contrasts/create', methods=['POST'])
@admin_audit_required(
    action='word_contrast.create', target_type='word_contrast',
)
def word_contrast_create():
    a_name = request.form.get('word_a', '').strip()
    b_name = request.form.get('word_b', '').strip()
    note = (request.form.get('note_ru', '') or '').strip()

    if not a_name or not b_name or not note:
        flash('Заполните оба слова и текст объяснения.', 'warning')
        return redirect(url_for('word_contrast_admin.word_contrast_index'))
    if len(note) > _MAX_NOTE_LENGTH:
        flash(f'Объяснение длиннее лимита ({_MAX_NOTE_LENGTH} символов).', 'warning')
        return redirect(url_for('word_contrast_admin.word_contrast_index'))

    a = _lookup_word(a_name)
    b = _lookup_word(b_name)
    if a is None or b is None:
        missing = a_name if a is None else b_name
        flash(f'Слово «{missing}» не найдено в словаре.', 'danger')
        return redirect(url_for('word_contrast_admin.word_contrast_index'))
    if a.id == b.id:
        flash('Нельзя сделать пару из одного и того же слова.', 'warning')
        return redirect(url_for('word_contrast_admin.word_contrast_index'))

    low_id, high_id = sorted((a.id, b.id))
    row = WordContrast(word_a_id=low_id, word_b_id=high_id, note_ru=note)
    db.session.add(row)
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        flash('Такая пара уже есть.', 'info')
        return redirect(url_for('word_contrast_admin.word_contrast_index'))

    flash(f'Добавлена пара #{row.id}: {a.english_word} ↔ {b.english_word}.', 'success')
    return redirect(url_for('word_contrast_admin.word_contrast_index'))


@word_contrast_bp.route('/word-contrasts/<int:pair_id>/update', methods=['POST'])
@admin_audit_required(
    action='word_contrast.update', target_type='word_contrast',
    target_id_arg='pair_id',
)
def word_contrast_update(pair_id: int):
    row = WordContrast.query.get_or_404(pair_id)
    note = (request.form.get('note_ru', '') or '').strip()
    if not note:
        flash('Текст объяснения не может быть пустым.', 'warning')
        return redirect(url_for('word_contrast_admin.word_contrast_index'))
    if len(note) > _MAX_NOTE_LENGTH:
        flash(f'Объяснение длиннее лимита ({_MAX_NOTE_LENGTH} символов).', 'warning')
        return redirect(url_for('word_contrast_admin.word_contrast_index'))
    row.note_ru = note
    db.session.commit()
    flash(f'Объяснение для пары #{row.id} обновлено.', 'success')
    return redirect(url_for('word_contrast_admin.word_contrast_index'))


@word_contrast_bp.route('/word-contrasts/<int:pair_id>/delete', methods=['POST'])
@admin_audit_required(
    action='word_contrast.delete', target_type='word_contrast',
    target_id_arg='pair_id',
)
def word_contrast_delete(pair_id: int):
    row = WordContrast.query.get_or_404(pair_id)
    db.session.delete(row)
    db.session.commit()
    flash(f'Пара #{pair_id} удалена.', 'success')
    return redirect(url_for('word_contrast_admin.word_contrast_index'))
