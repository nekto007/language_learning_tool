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
from app.admin.utils.request_validators import escape_like
from app.utils.db import db
from app.words.models import CollectionWords, WordContrast

word_contrast_bp = Blueprint('word_contrast_admin', __name__)

logger = logging.getLogger(__name__)

# Keep ``note_ru`` sane — long notes break the visual rhythm of the word
# page and the channel post. 2000 chars is comfortably more than any
# curated seed entry.
_MAX_NOTE_LENGTH = 2000
_PER_PAGE = 50

# Bulk import: cap the uploaded file so an admin can't accidentally OOM
# the worker by attaching a multi-megabyte dictionary dump.
_MAX_IMPORT_FILE_SIZE = 1 * 1024 * 1024  # 1 MB
_MAX_IMPORT_ROWS = 5000


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
        like = f'%{escape_like(search.lower())}%'
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


def _parse_import_text(text: str) -> tuple[list[tuple[str, str, str]], list[str]]:
    """Parse the bulk-import payload.

    Expected line format: ``word_a;word_b;note_ru``. Blank lines and
    lines without two semicolons are reported as malformed (line numbers
    are 1-indexed).

    Returns ``(entries, malformed_messages)``. Each ``entries`` tuple is
    already whitespace-stripped; the caller validates that the words
    exist and creates the rows.
    """
    entries: list[tuple[str, str, str]] = []
    malformed: list[str] = []
    for lineno, raw in enumerate(text.splitlines(), start=1):
        line = raw.strip()
        if not line:
            continue
        # ``note_ru`` may legitimately contain ``;`` inside the HTML/text,
        # so split on the first two delimiters only.
        parts = line.split(';', 2)
        if len(parts) != 3:
            malformed.append(f'Строка {lineno}: ожидался формат a;b;объяснение')
            continue
        word_a, word_b, note = parts[0].strip(), parts[1].strip(), parts[2].strip()
        if not word_a or not word_b or not note:
            malformed.append(f'Строка {lineno}: пустое слово или объяснение')
            continue
        entries.append((word_a, word_b, note))
    return entries, malformed


@word_contrast_bp.route('/word-contrasts/import', methods=['POST'])
@admin_audit_required(
    action='word_contrast.import', target_type='word_contrast',
)
def word_contrast_import():
    """Bulk-import contrast pairs from a txt/csv upload.

    File format: one pair per non-empty line, fields separated by ``;``:

        bus stop;bus station;<b>bus stop</b> — место... <b>bus station</b> — автовокзал...
        home;house;<b>home</b> — дом... <b>house</b> — здание...

    Empty lines are ignored so the admin can keep the file readable.
    Already-existing pairs (matched on the canonical ``(low_id, high_id)``
    tuple) are silently skipped — the existing note is preserved. Lines
    where one of the words is missing from ``CollectionWords`` are
    reported in the flash summary so the admin can fix them and retry.
    """
    upload = request.files.get('file')
    if upload is None or not upload.filename:
        flash('Файл не выбран.', 'warning')
        return redirect(url_for('word_contrast_admin.word_contrast_index'))

    # Size guard — werkzeug streams the body, so an oversized file would
    # have already failed Flask's MAX_CONTENT_LENGTH; this is a defence
    # in depth for environments without that ceiling configured.
    try:
        raw = upload.read(_MAX_IMPORT_FILE_SIZE + 1)
    except Exception:
        flash('Не удалось прочитать файл.', 'danger')
        return redirect(url_for('word_contrast_admin.word_contrast_index'))
    if len(raw) > _MAX_IMPORT_FILE_SIZE:
        flash(f'Файл больше лимита ({_MAX_IMPORT_FILE_SIZE // 1024} KB).', 'warning')
        return redirect(url_for('word_contrast_admin.word_contrast_index'))

    try:
        text = raw.decode('utf-8')
    except UnicodeDecodeError:
        flash('Файл должен быть в кодировке UTF-8.', 'danger')
        return redirect(url_for('word_contrast_admin.word_contrast_index'))

    entries, malformed = _parse_import_text(text)
    if not entries:
        msg = 'В файле нет корректных строк.'
        if malformed:
            msg += ' ' + malformed[0]
        flash(msg, 'warning')
        return redirect(url_for('word_contrast_admin.word_contrast_index'))

    if len(entries) > _MAX_IMPORT_ROWS:
        flash(
            f'Слишком много строк ({len(entries)}). Лимит — {_MAX_IMPORT_ROWS}.',
            'warning',
        )
        return redirect(url_for('word_contrast_admin.word_contrast_index'))

    created = 0
    duplicates = 0
    too_long: list[str] = []
    missing: list[str] = []
    too_long_count = 0
    for word_a, word_b, note in entries:
        if len(note) > _MAX_NOTE_LENGTH:
            too_long_count += 1
            if len(too_long) < 5:
                too_long.append(f'{word_a} ↔ {word_b}')
            continue
        a = _lookup_word(word_a)
        b = _lookup_word(word_b)
        if a is None or b is None:
            missing_name = word_a if a is None else word_b
            missing.append(missing_name)
            continue
        if a.id == b.id:
            continue
        low_id, high_id = sorted((a.id, b.id))
        # Pre-check for duplicate — saves a savepoint round-trip in the
        # common case where re-importing a file mostly hits known pairs.
        existing = WordContrast.query.filter_by(
            word_a_id=low_id, word_b_id=high_id,
        ).first()
        if existing is not None:
            duplicates += 1
            continue
        row = WordContrast(word_a_id=low_id, word_b_id=high_id, note_ru=note)
        db.session.add(row)
        try:
            with db.session.begin_nested():
                db.session.flush()
        except IntegrityError:
            # Race against another writer or two equivalent lines in the
            # same upload — count as duplicate.
            duplicates += 1
            continue
        created += 1

    db.session.commit()

    summary_parts = [
        f'добавлено: {created}',
        f'дубликаты: {duplicates}',
    ]
    if missing:
        unique_missing = sorted(set(missing))
        preview = ', '.join(unique_missing[:5])
        suffix = '…' if len(unique_missing) > 5 else ''
        summary_parts.append(f'не найдено слов: {len(unique_missing)} ({preview}{suffix})')
    if too_long_count:
        summary_parts.append(f'слишком длинных объяснений: {too_long_count}')
    if malformed:
        summary_parts.append(f'некорректных строк: {len(malformed)}')

    category = 'success' if created and not missing and not malformed else 'info'
    flash('Импорт завершён — ' + '; '.join(summary_parts) + '.', category)
    return redirect(url_for('word_contrast_admin.word_contrast_index'))
