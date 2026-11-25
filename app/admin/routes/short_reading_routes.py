"""Publish a short reading and its formative practice together."""

import json
from copy import deepcopy
from hashlib import sha256

from flask import Blueprint, abort, current_app, flash, make_response, redirect, render_template, request, url_for
from flask.typing import ResponseReturnValue
from flask_login import current_user
from itsdangerous import BadSignature, URLSafeTimedSerializer

from app.admin.audit import log_admin_action
from app.admin.routes.materials import materials_return_url
from app.admin.services.chapter_editor import apply_chapter, review_chapter, text_for_edit
from app.admin.utils.decorators import admin_required
from app.books.models import Book, Chapter
from app.books.short_readings import validate_reading_item, words
from app.utils.db import db

short_reading_bp = Blueprint('short_reading_admin', __name__)
_QUESTION_FIELDS = ('instruction', 'prompt', 'prompt_translation', 'explanation', 'correct_option')


def _digest(value: object) -> str:
    return sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def _fields(reading: dict) -> dict:
    raw_glossary, raw_questions = reading.get('glossary'), reading.get('questions')
    glossary = [row for row in raw_glossary if isinstance(row, dict)] if isinstance(raw_glossary, list) else []
    glossary += [{'english': '', 'translation': ''} for _ in range(5 - len(glossary))]
    questions = [row.copy() for row in raw_questions if isinstance(row, dict)][:3] if isinstance(raw_questions, list) else []
    ids = {q.get('id') for q in questions if isinstance(q.get('id'), str)}
    new_ids = (f'q{i}' for i in range(1, 7) if f'q{i}' not in ids)
    questions += [{} for _ in range(3 - len(questions))]
    assigned = set()
    for row in questions:
        if not isinstance(row.get('id'), str) or not row['id'] or row['id'] in assigned:
            row['id'] = next(new_ids)
        assigned.add(row['id'])
        options = row.get('options')
        if not isinstance(options, list) or len(options) != 3 or not all(
            isinstance(option, dict) and isinstance(option.get('id'), str) for option in options
        ) or len({option['id'] for option in options}) != 3:
            row['options'] = [{'id': key, 'text': ''} for key in ('a', 'b', 'c')]
    return deepcopy({'glossary': glossary[:5], 'questions': questions,
                     'focus': reading.get('focus', ''), 'estimated_minutes': reading.get('estimated_minutes', 3)})


def _submitted(reading: dict, fields: dict) -> dict:
    fields['focus'] = request.form.get('focus', '').strip()
    raw_eta = request.form.get('estimated_minutes', '').strip()
    fields['estimated_minutes'] = int(raw_eta) if raw_eta.isascii() and raw_eta.isdecimal() and len(raw_eta) <= 3 else raw_eta
    for index, row in enumerate(fields['glossary']):
        for key in ('english', 'translation'):
            row[key] = request.form.get(f'g{index}_{key}', '').strip()
    for index, row in enumerate(fields['questions']):
        for key in _QUESTION_FIELDS:
            row[key] = request.form.get(f'q{index}_{key}', '').strip()
        for option_index, option in enumerate(row['options']):
            option['text'] = request.form.get(f'q{index}_option{option_index}', '').strip()
    return {
        **reading,
        'focus': fields['focus'],
        **({'estimated_minutes': fields['estimated_minutes']}
           if 'estimated_minutes' in reading or fields['estimated_minutes'] != 3 else {}),
        'glossary': [row for row in fields['glossary'] if row['english'] or row['translation']],
        'questions': [row for row in fields['questions'] if any(row[key] for key in _QUESTION_FIELDS)
                      or any(option['text'] for option in row['options'])],
    }


@short_reading_bp.route('/books/<int:book_id>/short-reading', methods=['GET', 'POST'])
@admin_required
def edit(book_id: int) -> ResponseReturnValue:
    action = request.form.get('action') if request.method == 'POST' else None
    book_query = Book.query.filter_by(id=book_id)
    chapter_query = Chapter.query.filter_by(book_id=book_id).order_by(Chapter.id)
    if action == 'apply':
        book_query = book_query.with_for_update().populate_existing()
        chapter_query = chapter_query.with_for_update().populate_existing()
    book = book_query.first_or_404()
    if not book.is_short_reading:
        abort(404)
    chapters = chapter_query.limit(2).all()
    if len(chapters) != 1:
        abort(409, 'Для короткого чтения требуется ровно одна глава.')
    chapter = chapters[0]
    current = {'slug': book.slug, 'title': book.title, 'text': chapter.text_raw, 'reading': book.reading}
    revision = _digest([chapter.id, chapter.title, current])
    text, fields = text_for_edit(chapter.text_raw), _fields(book.reading)
    error, token, changes, structural, status = '', '', [], False, 200
    if request.method == 'POST':
        text = text_for_edit(request.form.get('text', ''))
        candidate = {**current, 'text': text, 'reading': _submitted(book.reading, fields)}
        try:
            if request.form.get('revision') != revision:
                raise BadSignature('stale reading')
            if action not in ('preview', 'apply'):
                raise ValueError('Выберите предпросмотр или публикацию.')
            signer = URLSafeTimedSerializer(current_app.secret_key, salt='admin-short-reading')
            binding = [current_user.id, book.id, revision, _digest(candidate)]
            if action == 'apply':
                signed = request.form.get('preview_token', '')
                if len(signed) > 1024 or signer.loads(signed, max_age=1800) != binding:
                    raise BadSignature('stale preview')
            validate_reading_item(candidate)
            review = review_chapter(book, chapter, chapter.title, text, coordinated_reading=True)
            structural = review.structure_changed
            if review.text_changed:
                changes.append(('Текст', text_for_edit(chapter.text_raw), text))
            for key, label, fallback in (('focus', 'Цель чтения', ''), ('estimated_minutes', 'Минуты', 3),
                                         ('glossary', 'Словарь', []), ('questions', 'Вопросы', [])):
                old, new = book.reading.get(key, fallback), candidate['reading'].get(key, fallback)
                if old != new:
                    if key in ('focus', 'estimated_minutes') or not isinstance(old, list):
                        old = str(old)
                    changes.append((label, old, str(new) if key == 'estimated_minutes' else new))
            if action == 'preview':
                token = signer.dumps(binding) if changes else ''
                if not changes:
                    error = 'Изменений нет.'
            else:
                if not changes:
                    raise BadSignature('repeated publication')
                apply_chapter(book, chapter, chapter.title, text, review)
                if review.text_changed and review.index is None:
                    tokens = words(text)
                    chapter.words = book.words_total = len(tokens)
                    book.unique_words = len({word.casefold() for word in tokens})
                if book.summary == book.reading.get('focus'):
                    book.summary = candidate['reading']['focus']
                book.reading = candidate['reading']
                log_admin_action(current_user.id, 'book.short_reading.publish', 'book', book.id, required=True)
                db.session.commit()
                flash('Короткое чтение опубликовано.', 'success')
                return redirect(materials_return_url() or url_for('.edit', book_id=book.id), code=303)
        except BadSignature:
            error, status = 'Текст или черновик изменились. Откройте свежий предпросмотр.', 409
        except ValueError as exc:
            error, status = str(exc), 422
        except Exception:
            db.session.rollback()
            raise
    response = make_response(render_template('admin/books/edit_short_reading.html', book=book, text=text,
                                            fields=fields, revision=revision, error=error, token=token,
                                            changes=changes, structural=structural), status)
    response.headers['Cache-Control'] = 'private, no-store'
    return response
