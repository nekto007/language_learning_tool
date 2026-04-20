"""Books catalog API for the linear-plan reading slot.

Endpoints:
- ``GET /api/books/catalog`` — books filtered to the user's level window
  (``[user_level - 1, user_level, user_level + 1]``).
- ``POST /api/books/select`` — persist the user's chosen book in
  ``UserReadingPreference`` and return the refreshed reading slot.

Both endpoints are session-authenticated (browser AJAX). They are not
exposed to JWT/mobile clients and keep CSRF protection on.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from flask import Blueprint, jsonify, request
from flask_login import current_user

from app.api.decorators import api_auth_required
from app.api.errors import api_error
from app.books.models import Book
from app.curriculum.models import CEFRLevel
from app.daily_plan.level_utils import _cefr_code_to_order, get_user_current_cefr_level
from app.daily_plan.linear.models import UserReadingPreference
from app.daily_plan.linear.slots.reading_slot import build_reading_slot
from app.utils.db import db

logger = logging.getLogger(__name__)

api_books_catalog = Blueprint('api_books_catalog', __name__)


def _level_window_codes(user_level_code: str) -> list[str]:
    """Return CEFR codes within ±1 of the user's level, ordered by ``order``."""
    user_order = _cefr_code_to_order(user_level_code, db)
    if user_order < 0:
        # Unknown user level — fall back to all books.
        rows = db.session.query(CEFRLevel.code).order_by(CEFRLevel.order.asc()).all()
        return [row[0] for row in rows]

    rows = (
        db.session.query(CEFRLevel.code)
        .filter(CEFRLevel.order.between(user_order - 1, user_order + 1))
        .order_by(CEFRLevel.order.asc())
        .all()
    )
    return [row[0] for row in rows]


@api_books_catalog.route('/books/catalog', methods=['GET'])
@api_auth_required
def get_books_catalog():
    """Return books filtered to the user's level window."""
    requested_level = request.args.get('level')
    user_level = requested_level or get_user_current_cefr_level(current_user.id, db)

    codes = _level_window_codes(user_level)

    query = db.session.query(Book).filter(Book.chapters_cnt > 0)
    if codes:
        query = query.filter(Book.level.in_(codes))
    books = query.order_by(Book.level.asc(), Book.title.asc()).all()

    payload = [
        {
            'id': book.id,
            'title': book.title,
            'author': book.author,
            'level': book.level,
            'summary': book.summary,
            'cover_image': book.cover_image,
            'chapters_cnt': book.chapters_cnt,
            'words_total': book.words_total,
        }
        for book in books
    ]
    return jsonify({'user_level': user_level, 'books': payload})


@api_books_catalog.route('/books/select', methods=['POST'])
@api_auth_required
def select_book():
    """Persist the user's chosen reading book and return the refreshed slot."""
    data = request.get_json(silent=True) or {}
    book_id = data.get('book_id')
    # ``isinstance(True, int)`` is True in Python — reject booleans explicitly.
    if not isinstance(book_id, int) or isinstance(book_id, bool):
        return api_error('invalid_book_id', 'book_id must be an integer', 400)

    book = db.session.get(Book, book_id)
    if book is None:
        return api_error('book_not_found', 'Book not found', 404)

    pref = (
        db.session.query(UserReadingPreference)
        .filter(UserReadingPreference.user_id == current_user.id)
        .first()
    )
    if pref is None:
        pref = UserReadingPreference(
            user_id=current_user.id,
            book_id=book.id,
            selected_at=datetime.now(timezone.utc),
        )
        db.session.add(pref)
    else:
        pref.book_id = book.id
        pref.selected_at = datetime.now(timezone.utc)

    try:
        db.session.commit()
    except Exception:
        db.session.rollback()
        logger.exception('Failed to persist UserReadingPreference for user_id=%s', current_user.id)
        return api_error('server_error', 'Не удалось сохранить выбор книги', 500)

    slot = build_reading_slot(current_user.id, db)
    return jsonify({'success': True, 'slot': slot.to_dict()})
