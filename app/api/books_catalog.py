"""Books catalog API for the linear-plan reading slot.

Endpoints:
- ``GET /api/books/catalog`` — books filtered to the user's level window
  (``[user_level - 1, user_level, user_level + 1]``).
- ``POST /api/books/select`` — persist the user's chosen book in
  ``UserReadingPreference`` and return the refreshed reading slot.

GET accepts session/JWT authentication. With ``include_library=1`` it also
returns the account reading history, independently of the recommendation
level window. Browser selection keeps CSRF protection on.
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from math import ceil

from flask import Blueprint, current_app, jsonify, request, url_for
from flask.typing import ResponseReturnValue
from flask_login import current_user
from sqlalchemy import exists, func, or_, select

from app.api.decorators import api_auth_required
from app.api.errors import api_error
from app.books.access import accessible_books_filter, can_user_access_book
from app.books.models import Book, Chapter, UserChapterProgress
from app.books.progress import _progress_from_records, get_book_completion_state, get_completed_book_ids
from app.books.readability import book_has_text, chapter_has_text
from app.books.text_access import book_allows_learner_text, book_allows_text, visible_chapter_text
from app.curriculum.models import CEFRLevel
from app.daily_plan.level_utils import _cefr_code_to_order, get_user_current_cefr_level
from app.daily_plan.linear.models import UserReadingPreference
from app.daily_plan.linear.slots.reading_slot import build_reading_slot
from app.utils.db import db

logger = logging.getLogger(__name__)

api_books_catalog = Blueprint('api_books_catalog', __name__)
_EXCERPT_MAX_WORDS = 160
_EXCERPT_MAX_CHARS = 2600
_EXCERPT_WORDS_PER_MINUTE = 120


def _plan_excerpt_book(book: Book) -> bool:
    slug = current_app.config.get('BOOK_PLAN_EXCERPT_SLUG')
    return bool(slug and book.slug == slug and book.is_published and book.level
                and book.rights_status == 'public_domain')


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

    query = (
        db.session.query(Book)
        .filter(book_has_text(Book.id))
        .filter(Book.is_published == True)
        .filter(accessible_books_filter(current_user))
    )
    if not current_user.is_admin:
        query = query.filter(book_allows_learner_text())
    if codes:
        query = query.filter(Book.level.in_(codes))
    books = query.order_by(Book.level.asc(), Book.title.asc()).all()
    # The original A1 pack follows its learning sequence, not alphabetic title order.
    books.sort(key=lambda book: (
        book.level or '', 0 if book.is_short_reading else 1,
        (book.reading or {}).get('order', 0) if book.is_short_reading else 0, book.title,
    ))
    completed_book_ids = get_completed_book_ids(current_user.id, [book.id for book in books], db)
    books = [book for book in books if book.id not in completed_book_ids]

    result = {'user_level': user_level, 'books': [_book_payload(book) for book in books]}
    if request.args.get('view') == 'plan_picker':
        for book, row in zip(books, result['books'], strict=True):
            if _plan_excerpt_book(book):
                row['plan_excerpt_url'] = url_for('.get_plan_excerpt', book_id=book.id)
    if request.args.get('include_library') == '1':
        result['library_books'] = _account_library(current_user)
    shelf_books = result['books'] + [item['book'] for item in result.get('library_books', [])]
    _add_book_courses(shelf_books)
    response = jsonify(result)
    response.headers["Cache-Control"] = "private, no-store"
    return response


@api_books_catalog.route('/books/<int:book_id>/plan-excerpt', methods=['GET'])
@api_auth_required
def get_plan_excerpt(book_id: int) -> ResponseReturnValue:
    """Project a short, read-only learner excerpt for the configured book."""
    book = db.session.get(Book, book_id)
    if book is None or not _plan_excerpt_book(book) or not can_user_access_book(current_user, book):
        return api_error('excerpt_not_found', 'Отрывок недоступен', 404)
    chapter = db.session.query(Chapter.title, Chapter.text_raw).filter(
        Chapter.book_id == book.id, chapter_has_text(),
    ).order_by(Chapter.chap_num, Chapter.id).first()
    if chapter is None:
        return api_error('excerpt_not_found', 'Отрывок недоступен', 404)

    projected, _ = visible_chapter_text(book, chapter.text_raw, admin=False)
    text = projected.replace('\\n', '\n').replace('\r\n', '\n').strip()
    words = list(re.finditer(r'\S+', text[:_EXCERPT_MAX_CHARS]))
    if (len(text) > _EXCERPT_MAX_CHARS and not text[_EXCERPT_MAX_CHARS].isspace()
            and words and words[-1].end() == _EXCERPT_MAX_CHARS):
        words.pop()
    if not words:
        return api_error('excerpt_not_found', 'Отрывок недоступен', 404)
    if len(text) > _EXCERPT_MAX_CHARS or len(words) > _EXCERPT_MAX_WORDS:
        stop = words[min(len(words), _EXCERPT_MAX_WORDS) - 1].end()
        text = text[:stop]
        boundaries = list(re.finditer(r"""[.!?]["'\u2019\u201d]?(?=\s|$)""", text))
        if boundaries and boundaries[-1].end() >= stop // 2:
            text = text[:boundaries[-1].end()]
        else:
            text += '…'
    count = len(text.split())
    response = jsonify(
        title=book.title, chapter_title=chapter.title, level=book.level,
        paragraphs=re.split(r'\n\s*\n', text), words=count, minutes=ceil(count / _EXCERPT_WORDS_PER_MINUTE),
    )
    response.headers['Cache-Control'] = 'private, no-store'
    return response


def _add_book_courses(books: list[dict]) -> None:
    from app.curriculum.book_courses import BookCourse

    if not books:
        return
    # Both catalog shelves have already applied the user's book access policy.
    # Even an administrator's draft reading history gets no public course links.
    rows = (BookCourse.active_for_books({book['id'] for book in books})
            .join(Book, Book.id == BookCourse.book_id).filter(Book.is_published.is_(True))
            .with_entities(BookCourse.book_id, BookCourse.id, BookCourse.title).all())
    by_book: dict[int, list[dict[str, str]]] = {}
    for book_id, course_id, title in rows:
        by_book.setdefault(book_id, []).append({
            'title': title, 'path': url_for('book_courses.view_course', course_id=course_id),
        })
    for book in books:
        book['book_courses'] = by_book.get(book['id'], [])


def _book_payload(book):
    from app.books.short_readings import reading_summary

    return {
        'id': book.id,
        'title': book.title,
        'author': book.author,
        'level': book.level,
        'summary': book.summary,
        'cover_image': book.cover_image,
        'chapters_cnt': book.chapters_cnt,
        'words_total': book.words_total,
        'reading': reading_summary(book),
    }


def _utc(value):
    return value.replace(tzinfo=timezone.utc) if value and value.tzinfo is None else value


def _account_library(user):
    """Batch account history; no chapter text, per-book queries or shared cache."""
    from app.books.reading_session import CHAPTER_COMPLETION_THRESHOLD

    pref = db.session.query(UserReadingPreference).filter_by(user_id=user.id).first()
    has_progress = exists(select(UserChapterProgress.chapter_id).join(
        Chapter, Chapter.id == UserChapterProgress.chapter_id,
    ).where(UserChapterProgress.user_id == user.id, Chapter.book_id == Book.id))
    query = db.session.query(Book).filter(accessible_books_filter(user)).filter(
        or_(has_progress, Book.id == pref.book_id) if pref else has_progress,
    )
    if not getattr(user, 'is_admin', False):
        query = query.filter(Book.is_published.is_(True))
    books = query.all()
    if not books:
        return []
    ids = [book.id for book in books]
    counts = {bid: (count, first) for bid, count, first in db.session.query(
        Chapter.book_id, func.count(Chapter.id), func.min(Chapter.chap_num),
    ).filter(Chapter.book_id.in_(ids), chapter_has_text()).group_by(Chapter.book_id).all()}
    grouped = {}
    for record, book_id, chapter_num in db.session.query(UserChapterProgress, Chapter.book_id, Chapter.chap_num).join(
        Chapter, Chapter.id == UserChapterProgress.chapter_id,
    ).filter(UserChapterProgress.user_id == user.id, Chapter.book_id.in_(ids), chapter_has_text()).all():
        grouped.setdefault(book_id, []).append((record, chapter_num))
    result = []
    for book in books:
        total, first = counts.get(book.id, (0, 1))
        if total == 0:
            continue
        rows = grouped.get(book.id, [])
        rows.sort(key=lambda pair: (_utc(pair[0].updated_at) or datetime.min.replace(tzinfo=timezone.utc), pair[1]), reverse=True)
        records = [pair[0] for pair in rows]
        completed = sum((row.offset_pct or 0) >= CHAPTER_COMPLETION_THRESHOLD for row in records)
        latest = rows[0] if rows else None
        selected = pref is not None and pref.book_id == book.id
        last_read = _utc(latest[0].updated_at) if latest else None
        result.append({
            'book': _book_payload(book),
            'progress': {
                'progress_pct': int(_progress_from_records(records, total)),
                'current_chapter': latest[1] if latest else first,
                'offset_pct': latest[0].offset_pct if latest else 0,
                'completed_chapters': completed,
                'total_chapters': total,
                'is_completed': completed >= total,
                'is_selected': selected,
                'last_read': last_read.isoformat() if last_read else None,
            },
        })
    result.sort(key=lambda item: (item['progress']['last_read'] or '', item['book']['id']), reverse=True)
    return result



@api_books_catalog.route('/books/select', methods=['POST'])
@api_auth_required
def select_book():
    """Persist the user's chosen reading book and return the refreshed slot."""
    data = request.get_json(silent=True)
    book_id = data.get('book_id') if isinstance(data, dict) else None
    # ``isinstance(True, int)`` is True in Python — reject booleans explicitly.
    if not isinstance(book_id, int) or isinstance(book_id, bool):
        return api_error('invalid_book_id', 'book_id must be an integer', 400)

    book = db.session.get(Book, book_id)
    if book is None:
        return api_error('book_not_found', 'Book not found', 404)

    # Drafts must look nonexistent to non-admins, the same verdict every
    # reader route gives (app/books/routes.py:358 et al). ``can_user_access_book``
    # deliberately answers only the rights question and documents that the
    # route layer owns this check. Without it a POST with a guessed id pins
    # ``UserReadingPreference`` to a book whose reader 404s, so the required
    # reading slot can never complete and ``day_secured`` stays unreachable.
    if not book.is_published and not getattr(current_user, 'is_admin', False):
        return api_error('book_not_found', 'Book not found', 404)

    if not can_user_access_book(current_user, book):
        return api_error('book_access_denied', 'Нет доступа к этой книге', 403)

    if not book_allows_text(book, admin=current_user.is_admin) or not db.session.query(book_has_text(book.id)).scalar():
        return api_error('book_not_readable', 'Текст книги пока недоступен', 409)

    if get_book_completion_state(current_user.id, book.id, db)['is_completed']:
        return api_error('book_already_completed', 'Эта книга уже прочитана', 409)

    try:
        # Serialise concurrent first picks: the user row is the lock, so the
        # second request sees the preference the first one wrote (item 16).
        from app.auth.models import User
        db.session.query(User.id).filter(User.id == current_user.id).with_for_update().scalar()
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
            # Item 16: the first book turns the daily reading goal on (5 min);
            # switching books later leaves an explicit «по желанию» alone. Same
            # transaction as the preference: a failure rolls both back.
            from app.daily_plan.items.reading import ensure_reading_goal_on_first_book
            ensure_reading_goal_on_first_book(current_user.id, db)
        else:
            pref.book_id = book.id
            pref.selected_at = datetime.now(timezone.utc)
        db.session.commit()
    except Exception:
        db.session.rollback()
        logger.exception('Failed to persist UserReadingPreference for user_id=%s', current_user.id)
        return api_error('server_error', 'Не удалось сохранить выбор книги', 500)

    slot = build_reading_slot(current_user.id, db)
    return jsonify({'success': True, 'slot': slot.to_dict()})
